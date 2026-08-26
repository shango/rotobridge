/*
 * RotoBridge - After Effects import. File > Scripts > Run Script File...
 *
 * Reads a `.rbj` and builds masks (prd.md section 9.1). The authored `keys` are
 * set with the interpolation the file asked for, then the drift pass measures
 * what After Effects actually renders between them and pins whatever moved with
 * extra keys. That is tier 3 of prd.md section 7: the interpolation fit can be
 * wrong, the positions cannot.
 *
 * One control decides the mode, `tolerance` in pixels (prd.md section 8):
 * infinity leaves the authored keys alone, 0 keys every frame and reproduces the
 * file exactly at the cost of an uneditable shape, and the 0.5 default lands
 * corrective keys only where the mismatch is visible. A file with no `keys` at
 * all is spec section 9's dense document and keys every frame whatever tolerance
 * was asked for - that is a claim about the geometry, not a fallback.
 *
 * The geometry is converted to layer space frame-major, in one pass, before any
 * of that starts (prd.md section 9.1 step 4): `compPointToSource` has no time
 * parameter, so it can only be read at the current `comp.time`, and a target
 * layer with an animated transform needs it set per frame. The drift pass then
 * iterates over `setValueAtTime` and `valueAtTime`, neither of which touches
 * `comp.time`, so it never pays that cost again.
 */

#include "rotobridge_ae.jsx"

