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

    /* How far a conformed key may leave the dense layer. The same 0.5 px the
     * importers default to and acceptance criterion 4 bounds, and measured in
     * rendered pixels to cost nothing: at 0.5 px against 0, no pixel on any
     * frame of the scene golden differs by more than 0.01 alpha. */
    var CONFORM_TOLERANCE = 0.5;

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
                    warn(RB.messages.render("name-collision",
                                            { name: name, first: seen[name],
                                              second: layer.name }));
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
        var mode = mask.maskMode;

        if (mask.inverted) {
            warn(RB.messages.render("inverted-dropped",
                                    { subject: "mask '" + entry.name + "'" }));
        }

        var expansion = ae.maskProp(mask, ae.MASK_EXPANSION);
        if (expansion && Math.abs(expansion.value) > 1e-9) {
            /* Not in the format and not in prd.md section 10 either - the probe
             * turned it up while looking for feather. Silently dropping a
             * non-zero expansion would change the matte, so it is named. */
            warn(RB.messages.render("expansion-dropped",
                                    { subject: "mask '" + entry.name + "'",
                                      px: expansion.value }));
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
            warn(RB.messages.render("transform-not-affine",
                                    { layer: layerName,
                                      px: RB.messages.px(off, 6) }));
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

    /* The three per-point shaping arrays section 9.3 names as readable but
     * .rbj has no member for. Zero is the authoring default for each, so a
     * non-zero entry is a value somebody set. */
    var FEATHER_SHAPING = [["featherInterps", "interpolation"],
                           ["featherTensions", "tension"],
                           ["featherRelCornerAngles", "corner angle"]];

    function applyFeather(path, points, state) {
        /* Read this frame's feather points, both ways. Returns the anchored
         * reading (spec/rbj-v2-draft.md section 6.3); the snapped one is
         * written onto `points` as it always was.
         *
         * Both, because which one the file carries is a per-shape decision
         * (section 6.7) and this is a per-frame reading. The shape does not
         * know until every frame is in whether the snap would lose anything,
         * so `finishFeather` chooses and throws the other away.
         *
         * Feather points live on the `Shape` the path evaluates to, so they
         * animate with it and have to be read inside the frame loop like
         * everything else here. */
        var radii = path.featherRadii;
        if (!radii || !radii.length) {
            state.anchorCounts[0] = true;
            return [];
        }

        state.sawFeather = true;
        for (var sh = 0; sh < FEATHER_SHAPING.length; sh++) {
            var values = path[FEATHER_SHAPING[sh][0]];
            for (var v = 0; values && v < values.length; v++) {
                if (values[v]) { state.shaping[FEATHER_SHAPING[sh][1]] = true; }
            }
        }
        var got = geom.snapFeatherPoints(path.featherSegLocs,
                                         path.featherRelSegLocs,
                                         radii, points.length);
        for (var i = 0; i < points.length; i++) {
            points[i]["feather"] = got.feather[i];
        }

        /* What the snap would cost, recorded rather than warned about: under
         * `anchored` nothing is snapped and nothing is dropped, so warning
         * here would describe damage the file does not end up taking. */
        if (got.snapped.length > state.snapped) {
            state.snapped = got.snapped.length;
        }
        for (var d = 0; d < got.dropped.length; d++) {
            state.dropped[state.dropped.length] = got.dropped[d];
        }

        var anchors = geom.featherAnchors(path.featherSegLocs,
                                          path.featherRelSegLocs,
                                          radii, points.length, state.closed);
        state.anchorCounts[anchors.length] = true;
        return anchors;
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
            states[s] = { sawFeather: false, vertexCount: null, closed: null,
                          snapped: 0, dropped: [], anchorCounts: {},
                          shaping: {} };
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
                var anchors = applyFeather(path, points, states[s]);

                var opacity = ae.maskProp(entry.mask, ae.MASK_OPACITY)
                                .valueAtTime(t, false);
                var feather = ae.maskProp(entry.mask, ae.MASK_FEATHER)
                                .valueAtTime(t, false);

                var record = {
                    /* Opacity is a percentage in the host and a 0-1 fraction in
                     * the format (spec section 7.2). Uniform feather is read
                     * per frame because it animates - run 6 measured a keyed
                     * `maskFeather` going 10 to 80 - and reading it once per
                     * shape would freeze it at the first frame. */
                    "opacity": Number(opacity) / 100.0,
                    "feather_uniform": [Number(feather[0]), Number(feather[1])],
                    "points": points
                };
                if (anchors.length) {
                    /* Kept only if the shape ends up `anchored`; finishFeather
                     * deletes it otherwise, which is what keeps a file whose
                     * anchors already sit on vertices byte-identical to what
                     * v1 wrote (section 6.7). */
                    record["feather_points"] = anchors;
                }
                headers[s]["frames"][String(frame)] = record;
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
                warn(RB.messages.render("open-spline-stroke",
                                        { subject: "mask '"
                                                   + shapes[s].name + "'" }));
            }
            finishFeather(headers[s], states[s], shapes[s].name, warn);
        }
        return headers;
    }

    function countsAgree(counts) {
        /* One anchor count across every frame, which section 6.3 requires for
         * the reason section 7.3 gives about vertices. A shape that fails this
         * cannot be `anchored` at all and takes the v1 snap instead, which is
         * the fallback section 6.8 keeps `snapFeatherPoints` around for. */
        var seen = 0;
        for (var n in counts) {
            if (RB.util.hasOwn(counts, n)) { seen += 1; }
        }
        return seen <= 1;
    }

    function stripFeather(frames, points_too) {
        for (var key in frames) {
            if (!RB.util.hasOwn(frames, key)) { continue; }
            delete frames[key]["feather_points"];
            if (!points_too) { continue; }
            var points = frames[key]["points"];
            for (var i = 0; i < points.length; i++) {
                delete points[i]["feather"];
            }
        }
    }

    function finishFeather(header, state, name, warn) {
        /* `feather_model` is a per-shape member but feather points are a
         * per-frame reading, so it can only be decided once every frame is in.
         * Section 6.7 is the decision, and it turns on one question: would the
         * snap lose anything?
         *
         * Under `per_point` the spec requires `feather` on every point of every
         * frame, so frames that had no feather points are filled with zeros -
         * which is also what they mean. Under `none` the member must be absent
         * entirely, because a zero written under `none` is indistinguishable
         * from an authored zero-width point. Under `anchored` no point carries
         * `feather` at all: two places to look is one too many. */
        var frames = header["frames"];
        var key, i, points;
        if (!state.sawFeather) {
            stripFeather(frames, true);
            return;
        }

        var shaped = [];
        for (var sh = 0; sh < FEATHER_SHAPING.length; sh++) {
            if (RB.util.hasOwn(state.shaping, FEATHER_SHAPING[sh][1])) {
                shaped[shaped.length] = FEATHER_SHAPING[sh][1];
            }
        }
        if (shaped.length) {
            /* Before the model decision, because both models take this loss:
             * .rbj carries where the feather sits and how far it reaches, and
             * nothing else about its profile. */
            warn(RB.messages.render("feather-shaping-dropped",
                                    { subject: "mask '" + name + "'",
                                      members: shaped.join(", ") }));
        }

        var lossy = state.snapped > 0 || state.dropped.length > 0;
        if (lossy && countsAgree(state.anchorCounts)) {
            /* Section 6.7: only a shape the snap would damage becomes a v2
             * file, so the compatibility cost is paid by exactly the files
             * that were being wrecked and by nothing else. */
            header["feather_model"] = "anchored";
            for (key in frames) {
                if (!RB.util.hasOwn(frames, key)) { continue; }
                points = frames[key]["points"];
                for (i = 0; i < points.length; i++) {
                    delete points[i]["feather"];
                }
            }
            warn(RB.messages.render("feather-anchored-v2",
                                    { subject: "mask '" + name + "'" }));
            return;
        }

        /* The v1 reading, and now the only path that can lose something, so
         * this is where the losses are finally said out loud. */
        header["feather_model"] = "per_point";
        stripFeather(frames, false);
        for (key in frames) {
            if (!RB.util.hasOwn(frames, key)) { continue; }
            points = frames[key]["points"];
            for (i = 0; i < points.length; i++) {
                if (!RB.util.hasOwn(points[i], "feather")) {
                    points[i]["feather"] = 0.0;
                }
            }
        }
        if (lossy && !countsAgree(state.anchorCounts)) {
            warn(RB.messages.render("feather-count-changes",
                                    { subject: "mask '" + name + "'" }));
        }
        if (state.snapped) {
            warn(RB.messages.render("feather-snapped",
                                    { subject: "mask '" + name + "'",
                                      count: state.snapped }));
        }
        for (var d = 0; d < state.dropped.length; d++) {
            var drop = state.dropped[d];
            warn(RB.messages.render("feather-duplicate-dropped",
                                    { subject: "mask '" + name + "'",
                                      vertex: drop.vertex, kept: drop.kept,
                                      dropped: drop.radius }));
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
                warn(RB.messages.render("key-off-grid",
                                        { subject: what,
                                          offset: RB.messages.px(off, 3),
                                          frame: frame }));
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

    var POINT_VECTORS = ["c", "in", "out"];

    function samePoints(a, b) {
        /* Exact equality, not a tolerance. Both sides come from the same bake
         * of the same host, so a segment that is genuinely flat is
         * bit-identical - measured, `test/golden/ae_scene.rbj` frames 19-23 of
         * `mixed`. Any doubt therefore reads as "not flat", which is the
         * pre-existing answer, so this can only ever add a `hold` it can
         * prove. */
        if (a.length !== b.length) { return false; }
        for (var i = 0; i < a.length; i++) {
            for (var m = 0; m < POINT_VECTORS.length; m++) {
                var k = POINT_VECTORS[m];
                if (a[i][k][0] !== b[i][k][0] || a[i][k][1] !== b[i][k][1]) {
                    return false;
                }
            }
            /* Per-point feather rides on the point and is part of the shape a
             * destination keys, so a segment whose feather breathes is not
             * flat even when every vertex stands still. */
            if (a[i]["feather"] !== b[i]["feather"]) { return false; }
        }
        return true;
    }

    function segmentVerdict(baked, from, to) {
        /* What the bake can say about the segment leaving `from`: "flat",
         * "moves", or **null for cannot tell**, which is the answer more often
         * than it looks and getting it wrong reads as a confident lie.
         *
         * A hold and a smooth interpolation produce identical frames whenever
         * their endpoints agree, so the bake can only separate them when the
         * question is observable at all. Two ways it is not:
         *
         * - **Adjacent keys.** A segment from f to f+1 has no interior frame,
         *   and both readings put the next key's value on f+1. Nothing to see.
         * - **A shape that never moves.** Flat all the way through and flat at
         *   the far key too: hold and ease agree everywhere, so neither is more
         *   true and the authored answer stands.
         *
         * A `hold` is only worth claiming where the shape stands still and then
         * jumps, which is what a hold means and what nothing else expresses. */
        var a = baked["frames"][String(from)];
        var far = baked["frames"][String(to)];
        var f, mid;
        if (!a || !far || to <= from + 1) { return null; }
        for (f = from + 1; f < to; f++) {
            mid = baked["frames"][String(f)];
            if (!mid) { return null; }
            if (!samePoints(a["points"], mid["points"])) { return "moves"; }
        }
        return samePoints(a["points"], far["points"]) ? null : "flat";
    }

    function holdOut(key) {
        /* A side carries an `ease` entry only when its interp is `ease` (spec
         * section 10.3), so promoting a side to `hold` has to take that
         * entry with it or the file fails its own validator. */
        key["interp"]["out"] = RB.interp.HOLD;
        if (key["ease"]) {
            delete key["ease"]["out"];
            if (!RB.util.hasOwn(key["ease"], "in")) { delete key["ease"]; }
        }
    }

    function denseVectors(baked, frames) {
        /* The dense layer as one flat array of numbers per frame: every scalar
         * a destination will interpolate, in a fixed order. A shape's point
         * count cannot change inside a range (spec section 7.3), so the order
         * is the same on every frame and the comparison is component-wise. */
        var dense = {};
        for (var f = 0; f < frames.length; f++) {
            var key = String(frames[f]);
            var points = baked["frames"][key]["points"];
            var flat = [];
            for (var i = 0; i < points.length; i++) {
                var point = points[i];
                flat[flat.length] = point["c"][0];
                flat[flat.length] = point["c"][1];
                flat[flat.length] = point["in"][0];
                flat[flat.length] = point["in"][1];
                flat[flat.length] = point["out"][0];
                flat[flat.length] = point["out"][1];
                if (RB.util.hasOwn(point, "feather")) {
                    flat[flat.length] = point["feather"];
                }
            }
            dense[key] = flat;
        }
        return dense;
    }

    function anySide(ease) {
        return RB.util.hasOwn(ease, "in") || RB.util.hasOwn(ease, "out");
    }

    function conformEase(keys, baked, frames, name, warn) {
        /* Rewrite every `ease` side as `linear` and add the keys that costs.
         *
         * Nuke's roto curves have no vocabulary for After Effects' temporal
         * ease at all - measured, `core/interp.to_nuke` and
         * `test/probe/probe_nuke_ease.py`: under the cubic types Nuke
         * recomputes a written slope, only interior keys honour an authored
         * tangent, and the best fit to a real AE curve is about 77 px off on a
         * 700 px travel. So an eased key crosses as a dense bake, and the
         * compositor opens a shape keyed on every frame with nothing saying
         * why. That cost is not avoidable; where it is paid is a choice.
         *
         * It is paid here, in the application that created the problem. The
         * file that reaches Nuke is then already in Nuke's vocabulary and
         * needs no correction at the other end, whatever tolerance the
         * compositor imports at. Measured on a static layer, which is what
         * roto actually sits on: an AE `linear` mask crosses with 0 corrective
         * keys and an eased one with 22 over a 25-frame range.
         *
         * `hold` and `linear` are left exactly as they are. Both cross
         * losslessly - `hold` maps to Nuke's step - and rewriting a hold as
         * linear would turn a frozen interval into a slide and then need a key
         * on every frame of it to flatten it again, which is paying keys to
         * destroy something that already transfers for free.
         *
         * A shape with no eased side at all is returned untouched.
         */
        var i, side, name_;
        var sides = ["in", "out"];
        var eased = 0, authored = 0;
        for (i = 0; i < keys.length; i++) {
            for (side = 0; side < sides.length; side++) {
                name_ = sides[side];
                if (keys[i]["interp"][name_] !== RB.interp.EASE) { continue; }
                eased += 1;
                /* An `ease` entry is what separates a curve the artist drew
                 * from one this exporter invented. A pinned endpoint or a
                 * transform key has no authored side to read, so section 10.3
                 * spells it `ease` with no parameters - "unknown, rely on the
                 * drift pass". Both are conformed, because Nuke reads either
                 * as cubic; only the first is worth telling the artist about,
                 * since only the first loses something they made. */
                if (RB.util.hasOwn(keys[i], "ease")
                    && RB.util.hasOwn(keys[i]["ease"], name_)) {
                    authored += 1;
                }
            }
        }
        if (!eased) { return keys; }

        var byFrame = {};
        var wanted = [];
        var holds = [];
        for (i = 0; i < keys.length; i++) {
            byFrame[String(keys[i]["frame"])] = keys[i];
            wanted[wanted.length] = keys[i]["frame"];
            /* A held segment is flat by definition, so the fit must not price
             * it as a straight line to the next key. Passing the holds through
             * is what keeps the conform from paying keys to destroy them. */
            if (keys[i]["interp"]["out"] === RB.interp.HOLD) {
                holds[holds.length] = keys[i]["frame"];
            }
        }

        var fit = RB.drift.linearFit(frames, denseVectors(baked, frames),
                                     wanted, CONFORM_TOLERANCE, holds);
        var out = [];
        for (i = 0; i < fit.keys.length; i++) {
            var frame = fit.keys[i];
            var key = RB.util.hasOwn(byFrame, String(frame))
                ? byFrame[String(frame)]
                : { "frame": frame,
                    "interp": { "in": RB.interp.LINEAR,
                                "out": RB.interp.LINEAR } };
            for (side = 0; side < sides.length; side++) {
                if (key["interp"][sides[side]] === RB.interp.EASE) {
                    key["interp"][sides[side]] = RB.interp.LINEAR;
                    /* A side carries an `ease` entry only while its interp is
                     * `ease` (spec section 10.3), so the parameters go with
                     * the side that named them. */
                    if (RB.util.hasOwn(key, "ease")) {
                        delete key["ease"][sides[side]];
                    }
                }
            }
            if (RB.util.hasOwn(key, "ease") && !anySide(key["ease"])) {
                delete key["ease"];
            }
            out[out.length] = key;
        }

        var added = out.length - keys.length;
        if (authored) {
            warn(RB.messages.render("ease-conformed",
                                    { subject: "mask '" + name + "'",
                                      count: authored, added: added,
                                      tolerance: CONFORM_TOLERANCE }));
        } else if (added) {
            warn(RB.messages.render("keys-added",
                                    { subject: "mask '" + name + "'",
                                      added: added,
                                      tolerance: CONFORM_TOLERANCE }));
        }
        return out;
    }

    function sparseKeys(comp, entry, frames, baked, warn) {
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
        var unheld = 0;
        for (i = 0; i < all.length; i++) {
            var frame = all[i];
            var at = RB.util.hasOwn(onPath.index, String(frame))
                ? onPath.index[String(frame)] : null;
            /* A frame with no path key of its own is a pinned endpoint or a
             * transform key. Nothing was authored there to read, so the side is
             * unknown, which spec section 10.3 spells `ease` with no
             * parameters: "smooth, parameters unknown, rely on the drift
             * pass". */
            var key = at === null
                ? { "frame": frame,
                    "interp": { "in": RB.interp.EASE, "out": RB.interp.EASE } }
                : pathKey(path, at, frame);

            /* Then the bake overrules both of them on one question.
             *
             * Spec section 10.2 defines `hold` as a property of the SEGMENT -
             * "when `A.interp.out` is `hold` the segment is flat" - and
             * `frames` carries the composite, path through layer transform.
             * The path property alone cannot answer it and gets it wrong in
             * both directions: a transform key landing inside a held segment
             * reads `ease` while the shape stands still, and a hold authored
             * under a moving layer reads `hold` while the shape moves. Both
             * are claims the dense layer sitting beside them contradicts, and
             * `frames` is the one that renders.
             *
             * Only the outgoing side, because only it governs a segment
             * (section 10.2, and `interp.to_nuke` reads only `out` for step).
             * Only where there is a next key: the last key has no segment
             * leaving it (section 10.1). Only the hold question - whether what
             * is left is linear or eased is a fit, not a measurement, and
             * belongs to the drift pass. And only where the bake can actually
             * tell, which `segmentVerdict` decides and is not always. */
            var verdict = i + 1 < all.length
                ? segmentVerdict(baked, frame, all[i + 1]) : null;
            if (verdict === "flat") {
                holdOut(key);
            } else if (verdict === "moves"
                       && key["interp"]["out"] === RB.interp.HOLD) {
                key["interp"]["out"] = RB.interp.EASE;
                unheld += 1;
            }
            out[out.length] = key;
        }
        if (unheld) {
            warn(RB.messages.render("hold-under-motion",
                                    { subject: "mask '" + name + "'",
                                      count: unheld }));
        }
        var authored = copyKeys(out);
        var conformed = conformEase(out, baked, frames, name, warn);
        if (conformed !== out) {
            /* The conform rewrote something, and it rewrites the key objects
             * in place - which is why the copy was taken first. The authored
             * keys ride along as provenance (spec/rbj-v3-draft.md section 5):
             * the shape survives via the bake either way, but without this
             * the artist's timing was gone from the file forever, foreclosing
             * any future importer that could honour it. Importers ignore it,
             * exactly as they ignore warnings. */
            baked["pre_conform_keys"] = authored;
        }
        return conformed;
    }

    function copyKeys(keys) {
        /* A deep copy of a keys array - three known levels, written out
         * rather than recursed because that is all a key can hold. */
        var out = [];
        for (var i = 0; i < keys.length; i++) {
            var key = { "frame": keys[i]["frame"],
                        "interp": { "in": keys[i]["interp"]["in"],
                                    "out": keys[i]["interp"]["out"] } };
            if (RB.util.hasOwn(keys[i], "ease")) {
                var sides = ["in", "out"];
                var ease = {};
                for (var s = 0; s < sides.length; s++) {
                    if (RB.util.hasOwn(keys[i]["ease"], sides[s])) {
                        ease[sides[s]] =
                            keys[i]["ease"][sides[s]].slice(0);
                    }
                }
                key["ease"] = ease;
            }
            out[out.length] = key;
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
            headers[s]["keys"] = sparseKeys(comp, shapes[s], frames, headers[s],
                                            warn.fn());
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
        /* Folding is the writer's decision, made at the last moment so the
         * alert below still counts the dense document. The "\n" matches
         * export_to_file on the Nuke side, and both live here, not in
         * stringify, whose bare output the cross-check compares byte for
         * byte between the two implementations. */
        ae.writeText(target, RB.rbj.stringify(RB.rbj.foldFrames(doc)) + "\n");
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
