/*
 * RotoBridge - After Effects export. File > Scripts > Run Script File...
 *
 * Reads the masks on the selected layers and writes a `.rbj` (prd.md section
 * 9.1). Both layers are written: every frame of the work area is baked into
 * `frames`, and the keys the artist actually authored go into `keys` (spec
 * sections 7 and 9). `keys` is never omitted - an absent `keys` means "treat
 * every frame as a key", which is a different claim, and one this exporter has
 * no reason to make.
 *
 * The one structural decision here is the **frame-major loop** (prd.md section
 * 9.1 step 4). `sourcePointToComp` has no time parameter, so the layer
 * transform can only be read at the current `comp.time`, and setting
 * `comp.time` measured 5.75-20.89 ms across Phase 0's six runs against
 * 0.02-1.52 ms for `valueAtTime`. Mask-major would pay that once per mask per
 * frame - about 31 s for ten shapes over 150 frames at the slow end, which
 * breaks acceptance criterion 11 before any real work happens. Frame-major pays
 * it 150 times total, independent of shape count.
 */

#include "rotobridge_ae.jsx"

(function () {
    var ae = RB.ae;
    var geom = RB.geom;

    /* How far the derived affine may land from the host's own answer before the
     * export stops trusting it. A tenth of a thousandth of a pixel is far below
     * anything that could matter and far above float noise, which measured
     * around 1e-12 px in the test harness. */
    var AFFINE_TOLERANCE = 1e-4;

    function collectShapes(comp, warn) {
        /* Every mask to export, paired with the layer it belongs to.
         *
         * Names are taken verbatim, matching the Nuke exporter. They are unique
         * within a layer but not across layers, and the importer's subset
         * selection is by name, so a collision is worth a warning even though
         * the file itself stays legal. */
        var layers = ae.maskedLayers(comp);
        var shapes = [];
        var seen = {};
        for (var i = 0; i < layers.length; i++) {
            var layer = layers[i];
            ae.checkLayer(layer);
            var masks = ae.maskGroup(layer);
            for (var m = 1; m <= masks.numProperties; m++) {
                var mask = masks.property(m);
                var name = mask.name;
                if (RB.util.hasOwn(seen, name)) {
                    warn("two masks are both named '" + name + "' (on layers '"
                         + seen[name] + "' and '" + layer.name + "'); importing"
                         + " a subset by name cannot tell them apart");
                } else {
                    seen[name] = layer.name;
                }
                shapes[shapes.length] = { layer: layer, mask: mask, name: name };
            }
        }
        return shapes;
    }

    function shapeHeader(entry, warn) {
        /* The per-shape members that do not vary with time. */
        var mask = entry.mask;
        var mode = ae.maskProp(mask, ae.MASK_PATH) ? mask.maskMode : null;

        if (mask.inverted) {
            warn("mask '" + entry.name + "': the inverted flag was dropped;"
                 + " .rbj v1 has no field for it");
        }

        var expansion = ae.maskProp(mask, ae.MASK_EXPANSION);
        if (expansion && Math.abs(expansion.value) > 1e-9) {
            /* Not in the format and not in prd.md section 10 either - the probe
             * turned it up while looking for feather. Silently dropping a
             * non-zero expansion would change the matte, so it is named. */
            warn("mask '" + entry.name + "': mask expansion of " + expansion.value
                 + " px was dropped; .rbj v1 has no field for it");
        }

        return {
            "name": entry.name,
            "closed": true,
            "blend": ae.blendFromMode(mode, warn, entry.name),
            "feather_model": "none",
            "feather_falloff": ae.falloffToRbj(mask.maskFeatherFalloff),
            "frames": {}
        };
    }

    function layerAffine(layer, warn, layerName) {
        /* The layer transform at the CURRENT comp.time, as an affine.
         *
         * Returns null when the host disagrees with the derived map, which
         * makes the caller fall back to per-vertex host calls for this frame.
         * The claim being checked is that a 2D unparented layer's transform is
         * affine; it should be, 3D and parented layers being hard failures, but
         * this project has been caught twice by an API that introspects as one
         * thing and behaves as another. */
        var span = geom.AFFINE_SPAN;
        var m = geom.affineFromProbes(ae.pointToComp(layer, [0, 0]),
                                      ae.pointToComp(layer, [span, 0]),
                                      ae.pointToComp(layer, [0, span]));
        var check = [span * 0.37, span * -0.61];
        var off = geom.affineDisagreement(m, check,
                                          ae.pointToComp(layer, check));
        if (off > AFFINE_TOLERANCE) {
            warn("layer '" + layerName + "': its transform is not affine (off by "
                 + off.toFixed(6) + " px); every point was converted through the"
                 + " host instead, which is slower but exact");
            return null;
        }
        return m;
    }

    function pointsAtFrame(entry, path, affine, compHeight) {
        /* One frame of one mask, in canonical space.
         *
         * Tangents come out of After Effects vertex-relative already, so the
         * only thing the conversion does to them is the Y flip - but they are
         * relative in LAYER space, and the layer transform can rotate and
         * scale, so they still have to go through it. */
        var layer = entry.layer;
        var vertices = path.vertices;
        var inTangents = path.inTangents;
        var outTangents = path.outTangents;
        var points = [];

        for (var i = 0; i < vertices.length; i++) {
            var v = vertices[i];
            var comp, tIn, tOut;
            if (affine) {
                comp = geom.applyAffinePoint(affine, v);
                tIn = geom.applyAffineTangent(affine, inTangents[i]);
                tOut = geom.applyAffineTangent(affine, outTangents[i]);
            } else {
                comp = ae.pointToComp(layer, v);
                tIn = ae.tangentToComp(layer, v, inTangents[i]);
                tOut = ae.tangentToComp(layer, v, outTangents[i]);
            }
            points[i] = {
                "c": geom.compToCanonicalPoint(comp, compHeight),
                "in": geom.compToCanonicalTangent(tIn),
                "out": geom.compToCanonicalTangent(tOut)
            };
        }
        return points;
    }

    function applyFeather(entry, path, points, state, warn) {
        /* Resolve this frame's feather points onto the vertices.
         *
         * After Effects places a feather point anywhere along a segment; .rbj
         * carries one signed scalar per vertex (prd.md section 9.3). Feather
         * points live on the `Shape` the path evaluates to, so they animate
         * with it and have to be read inside the frame loop like everything
         * else here. */
        var radii = path.featherRadii;
        if (!radii || !radii.length) { return; }

        state.sawFeather = true;
        var got = geom.snapFeatherPoints(path.featherSegLocs,
                                         path.featherRelSegLocs,
                                         radii, points.length);
        for (var i = 0; i < points.length; i++) {
            points[i]["feather"] = got.feather[i];
        }

        if (got.snapped.length) {
            warn("mask '" + entry.name + "': " + got.snapped.length
                 + " feather point(s) sat mid-segment and were snapped to the"
                 + " nearer vertex; Nuke can only anchor feather at a vertex");
        }
        for (var d = 0; d < got.dropped.length; d++) {
            var drop = got.dropped[d];
            warn("mask '" + entry.name + "': two feather points resolved to"
                 + " vertex " + drop.vertex + "; kept radius " + drop.kept
                 + " and dropped " + drop.radius);
        }
    }

    function bake(comp, shapes, frames, warn) {
        /* The frame-major dense loop. See the file header for why.
         *
         * `comp.time` is set once per frame and every shape is read at that
         * time, so the cost of setting it is paid 150 times rather than 150
         * times per shape. */
        var headers = [];
        var states = [];
        var s;
        for (s = 0; s < shapes.length; s++) {
            headers[s] = shapeHeader(shapes[s], warn);
            states[s] = { sawFeather: false, vertexCount: null, closed: null };
        }

        for (var f = 0; f < frames.length; f++) {
            var frame = frames[f];
            var t = ae.frameToTime(comp, frame);
            comp.time = t;

            var affines = {};
            for (s = 0; s < shapes.length; s++) {
                var entry = shapes[s];
                var layerKey = String(entry.layer.index);
                if (!RB.util.hasOwn(affines, layerKey)) {
                    /* Once per layer per frame, not once per mask: several
                     * masks on one layer share its transform. */
                    affines[layerKey] = layerAffine(entry.layer, warn,
                                                    entry.layer.name);
                }

                var path = ae.maskProp(entry.mask, ae.MASK_PATH)
                             .valueAtTime(t, false);
                if (states[s].closed === null) {
                    states[s].closed = path.closed;
                } else if (states[s].closed !== path.closed) {
                    /* Same class as a changing vertex count below: the file
                     * carries one `closed` for the whole shape, and there is no
                     * correct reading of a path that opens partway through. */
                    throw new Error("mask '" + entry.name + "' is "
                        + (path.closed ? "closed" : "open") + " at frame "
                        + frame + " but " + (states[s].closed ? "closed" : "open")
                        + " earlier; .rbj carries one open/closed state per"
                        + " shape");
                }

                var points = pointsAtFrame(entry, path, affines[layerKey],
                                           comp.height);
                if (states[s].vertexCount === null) {
                    states[s].vertexCount = points.length;
                } else if (states[s].vertexCount !== points.length) {
                    throw new Error("mask '" + entry.name + "' has "
                        + points.length + " vertices at frame " + frame
                        + " but " + states[s].vertexCount + " earlier; Nuke"
                        + " cannot represent a changing vertex count and there"
                        + " is no correct interpolation between two");
                }
                applyFeather(entry, path, points, states[s], warn);

                var opacity = ae.maskProp(entry.mask, ae.MASK_OPACITY)
                                .valueAtTime(t, false);
                var feather = ae.maskProp(entry.mask, ae.MASK_FEATHER)
                                .valueAtTime(t, false);

                headers[s]["frames"][String(frame)] = {
                    /* Opacity is a percentage in the host and a 0-1 fraction in
                     * the format (spec section 7.2). Uniform feather is read
                     * per frame because it animates - run 6 measured a keyed
                     * `maskFeather` going 10 to 80 - and reading it once per
                     * shape would freeze it at the first frame. */
                    "opacity": Number(opacity) / 100.0,
                    "feather_uniform": [Number(feather[0]), Number(feather[1])],
                    "points": points
                };
            }
        }

        for (s = 0; s < shapes.length; s++) {
            headers[s]["closed"] = states[s].closed;
            if (!states[s].closed) {
                /* An open mask path produces no alpha in After Effects, so
                 * this mask was not matting anything here either. The geometry
                 * is still worth carrying - it mattes in Nuke - but no host's
                 * stroke settings travel with it, and Nuke's are node knobs the
                 * file has no member for. spec/rbj-v2-draft.md section 5. */
                warn("mask '" + shapes[s].name + "' is an open spline, which"
                     + " produces no alpha as an After Effects mask; the"
                     + " geometry is carried but no stroke width or end caps"
                     + " are");
            }
            finishFeather(headers[s], states[s]);
        }
        return headers;
    }

    function finishFeather(header, state) {
        /* `feather_model` is a per-shape member but feather points are a
         * per-frame reading, so it can only be decided once every frame is in.
         *
         * Under `per_point` the spec requires `feather` on every point of every
         * frame, so frames that had no feather points are filled with zeros -
         * which is also what they mean. Under `none` the member must be absent
         * entirely, because a zero written under `none` is indistinguishable
         * from an authored zero-width point. */
        var frames = header["frames"];
        var key, i, points;
        if (!state.sawFeather) {
            for (key in frames) {
                if (!RB.util.hasOwn(frames, key)) { continue; }
                points = frames[key]["points"];
                for (i = 0; i < points.length; i++) {
                    delete points[i]["feather"];
                }
            }
            return;
        }
        header["feather_model"] = "per_point";
        for (key in frames) {
            if (!RB.util.hasOwn(frames, key)) { continue; }
            points = frames[key]["points"];
            for (i = 0; i < points.length; i++) {
                if (!RB.util.hasOwn(points[i], "feather")) {
                    points[i]["feather"] = 0.0;
                }
            }
        }
    }

    /* --- the sparse layer ---------------------------------------------------
     *
     * After Effects carries one keyframe per time for the whole mask path, and
     * `.rbj` carries one key per frame for the whole shape, so this direction
     * needs none of the tier machinery `core/interp.py` grew for Nuke - there
     * is nothing to reduce. What a key does need is the layer transform, which
     * is baked into the exported points and therefore animates the geometry
     * even when the path itself never moves (prd.md section 9.2 step 5, and
     * case 77 on the Nuke side for the same reason).
     */

    var TRANSFORM_GROUP = "ADBE Transform Group";

    /* Only the transform properties that move geometry. Layer opacity lives in
     * the same group and does not, and keying it would otherwise plant an
     * `ease` key in the middle of a shape that never moved. Separated
     * dimensions replace `ADBE Position` with two properties rather than
     * hiding it, so both spellings are read and the union sorts it out. */
    var TRANSFORM_GEOMETRY = ["ADBE Anchor Point", "ADBE Position",
                              "ADBE Position_0", "ADBE Position_1",
                              "ADBE Scale", "ADBE Rotate Z"];

    /* How far a key time may sit from the frame grid before it is worth
     * saying so. After Effects reports frame 200 at 24 fps as 8.333333 s, and
     * that rounding noise is around 1e-6 frames - four orders below this. */
    var OFFGRID_FRAMES = 1e-3;

    function subProperty(group, matchName) {
        /* Absent rather than an error: the transform group holds a different
         * set of properties depending on whether the position is separated. */
        try {
            return group.property(matchName) || null;
        } catch (e) {
            return null;
        }
    }

    function keyFrames(comp, prop, out, warn, what) {
        /* Every key time on one property, snapped to the frame grid.
         *
         * Frames are appended to `out.frames` and, where the caller supplied
         * an `out.index`, the property's own 1-based key number is recorded
         * against the frame so the interpolation can be read back off it.
         *
         * Snapping is not optional: spec section 9 requires every
         * `keys[].frame` to name a frame that exists in `frames`, and After
         * Effects permits a keyframe anywhere in continuous time. */
        if (!prop) { return; }
        var fps = comp.frameRate;
        var sf = ae.startFrame(comp);
        for (var i = 1; i <= prop.numKeys; i++) {
            var seconds = prop.keyTime(i);
            var frame = RB.timing.secondsToFrame(seconds, fps, sf);
            var off = RB.timing.subframeResidual(seconds, fps, sf);
            if (Math.abs(off) > OFFGRID_FRAMES) {
                warn(what + ": a key sat " + off.toFixed(3) + " of a frame off"
                     + " the grid and was snapped to frame " + frame
                     + "; .rbj keys are whole frames");
            }
            out.frames[out.frames.length] = frame;
            if (out.index) { out.index[String(frame)] = i; }
        }
    }

    function transformKeyFrames(comp, layer, out, warn) {
        var group;
        try {
            group = layer.property(TRANSFORM_GROUP);
        } catch (e) {
            group = null;
        }
        if (!group) { return; }
        for (var i = 0; i < TRANSFORM_GEOMETRY.length; i++) {
            keyFrames(comp, subProperty(group, TRANSFORM_GEOMETRY[i]), out,
                      warn, "layer '" + layer.name + "'");
        }
    }

    function easeSide(eases) {
        /* One `KeyframeEase` to the `[influence, speed]` pair of spec section
         * 10.3. The array is one entry long on a mask path - probe run 6
         * section G reported "1 dim" on all three keys of a keyed path - which
         * is what makes a single shape-wide `ease` the right storage. */
        var e = eases[0];
        return RB.interp.easeFromAe(e.influence, e.speed);
    }

    function pathKey(path, at, frame) {
        /* One mask-path keyframe, both sides, with its ease where it has one. */
        var sides = {
            "in": RB.interp.sideFromAe(path.keyInInterpolationType(at)),
            "out": RB.interp.sideFromAe(path.keyOutInterpolationType(at))
        };
        var key = { "frame": frame, "interp": sides };

        /* A side has an `ease` entry only when its interp is `ease` - spec
         * section 10.3, and the validator rejects the alternative. After
         * Effects reports an ease on every key whatever its type (run 6 read
         * influence 16.667 off a LINEAR key), so reading unconditionally would
         * write parameters that describe nothing. */
        var ease = {};
        var any = false;
        if (sides["in"] === RB.interp.EASE) {
            ease["in"] = easeSide(path.keyInTemporalEase(at));
            any = true;
        }
        if (sides["out"] === RB.interp.EASE) {
            ease["out"] = easeSide(path.keyOutTemporalEase(at));
            any = true;
        }
        if (any) { key["ease"] = ease; }
        return key;
    }

    function sparseKeys(comp, entry, frames, warn) {
        /* The `keys` array for one shape: which frames, and how each one
         * interpolates.
         *
         * The range endpoints are always pinned. A key outside the exported
         * range still drives the values inside it, and the dense layer covers
         * exactly [first, last], so without them a mask keyed at 60 and 200 and
         * exported over 1 to 100 would claim to be static for its first 59
         * frames. Two keys, and the sparse layer brackets the truth instead of
         * flattening at the edge; the importer's drift pass fills in whatever
         * curves between them.
         */
        var first = frames[0];
        var last = frames[frames.length - 1];
        var path = ae.maskProp(entry.mask, ae.MASK_PATH);
        var name = "mask '" + entry.name + "'";

        var onPath = { frames: [], index: {} };
        keyFrames(comp, path, onPath, warn, name);
        var union = { frames: onPath.frames.slice(0), index: null };
        transformKeyFrames(comp, entry.layer, union, warn);

        var wanted = [first, last];
        var all = RB.util.sortedInts(union.frames);
        var i;
        for (i = 0; i < all.length; i++) {
            if (all[i] >= first && all[i] <= last) {
                wanted[wanted.length] = all[i];
            }
        }

        var out = [];
        all = RB.util.sortedInts(wanted);
        for (i = 0; i < all.length; i++) {
            var frame = all[i];
            var at = RB.util.hasOwn(onPath.index, String(frame))
                ? onPath.index[String(frame)] : null;
            /* A frame with no path key of its own is a pinned endpoint or a
             * transform key. Nothing was authored there to read, so the side is
             * unknown, which spec section 10.3 spells `ease` with no
             * parameters: "smooth, parameters unknown, rely on the drift
             * pass". That is exactly what is true here. */
            out[out.length] = at === null
                ? { "frame": frame,
                    "interp": { "in": RB.interp.EASE, "out": RB.interp.EASE } }
                : pathKey(path, at, frame);
        }
        return out;
    }

    function buildDocument(comp, warn) {
        var shapes = collectShapes(comp, warn.fn());
        var range = ae.workAreaFrames(comp);
        var frames = RB.timing.frameRange(range[0], range[1]);
        var headers = bake(comp, shapes, frames, warn.fn());
        for (var s = 0; s < shapes.length; s++) {
            /* After the bake, not during it: `sparseKeys` reads key times and
             * key times do not depend on `comp.time`, so pulling it out of the
             * frame loop costs one pass per shape instead of one per frame. */
            headers[s]["keys"] = sparseKeys(comp, shapes[s], frames, warn.fn());
        }
        return {
            "format": "rotobridge",
            "version": RB.rbj.versionFor(headers),
            "source": ae.sourceBlock(comp),
            "range": [range[0], range[1]],
            "warnings": warn.messages,
            "shapes": headers
        };
    }

    function countPoints(doc) {
        var total = 0;
        for (var s = 0; s < doc.shapes.length; s++) {
            for (var key in doc.shapes[s]["frames"]) {
                if (RB.util.hasOwn(doc.shapes[s]["frames"], key)) {
                    total += doc.shapes[s]["frames"][key]["points"].length;
                }
            }
        }
        return total;
    }

    function countKeys(doc) {
        var total = 0;
        for (var s = 0; s < doc.shapes.length; s++) {
            total += doc.shapes[s]["keys"].length;
        }
        return total;
    }

    function main() {
        var comp = ae.activeComp();
        var target = File.saveDialog("Export RotoBridge .rbj", "*.rbj");
        if (!target) { return; }
        if (!/\.rbj$/i.test(target.fsName)) {
            target = new File(target.fsName + ".rbj");
        }

        var warn = new ae.Warnings();
        var restore = comp.time;
        var started = new Date().getTime();
        var doc;
        try {
            doc = buildDocument(comp, warn);
        } finally {
            /* Whatever happened, put the playhead back. The export moves it
             * 150 times and an artist did not ask for that. */
            comp.time = restore;
        }

        /* `stringify` validates before it serialises and throws rather than
         * returning something partial - prd.md section 11 requires aborting
         * over writing a file that looks correct until it is composited. */
        ae.writeText(target, RB.rbj.stringify(doc));
        var elapsed = (new Date().getTime() - started) / 1000.0;

        var lines = [
            "Exported " + doc.shapes.length + " shape(s) to " + target.name,
            "",
            "frames " + doc.range[0] + " to " + doc.range[1]
                + "  (" + countPoints(doc) + " points baked)",
            "took " + elapsed.toFixed(2) + " s",
            "",
            countKeys(doc) + " authored key(s) across all shapes; an importer"
                + " sets those and lets its drift pass fill the rest."
        ];
        if (warn.messages.length) {
            lines[lines.length] = "";
            lines[lines.length] = warn.messages.length + " warning(s):";
            for (var i = 0; i < warn.messages.length; i++) {
                lines[lines.length] = "  - " + warn.messages[i];
            }
        }
        alert(lines.join("\n"), "RotoBridge");
    }

    try {
        main();
    } catch (e) {
        alert("RotoBridge export failed:\n\n" + (e.message || e)
              + (e.line ? "\n\n(line " + e.line + ")" : ""), "RotoBridge");
    }
}());
