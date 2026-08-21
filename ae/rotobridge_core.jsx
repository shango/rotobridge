/*
 * RotoBridge - host-free core for the After Effects adapters.
 *
 * The ExtendScript counterpart of `core/`. Same rule as the Python: nothing in
 * here touches the host. `app`, `comp` and every `Layer` stay in the adapter
 * scripts, so this file runs unchanged under plain JavaScript and is tested
 * without After Effects present - the same lever `core/` gives the Nuke side
 * against a licence it cannot always get.
 *
 * ExtendScript is ES3. No `let`, no `const`, no `JSON`, no `Array.forEach` /
 * `map` / `filter`, and - the one that bites hardest - **no `Array.indexOf`**.
 * There is no `Math.hypot` either. Where a shim is needed it is written out
 * rather than patched onto `Array.prototype`, because a host script that
 * extends a built-in prototype changes the behaviour of every other script the
 * user runs in the same session.
 *
 * Only what After Effects actually needs is ported. `core/geom.py`'s matrix
 * bake and normal projection are Nuke's - AE reads `featherRadii` as a signed
 * scalar verbatim (prd.md section 9.1 step 6) and converts points through
 * `sourcePointToComp`, so neither has a caller here. `core/interp.py`'s
 * `sides_from_nuke` / `reduce_sides` / `to_nuke` are Nuke's too: they exist to
 * collapse one type per axis per control point down to one per key, and After
 * Effects already has one per key.
 */