(function () {
    var ae = RB.ae;
    var geom = RB.geom;

    var AFFINE_TOLERANCE = 1e-4;

    /* How far a dropped opacity or feather sample may sit from the line drawn
     * through the samples kept either side of it: a thousandth of a percent of
     * opacity, or a thousandth of a pixel of feather. Both are far below what
     * After Effects can render, and it is loose enough that the residue of the
     * host's own arithmetic cannot masquerade as a curve worth keys. */
    var COLLAPSE_TOLERANCE = 1e-3;

    /* Adding a mask, and the `Shape` members that carry feather points, are the
     * calls Phase 0 exercised in probe section E2 rather than inferred: run 6
     * wrote `featherRadii = [30, -15]` with `featherTypes = [0, 1]` and read
     * back exactly that, signs intact. */
    var MASK_PARADE = "ADBE Mask Parade";
    var MASK_ATOM = "ADBE Mask Atom";

    function readDocument(file) {
        /* `parse` validates and throws with every reason at once, so a
         * hand-edited file reports all its problems in one alert. */
        return RB.rbj.parse(ae.readText(file));
    }

    function chooseShapes(doc, subset, warn) {
        /* The shapes to build, in file order. An unmatched name is a mistake
         * worth naming: silently importing nothing looks like a broken script. */
        if (!subset || !subset.length) { return doc.shapes.slice(0); }
        var wanted = {};
        var i;
        for (i = 0; i < subset.length; i++) { wanted[subset[i]] = false; }

        var out = [];
        for (i = 0; i < doc.shapes.length; i++) {
            /* By id first and name second: an id is unique when present (the
             * validator enforces it); a name is a display label that may
             * collide. Either is what the file or the record shows the
             * artist. */
            var name = doc.shapes[i].name;
            var id = doc.shapes[i].id;
            var hit = RB.util.hasOwn(wanted, name) ? name
                : (id !== undefined && RB.util.hasOwn(wanted, id) ? id : null);
            if (hit !== null) {
                wanted[hit] = true;
                out[out.length] = doc.shapes[i];
            }
        }
        for (var key in wanted) {
            if (RB.util.hasOwn(wanted, key) && !wanted[key]) {
                warn(RB.messages.render("subset-missing", { name: key }));
            }
        }
        if (!out.length) {
            throw new Error("none of the requested shape names are in this file");
        }
        return out;
    }

    function targetLayer(comp, doc) {
        /* The selected layer, or a new comp-sized solid.
         *
         * A new solid is created with an identity transform, which makes the
         * comp-to-layer conversion below a no-op - the simple case, and the
         * one an artist gets by default. */
        if (comp.selectedLayers.length === 1) {
            var layer = comp.selectedLayers[0];
            ae.checkLayer(layer);
            return layer;
        }
        if (comp.selectedLayers.length > 1) {
            throw new Error("select one layer to add the masks to, or none to"
                            + " have a solid created");
        }
        return comp.layers.addSolid([0, 0, 0], "RotoBridge",
                                    comp.width, comp.height, comp.pixelAspect);
    }

    function checkSource(doc, comp, warn) {
        /* Spec section 12.2 makes both of these soft failures. Neither stops
         * an import, and both change what the artist sees, so neither is
         * allowed to pass silently. */
        var src = doc.source;
        if (src.width !== comp.width || src.height !== comp.height) {
            warn(RB.messages.render("comp-size-differs",
                                    { src: src.width + "x" + src.height,
                                      dst: comp.width + "x" + comp.height }));
        }
        if (Math.abs(src.fps - comp.frameRate) > 1e-6) {
            warn(RB.messages.render("fps-differs",
                                    { src: src.fps, dst: comp.frameRate }));
        }
        if (Math.abs(src.pixel_aspect - comp.pixelAspect) > 1e-6) {
            warn(RB.messages.render("pixel-aspect-differs",
                                    { src: src.pixel_aspect,
                                      dst: comp.pixelAspect }));
        }
    }

    function inverseAffine(layer, warn) {
        /* The comp-to-layer transform at the current `comp.time`, as an affine.
         *
         * Same argument as the export's forward pass, and the same runtime
         * check: three probes fix the map, a fourth proves it. Returns null to
         * mean "use the host per point", which is slower and always right. */
        var span = geom.AFFINE_SPAN;
        var m = geom.affineFromProbes(ae.pointToLayer(layer, [0, 0]),
                                      ae.pointToLayer(layer, [span, 0]),
                                      ae.pointToLayer(layer, [0, span]));
        var check = [span * 0.37, span * -0.61];
        var off = geom.affineDisagreement(m, check,
                                          ae.pointToLayer(layer, check));
        if (off > AFFINE_TOLERANCE) {
            warn(RB.messages.render("transform-not-affine",
                                    { layer: layer.name,
                                      px: RB.messages.px(off, 6) }));
            return null;
        }
        return m;
    }

    function buildShape(record, layer, affine, compHeight, model, closed) {
        /* One frame of one shape, as the `Shape` object After Effects wants.
         *
         * Canonical space is Y-up with the origin bottom-left, comp space is
         * Y-down from the top, and mask paths are in LAYER space - so every
         * point makes both hops. Tangents make only the second: they are
         * vertex-relative, so the Y flip needs no height and the layer
         * transform contributes only its linear part. */
        var points = record.points;
        var shape = new Shape();
        var vertices = [];
        var inTangents = [];
        var outTangents = [];
        var feather = [];

        for (var i = 0; i < points.length; i++) {
            var pt = points[i];
            var comp = geom.canonicalToCompPoint(pt["c"], compHeight);
            var tIn = geom.canonicalToCompTangent(pt["in"]);
            var tOut = geom.canonicalToCompTangent(pt["out"]);

            if (affine) {
                vertices[i] = geom.applyAffinePoint(affine, comp);
                inTangents[i] = geom.applyAffineTangent(affine, tIn);
                outTangents[i] = geom.applyAffineTangent(affine, tOut);
            } else {
                vertices[i] = ae.pointToLayer(layer, comp);
                inTangents[i] = ae.tangentToLayer(layer, comp, tIn);
                outTangents[i] = ae.tangentToLayer(layer, comp, tOut);
            }
            if (model === "per_point") { feather[i] = pt["feather"]; }
        }

        shape.vertices = vertices;
        shape.inTangents = inTangents;
        shape.outTangents = outTangents;
        shape.closed = closed;

        /* Two feather models reach the same four arrays, and this is the host
         * that can take either without losing anything - spec/rbj-v2-draft.md
         * section 6 exists because After Effects anchors feather anywhere
         * along a segment and .rbj v1 could only say "at a vertex".
         *
         * `per_point` pins one point per vertex to the start of its own
         * segment; `anchored` puts each one where the file says. A point's
         * direction cannot be changed after creation, so in both cases the
         * type has to be right up front rather than corrected afterwards. */
        var made = null;
        if (model === "per_point") {
            made = geom.featherPointsFromVertices(feather);
        } else if (model === "anchored") {
            made = geom.featherPointsFromAnchors(record["feather_points"]);
        }
        if (made) {
            var flat = [];
            for (var f = 0; f < made.radii.length; f++) { flat[f] = 0; }
            shape.featherSegLocs = made.segLocs;
            shape.featherRelSegLocs = made.relLocs;
            shape.featherRadii = made.radii;
            shape.featherTypes = made.types;
            shape.featherInterps = flat;
            shape.featherTensions = flat;
            shape.featherRelCornerAngles = flat;
        }
        return shape;
    }

    function createMask(layer, spec) {
        /* Returns the mask's INDEX in the parade, not the mask.
         *
         * After Effects invalidates a handle into the parade when the parade
         * changes, and every later `addProperty` changes it - so a script that
         * creates all its masks and then writes into what `addProperty` handed
         * back is holding one stale reference per mask by the time it writes.
         * Measured in the host on 2026-08-21: six shapes failed with "object
         * invalid" and the same import restricted to one shape succeeded.
         *
         * This is the hazard the Nuke side already carries - `append()` copies
         * into the tree, re-fetch the live child from its parent - in a
         * different API. An index cannot go stale; only a handle can. */
        var parade = layer.property(MASK_PARADE);
        var mask = parade.addProperty(MASK_ATOM);
        mask.name = spec.name;
        mask.maskMode = ae.modeFromBlend(spec.blend);
        mask.maskFeatherFalloff = ae.falloffFromRbj(spec.feather_falloff);
        return parade.numProperties;
    }

    function liveMask(layer, index) {
        /* A fresh handle to a mask, fetched at the moment it is used. */
        return layer.property(MASK_PARADE).property(index);
    }

    function bakeTargets(comp, layer, specs, frames, offset, warn) {
        /* Every frame of every shape, converted to layer space, in one
         * frame-major pass.
         *
         * This is the only loop that touches `comp.time`, and it is why the
         * drift pass below can iterate freely: `setValueAtTime` and
         * `valueAtTime` both take their own time argument, so once the targets
         * are in hand the playhead never has to move again. Setting it measured
         * 5.75-20.89 ms in Phase 0 - paying that per drift pass would cost more
         * than the rest of the import put together.
         */
        var targets = [];
        var s;
        for (s = 0; s < specs.length; s++) { targets[s] = {}; }

        for (var f = 0; f < frames.length; f++) {
            var frame = frames[f];
            comp.time = ae.frameToTime(comp, frame + offset);
            var affine = inverseAffine(layer, warn);
            for (s = 0; s < specs.length; s++) {
                targets[s][String(frame)] = buildShape(
                    specs[s]["frames"][String(frame)], layer, affine,
                    comp.height, specs[s]["feather_model"],
                    specs[s]["closed"]);
            }
        }
        return targets;
    }

    /* --- the sparse layer --------------------------------------------------- */

    function keyPlan(spec, frames) {
        /* Which frames to key, and the file's key against each one.
         *
         * An absent `keys` is spec section 9's dense import: every frame is a
         * key. That is a claim about the geometry, not a fallback, so it is not
         * merged with the tolerance control - a dense document keys every frame
         * whatever tolerance was asked for, and leaves the drift pass nothing to
         * correct.
         */
        var keys = RB.util.hasOwn(spec, "keys") ? spec["keys"] : null;
        if (!keys) {
            return { frames: frames.slice(0), byFrame: {}, dense: true };
        }
        var out = [];
        var byFrame = {};
        for (var i = 0; i < keys.length; i++) {
            var frame = Math.floor(Number(keys[i]["frame"]));
            out[out.length] = frame;
            byFrame[String(frame)] = keys[i];
        }
        return { frames: out, byFrame: byFrame, dense: false };
    }

    function easeFor(pair) {
        /* One side of an .rbj `ease` as the host's own object. A side that is
         * `ease` with no parameters - spec section 10.3's "smooth, parameters
         * unknown" - gets After Effects' own default, which is what a key the
         * artist never touched carries. */
        if (!pair) {
            return new KeyframeEase(0, RB.interp.AE_DEFAULT_INFLUENCE);
        }
        var got = RB.interp.easeToAe(pair);
        return new KeyframeEase(got[1], got[0]);
    }

    function applyKeyInterp(prop, at, key) {
        var linear = KeyframeInterpolationType.LINEAR;
        if (!key) {
            /* A corrective key, and corrective keys are linear. One exists
             * precisely because the host's own interpolation left the dense
             * layer, so a bezier one could overshoot between corrective keys
             * and manufacture fresh drift; straight segments between measured
             * frames cannot, which is what makes each pass reduce the error
             * rather than move it around. */
            prop.setInterpolationTypeAtKey(at, linear, linear);
            return;
        }
        var sides = key["interp"];
        var ease = RB.util.hasOwn(key, "ease") ? key["ease"] : null;
        if (ease) {
            /* Ease first, type second. `setTemporalEaseAtKey` forces the key to
             * BEZIER, so the types have to go on afterwards or a `hold` side
             * arrives smooth. Doing it in this order keeps the ease values -
             * After Effects stores them per key and honours them only on the
             * sides that are bezier. */
            prop.setTemporalEaseAtKey(at, [easeFor(ease["in"])],
                                      [easeFor(ease["out"])]);
        }
        prop.setInterpolationTypeAtKey(at, RB.interp.sideToAe(sides["in"]),
                                       RB.interp.sideToAe(sides["out"]));
    }

    function pushInterp(comp, prop, plan, offset) {
        /* Push the authored interpolation onto every key, by index.
         *
         * Re-run after every drift pass rather than once: the pass inserts
         * keys, and every index above an insertion moves. Matching by key time
         * rather than by position is what makes that safe.
         */
        var fps = comp.frameRate;
        var sf = ae.startFrame(comp);
        for (var at = 1; at <= prop.numKeys; at++) {
            var frame = RB.timing.secondsToFrame(prop.keyTime(at), fps, sf)
                        - offset;
            applyKeyInterp(prop, at,
                           RB.util.hasOwn(plan.byFrame, String(frame))
                               ? plan.byFrame[String(frame)] : null);
        }
    }

    var MEASURED = ["vertices", "inTangents", "outTangents"];

    function featherByAnchor(shape) {
        /* Feather radii keyed by where each point actually sits on the path,
         * not by its position in the array.
         *
         * After Effects hands feather points back in an order of its own, and
         * two probes measured what it does. The anchor is always renamed: a
         * point written at (segment i, rel 0) returns at (segment i-1, rel 1),
         * the same place described as the end of the previous segment
         * (`probe_ae_feather_order.jsx`). And at an INTERPOLATED frame the
         * points are regrouped by type, non-negative before negative, for
         * LINEAR keys as well as BEZIER (`probe_ae_feather_interpolated.jsx`).
         *
         * Both preserve every point; only the array order moves. So comparing
         * `featherRadii` element by element measures the host's bookkeeping
         * instead of the feather, which is what left `feathered` from
         * `test/golden/ae_scene.rbj` with exactly 27.0000 px of drift the pass
         * could never remove - the file's feather is [30, -15, 0, 12] on every
         * frame, and 12 - (-15) = 27.
         *
         * `seg + rel` is the position in segment units and is invariant under
         * the rename: (0, 0) and (n-1, 1) both land on vertex 0 once the sum
         * wraps. Keying on it makes the comparison independent of both
         * reorderings without assuming either.
         */
        var out = {};
        var radii = shape.featherRadii || [];
        var n = shape.vertices.length;
        if (!n) { return out; }
        for (var i = 0; i < radii.length; i++) {
            var seg = Number(shape.featherSegLocs[i]);
            var rel = Number(shape.featherRelSegLocs[i]);
            var pos = (seg + rel) % n;
            out[pos.toFixed(4)] = Number(radii[i]);
        }
        return out;
    }

    function deviation(got, target) {
        /* How far the host's own interpolation sits from the dense layer, in
         * pixels - the worst single coordinate.
         *
         * Tangents are measured on the same scale as vertices and against the
         * same tolerance. They are vertex-relative pixel offsets, and a tangent
         * that drifts bends the rendered edge exactly as far as a vertex that
         * drifts does. Feather radii are pixels too.
         */
        var worst = 0.0;
        var i, j, k, d;
        for (k = 0; k < MEASURED.length; k++) {
            var mine = got[MEASURED[k]];
            var theirs = target[MEASURED[k]];
            for (i = 0; i < theirs.length; i++) {
                for (j = 0; j < 2; j++) {
                    d = Math.abs(mine[i][j] - theirs[i][j]);
                    if (d > worst) { worst = d; }
                }
            }
        }
        var want = featherByAnchor(target);
        var have = featherByAnchor(got);
        var at;
        for (at in want) {
            if (!RB.util.hasOwn(want, at)) { continue; }
            d = Math.abs((RB.util.hasOwn(have, at) ? have[at] : 0) - want[at]);
            if (d > worst) { worst = d; }
        }
        for (at in have) {
            /* A point the host carries that the dense layer does not is a real
             * difference, not a bookkeeping one. */
            if (!RB.util.hasOwn(have, at) || RB.util.hasOwn(want, at)) {
                continue;
            }
            d = Math.abs(have[at]);
            if (d > worst) { worst = d; }
        }
        return worst;
    }

    function removeKeyAtFrame(comp, prop, frame) {
        /* Take one key off, addressed by frame rather than by index.
         *
         * After Effects renumbers every key above the one that goes, so an
         * index read before a removal is worthless after it. `nearestKeyIndex`
         * is the host's own lookup and it always returns something, so the time
         * it lands on is checked against the one asked for - half a frame is
         * far wider than the rounding `RB.timing` leaves behind and far
         * narrower than the gap to the next key.
         */
        if (!prop.numKeys) { return; }
        var at = ae.frameToTime(comp, frame);
        var index = prop.nearestKeyIndex(at);
        if (Math.abs(prop.keyTime(index) - at) * comp.frameRate < 0.5) {
            prop.removeKey(index);
        }
    }

    function buildOne(comp, mask, spec, targets, frames, offset, tolerance,
                      warn) {
        /* Set one shape's keys, then let the drift pass bound what is left.
         *
         * Returns a report: how many keys the file authored, how many the pass
         * had to add, and the worst residual. prd.md section 8 requires this -
         * it is what tells an artist which shape to re-import tighter.
         */
        var prop = ae.maskProp(mask, ae.MASK_PATH);
        var plan = keyPlan(spec, frames);
        var written = {};

        function applyKeys(wanted) {
            /* `RB.drift.correct` asks for exactly this set, not a superset: its
             * sweep tries the path without a key to find out whether the key is
             * needed. A frame already written is already correct, so only the
             * difference in each direction costs a host call. The interpolation
             * is re-pushed every time, because the keys whose indices moved are
             * not only the new ones. */
            var asked = {}, frame, i;
            for (i = 0; i < wanted.length; i++) { asked[String(wanted[i])] = true; }
            for (frame in written) {
                if (!RB.util.hasOwn(written, frame)
                        || RB.util.hasOwn(asked, frame)) { continue; }
                removeKeyAtFrame(comp, prop, Number(frame) + offset);
                delete written[frame];
            }
            for (i = 0; i < wanted.length; i++) {
                frame = wanted[i];
                if (!RB.util.hasOwn(written, String(frame))) {
                    prop.setValueAtTime(ae.frameToTime(comp, frame + offset),
                                        targets[String(frame)]);
                    written[String(frame)] = true;
                }
            }
            pushInterp(comp, prop, plan, offset);
        }

        function measure(frame) {
            return deviation(
                prop.valueAtTime(ae.frameToTime(comp, frame + offset), false),
                targets[String(frame)]);
        }

        var got = RB.drift.correct(frames, plan.frames, applyKeys, measure,
                                   plan.dense ? 0.0 : tolerance);

        if (got.worst > tolerance) {
            warn(RB.messages.render("drift-residual",
                                    { subject: "shape '" + spec.name + "'",
                                      residual: RB.messages.px(got.worst, 4),
                                      frame: got.at + offset }));
        }

        var authored = 0;
        var last = frames[frames.length - 1];
        for (var i = 0; i < plan.frames.length; i++) {
            if (plan.frames[i] >= frames[0] && plan.frames[i] <= last) {
                authored += 1;
            }
        }
        /* `worst_frame` is in **host** numbering, offset already applied, so
         * that it names the frame an artist would look at. The drift pass
         * works in source frames and has no offset to apply. */
        return { name: spec.name,
                 feather_model: spec.feather_model,
                 points: spec.frames[String(frames[0])].points.length,
                 authored: authored,
                 corrective: got.keys.length - authored,
                 residual: got.worst,
                 worst_frame: got.at === null ? null : got.at + offset };
    }

    /* --- opacity and uniform feather ---------------------------------------- */

    function same(a, b) {
        if (RB.util.isArray(a)) {
            for (var i = 0; i < a.length; i++) {
                if (Math.abs(a[i] - b[i]) > 1e-9) { return false; }
            }
            return true;
        }
        return Math.abs(a - b) <= 1e-9;
    }

    function collapse(frames, samples, tolerance) {
        /* The samples a linear reconstruction of this attribute needs.
         *
         * An artist opening a shape whose opacity was never animated should
         * find one key on it, not a hundred and fifty - and one who ramped it
         * across a hundred frames authored two keys and should get two back.
         * Opacity and uniform feather have no sparse layer in the format (spec
         * section 7.2): they arrive as one value per frame, so writing them
         * straight out keys every frame of the range whatever the artist did.
         *
         * The dense layer is still where the values come from. What changes is
         * only which of them are spelled as keys, and a sample is dropped only
         * where the line through the keys either side of it lands on top of it
         * anyway. A curve that line cannot follow stays dense, which is the
         * policy the mask path already gets from the drift pass: honour what
         * can be honoured, pin the rest.
         *
         * Tolerance 0 keeps every sample. It is the mode that reproduces the
         * file exactly at the cost of an uneditable shape (prd.md section 8),
         * and a line drawn through two of these values reproduces the rest to
         * within the arithmetic, not to the bit - a real Nuke file's uniform
         * feather crosses 7e-07 px off it. An artist who asked for exact gets
         * exact. Collapsing a value that never changes is not that trade and
         * happens either way: one key is every sample, spelled once.
         */
        var i;
        for (i = 1; i < samples.length; i++) {
            if (!same(samples[i].value, samples[0].value)) { break; }
        }
        if (i >= samples.length) { return samples.slice(0, 1); }
        if (tolerance <= 0) { return samples; }

        var dense = {};
        for (i = 0; i < frames.length; i++) {
            dense[String(frames[i])] = RB.util.isArray(samples[i].value)
                ? samples[i].value : [samples[i].value];
        }
        var got = RB.drift.linearFit(frames, dense,
                                     [frames[0], frames[frames.length - 1]],
                                     COLLAPSE_TOLERANCE);
        var keep = {};
        for (i = 0; i < got.keys.length; i++) {
            keep[String(got.keys[i])] = true;
        }
        var out = [];
        for (i = 0; i < frames.length; i++) {
            if (RB.util.hasOwn(keep, String(frames[i]))) {
                out[out.length] = samples[i];
            }
        }
        return out;
    }

    function writeAttributes(comp, mask, spec, frames, offset, tolerance) {
        /* Opacity and uniform feather are per frame in the format because both
         * animate (spec section 7.2, and Phase 0 run 6 measured a keyed
         * `maskFeather`), so they come out of the dense layer rather than the
         * sparse one - the file carries no keys for them to honour. */
        var opacity = [];
        var feather = [];
        for (var f = 0; f < frames.length; f++) {
            var record = spec["frames"][String(frames[f])];
            var t = ae.frameToTime(comp, frames[f] + offset);
            opacity[f] = { t: t, value: Number(record["opacity"]) * 100.0 };
            feather[f] = { t: t,
                           value: [Number(record["feather_uniform"][0]),
                                   Number(record["feather_uniform"][1])] };
        }
        setSamples(ae.maskProp(mask, ae.MASK_OPACITY),
                   collapse(frames, opacity, tolerance));
        setSamples(ae.maskProp(mask, ae.MASK_FEATHER),
                   collapse(frames, feather, tolerance));
    }

    function setSamples(prop, samples) {
        for (var i = 0; i < samples.length; i++) {
            prop.setValueAtTime(samples[i].t, samples[i].value);
        }
        setLinear(prop);
    }

    function setLinear(prop) {
        /* Every frame these carry is a key, so the interpolation between them
         * cannot change a value the format describes. It is still set
         * explicitly: a bezier key left at the host's default eases in
         * sub-frame space, which shows up under motion blur and on a retime,
         * and neither is something the file asked for. */
        var linear = KeyframeInterpolationType.LINEAR;
        for (var i = 1; i <= prop.numKeys; i++) {
            prop.setInterpolationTypeAtKey(i, linear, linear);
        }
    }

    function importShapes(comp, layer, doc, specs, offset, tolerance, warn) {
        var maskIndex = [];
        var s;
        for (s = 0; s < specs.length; s++) {
            /* After Effects cannot matte an open path at all: a mask whose
             * path is open produces no alpha. Open paths are usable in AE on a
             * shape layer, for strokes and trim paths, but not for masking.
             * Reported by the user 2026-08-21 and it is why this warns on every
             * open spline rather than only on one from another application -
             * the provenance makes no difference to the result.
             * spec/rbj-v2-draft.md section 5. */
            if (specs[s]["closed"] === false) {
                warn(RB.messages.render("open-spline-renders-nothing",
                                        { subject: "shape '"
                                                   + specs[s].name + "'" }));
            }
            maskIndex[s] = createMask(layer, specs[s]);
        }

        var frames = RB.timing.frameRange(doc.range[0], doc.range[1]);
        var targets = bakeTargets(comp, layer, specs, frames, offset, warn);

        var reports = [];
        for (s = 0; s < specs.length; s++) {
            /* Re-fetched here, once per shape, rather than carried down from
             * the creation loop above: every `addProperty` in that loop
             * invalidated the handles the ones before it returned. */
            var mask = liveMask(layer, maskIndex[s]);
            reports[s] = buildOne(comp, mask, specs[s], targets[s], frames,
                                  offset, tolerance, warn);
            writeAttributes(comp, mask, specs[s], frames, offset,
                            tolerance);
        }
        return { count: specs.length, frames: frames, reports: reports };
    }

    var DEFAULT_TOLERANCE = 0.5;

    function parseTolerance(raw) {
        var text = String(raw).replace(/^\s+/, "").replace(/\s+$/, "");
        if (/^inf(inity)?$/i.test(text)) { return Infinity; }
        var value = Number(text);
        if (text === "" || isNaN(value)) {
            throw new Error("'" + raw + "' is not a drift tolerance in pixels");
        }
        if (value < 0) {
            throw new Error("drift tolerance must not be negative; got " + value);
        }
        return value;
    }

    function askTolerance(specs) {
        /* Only asked when the file has something to honour. A dense document
         * keys every frame whatever the answer is, and a question whose answer
         * changes nothing is worse than no question. Returns null if the artist
         * cancelled. */
        var sparse = false;
        for (var i = 0; i < specs.length; i++) {
            if (RB.util.hasOwn(specs[i], "keys") && specs[i]["keys"]) {
                sparse = true;
            }
        }
        if (!sparse) { return 0.0; }
        var raw = prompt("Drift tolerance in pixels\n\nHow far the shape may"
            + " sit from the file between the keys it authored.\n0 keys every"
            + " frame: exact, but not editable.\n'inf' keeps the authored keys"
            + " and nothing else.", String(DEFAULT_TOLERANCE));
        return raw === null ? null : parseTolerance(raw);
    }

    function parseSubset(raw) {
        if (!raw) { return []; }
        var parts = String(raw).split(",");
        var out = [];
        for (var i = 0; i < parts.length; i++) {
            var name = parts[i].replace(/^\s+/, "").replace(/\s+$/, "");
            if (name.length) { out[out.length] = name; }
        }
        return out;
    }

    function stamp(now) {
        /* "2026-08-22 09:14:03", which is what `time.strftime` writes on the
         * Nuke side. ExtendScript has no `strftime` and no `padStart`. */
        function two(n) { return (n < 10 ? "0" : "") + n; }
        return now.getFullYear() + "-" + two(now.getMonth() + 1) + "-"
            + two(now.getDate()) + " " + two(now.getHours()) + ":"
            + two(now.getMinutes()) + ":" + two(now.getSeconds());
    }

    function buildRecord(doc, file, comp, layer, built, offset, tolerance,
                         warn) {
        /* Everything this import knows, in the shape `RB.report` renders.
         *
         * The two warning lists stay apart: what the exporter already lost is
         * evidence about the other application, and a record that ran them
         * together would answer "which one dropped it?" with "one of them
         * did". Mirrors `build_record` in `nuke/rotobridge_import.py`. */
        return {
            written: stamp(new Date()),
            tool: RB.LABEL,
            host: "After Effects " + app.version,
            target: "comp '" + comp.name + "', layer '" + layer.name + "'",
            source_file: file.fsName,
            source: doc.source,
            version: doc.version,
            range: doc.range,
            offset: offset,
            tolerance: tolerance,
            shapes: built.reports,
            file_warnings: doc.warnings,
            import_warnings: warn.messages
        };
    }

    function writeRecord(record, file, warn) {
        /* Append the record beside the project, or beside the .rbj when the
         * project has never been saved. Returns the path, or null.
         *
         * A record that cannot be written is a warning and not an exception:
         * the masks are already in the comp by the time this runs, and losing
         * an import over a read-only folder would be a worse failure than the
         * one being reported. */
        var anchor = (app.project.file ? app.project.file.fsName : file.fsName);
        var path = RB.report.pathFor(anchor);
        try {
            ae.appendText(new File(path), RB.report.render(record));
        } catch (e) {
            warn(RB.messages.render("record-unwritable",
                                    { path: path,
                                      reason: String(e.message || e) }));
            return null;
        }
        return path;
    }

    function main() {
        var comp = ae.activeComp();
        var file = File.openDialog("Import RotoBridge .rbj", "*.rbj");
        if (!file) { return; }

        var doc = readDocument(file);
        var warn = new ae.Warnings();

        var startRaw = prompt("Start frame in this comp\n\nThe file covers "
            + doc.range[0] + " to " + doc.range[1] + ".",
            String(doc.range[0]));
        if (startRaw === null) { return; }
        var start = RB.timing.snapFrame(Number(startRaw));
        if (isNaN(start)) {
            throw new Error("'" + startRaw + "' is not a frame number");
        }
        var offset = RB.timing.offsetToStart(doc.range[0], start);

        var names = [];
        for (var i = 0; i < doc.shapes.length; i++) {
            names[names.length] = doc.shapes[i].name;
        }
        var subsetRaw = prompt("Shapes to import, comma separated\n\nLeave"
            + " empty for all " + names.length + ":\n" + names.join(", "), "");
        if (subsetRaw === null) { return; }
        var specs = chooseShapes(doc, parseSubset(subsetRaw), warn.fn());

        var tolerance = askTolerance(specs);
        if (tolerance === null) { return; }

        checkSource(doc, comp, warn.fn());

        var restore = comp.time;
        var started = new Date().getTime();
        var built;
        app.beginUndoGroup("RotoBridge import");
        try {
            var layer = targetLayer(comp, doc);
            built = importShapes(comp, layer, doc, specs, offset, tolerance,
                                 warn.fn());
        } finally {
            /* One undo step for the whole import, and the playhead back where
             * the artist left it. */
            app.endUndoGroup();
            comp.time = restore;
        }
        var elapsed = (new Date().getTime() - started) / 1000.0;

        var lines = [
            "Imported " + built.count + " shape(s) from " + file.name,
            "",
            "frames " + (doc.range[0] + offset) + " to "
                + (doc.range[1] + offset)
                + "  (" + built.frames.length + " frames)",
            "took " + elapsed.toFixed(2) + " s",
            ""
        ];
        for (i = 0; i < built.reports.length; i++) {
            /* Per shape, because the answer differs per shape and re-importing
             * tighter is a per-shape decision (prd.md section 8). */
            var report = built.reports[i];
            var line = "  " + report.name + ": " + report.authored
                + " authored key(s), " + report.corrective + " corrective";
            if (report.worst_frame !== null) {
                line += "; worst drift " + report.residual.toFixed(4)
                        + " px at frame " + report.worst_frame;
            }
            lines[lines.length] = line;
        }
        var recorded = writeRecord(
            buildRecord(doc, file, comp, layer, built, offset, tolerance, warn),
            file, warn.fn());
        if (recorded) {
            lines[lines.length] = "";
            lines[lines.length] = "recorded in " + recorded;
        }
        if (doc.warnings.length) {
            lines[lines.length] = "";
            lines[lines.length] = doc.warnings.length
                + " warning(s) recorded when the file was written:";
            for (i = 0; i < doc.warnings.length; i++) {
                lines[lines.length] = "  - " + doc.warnings[i];
            }
        }
        if (warn.messages.length) {
            lines[lines.length] = "";
            lines[lines.length] = warn.messages.length
                + " warning(s) from this import:";
            for (i = 0; i < warn.messages.length; i++) {
                lines[lines.length] = "  - " + warn.messages[i];
            }
        }
        lines[lines.length] = "";
        lines[lines.length] = RB.LABEL;
        alert(lines.join("\n"), RB.LABEL);
    }

    try {
        main();
    } catch (e) {
        alert("RotoBridge import failed:\n\n" + (e.message || e)
              + (e.line ? "\n\n(line " + e.line + ")" : ""), RB.LABEL);
    }
}());
