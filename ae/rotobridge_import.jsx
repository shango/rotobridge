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
            var name = doc.shapes[i].name;
            if (RB.util.hasOwn(wanted, name)) {
                wanted[name] = true;
                out[out.length] = doc.shapes[i];
            }
        }
        for (var key in wanted) {
            if (RB.util.hasOwn(wanted, key) && !wanted[key]) {
                warn("no shape named '" + key + "' in this file");
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
            warn("the file was exported from a " + src.width + "x" + src.height
                 + " comp and this one is " + comp.width + "x" + comp.height
                 + "; coordinates were used as-is, not rescaled");
        }
        if (Math.abs(src.fps - comp.frameRate) > 1e-6) {
            warn("the file was exported at " + src.fps + " fps and this comp is"
                 + " " + comp.frameRate + " fps; frame numbers were used as-is,"
                 + " so the timing in seconds differs");
        }
        if (Math.abs(src.pixel_aspect - comp.pixelAspect) > 1e-6) {
            warn("pixel aspect differs (" + src.pixel_aspect + " against "
                 + comp.pixelAspect + "); .rbj v1 treats pixels as square");
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
            warn("layer '" + layer.name + "': its transform is not affine (off"
                 + " by " + off.toFixed(6) + " px); every point was converted"
                 + " through the host instead, which is slower but exact");
            return null;
        }
        return m;
    }

    function buildShape(record, layer, affine, compHeight, model) {
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
        shape.closed = true;

        if (model === "per_point") {
            /* One feather point per vertex, pinned to the start of its own
             * segment, signed radius carrying the direction. A point's
             * direction cannot be changed after creation, so the type has to be
             * right up front rather than corrected afterwards. */
            var made = geom.featherPointsFromVertices(feather);
            var flat = [];
            for (var f = 0; f < feather.length; f++) { flat[f] = 0; }
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
        var mask = layer.property(MASK_PARADE).addProperty(MASK_ATOM);
        mask.name = spec.name;
        mask.maskMode = ae.modeFromBlend(spec.blend);
        mask.maskFeatherFalloff = ae.falloffFromRbj(spec.feather_falloff);
        return mask;
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
                    comp.height, specs[s]["feather_model"]);
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
        var radii = target.featherRadii || [];
        var here = got.featherRadii || [];
        for (i = 0; i < radii.length; i++) {
            d = Math.abs(Number(here[i] || 0) - Number(radii[i]));
            if (d > worst) { worst = d; }
        }
        return worst;
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
            /* The pass only ever grows its key list, so a frame already written
             * is already correct and re-issuing it would be a wasted host call.
             * The interpolation is re-pushed every time, because the new keys
             * are not the only ones whose indices moved. */
            for (var i = 0; i < wanted.length; i++) {
                var frame = wanted[i];
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
            warn("shape '" + spec.name + "': the drift pass ran out of passes"
                 + " with " + got.worst.toFixed(4) + " px still unaccounted for"
                 + " at frame " + (got.at + offset) + "; re-import this shape at"
                 + " a tighter tolerance if it shows");
        }

        var authored = 0;
        var last = frames[frames.length - 1];
        for (var i = 0; i < plan.frames.length; i++) {
            if (plan.frames[i] >= frames[0] && plan.frames[i] <= last) {
                authored += 1;
            }
        }
        return { name: spec.name, authored: authored,
                 corrective: got.keys.length - authored,
                 residual: got.worst, worstFrame: got.at };
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

    function collapse(samples) {
        /* One key instead of one per frame when the value never changes.
         *
         * An artist opening a shape whose opacity was never animated should
         * find one key on it, not a hundred and fifty. This changes nothing
         * about the values - the dense layer is still where they came from -
         * only how much of the timeline an unanimated attribute takes up. */
        for (var i = 1; i < samples.length; i++) {
            if (!same(samples[i].value, samples[0].value)) { return samples; }
        }
        return samples.slice(0, 1);
    }

    function writeAttributes(comp, mask, spec, frames, offset) {
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
        setSamples(ae.maskProp(mask, ae.MASK_OPACITY), collapse(opacity));
        setSamples(ae.maskProp(mask, ae.MASK_FEATHER), collapse(feather));
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
        var masks = [];
        var s;
        for (s = 0; s < specs.length; s++) {
            masks[s] = createMask(layer, specs[s]);
        }

        var frames = RB.timing.frameRange(doc.range[0], doc.range[1]);
        var targets = bakeTargets(comp, layer, specs, frames, offset, warn);

        var reports = [];
        for (s = 0; s < specs.length; s++) {
            reports[s] = buildOne(comp, masks[s], specs[s], targets[s], frames,
                                  offset, tolerance, warn);
            writeAttributes(comp, masks[s], specs[s], frames, offset);
        }
        return { masks: masks, frames: frames, reports: reports };
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
            "Imported " + built.masks.length + " shape(s) from " + file.name,
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
            if (report.worstFrame !== null) {
                line += "; worst drift " + report.residual.toFixed(4)
                        + " px at frame " + (report.worstFrame + offset);
            }
            lines[lines.length] = line;
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
        alert(lines.join("\n"), "RotoBridge");
    }

    try {
        main();
    } catch (e) {
        alert("RotoBridge import failed:\n\n" + (e.message || e)
              + (e.line ? "\n\n(line " + e.line + ")" : ""), "RotoBridge");
    }
}());
