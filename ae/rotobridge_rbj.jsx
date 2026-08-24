/*
 * RotoBridge - the .rbj v1 schema, executable, for After Effects.
 *
 * The ExtendScript counterpart of `core/rbj.py`, and the same contract:
 * validation and serialisation only, no file access. The adapter scripts read
 * and write the bytes; this file decides whether they are legal. That split is
 * what lets the golden .rbj files test either adapter with neither application
 * present (prd.md section 5.1).
 *
 * `validate` returns every problem it finds rather than stopping at the first,
 * so one run tells an artist everything wrong with a file. `parse` and
 * `stringify` throw, because prd.md section 11 requires aborting rather than
 * emitting partial output: a file that is written but invalid looks correct
 * until it is composited.
 *
 * Requires `rotobridge_core.jsx` for `RB.util`.
 *
 * **One divergence from the Python, and it is not fixable.** `core/rbj.py`
 * distinguishes an integer from a float, so it rejects a `version` of `1.0`.
 * JavaScript has one number type and `1.0 === 1`, so this reader accepts it.
 * The check here is "a whole number", which is the strongest statement the
 * language permits. Nothing is lost in the direction that matters: a file this
 * accepts and the Python rejects differs only in how it was spelled.
 */

/* global RB */

(function (RB) {
    var hasOwn = RB.util.hasOwn;
    var isArray = RB.util.isArray;

    var rbj = {};
    RB.rbj = rbj;

    rbj.VERSION = 1;

    /* spec/rbj-v2-draft.md section 2: a writer emits the lowest version that
     * can express the file, not the highest it implements. */
    rbj.VERSION_OPEN_SPLINES = 2;
    rbj.VERSION_ANCHORED_FEATHER = 2;
    /* spec/rbj-v3-draft.md section 3: a dense frame may say {"same_as": N}
     * instead of repeating an earlier frame it is identical to. A v1/v2
     * reader hard-fails on the reference record, so this one costs a
     * version - the constant lives on versionFor's side of the ledger but
     * only foldFrames spends it. */
    rbj.VERSION_FRAME_REFS = 3;
    rbj.MAX_VERSION = 3;

    rbj.versionFor = function (shapes) {
        /* Section 6.7 keeps the anchored clause narrow: the exporter writes
         * `anchored` only where the snap would lose something, so a file whose
         * feather already sits on vertices is still a v1 file. */
        for (var i = 0; i < shapes.length; i++) {
            if (shapes[i]["closed"] === false) {
                return rbj.VERSION_OPEN_SPLINES;
            }
            if (shapes[i]["feather_model"] === "anchored") {
                return rbj.VERSION_ANCHORED_FEATHER;
            }
        }
        return rbj.VERSION;
    };

    rbj.BLENDS = ["union", "difference", "intersection"];
    /* spec/rbj-v2-draft.md section 6.2: three exclusive models. `anchored`
     * moves the whole per-point feather layer into the frame's own
     * `feather_points`, because After Effects anchors feather anywhere along a
     * segment and can put two anchors on one segment - which no per-point
     * member can hold, so this is a new list rather than a widened field. */
    rbj.FEATHER_MODELS = ["per_point", "anchored", "none"];
    rbj.FALLOFFS = ["linear", "smooth"];
    rbj.INTERPS = ["hold", "linear", "ease"];

    /* spec section 7.1: plain decimal integers, no padding, no leading +,
     * no "-0". */
    var FRAME_KEY_RE = /^(0|-?[1-9][0-9]*)$/;

    /* A malformed dense layer can produce one error per frame per point.
     * Report enough to diagnose, then say how many were suppressed. */
    var MAX_ERRORS_PER_SHAPE = 5;

    /* --- small helpers ---------------------------------------------------- */

    function show(v) {
        /* Stand-in for Python's %r in error messages. Deliberately shallow:
         * an error that quotes an entire 150-frame dense layer back at the
         * reader is not a better error. */
        if (v === null) { return "null"; }
        if (v === undefined) { return "undefined"; }
        if (typeof v === "string") { return '"' + v + '"'; }
        if (isArray(v)) { return "an array of " + v.length; }
        if (typeof v === "object") { return "an object"; }
        return String(v);
    }

    function isNum(v) {
        return typeof v === "number" && isFinite(v);
    }

    function isInt(v) {
        return isNum(v) && Math.floor(v) === v;
    }

    function isStr(v) {
        return typeof v === "string";
    }

    function isObj(v) {
        return v !== null && typeof v === "object" && !isArray(v);
    }

    function num(errs, where, obj, key, required) {
        if (required === undefined) { required = true; }
        if (!hasOwn(obj, key)) {
            if (required) { errs[errs.length] = where + ": missing " + key; }
            return null;
        }
        var v = obj[key];
        if (typeof v !== "number") {
            errs[errs.length] = where + ": " + key + " is " + show(v)
                + ", expected a number";
            return null;
        }
        if (!isFinite(v)) {
            errs[errs.length] = where + ": " + key + " is " + show(v)
                + ", which is not finite";
            return null;
        }
        return v;
    }

    function vec2(errs, where, obj, key, required) {
        if (required === undefined) { required = true; }
        if (!hasOwn(obj, key)) {
            if (required) { errs[errs.length] = where + ": missing " + key; }
            return null;
        }
        var v = obj[key];
        if (!isArray(v) || v.length !== 2) {
            errs[errs.length] = where + ": " + key + " is " + show(v)
                + ", expected a two-element array";
            return null;
        }
        var out = [];
        for (var i = 0; i < 2; i++) {
            if (typeof v[i] !== "number") {
                errs[errs.length] = where + ": " + key + "[" + i + "] is "
                    + show(v[i]) + ", expected a number";
                return null;
            }
            if (!isFinite(v[i])) {
                errs[errs.length] = where + ": " + key + "[" + i + "] is "
                    + show(v[i]) + ", which is not finite";
                return null;
            }
            out[i] = v[i];
        }
        return out;
    }

    function enumOf(errs, where, obj, key, allowed) {
        var v = hasOwn(obj, key) ? obj[key] : undefined;
        if (RB.util.indexOf(allowed, v) === -1) {
            errs[errs.length] = where + ": " + key + " is " + show(v)
                + ", expected one of " + allowed.join(" | ");
            return null;
        }
        return v;
    }

    function byNumber(a, b) { return Number(a) - Number(b); }

    /* --- validation ------------------------------------------------------- */

    rbj.validate = function (doc) {
        /* Every reason `doc` is not a legal v1 .rbj. An empty list means legal. */
        if (!isObj(doc)) {
            return ["top level is " + show(doc) + ", expected a JSON object"];
        }

        var errs = [];

        if (doc["format"] !== "rotobridge") {
            errs[errs.length] = "format is " + show(doc["format"])
                + ", expected \"rotobridge\"";
        }

        var ver = doc["version"];
        if (!isInt(ver)) {
            errs[errs.length] = "version is " + show(ver)
                + ", expected an integer";
            ver = null;
        } else if (ver > rbj.MAX_VERSION) {
            errs[errs.length] = "version " + ver
                + " is newer than this reader implements ("
                + rbj.MAX_VERSION + ")";
        } else if (ver < 1) {
            errs[errs.length] = "version " + ver + " is not a released version";
        }

        validateSource(errs, doc["source"]);
        var framesExpected = validateRange(errs, doc["range"]);

        var warnings = doc["warnings"];
        if (!isArray(warnings)) {
            errs[errs.length] = "warnings is " + show(warnings)
                + ", expected an array (possibly empty)";
        } else {
            for (var w = 0; w < warnings.length; w++) {
                if (!isStr(warnings[w])) {
                    errs[errs.length] = "warnings[" + w + "] is "
                        + show(warnings[w]) + ", expected a string";
                }
            }
        }

        var shapes = doc["shapes"];
        if (!isArray(shapes)) {
            errs[errs.length] = "shapes is " + show(shapes)
                + ", expected an array";
        } else if (!shapes.length) {
            errs[errs.length] =
                "shapes is empty; a file with no shapes is a hard failure";
        } else {
            for (var i = 0; i < shapes.length; i++) {
                validateShape(errs, i, shapes[i], framesExpected, ver);
            }
        }

        return errs;
    };

    function validateSource(errs, src) {
        if (!isObj(src)) {
            errs[errs.length] = "source is " + show(src) + ", expected an object";
            return;
        }
        var strings = ["app", "app_version"];
        for (var i = 0; i < strings.length; i++) {
            if (!isStr(src[strings[i]])) {
                errs[errs.length] = "source: " + strings[i] + " is "
                    + show(src[strings[i]]) + ", expected a string";
            }
        }
        var ints = ["width", "height"];
        for (var j = 0; j < ints.length; j++) {
            var v = src[ints[j]];
            if (!isInt(v)) {
                errs[errs.length] = "source: " + ints[j] + " is " + show(v)
                    + ", expected an integer";
            } else if (v <= 0) {
                errs[errs.length] = "source: " + ints[j] + " is " + v
                    + ", expected greater than zero";
            }
        }
        num(errs, "source", src, "pixel_aspect");
        var fps = num(errs, "source", src, "fps");
        if (fps !== null && fps <= 0) {
            errs[errs.length] = "source: fps is " + fps
                + ", expected greater than zero";
        }
    }

    function validateRange(errs, rng) {
        /* Returns a lookup of the frame-key strings the dense layer must
         * cover, or null when the range itself is unusable. */
        if (!isArray(rng) || rng.length !== 2) {
            errs[errs.length] = "range is " + show(rng)
                + ", expected [first, last]";
            return null;
        }
        var first = rng[0];
        var last = rng[1];
        if (!isInt(first) || !isInt(last)) {
            errs[errs.length] = "range is " + show(rng)
                + ", expected two integers";
            return null;
        }
        if (first > last) {
            errs[errs.length] = "range is [" + first + ", " + last
                + "], which is not ascending";
            return null;
        }
        var expected = {};
        for (var f = first; f <= last; f++) { expected[String(f)] = true; }
        return expected;
    }

    function validateShape(errs, index, shape, framesExpected, version) {
        var where = "shapes[" + index + "]";
        if (!isObj(shape)) {
            errs[errs.length] = where + " is " + show(shape)
                + ", expected an object";
            return;
        }

        var name = shape["name"];
        if (isStr(name)) {
            where = where + " '" + name + "'";
        } else {
            errs[errs.length] = where + ": name is " + show(name)
                + ", expected a string";
        }

        var closed = shape["closed"];
        if (closed !== true && closed !== false) {
            errs[errs.length] = where + ": closed is " + show(closed)
                + ", expected a boolean";
        } else if (closed === false && version !== null
                   && version < rbj.VERSION_OPEN_SPLINES) {
            errs[errs.length] = where + ": closed is false, which needs version "
                + rbj.VERSION_OPEN_SPLINES + "; this file declares version "
                + version + " (spec/rbj-v2-draft.md section 3)";
        }

        enumOf(errs, where, shape, "blend", rbj.BLENDS);
        var model = enumOf(errs, where, shape, "feather_model",
                           rbj.FEATHER_MODELS);
        enumOf(errs, where, shape, "feather_falloff", rbj.FALLOFFS);
        if (model === "anchored" && version !== null
                && version < rbj.VERSION_ANCHORED_FEATHER) {
            errs[errs.length] = where + ": feather_model is 'anchored', which"
                + " needs version " + rbj.VERSION_ANCHORED_FEATHER + "; this"
                + " file declares version " + version
                + " (spec/rbj-v2-draft.md section 6.2)";
        }

        var frameKeys = validateFrames(errs, where, shape["frames"],
                                       framesExpected, model, closed,
                                       version);
        validateKeys(errs, where, shape["keys"], frameKeys);
        if (hasOwn(shape, "pre_conform_keys")) {
            /* Optional provenance (spec/rbj-v3-draft.md section 5): the
             * authored keys exactly as they were before the exporter
             * conformed them. Same schema as keys, so the same machinery. */
            if (shape["pre_conform_keys"] === null) {
                errs[errs.length] = where + ": pre_conform_keys is null;"
                    + " omit the member instead";
            } else {
                validateKeys(errs, where + " pre_conform_keys",
                             shape["pre_conform_keys"], frameKeys);
            }
        }
    }

    function validateFrames(errs, where, frames, framesExpected, model,
                            closed, version) {
        /* Returns the frame keys present, or null.
         *
         * Null means the dense layer was unusable, so callers must not go on to
         * report every key as pointing at a missing frame - that buries the one
         * error that matters under a hundred that follow from it. */
        if (!isObj(frames)) {
            errs[errs.length] = where + ": frames is " + show(frames)
                + ", expected an object";
            return null;
        }

        var present = {};
        var presentList = [];
        var k;
        for (k in frames) {
            if (hasOwn(frames, k)) {
                present[k] = true;
                presentList[presentList.length] = k;
            }
        }

        var malformed = [];
        var wellFormed = [];
        for (var i = 0; i < presentList.length; i++) {
            if (FRAME_KEY_RE.test(presentList[i])) {
                wellFormed[wellFormed.length] = presentList[i];
            } else {
                malformed[malformed.length] = presentList[i];
            }
        }
        malformed.sort();
        for (var m = 0; m < malformed.length && m < MAX_ERRORS_PER_SHAPE; m++) {
            errs[errs.length] = where + ": frames key \"" + malformed[m]
                + "\" is not a plain decimal integer";
        }
        if (malformed.length > MAX_ERRORS_PER_SHAPE) {
            errs[errs.length] = where + ": and "
                + (malformed.length - MAX_ERRORS_PER_SHAPE)
                + " more malformed frames keys";
        }

        if (framesExpected !== null) {
            var missing = [];
            for (k in framesExpected) {
                if (hasOwn(framesExpected, k) && !hasOwn(present, k)) {
                    missing[missing.length] = k;
                }
            }
            var extra = [];
            for (var e = 0; e < wellFormed.length; e++) {
                if (!hasOwn(framesExpected, wellFormed[e])) {
                    extra[extra.length] = wellFormed[e];
                }
            }
            missing.sort(byNumber);
            extra.sort(byNumber);
            if (missing.length) {
                errs[errs.length] = where + ": frames is missing "
                    + missing.length + " frame(s) in range, first " + missing[0];
            }
            if (extra.length) {
                errs[errs.length] = where + ": frames has " + extra.length
                    + " frame(s) outside range, first " + extra[0];
            }
        }

        wellFormed.sort(byNumber);
        var shapeErrs = [];
        var counts = {};
        var countList = [];
        var anchorCounts = {};
        var anchorList = [];
        for (var f = 0; f < wellFormed.length; f++) {
            if (shapeErrs.length > MAX_ERRORS_PER_SHAPE) { break; }
            var key = wellFormed[f];
            if (isRef(frames[key])) {
                validateRef(shapeErrs, where + " frame " + key, key,
                            frames[key], frames, version);
                continue;
            }
            var got = validateFrameRecord(shapeErrs, where + " frame " + key,
                                          frames[key], model, closed);
            var n = got[0];
            if (n !== null && !hasOwn(counts, n)) {
                counts[n] = key;
                countList[countList.length] = n;
            }
            if (got[1] !== null && !hasOwn(anchorCounts, got[1])) {
                anchorCounts[got[1]] = key;
                anchorList[anchorList.length] = got[1];
            }
        }

        for (var s = 0; s < shapeErrs.length && s < MAX_ERRORS_PER_SHAPE; s++) {
            errs[errs.length] = shapeErrs[s];
        }
        if (shapeErrs.length > MAX_ERRORS_PER_SHAPE) {
            errs[errs.length] = where
                + ": and further problems in later frames, suppressed";
        }

        if (countList.length > 1) {
            countList.sort(byNumber);
            var parts = [];
            for (var c = 0; c < countList.length; c++) {
                parts[parts.length] = countList[c] + " at frame "
                    + counts[countList[c]];
            }
            errs[errs.length] = where + ": vertex count changes across frames ("
                + parts.join(", ") + "); Nuke cannot represent this and there is"
                + " no correct interpolation between two counts";
        }

        /* Section 6.3 defers to section 7.3's reasoning about vertices: two
         * different counts have no correct interpolation between them, and
         * that is as true of the anchors as of the points they hang off. */
        if (anchorList.length > 1) {
            anchorList.sort(byNumber);
            var aParts = [];
            for (var a = 0; a < anchorList.length; a++) {
                aParts[aParts.length] = anchorList[a] + " at frame "
                    + anchorCounts[anchorList[a]];
            }
            errs[errs.length] = where + ": feather_points count changes across"
                + " frames (" + aParts.join(", ") + "); there is no correct"
                + " interpolation between two counts (spec/rbj-v2-draft.md"
                + " section 6.3)";
        }

        return present;
    }

    function isRef(rec) {
        /* Exactly {"same_as": N} and nothing else - the mirror of
         * `core/rbj.py` `_is_ref` (spec/rbj-v3-draft.md section 3). */
        if (!isObj(rec) || !hasOwn(rec, "same_as")) { return false; }
        for (var k in rec) {
            if (hasOwn(rec, k) && k !== "same_as") { return false; }
        }
        return true;
    }

    function validateRef(errs, where, key, rec, frames, version) {
        if (version !== null && version < rbj.VERSION_FRAME_REFS) {
            errs[errs.length] = where + ": same_as needs version "
                + rbj.VERSION_FRAME_REFS + "; this file declares version "
                + version + " (spec/rbj-v3-draft.md section 3)";
        }
        var target = rec["same_as"];
        if (!isInt(target)) {
            errs[errs.length] = where + ": same_as is " + show(target)
                + ", expected an integer frame";
            return;
        }
        if (target >= Number(key)) {
            /* Earlier only. Backward references keep a reader single-pass
             * and make a cycle impossible to write. */
            errs[errs.length] = where + ": same_as " + target
                + " does not point at an earlier frame";
            return;
        }
        if (!hasOwn(frames, String(target))) {
            errs[errs.length] = where + ": same_as " + target
                + ", which is not in the dense layer";
        } else if (isRef(frames[String(target)])) {
            errs[errs.length] = where + ": same_as " + target
                + ", which is itself a reference; references do not chain,"
                + " so every reference resolves in one step";
        }
    }

    function deepEqual(a, b) {
        /* Data equality over JSON trees, mirroring what Python's == does to
         * dicts and lists. One number type here, so 1 and 1.0 cannot even
         * disagree - which is what keeps the two writers making the same
         * folding decisions. */
        if (a === b) { return true; }
        var i, k;
        if (isArray(a) || isArray(b)) {
            if (!isArray(a) || !isArray(b) || a.length !== b.length) {
                return false;
            }
            for (i = 0; i < a.length; i++) {
                if (!deepEqual(a[i], b[i])) { return false; }
            }
            return true;
        }
        if (isObj(a) && isObj(b)) {
            for (k in a) {
                if (hasOwn(a, k) && (!hasOwn(b, k)
                                     || !deepEqual(a[k], b[k]))) {
                    return false;
                }
            }
            for (k in b) {
                if (hasOwn(b, k) && !hasOwn(a, k)) { return false; }
            }
            return true;
        }
        return false;
    }

    function deepCopy(value) {
        var i, k, out;
        if (isArray(value)) {
            out = [];
            for (i = 0; i < value.length; i++) {
                out[i] = deepCopy(value[i]);
            }
            return out;
        }
        if (isObj(value)) {
            out = {};
            for (k in value) {
                if (hasOwn(value, k)) { out[k] = deepCopy(value[k]); }
            }
            return out;
        }
        return value;
    }

    rbj.foldFrames = function (doc) {
        /* Fold runs of identical consecutive frames into references.
         *
         * Returns a new document; `doc` is untouched. Bumps the version to
         * VERSION_FRAME_REFS only when something actually folded - section
         * 6.7's policy: only the files that benefit pay the compatibility
         * cost. Explicit rather than built into `stringify`, so
         * parse(stringify(doc)) stays the identity and the exporter owns the
         * decision. Mirrors `core/rbj.py` `fold_frames`.
         */
        var foldedAny = false;
        var shapesOut = [];
        for (var s = 0; s < doc["shapes"].length; s++) {
            var shape = doc["shapes"][s];
            var frames = shape["frames"];
            var ordered = [];
            var key;
            for (key in frames) {
                if (hasOwn(frames, key)) { ordered[ordered.length] = key; }
            }
            ordered.sort(byNumber);
            var out = {};
            var head = null;
            for (var f = 0; f < ordered.length; f++) {
                key = ordered[f];
                if (head !== null && deepEqual(frames[key], frames[head])) {
                    out[key] = { "same_as": Number(head) };
                    foldedAny = true;
                } else {
                    out[key] = frames[key];
                    head = key;
                }
            }
            var folded = {};
            for (key in shape) {
                if (hasOwn(shape, key)) { folded[key] = shape[key]; }
            }
            folded["frames"] = out;
            shapesOut[shapesOut.length] = folded;
        }
        var outDoc = {};
        for (var k in doc) {
            if (hasOwn(doc, k)) { outDoc[k] = doc[k]; }
        }
        outDoc["shapes"] = shapesOut;
        if (foldedAny && outDoc["version"] < rbj.VERSION_FRAME_REFS) {
            outDoc["version"] = rbj.VERSION_FRAME_REFS;
        }
        return outDoc;
    };

    rbj.expandFrames = function (doc) {
        /* Resolve every reference to a deep copy of its frame - the inverse
         * of foldFrames, applied by `parse` after validation so everything
         * downstream of a reader still sees a dense layer on every frame.
         * Deep copies, because two keys sharing one record would let a
         * mutation of "frame 11" silently edit frame 10 as well. */
        var shapesOut = [];
        for (var s = 0; s < doc["shapes"].length; s++) {
            var shape = doc["shapes"][s];
            var frames = shape["frames"];
            var out = {};
            var key;
            for (key in frames) {
                if (!hasOwn(frames, key)) { continue; }
                if (isRef(frames[key])) {
                    out[key] = deepCopy(frames[String(frames[key]["same_as"])]);
                } else {
                    out[key] = frames[key];
                }
            }
            var expanded = {};
            for (key in shape) {
                if (hasOwn(shape, key)) { expanded[key] = shape[key]; }
            }
            expanded["frames"] = out;
            shapesOut[shapesOut.length] = expanded;
        }
        var outDoc = {};
        for (var k in doc) {
            if (hasOwn(doc, k)) { outDoc[k] = doc[k]; }
        }
        outDoc["shapes"] = shapesOut;
        return outDoc;
    };

    function validateFrameRecord(errs, where, rec, model, closed) {
        /* Returns `[vertex count, feather anchor count]`, either of which is
         * null when that layer was unusable and the caller should not compare
         * it across frames. */
        if (!isObj(rec)) {
            errs[errs.length] = where + " is " + show(rec)
                + ", expected an object";
            return [null, null];
        }

        var opacity = num(errs, where, rec, "opacity");
        if (opacity !== null && (opacity < 0.0 || opacity > 1.0)) {
            errs[errs.length] = where + ": opacity is " + opacity
                + ", expected 0.0 to 1.0";
        }
        vec2(errs, where, rec, "feather_uniform");

        var points = rec["points"];
        if (!isArray(points)) {
            errs[errs.length] = where + ": points is " + show(points)
                + ", expected an array";
            return [null, null];
        }
        if (!points.length) {
            errs[errs.length] = where + ": points is empty";
            return [null, null];
        }

        for (var i = 0; i < points.length; i++) {
            validatePoint(errs, where + " point " + i, points[i], model);
        }
        return [points.length,
                validateFeatherPoints(errs, where, rec, model, closed,
                                      points.length)];
    }

    function validateFeatherPoints(errs, where, rec, model, closed, nPoints) {
        /* The `anchored` feather layer, spec section 6.3. Returns its count.
         *
         * Required exactly when the model is `anchored` and forbidden
         * otherwise, which is section 2's rule that a file says what it means:
         * an empty list under `per_point` and an absent one would be two
         * spellings of the same nothing. */
        var present = hasOwn(rec, "feather_points");
        if (model !== "anchored") {
            if (present && model !== null) {
                errs[errs.length] = where + ": feather_points is present but"
                    + " feather_model is " + show(model) + ", not 'anchored'";
            }
            return null;
        }
        if (!present) {
            errs[errs.length] = where + ": missing feather_points, which"
                + " feather_model 'anchored' requires";
            return null;
        }

        var anchors = rec["feather_points"];
        if (!isArray(anchors)) {
            errs[errs.length] = where + ": feather_points is " + show(anchors)
                + ", expected an array";
            return null;
        }

        /* Section 6.4. A closed shape has one segment per vertex, and t = n
         * names the same anchor as t = 0, so the upper bound is exclusive and
         * must be written as 0. An open shape has one segment fewer and
         * genuinely ends on its last vertex, so there the bound is inclusive.
         *
         * A `closed` that is neither true nor false has already been reported
         * by the caller. Reading it as closed here takes the wider of the two
         * bounds, so the one real error does not drag a range error behind
         * it. */
        var isOpen = closed === false;
        var limit = isOpen ? nPoints - 1 : nPoints;
        var prev = null;
        for (var i = 0; i < anchors.length; i++) {
            var awhere = where + " feather_points[" + i + "]";
            if (!isObj(anchors[i])) {
                errs[errs.length] = awhere + " is " + show(anchors[i])
                    + ", expected an object";
                continue;
            }
            var t = num(errs, awhere, anchors[i], "t");
            if (t !== null) {
                var over = isOpen ? t > limit : t >= limit;
                if (t < 0.0 || over) {
                    errs[errs.length] = awhere + ": t is " + show(t)
                        + ", expected 0 to " + limit + " on "
                        + (isOpen ? "an open" : "a closed") + " shape of "
                        + nPoints + " point(s)";
                } else if (prev !== null && t < prev) {
                    errs[errs.length] = awhere + ": t is " + show(t)
                        + ", which is below the previous anchor's " + show(prev)
                        + "; feather_points is ordered by t ascending"
                        + " (spec/rbj-v2-draft.md section 6.3)";
                }
                prev = t;
            }
            num(errs, awhere, anchors[i], "feather");
            if (hasOwn(anchors[i], "feather_offset")) {
                vec2(errs, awhere, anchors[i], "feather_offset");
            }
        }
        return anchors.length;
    }

    function validatePoint(errs, where, pt, model) {
        if (!isObj(pt)) {
            errs[errs.length] = where + " is " + show(pt)
                + ", expected an object";
            return;
        }
        vec2(errs, where, pt, "c");
        vec2(errs, where, pt, "in");
        vec2(errs, where, pt, "out");

        var hasFeather = hasOwn(pt, "feather");
        if (model === "per_point") {
            num(errs, where, pt, "feather");
        } else if (model === "none" && hasFeather) {
            errs[errs.length] = where + ": feather is present but feather_model"
                + " is 'none'; a zero under 'none' is indistinguishable from an"
                + " authored zero-width point";
        } else if (model === "anchored" && hasFeather) {
            errs[errs.length] = where + ": feather is present but feather_model"
                + " is 'anchored', which carries the whole feather layer in the"
                + " frame's feather_points; two places to look is one too many"
                + " (spec/rbj-v2-draft.md section 6.2)";
        }

        if (hasOwn(pt, "feather_offset")) {
            if (!hasFeather) {
                errs[errs.length] = where + ": feather_offset without feather";
            }
            vec2(errs, where, pt, "feather_offset");
        }
    }

    function validateKeys(errs, where, keys, frameKeys) {
        if (keys === undefined || keys === null) { return; }
        if (!isArray(keys)) {
            errs[errs.length] = where + ": keys is " + show(keys)
                + ", expected an array";
            return;
        }

        var keyErrs = [];
        var prev = null;
        for (var i = 0; i < keys.length; i++) {
            if (keyErrs.length > MAX_ERRORS_PER_SHAPE) { break; }
            var key = keys[i];
            var kwhere = where + " keys[" + i + "]";
            if (!isObj(key)) {
                keyErrs[keyErrs.length] = kwhere + " is " + show(key)
                    + ", expected an object";
                continue;
            }

            var frame = key["frame"];
            if (!isInt(frame)) {
                keyErrs[keyErrs.length] = kwhere + ": frame is " + show(frame)
                    + ", expected an integer";
            } else {
                kwhere = where + " keys[" + i + "] frame " + frame;
                if (frameKeys !== null && !hasOwn(frameKeys, String(frame))) {
                    keyErrs[keyErrs.length] = kwhere
                        + ": no such frame in the dense layer";
                }
                if (prev !== null) {
                    if (frame === prev) {
                        keyErrs[keyErrs.length] = kwhere + ": duplicate key frame";
                    } else if (frame < prev) {
                        keyErrs[keyErrs.length] = kwhere
                            + ": keys are not sorted ascending (follows "
                            + prev + ")";
                    }
                }
                prev = frame;
            }

            validateInterp(keyErrs, kwhere, key);
        }

        for (var e = 0; e < keyErrs.length && e < MAX_ERRORS_PER_SHAPE; e++) {
            errs[errs.length] = keyErrs[e];
        }
        if (keyErrs.length > MAX_ERRORS_PER_SHAPE) {
            errs[errs.length] = where
                + ": and further problems in later keys, suppressed";
        }
    }

    function validateInterp(errs, where, key) {
        var interp = key["interp"];
        if (!isObj(interp)) {
            errs[errs.length] = where + ": interp is " + show(interp)
                + ", expected an object with in and out";
            return;
        }

        var sides = {};
        sides["in"] = enumOf(errs, where, interp, "in", rbj.INTERPS);
        sides["out"] = enumOf(errs, where, interp, "out", rbj.INTERPS);

        var ease = hasOwn(key, "ease") ? key["ease"] : null;
        if (ease === null || ease === undefined) { return; }
        if (!isObj(ease)) {
            errs[errs.length] = where + ": ease is " + show(ease)
                + ", expected an object";
            return;
        }
        var named = ["in", "out"];
        for (var i = 0; i < 2; i++) {
            var side = named[i];
            if (!hasOwn(ease, side)) { continue; }
            if (sides[side] !== "ease") {
                errs[errs.length] = where + ": ease has an entry for the "
                    + side + " side, whose interp is " + show(sides[side])
                    + ", not 'ease'";
            }
            vec2(errs, where, ease, side);
        }
        for (var k in ease) {
            if (hasOwn(ease, k) && k !== "in" && k !== "out") {
                errs[errs.length] = where + ": ease has an unexpected side \""
                    + k + "\"";
            }
        }
    }

    /* --- parsing and serialisation ---------------------------------------- */

    function RbjError(errors) {
        var err = new Error("invalid .rbj:\n  " + errors.join("\n  "));
        err.name = "RbjError";
        err.errors = errors;
        return err;
    }
    rbj.RbjError = RbjError;

    rbj.parse = function (text) {
        /* Parse and validate. Throws an error carrying every problem found.
         *
         * ExtendScript has no native `JSON`. Rather than bundle json2.js this
         * uses its documented fallback verbatim: prove the text contains only
         * JSON tokens with a regex chain, then let the language's own parser
         * read it. The chain blanks escapes, then whole string / number /
         * literal tokens, then open brackets, and what must remain is only
         * punctuation. `eval` is safe on text that survives that, and unsafe on
         * text that has not been through it - so never move the call. */
        var doc;
        try {
            if (typeof JSON !== "undefined" && JSON.parse) {
                doc = JSON.parse(text);
            } else {
                var stripped = String(text)
                    .replace(/\\(?:["\\\/bfnrt]|u[0-9a-fA-F]{4})/g, "@")
                    .replace(/"[^"\\\n\r]*"|true|false|null|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?/g, "]")
                    .replace(/(?:^|:|,)(?:\s*\[)+/g, "");
                if (!(/^[\],:{}\s]*$/).test(stripped)) {
                    throw new Error("not valid JSON");
                }
                doc = eval("(" + text + ")");
            }
        } catch (e) {
            throw RbjError(["not valid JSON: " + e.message]);
        }
        var errs = rbj.validate(doc);
        if (errs.length) { throw RbjError(errs); }
        return rbj.expandFrames(doc);
    };

    var ESCAPES = {
        "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r",
        "\"": "\\\"", "\\": "\\\\"
    };
    /* JSON itself only requires escaping the quote, the backslash and the C0
     * controls. U+2028 and U+2029 are added because they are legal JSON but
     * terminate a line in JavaScript source, and `parse` above falls back to
     * `eval` on hosts with no native `JSON` - an unescaped one there would turn
     * a valid file into a syntax error. */
    var ESCAPABLE = /[\\"\u0000-\u001f\u2028\u2029]/g;

    function quote(s) {
        ESCAPABLE.lastIndex = 0;
        return '"' + String(s).replace(ESCAPABLE, function (c) {
            if (hasOwn(ESCAPES, c)) { return ESCAPES[c]; }
            var code = c.charCodeAt(0).toString(16);
            return "\\u" + "0000".substring(code.length) + code;
        }) + '"';
    }

    function leaf(v) {
        if (v === null) { return "null"; }
        if (v === true) { return "true"; }
        if (v === false) { return "false"; }
        if (typeof v === "number") {
            if (!isFinite(v)) {
                /* spec section 2.2 forbids NaN and Infinity, which are not
                 * legal JSON and which no parser is required to accept. */
                throw RbjError([String(v) + " is not a legal JSON number in .rbj"]);
            }
            return String(v);
        }
        return quote(v);
    }

    function pretty(obj, indent, level) {
        /* Pretty-print, but keep arrays of numbers on one line.
         *
         * One element per line turns every coordinate pair into three lines and
         * a 150-frame shape into something no one can read a diff of. The
         * format is meant to be diffable (spec section 2.1), and that is worth
         * thirty lines of printer. */
        var pad = new Array(indent * level + 1).join(" ");
        var inner = new Array(indent * (level + 1) + 1).join(" ");
        var items = [];
        var i;

        if (isArray(obj)) {
            if (!obj.length) { return "[]"; }
            var allNumbers = true;
            for (i = 0; i < obj.length; i++) {
                if (typeof obj[i] !== "number") { allNumbers = false; break; }
            }
            if (allNumbers) {
                for (i = 0; i < obj.length; i++) { items[i] = leaf(obj[i]); }
                return "[" + items.join(", ") + "]";
            }
            for (i = 0; i < obj.length; i++) {
                items[i] = inner + pretty(obj[i], indent, level + 1);
            }
            return "[\n" + items.join(",\n") + "\n" + pad + "]";
        }

        if (obj !== null && typeof obj === "object") {
            for (var k in obj) {
                if (hasOwn(obj, k)) {
                    items[items.length] = inner + quote(k) + ": "
                        + pretty(obj[k], indent, level + 1);
                }
            }
            if (!items.length) { return "{}"; }
            return "{\n" + items.join(",\n") + "\n" + pad + "}";
        }

        return leaf(obj);
    }

    rbj.stringify = function (doc, indent) {
        /* Validate, then serialise. Throws rather than writing an invalid file.
         *
         * Numbers come out through `String`, which is shortest-round-trip, so
         * a whole number loses the trailing ".0" the Python writer emits. Both
         * are the same JSON value and both readers accept either. */
        if (indent === undefined) { indent = 2; }
        var errs = rbj.validate(doc);
        if (errs.length) { throw RbjError(errs); }
        return pretty(doc, indent, 0);
    };
}(RB));

if (typeof module !== "undefined" && module.exports) { module.exports = RB; }