var RB = (function () {
    var RB = {};

    /* --- ES3 shims --------------------------------------------------------
     *
     * Local, not prototype patches. See the file header.
     */

    function indexOf(list, value) {
        for (var i = 0; i < list.length; i++) {
            if (list[i] === value) { return i; }
        }
        return -1;
    }

    function hasOwn(obj, key) {
        return Object.prototype.hasOwnProperty.call(obj, key);
    }

    function isArray(v) {
        return Object.prototype.toString.call(v) === "[object Array]";
    }

    function ascending(a, b) { return a - b; }

    function sortedInts(values) {
        /* Unique, ascending, integer. The Python this mirrors leans on `set`
         * and `sorted`; ES3 has neither, and `Array.sort` defaults to
         * comparing *strings*, which orders 10 before 9. */
        var seen = {};
        var out = [];
        for (var i = 0; i < values.length; i++) {
            var n = Math.floor(Number(values[i]));
            if (!hasOwn(seen, n)) {
                seen[n] = true;
                out[out.length] = n;
            }
        }
        out.sort(ascending);
        return out;
    }

    function hypot(dx, dy) {
        return Math.sqrt(dx * dx + dy * dy);
    }

    RB.util = {
        indexOf: indexOf,
        hasOwn: hasOwn,
        isArray: isArray,
        sortedInts: sortedInts,
        hypot: hypot
    };

    /* --- timing (core/timing.py, spec section 4) --------------------------
     *
     * .rbj is frame-based and After Effects is not: it addresses keyframes and
     * comp time in seconds, so every read and write on this side crosses here.
     */

    RB.timing = {};

    RB.timing.frameToSeconds = function (frame, fps, startFrame) {
        if (startFrame === undefined) { startFrame = 0; }
        return (Number(frame) - Number(startFrame)) / Number(fps);
    };

    RB.timing.secondsToFrame = function (seconds, fps, startFrame) {
        /* Rounds half up, and never truncates. Host key times land just under
         * the exact value - After Effects reported 8.333333 s for frame 200 at
         * 24 fps, which truncation turns into frame 199. */
        if (startFrame === undefined) { startFrame = 0; }
        return Math.floor(Number(seconds) * Number(fps) + Number(startFrame) + 0.5);
    };

    RB.timing.snapFrame = function (value) {
        return Math.floor(Number(value) + 0.5);
    };

    RB.timing.subframeResidual = function (seconds, fps, startFrame) {
        /* How far, in frames, `seconds` sits from the frame it snaps to.
         * After Effects permits keyframes off the frame grid; spec section 9
         * requires every `keys[].frame` to exist in `frames`, so such a key
         * gets snapped and warned about, and this is the number that decides
         * whether the warning is warranted and what it says. */
        if (startFrame === undefined) { startFrame = 0; }
        var exact = Number(seconds) * Number(fps) + Number(startFrame);
        return exact - RB.timing.secondsToFrame(seconds, fps, startFrame);
    };

    RB.timing.frameRange = function (first, last) {
        first = Math.floor(Number(first));
        last = Math.floor(Number(last));
        if (first > last) {
            throw new Error("range is not ascending: [" + first + ", " + last + "]");
        }
        var out = [];
        for (var f = first; f <= last; f++) { out[out.length] = f; }
        return out;
    };

    RB.timing.offsetToStart = function (srcFirst, dstFirst) {
        /* Added to source frames: srcFirst + offsetToStart(...) === dstFirst.
         * The direction is the easy thing to get backwards. */
        return Math.floor(Number(dstFirst)) - Math.floor(Number(srcFirst));
    };

    /* --- geometry (core/geom.py, spec section 3) --------------------------
     *
     * Canonical space is Nuke's: origin bottom-left, Y up, pixels, tangents
     * stored vertex-relative. These take points already in COMP space - the
     * layer-to-comp step is `sourcePointToComp`, which the host does exactly,
     * including rotation and non-uniform scale (Phase 0 section F). Redoing it
     * here would add a second source of truth for no gain.
     */

    RB.geom = {};

    RB.geom.compToCanonicalPoint = function (p, compHeight) {
        return [Number(p[0]), Number(compHeight) - Number(p[1])];
    };

    RB.geom.canonicalToCompPoint = function (p, compHeight) {
        /* Its own involution, which is why there is one formula and two names:
         * the call sites read in opposite directions and should say so. */
        return [Number(p[0]), Number(compHeight) - Number(p[1])];
    };

    RB.geom.compToCanonicalTangent = function (t) {
        /* Vertex-relative, so only the Y flip applies - no height. */
        return [Number(t[0]), -Number(t[1])];
    };

    RB.geom.canonicalToCompTangent = function (t) {
        return [Number(t[0]), -Number(t[1])];
    };

    RB.geom.aePointToCanonical = function (point, compHeight) {
        /* One .rbj point object (spec section 8) from comp space to canonical.
         * `feather` carries through untouched: it is a signed scalar along the
         * path normal with no Y component to flip. After Effects never writes
         * `feather_offset`. */
        var out = {
            "c": RB.geom.compToCanonicalPoint(point["c"], compHeight),
            "in": RB.geom.compToCanonicalTangent(point["in"]),
            "out": RB.geom.compToCanonicalTangent(point["out"])
        };
        if (hasOwn(point, "feather")) { out["feather"] = Number(point["feather"]); }
        return out;
    };

    RB.geom.canonicalPointToAe = function (point, compHeight) {
        /* Drops `feather_offset`: it is Nuke's tangential component and has no
         * After Effects representation (spec section 11.1). The caller warns;
         * this has no shape name to name. */
        var out = {
            "c": RB.geom.canonicalToCompPoint(point["c"], compHeight),
            "in": RB.geom.canonicalToCompTangent(point["in"]),
            "out": RB.geom.canonicalToCompTangent(point["out"])
        };
        if (hasOwn(point, "feather")) { out["feather"] = Number(point["feather"]); }
        return out;
    };

    /* --- the layer transform as an affine (prd.md section 9.1 step 4) -----
     *
     * `sourcePointToComp` is a host call, and the naive loop makes three of
     * them per vertex per frame: the vertex, and `vertex + tangent` for each
     * side. Ten shapes of twenty points over 150 frames is 90,000 calls, on top
     * of the `comp.time` assignment that prd.md section 9.1 already identifies
     * as the bottleneck. Acceptance criterion 11 gives the whole export ten
     * seconds.
     *
     * A 2D unparented layer's transform - anchor point, position, scale,
     * rotation, skew - is **affine**, and an affine map is fully determined by
     * where it sends three non-collinear points. So probe it three times per
     * frame and apply it in arithmetic thereafter: 450 host calls instead of
     * 90,000, and exact rather than approximate. 3D and parented layers are
     * already hard failures (prd.md section 11), which is what makes the
     * affine claim safe to rely on.
     *
     * "Safe to rely on" is still an assumption, and this project has been
     * caught by two of those already (`getMatrixAt`, `AnimAttributes.addKey`).
     * So the caller checks it: `affineDisagreement` transforms a real vertex
     * both ways and returns the distance between the answers. A frame where
     * that is not ~0 falls back to the host and warns, rather than writing
     * geometry nobody measured.
     */

    /* Probed a hundred units out rather than one. The arithmetic is identical
     * either way; the wider basis just keeps more significant digits when the
     * layer sits far from its anchor. */
    var AFFINE_SPAN = 100.0;

    RB.geom.AFFINE_SPAN = AFFINE_SPAN;

    RB.geom.affineFromProbes = function (origin, spanX, spanY) {
        /* The affine that sends [0,0] to `origin`, [SPAN,0] to `spanX` and
         * [0,SPAN] to `spanY`. Returns [a, b, tx, c, d, ty], so that
         * x' = a*x + b*y + tx and y' = c*x + d*y + ty. */
        var a = (spanX[0] - origin[0]) / AFFINE_SPAN;
        var c = (spanX[1] - origin[1]) / AFFINE_SPAN;
        var b = (spanY[0] - origin[0]) / AFFINE_SPAN;
        var d = (spanY[1] - origin[1]) / AFFINE_SPAN;
        return [a, b, Number(origin[0]), c, d, Number(origin[1])];
    };

    RB.geom.applyAffinePoint = function (m, p) {
        var x = Number(p[0]);
        var y = Number(p[1]);
        return [m[0] * x + m[1] * y + m[2], m[3] * x + m[4] * y + m[5]];
    };

    RB.geom.applyAffineTangent = function (m, t) {
        /* The linear part only. A tangent is a difference of two points, so
         * the translation cancels - which is the same thing the
         * transform-then-subtract rule of prd.md section 9.1 does, without the
         * two extra host calls. */
        var x = Number(t[0]);
        var y = Number(t[1]);
        return [m[0] * x + m[1] * y, m[3] * x + m[4] * y];
    };

    RB.geom.affineDisagreement = function (m, p, hostResult) {
        /* How far, in pixels, the derived affine lands from what the host says
         * for the same point. The runtime check on the assumption above. */
        var mine = RB.geom.applyAffinePoint(m, p);
        return hypot(mine[0] - Number(hostResult[0]),
                     mine[1] - Number(hostResult[1]));
    };

    /* --- After Effects feather points (prd.md section 9.3) ---------------
     *
     * The two applications anchor feather differently and neither is a
     * superset. After Effects places a point anywhere along a segment and
     * gives it a signed distance along the normal; Nuke anchors at a vertex
     * and gives it a free 2-D offset. `.rbj` carries one signed scalar per
     * vertex, so this side resolves a segment location to a vertex going out
     * and invents one coming back.
     *
     * Probe run 3 read four points off a seven-vertex mask - three
     * mid-segment, two on the same segment, one with a radius of exactly zero.
     * Every branch below comes from that data.
     */

    RB.geom.snapFeatherPoints = function (segLocs, relLocs, radii, vertexCount) {
        /* Returns {feather, snapped, dropped}. `feather` is `vertexCount`
         * long, zero where no point resolved there. `snapped` lists the
         * indices of points that were not already on a vertex, and `dropped`
         * the ones a collision discarded, each as
         * {index, vertex, radius, kept}. Both are for the caller's warnings;
         * this has no shape name to put in one.
         *
         * A point at `rel` 0.0 belongs to the segment's start vertex and one
         * at 1.0 to its end, both exactly. Anything between is snapped to the
         * nearer, which spec section 12.2 calls a soft failure. **A radius of
         * exactly zero is an authored point**, not an absent one: it pins the
         * feather back to zero width and competes for its vertex on equal
         * terms. */
        var feather = [];
        var i;
        for (i = 0; i < vertexCount; i++) { feather[i] = 0.0; }

        var claimedIndex = {};
        var claimedRadius = {};
        var snapped = [];
        var dropped = [];

        for (i = 0; i < radii.length; i++) {
            var rel = Number(relLocs[i]);
            var seg = Math.floor(Number(segLocs[i]));
            var radius = Number(radii[i]);

            var vertex = (rel >= 0.5) ? (seg + 1) % vertexCount
                                      : seg % vertexCount;
            if (rel !== 0.0 && rel !== 1.0) { snapped[snapped.length] = i; }

            if (hasOwn(claimedIndex, vertex)) {
                var otherIndex = claimedIndex[vertex];
                var otherRadius = claimedRadius[vertex];
                /* Larger magnitude wins. On a tie the earlier point holds the
                 * vertex, so the result does not depend on read order. */
                if (Math.abs(radius) > Math.abs(otherRadius)) {
                    dropped[dropped.length] = { index: otherIndex,
                                                vertex: vertex,
                                                radius: otherRadius,
                                                kept: radius };
                    claimedIndex[vertex] = i;
                    claimedRadius[vertex] = radius;
                    feather[vertex] = radius;
                } else {
                    dropped[dropped.length] = { index: i, vertex: vertex,
                                                radius: radius,
                                                kept: otherRadius };
                }
            } else {
                claimedIndex[vertex] = i;
                claimedRadius[vertex] = radius;
                feather[vertex] = radius;
            }
        }

        return { feather: feather, snapped: snapped, dropped: dropped };
    };

    RB.geom.featherPointsFromVertices = function (feather) {
        /* Returns {segLocs, relLocs, radii, types}, one entry per vertex, each
         * point pinned to the start of its own vertex's segment.
         *
         * `featherRadii` is signed and its sign agrees with `featherTypes` -
         * run 3 read type 0 back non-negative and type 1 non-positive - so the
         * radius alone carries the direction and the type is redundant. It is
         * still written consistently, because a point's direction cannot be
         * changed after creation and the host has to be given the right one up
         * front.
         *
         * Zeros are emitted rather than skipped: a shape with some zero and
         * some non-zero offsets is `per_point`, and dropping the zeros would
         * widen the feather at exactly the vertices that were pinned to
         * nothing. */
        var segLocs = [], relLocs = [], radii = [], types = [];
        for (var i = 0; i < feather.length; i++) {
            var d = Number(feather[i]);
            segLocs[i] = i;
            relLocs[i] = 0.0;
            radii[i] = d;
            types[i] = (d >= 0.0) ? 0 : 1;
        }
        return { segLocs: segLocs, relLocs: relLocs, radii: radii,
                 types: types };
    };

    /* --- interpolation (core/interp.py, spec section 10) ------------------ */

    RB.interp = {};

    RB.interp.HOLD = "hold";
    RB.interp.LINEAR = "linear";
    RB.interp.EASE = "ease";

    /* KeyframeInterpolationType, read off the host in Phase 0 (probe runs 2
     * and 4) rather than trusted from documentation. LINEAR is the *lowest* of
     * the three, which is easy to invert from memory because the menu presents
     * them in the other order. */
    RB.interp.AE_LINEAR = 6612;
    RB.interp.AE_BEZIER = 6613;
    RB.interp.AE_HOLD = 6614;

    RB.interp.AE_INFLUENCE_SCALE = 100.0;
    RB.interp.AE_DEFAULT_INFLUENCE = 16.667;

    RB.interp.sideFromAe = function (aeType) {
        /* Anything unrecognised is `ease`, not an error: spec section 10.3
         * defines bare `ease` as "smooth, parameters unknown, rely on the
         * drift pass", which is a truthful description of an unknown type and
         * keeps the geometry correct whatever it was. */
        if (aeType === RB.interp.AE_HOLD) { return RB.interp.HOLD; }
        if (aeType === RB.interp.AE_LINEAR) { return RB.interp.LINEAR; }
        return RB.interp.EASE;
    };

    RB.interp.sideToAe = function (side) {
        if (side === RB.interp.HOLD) { return RB.interp.AE_HOLD; }
        if (side === RB.interp.LINEAR) { return RB.interp.AE_LINEAR; }
        return RB.interp.AE_BEZIER;
    };

    RB.interp.easeFromAe = function (influence, speed) {
        /* Influence is scaled, speed is not: influence is a percentage of the
         * interval and normalises across control points, while speed is in
         * value-units per second and does not. That asymmetry is why the
         * freeze made `ease` shape-wide. */
        return [Number(influence) / RB.interp.AE_INFLUENCE_SCALE, Number(speed)];
    };

    RB.interp.easeToAe = function (pair) {
        /* Returns [influencePercent, speed]. Clamped to the 0.1-100 range
         * After Effects accepts: spec section 10.3 permits a stored 0.0, which
         * would otherwise raise inside the host rather than degrade. */
        var influence = Number(pair[0]) * RB.interp.AE_INFLUENCE_SCALE;
        if (influence < 0.1) { influence = 0.1; }
        if (influence > 100.0) { influence = 100.0; }
        return [influence, Number(pair[1])];
    };

    /* --- drift (core/drift.py, prd.md sections 5.4 and 8) -----------------
     *
     * Tier 3. Setting the authored keys is not enough: tiers 1 and 2 fit the
     * destination's interpolation as closely as it can be fitted, and whatever
     * is left over is measured here against the dense layer and pinned with
     * extra keys. That is what makes tier 2 safe - the fit can be wrong, the
     * positions cannot.
     *
     * Both host calls are injected, exactly as in the Python, so this runs
     * under a test harness with no After Effects and the AE adapter supplies
     * `setValueAtTime` for `applyKeys` and `valueAtTime` for `measure`.
     */

    RB.drift = {};

    RB.drift.gaps = function (frames, keys) {
        /* Maximal runs of consecutive non-key frames, in order. */
        var keyed = {};
        for (var k = 0; k < keys.length; k++) { keyed[keys[k]] = true; }
        var runs = [];
        var current = [];
        for (var i = 0; i < frames.length; i++) {
            if (hasOwn(keyed, frames[i])) {
                if (current.length) { runs[runs.length] = current; current = []; }
            } else {
                current[current.length] = frames[i];
            }
        }
        if (current.length) { runs[runs.length] = current; }
        return runs;
    };

    function survey(frames, keys, measure, tolerance) {
        /* Measure every non-key frame once. Returns
         * {additions, worst, at}: the worst frame of each gap that exceeds
         * tolerance, the worst deviation seen anywhere, and its frame. */
        var additions = [];
        var worst = 0.0;
        var worstAt = null;
        var runs = RB.drift.gaps(frames, keys);
        for (var r = 0; r < runs.length; r++) {
            var run = runs[r];
            var at = null;
            var deviation = -1.0;
            for (var i = 0; i < run.length; i++) {
                var here = Number(measure(run[i]));
                if (here > deviation) { at = run[i]; deviation = here; }
            }
            if (deviation > worst) { worst = deviation; worstAt = at; }
            if (deviation > tolerance) { additions[additions.length] = at; }
        }
        return { additions: additions, worst: worst, at: worstAt };
    }

    RB.drift.correct = function (frames, keys, applyKeys, measure, tolerance,
                                 maxPasses) {
        /* Add corrective keys until nothing drifts past `tolerance`.
         *
         * `applyKeys(keyFrames)` writes exactly those keys into the
         * destination. `measure(frame)` returns the worst deviation at that
         * frame, in pixels, between what the destination now interpolates and
         * the dense layer.
         *
         * Returns {keys, worst, at}. **On return the destination holds exactly
         * `keys`** - the last thing this does is apply and measure, so a caller
         * never has to guess whether the host is a pass behind. `worst` is
         * above `tolerance` only when `maxPasses` ran out, which is what a
         * caller warns about, and `at` is what makes that warning actionable:
         * prd.md section 8 requires the import report to name the frames of
         * worst drift.
         *
         * One frame is added per gap per pass, the worst in that gap, rather
         * than every offending frame. A key at the worst point of a run splits
         * it in two and usually fixes most of it, so bisecting converges in a
         * few passes and lands far fewer keys. Every gap is worked in the same
         * pass, so the pass count scales with how deep the worst gap has to
         * subdivide, not with the number of gaps.
         */
        if (maxPasses === undefined) { maxPasses = 8; }
        frames = sortedInts(frames);
        if (!frames.length) {
            throw new Error("drift pass needs at least one frame");
        }

        if (tolerance <= 0.0) {
            /* Tolerance 0 is the dense mode of prd.md section 8: every frame
             * is a key by definition and there is nothing left to measure.
             * Guarding here rather than letting the loop discover it means a
             * host's own storage residual can never be mistaken for drift that
             * more keys would fix. */
            applyKeys(frames);
            return { keys: frames, worst: 0.0, at: null };
        }

        var inRange = {};
        for (var f = 0; f < frames.length; f++) { inRange[frames[f]] = true; }
        var wanted = sortedInts(keys);
        var current = [];
        for (var w = 0; w < wanted.length; w++) {
            if (hasOwn(inRange, wanted[w])) { current[current.length] = wanted[w]; }
        }
        if (!current.length) {
            throw new Error("drift pass needs at least one key inside the frame"
                            + " range; got [" + wanted.join(", ") + "] against ["
                            + frames[0] + ", " + frames[frames.length - 1] + "]");
        }

        var converged = false;
        var result = { additions: [], worst: 0.0, at: null };
        for (var pass = 0; pass < maxPasses; pass++) {
            applyKeys(current);
            result = survey(frames, current, measure, tolerance);
            if (!result.additions.length) { converged = true; break; }
            current = sortedInts(current.concat(result.additions));
        }

        if (!converged) {
            /* The last pass chose frames it never got to apply. Apply and
             * re-measure so the host state and the returned `worst` both
             * describe `current`. */
            applyKeys(current);
            result = survey(frames, current, measure, tolerance);
        }

        return { keys: current, worst: result.worst, at: result.at };
    };

    return RB;
}());

/* Under node for the test harness; inert inside ExtendScript, which has no
 * `module`. This is what lets the port be verified before After Effects sees
 * it. */
if (typeof module !== "undefined" && module.exports) { module.exports = RB; }
