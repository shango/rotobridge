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

    /* --- build version ----------------------------------------------------
     *
     * Mirrors `core/version.py`; see that file for why this is not the .rbj
     * format version and why three files spell the same number.
     */

    RB.NAME = "RotoBridge";
    RB.VERSION = "0.10.0";
    RB.LABEL = RB.NAME + " " + RB.VERSION;

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

    RB.geom.featherAnchors = function (segLocs, relLocs, radii, vertexCount,
                                       closed) {
        /* After Effects feather points as the `feather_points` of spec
         * section 6.3: a list of {t, feather} sorted by t ascending.
         *
         * This is the lossless reading. `snapFeatherPoints` above resolves the
         * same input onto vertices and is what v1 files carry, at the cost
         * section 6.1 measures. Both are kept, because a file whose anchors
         * already sit on vertices is still a v1 file (section 6.7) and the
         * snap is still the fallback for a destination that cannot take extra
         * vertices.
         *
         * `t = segment + fraction` (section 6.4). One number rather than the
         * pair the host reports, because the pair is not stable: After Effects
         * renames a point written at (i, 0) to (i-1, 1) and regroups the
         * arrays by feather type when the shape is read between keyframes.
         * Both preserve the sum, which is why the sum is what is stored. On a
         * closed shape t = vertexCount names the same anchor as t = 0 and
         * section 6.4 requires the latter, so it wraps.
         *
         * **Sorted per frame, independently.** The host's array order is not
         * stable across frames - that same regrouping - so there is no index
         * to carry an anchor's identity from one frame to the next, and
         * sorting is the only thing that produces the required order. It also
         * means this cannot see two anchors crossing: the sorted sequence is
         * monotone by construction. Section 6.5 puts that on the reader, which
         * has the whole file at once.
         *
         * The tie-break on feather is for determinism, not meaning: two
         * anchors at one t are interchangeable, and re-exporting one scene
         * must not produce a different file because the host grouped its
         * arrays differently. */
        if (closed === undefined) { closed = true; }
        var anchors = [];
        for (var i = 0; i < radii.length; i++) {
            var t = Math.floor(Number(segLocs[i])) + Number(relLocs[i]);
            if (closed) {
                t = t % vertexCount;
                if (t < 0) { t += vertexCount; }
            }
            anchors[anchors.length] = { "t": t, "feather": Number(radii[i]) };
        }
        anchors.sort(function (a, b) {
            if (a["t"] !== b["t"]) { return a["t"] - b["t"]; }
            return a["feather"] - b["feather"];
        });
        return anchors;
    };

    RB.geom.featherPointsFromAnchors = function (anchors) {
        /* `feather_points` (spec section 6.3) back to the arrays After Effects
         * wants: {segLocs, relLocs, radii, types}.
         *
         * The inverse of `featherAnchors`, and the easy direction - AE anchors
         * feather anywhere along a segment, so every entry lands exactly where
         * the file says and nothing is snapped, split or dropped.
         *
         * t = segment + fraction, so the split is the floor and the remainder.
         * An integral t is written as (t, 0.0), the start of its own segment;
         * the host renames that to (t-1, 1.0) on the way back out, and
         * `featherAnchors` reads either spelling as the same number.
         *
         * `types` follows the sign, for the reason featherPointsFromVertices
         * gives: a point's direction cannot be changed after creation. */
        var segLocs = [], relLocs = [], radii = [], types = [];
        for (var i = 0; i < anchors.length; i++) {
            var t = Number(anchors[i]["t"]);
            var segment = Math.floor(t);
            var d = Number(anchors[i]["feather"]);
            segLocs[i] = segment;
            relLocs[i] = t - segment;
            radii[i] = d;
            types[i] = d >= 0.0 ? 0 : 1;
        }
        return { segLocs: segLocs, relLocs: relLocs, radii: radii,
                 types: types };
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
        /* Measure every non-key frame once. Returns {additions, worst, at}:
         * the frames to key next, the worst deviation seen anywhere, and its
         * frame.
         *
         * A gap over tolerance contributes its worst frame, and the gap's
         * MIDPOINT as well when that worst frame is one of the gap's two ends.
         * A key on the end of a run does not split it - it shortens it by one
         * frame - and correct()'s convergence argument is that a run gets
         * split. Error that grows steadily across a run puts its maximum on the
         * run's last frame every time, so the pass would walk backwards one
         * frame per pass instead of halving. That is what an outgoing `hold`
         * does when an ancestor transform moves the geometry through the held
         * interval. Mirrors core/drift.py, which carries the full reasoning. */
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
            if (deviation > tolerance) {
                if (at === run[0] || at === run[run.length - 1]) {
                    additions[additions.length] =
                        run[Math.floor(run.length / 2)];
                }
                additions[additions.length] = at;
            }
        }
        return { additions: additions, worst: worst, at: worstAt };
    }

    RB.drift.correct = function (frames, keys, applyKeys, measure, tolerance,
                                 maxPasses, authoredFrames) {
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
         * One or two frames are added per gap per pass - the worst in that
         * gap, and the gap's midpoint when the worst frame is an end of it -
         * rather than every offending frame. A key inside a run splits it in
         * two and usually fixes most of it, so bisecting converges in a few
         * passes and lands far fewer keys; survey() carries why the midpoint is
         * needed. Every gap is worked in the same pass, so the pass count
         * scales with how deep the worst gap has to subdivide, not with the
         * number of gaps.
         *
         * Bisecting overshoots, so sweep() then takes back what it can. **Only
         * invented keys are ever removed.** By default every frame the caller
         * asked for counts as authored and survives; a caller that knows
         * better - an importer reading a file that names the artist's own
         * frames - passes `authoredFrames`, and then the keys the caller
         * seeded but the artist never made (an exporter's pinned endpoints, a
         * layer transform's frames) are the sweep's to give back too. The
         * artist's keys are never this function's to optimise away, whatever
         * the tolerance would allow.
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
        var authored = {};
        var authoredSource = authoredFrames === undefined
            || authoredFrames === null ? current : authoredFrames;
        for (var a = 0; a < authoredSource.length; a++) {
            authored[authoredSource[a]] = true;
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
            return { keys: current, worst: result.worst, at: result.at };
        }

        var swept = sweep(frames, current, authored, applyKeys, measure,
                          tolerance);
        if (swept.length !== current.length) {
            /* The sweep left the host holding whichever trial it tried last,
             * which is not necessarily what it kept. Re-establish the
             * contract. */
            current = swept;
            applyKeys(current);
            result = survey(frames, current, measure, tolerance);
        }

        return { keys: current, worst: result.worst, at: result.at };
    };

    function sweep(frames, keys, authored, applyKeys, measure, tolerance) {
        /* Give back every added key the fit turns out not to need.
         *
         * correct() bisects, and bisection overshoots: it pins a gap's worst
         * frame and the gap's midpoint together, and the midpoint is usually
         * made redundant the moment the worst frame lands beside it. Nothing
         * in the loop revisits that. Mirrors core/drift.py `_sweep`, which
         * carries the measurement.
         *
         * `authored` is a set of the caller's own key frames, which are never
         * candidates - a shape cannot come back with fewer keys than the artist
         * put on it. Backwards, because the redundant midpoint is the one whose
         * neighbour landed after it.
         *
         * Removing a key only changes what the destination draws **between its
         * two neighbours**, so only that window is re-measured. An endpoint is
         * a candidate like any other unauthored key: dropping one truncates
         * the keyed span rather than merging two segments, and both hosts
         * hold the nearest key's value beyond it - so its window is everything
         * past its surviving neighbour, and a span that really is flat out to
         * the edge gives its endpoint back. One key always survives, because a
         * destination cannot hold a shape with none.
         *
         * **On return the destination holds exactly what is returned**, which
         * is what lets correct() keep its own promise. A trial has to be
         * applied to be measured, so a rejected one leaves the host a key short
         * of the answer - and the last trial is rejected as often as not.
         */
        var keep = keys.slice(0);
        var stale = false;
        for (var k = keys.length - 1; k >= 0; k--) {
            var frame = keys[k];
            if (hasOwn(authored, frame) || keep.length === 1) {
                continue;
            }
            var at = indexOf(keep, frame);
            var low = at > 0 ? keep[at - 1] : null;
            var high = at + 1 < keep.length ? keep[at + 1] : null;
            var trial = keep.slice(0, at).concat(keep.slice(at + 1));
            applyKeys(trial);
            stale = true;
            if (tolerance === Infinity) {
                /* Unbounded means "authored keys only" (prd.md section 8): no
                 * measurement can refuse the trial, so none is taken. */
                keep = trial;
                stale = false;
                continue;
            }
            var worst = 0.0;
            for (var f = 0; f < frames.length; f++) {
                if ((low === null || frames[f] > low)
                        && (high === null || frames[f] < high)) {
                    var here = Number(measure(frames[f]));
                    if (here > worst) { worst = here; }
                    if (worst > tolerance) { break; }
                }
            }
            if (worst <= tolerance) { keep = trial; stale = false; }
        }
        if (stale) { applyKeys(keep); }
        return keep;
    }

    function linearError(dense, keys, frame, held) {
        /* The worst component of what the destination will draw against the
         * bake. Mirrors core/drift.py `_linear_error`.
         *
         * A straight line between the bracketing keys, except where the key
         * before holds: `held` names the key frames whose outgoing side is
         * `hold`, and a held segment is flat by definition (spec section
         * 10.2). Measuring one as a line would report the whole travel of the
         * next key as drift and buy keys to flatten something already flat -
         * which is how a conform meaning to preserve holds would destroy them.
         */
        var target = dense[String(frame)];
        var before = null, after = null;
        var i;
        for (i = 0; i < keys.length; i++) {
            if (keys[i] <= frame) { before = keys[i]; }
            else if (after === null) { after = keys[i]; }
        }
        var worst = 0.0, value;
        if (before !== null && hasOwn(held, String(before))) {
            var flat = dense[String(before)];
            for (i = 0; i < target.length; i++) {
                value = Math.abs(flat[i] - target[i]);
                if (value > worst) { worst = value; }
            }
            return worst;
        }
        if (before === null || after === null) {
            /* Outside the keyed span there is no line to draw: the destination
             * holds the nearest key's value, which is what both hosts do
             * beyond their first and last key. */
            var edge = dense[String(before === null ? after : before)];
            for (i = 0; i < target.length; i++) {
                value = Math.abs(edge[i] - target[i]);
                if (value > worst) { worst = value; }
            }
            return worst;
        }

        var ratio = (frame - before) / (after - before);
        var low = dense[String(before)], high = dense[String(after)];
        for (i = 0; i < target.length; i++) {
            value = Math.abs(low[i] + (high[i] - low[i]) * ratio - target[i]);
            if (value > worst) { worst = value; }
        }
        return worst;
    }

    RB.drift.linearFit = function (frames, dense, keys, tolerance, holds,
                                   authoredFrames) {
        /* The key frames a LINEAR sparse layer needs to reproduce the dense
         * one. Mirrors core/drift.py `linear_fit`, which carries the full
         * reasoning.
         *
         * The export side of the question correct() answers at import, and the
         * same search: only the measure differs, and it needs no host, because
         * what a straight line between two keys leaves on the frames between
         * them is arithmetic on numbers the exporter already has.
         *
         * `dense` maps a frame to a flat array of every scalar the destination
         * will interpolate - each point's centre, both tangents and its
         * feather, end to end. Tangents and feather are measured on the same
         * scale as vertices against the same tolerance, which is the rule the
         * Nuke importer already applies: a tangent that drifts bends the
         * rendered edge exactly as far as a vertex that drifts.
         *
         * Returns {keys, worst, at}, as correct() does, and
         * `authoredFrames` passes straight through to it: a caller whose seed
         * keys are all its own invention - an attribute collapse seeding the
         * range endpoints - passes an empty array, and the fit may then land
         * fewer keys than it was given.
         */
        var chosen = sortedInts(keys);
        var held = {};
        var h = sortedInts(holds || []);
        for (var i = 0; i < h.length; i++) { held[String(h[i])] = true; }

        function applyKeys(keyFrames) { chosen = sortedInts(keyFrames); }

        function measure(frame) {
            return linearError(dense, chosen, frame, held);
        }

        return RB.drift.correct(frames, keys, applyKeys, measure, tolerance,
                                undefined, authoredFrames);
    };


    /* --- warnings (core/messages.py) --------------------------------------
     *
     * Every warning either implementation can write, rendered from one table.
     * The string leads with its code - "[feather-snapped] mask 'X': ..." - so
     * tests and tools match the code and the prose can be rewritten freely.
     * The Python file carries the full reasoning; the cross-check renders
     * every code on both sides and compares bytes, which is what keeps the
     * two hosts' prose for the same loss from drifting apart.
     */

    RB.messages = {};

    RB.messages.TEMPLATES = {
        "blend-unmapped":
            "{subject}: .rbj blend '{blend}' has no Nuke roto equivalent"
                + " - Nuke blends pixels, it has no boolean shape operations;"
                + " used 'over' instead",
        "comp-size-differs":
            "the file was exported from a {src} comp and this one is"
                + " {dst}; coordinates were used as-is, not rescaled",
        "drift-residual":
            "{subject}: the drift pass ran out of passes with {residual}"
                + " px still unaccounted for at frame {frame}; re-import this"
                + " shape at a tighter tolerance if it shows",
        "ease-conformed":
            "{subject}: {count} key side(s) carried temporal ease, which"
                + " Nuke's roto curves cannot hold. They were rewritten as"
                + " linear and {added} key(s) added, so the path is within"
                + " {tolerance} px of this comp on every frame. What is lost is"
                + " editable timing, not the shape",
        "ease-restored":
            "{subject}: the file's keys were conformed to linear on the way"
                + " out, for a destination that cannot hold temporal ease."
                + " This one can, so the {count} authored key(s) were rebuilt"
                + " from the timing the file kept beside them. The conform"
                + " warning the file carries does not apply here",
        "ease-dropped":
            "{subject}: {count} key(s) carry authored ease. Nuke's roto"
                + " curves cannot hold it, so the shape arrives as a dense bake"
                + " and the keyframe timing is not editable downstream."
                + " Geometry is unaffected",
        "element-skipped":
            "element '{name}' of unhandled type {type} skipped",
        "expansion-dropped":
            "{subject}: mask expansion of {px} px was dropped; .rbj v1"
                + " has no field for it",
        "expansion-animated":
            "{subject}: mask expansion is keyed on more than one frame and"
                + " was dropped entirely, animation and all; .rbj v1 has no"
                + " field for it",
        "feather-anchored-v2":
            "{subject}: feather is anchored along the path rather than at"
                + " vertices, which only .rbj version 2 can express, so this"
                + " file is version 2 and a version 1 reader will refuse it."
                + " Nothing is lost; under version 1 this mask's feather was"
                + " being moved to the nearest vertex",
        "feather-anchors-collide":
            "{subject}: {count} feather anchor(s) share a position with"
                + " another and could not be given a vertex of their own; the"
                + " larger radius was kept. Nuke carries one feather offset per"
                + " control point",
        "feather-anchors-cross":
            "{subject}: feather anchors cross each other between frames"
                + " ({detail} vertices would be needed), which would change the"
                + " shape's topology partway through. They were snapped to"
                + " vertices as .rbj version 1 does, so this shape's feather is"
                + " placed as it would have been before",
        "feather-count-changes":
            "{subject}: the number of feather points changes between"
                + " frames, which no .rbj version can carry - there is no"
                + " correct interpolation between two counts - so the anchors"
                + " were snapped to vertices as version 1 does",
        "feather-degenerate-vertex":
            "{subject}: a feather point sits on a degenerate vertex with"
                + " no defined normal; its feather was dropped",
        "feather-duplicate-dropped":
            "{subject}: two feather points resolved to vertex {vertex};"
                + " kept radius {kept} and dropped {dropped}",
        "feather-shaping-dropped":
            "{subject}: feather point {members} value(s) were authored;"
                + " .rbj has no member for them, so the feather's placement and"
                + " radius travel but this shaping does not",
        "feather-snapped":
            "{subject}: {count} feather point(s) sat mid-segment and were"
                + " snapped to the nearer vertex; Nuke can only anchor feather"
                + " at a vertex",
        "feather-tangential":
            "{subject}: feather offsets depart from the path normal; the"
                + " tangential component survives in feather_offset but is lost"
                + " to adapters other than Nuke",
        "feather-vertices-inserted":
            "{subject}: {count} {noun} inserted to hold feather anchors"
                + " that sat mid-segment. The subdivision is exact, so the"
                + " shape has not moved - it has more points than the artist"
                + " drew because Nuke can only anchor feather at a vertex",
        "file-from-newer-tool":
            "this file comes from RotoBridge {theirs} and this side is"
                + " running {ours}, which is older; it should still read"
                + " correctly, but update this side so both speak the same"
                + " build",
        "fps-differs":
            "the file was exported at {src} fps and this comp is {dst}"
                + " fps; frame numbers were used as-is, so the timing in"
                + " seconds differs",
        "hold-under-motion":
            "{subject}: {count} key(s) hold the mask path while the layer"
                + " moves under it, so the shape is not flat there and the hold"
                + " is not carried as one. Geometry is unaffected; what is lost"
                + " is a held key the artist could edit",
        "interp-mixed":
            "{subject}: {count} key(s) interpolate differently from one"
                + " control point to the next, which has no single-valued form;"
                + " they were written as 'ease' with no parameters and the"
                + " importer's drift pass carries the geometry (prd.md section"
                + " 7, tier 2)",
        "inverted-dropped":
            "{subject}: the inverted flag was dropped; .rbj v1 has no"
                + " field for it",
        "key-off-grid":
            "{subject}: a key sat {offset} of a frame off the grid and"
                + " was snapped to frame {frame}; .rbj keys are whole frames",
        "key-sides-collapsed":
            "{subject}: {count} key(s) carry a different interpolation on"
                + " each side, which a Nuke key cannot hold - one type governs"
                + " the whole key. The closest type Nuke has was used and the"
                + " drift pass corrected the positions",
        "keys-added":
            "{subject}: {added} key(s) added so a straight line between"
                + " keys stays within {tolerance} px of this comp on every"
                + " frame. Nothing the artist authored changed; the sparse"
                + " layer now needs no correction downstream",
        "layer-flattened":
            "layer '{name}' flattened to the root",
        "mask-mode-unmapped":
            "{subject}: mask mode '{mode}' has no .rbj equivalent; wrote"
                + " 'union'",
        "name-collision":
            "two masks are both named '{name}' (on layers '{first}' and"
                + " '{second}'); importing a subset by name cannot tell them"
                + " apart",
        "nuke-blend-unmapped":
            "{subject}: Nuke blending mode '{mode}' is a pixel operation"
                + " with no .rbj equivalent; wrote 'union'",
        "attr-animation-dropped":
            "{subject}: {attr} is keyed on more than one frame, but .rbj"
                + " carries it as one value per shape; only its value at the"
                + " first exported frame crossed",
        "open-spline-knobs":
            "{subject}: an open spline's render settings are node knobs"
                + " (openspline_width and the end types), not shape attributes,"
                + " so they are not carried in the file",
        "open-spline-renders-nothing":
            "{subject} is an open spline: After Effects produces no alpha"
                + " from an open mask path, so the geometry arrives exactly but"
                + " the mask renders nothing. Open paths matte in Nuke, not"
                + " here",
        "open-spline-stroke":
            "{subject} is an open spline, which produces no alpha as an"
                + " After Effects mask; the geometry is carried but no stroke"
                + " width or end caps are",
        "open-spline-unverified":
            "{subject} is an open spline from {app}; the geometry is"
                + " exact but what it renders as across applications is"
                + " unverified",
        "pixel-aspect-differs":
            "pixel aspect differs ({src} against {dst}); .rbj v1 treats"
                + " pixels as square",
        "record-unwritable":
            "the import record could not be written to {path} ({reason});"
                + " this import is not recorded anywhere but this dialog",
        "stroke-skipped":
            "paint stroke '{name}' skipped; .rbj v1 carries splines only",
        "subset-missing":
            "shape '{name}' was requested but is not in the file",
        "transform-not-affine":
            "layer '{layer}': its transform is not affine (off by {px}"
                + " px); every point was converted through the host instead,"
                + " which is slower but exact",
        "transform-order-unverified":
            "{subject}: a layer transform and a shape transform are both"
                + " active, and their composition order is unverified (Q10)."
                + " The geometry is baked assuming the shape's own transform"
                + " applies first",
    };

    function messageParam(value) {
        /* One parameter as text, spelled the same way by both
         * implementations. Strings pass through; numbers follow report's
         * rule: whole values lose the trailing zero on both sides. */
        if (typeof value === "string") { return value; }
        if (typeof value !== "number" || value !== value) {
            throw new Error("warning parameters are strings or numbers");
        }
        return String(value);
    }

    RB.messages.px = function (value, places) {
        /* Fixed decimals, rounded half away from zero - toFixed's rule,
         * stated rather than inherited so the Python matches it. */
        var scale = Math.pow(10, places);
        var v = Number(value);
        var scaled = Math.floor(Math.abs(v) * scale + 0.5);
        var sign = (v < 0.0 && scaled) ? "-" : "";
        var frac = String(scaled % scale);
        while (frac.length < places) { frac = "0" + frac; }
        return sign + String(Math.floor(scaled / scale)) + "." + frac;
    };

    RB.messages.codes = function () {
        var out = [];
        for (var code in RB.messages.TEMPLATES) {
            if (hasOwn(RB.messages.TEMPLATES, code)) {
                out[out.length] = code;
            }
        }
        out.sort();
        return out;
    };

    RB.messages.render = function (code, params) {
        /* "[code] " and the filled-in template. Throws on an unknown code or
         * an unfilled placeholder: a malformed warning is a bug in the
         * adapter, not a loss to record. */
        if (!hasOwn(RB.messages.TEMPLATES, code)) {
            throw new Error("unknown warning code: " + code);
        }
        params = params || {};
        var missing = [];
        var text = RB.messages.TEMPLATES[code].replace(
            /\{([a-z0-9_]+)\}/g,
            function (whole, key) {
                if (!hasOwn(params, key)) {
                    missing[missing.length] = key;
                    return whole;
                }
                return messageParam(params[key]);
            });
        if (missing.length) {
            throw new Error("warning '" + code + "' is missing parameter(s): "
                            + missing.join(", "));
        }
        return "[" + code + "] " + text;
    };

    /* --- the durable import record ----------------------------------------
     *
     * The mirror of `core/report.py`, and the one place in this file where the
     * mirroring is the point rather than a convenience: an import record is a
     * document written to settle an argument, so the two hosts have to produce
     * the same one. `TestEs3CrossCheck` renders the same record on both sides
     * and compares it byte for byte.
     */

    RB.report = {};

    RB.report.RULE = repeatChar("-", 78);

    RB.report.SUFFIX = ".rotobridge.txt";

    RB.report.pathFor = function (anchor) {
        /* The record that sits beside `anchor`. Mirrors `core.report.path_for`,
         * including its hand-written `splitext`: only a dot in the last path
         * component counts, and a leading dot is a name rather than an
         * extension. Which file is the anchor is the adapter's decision; the
         * naming is here so the two adapters cannot differ on it. */
        var text = String(anchor);
        var cut = text.lastIndexOf(".");
        var slash = Math.max(text.lastIndexOf("/"), text.lastIndexOf("\\"));
        if (cut > slash + 1) { text = text.substring(0, cut); }
        return text + RB.report.SUFFIX;
    };

    var REPORT_LABEL = 15;

    function repeatChar(c, n) {
        var out = "";
        for (var i = 0; i < n; i++) { out += c; }
        return out;
    }

    function reportNum(value) {
        /* A number spelled the way `core/report.py` spells it. `1.0 === 1`
         * here and `repr(1.0)` is "1.0" there, which is the one accepted
         * divergence between the two writers - and not one a shared document
         * may carry, so whole numbers lose the trailing zero on both sides.
         *
         * Nothing has to be done on this side: `String(24)` is already "24".
         * The function exists so the two implementations name the same rule in
         * the same place. */
        return String(Number(value));
    }

    function reportInt(value) { return String(Math.floor(Number(value))); }

    function reportPixels(value) {
        /* Four decimals, rounded half away from zero. Python's `%.4f` rounds
         * half to even, so the rule is stated rather than inherited. */
        var v = Number(value);
        var scaled = Math.floor(Math.abs(v) * 10000.0 + 0.5);
        var sign = (v < 0.0 && scaled) ? "-" : "";
        var frac = String(scaled % 10000);
        while (frac.length < 4) { frac = "0" + frac; }
        return sign + String(Math.floor(scaled / 10000)) + "." + frac;
    }

    function reportRow(label, text) {
        var padded = label;
        while (padded.length < REPORT_LABEL) { padded += " "; }
        return padded + text;
    }

    function reportTolerance(value) {
        var v = Number(value);
        if (v === Infinity) { return "unbounded (authored keys only)"; }
        if (v === 0.0) { return "0 px (every frame keyed)"; }
        return reportNum(v) + " px";
    }

    function reportShapeLine(shape) {
        var line = "  " + shape.name + ": feather " + shape.feather_model
            + ", " + reportInt(shape.points) + " point(s), "
            + reportInt(shape.authored) + " authored key(s), "
            + reportInt(shape.corrective) + " corrective";
        if (shape.worst_frame === null) {
            /* Both of the drift pass's silent cases: every frame was a key, or
             * nothing between the keys moved. See `core/report.py`. */
            return line + "; nothing drifted from the file";
        }
        return line + "; worst drift " + reportPixels(shape.residual)
            + " px at frame " + reportInt(shape.worst_frame);
    }

    function reportWarnings(lines, subject, messages) {
        if (!messages.length) {
            /* Stated rather than omitted. "Nothing was lost" is a claim the
             * record exists to support, and an absent section makes no claim
             * at all. */
            lines[lines.length] = "no warnings " + subject;
            return;
        }
        lines[lines.length] = String(messages.length) + " warning"
            + (messages.length === 1 ? "" : "s") + " " + subject + ":";
        for (var i = 0; i < messages.length; i++) {
            lines[lines.length] = "  - " + messages[i];
        }
    }

    RB.report.render = function (record) {
        /* One import as text, ending in a newline. See `core/report.py` for
         * what a record carries; every field is required there and here. */
        var src = record.source;
        var first = Number(record.range[0]);
        var last = Number(record.range[1]);
        var offset = Math.floor(Number(record.offset));
        var shapes = record.shapes;
        var i;

        var lines = [
            RB.report.RULE,
            "RotoBridge import record",
            "",
            reportRow("written", record.written),
            reportRow("imported with", record.tool),
            reportRow("into", record.host),
            reportRow("target", record.target),
            "",
            reportRow("source file", record.source_file),
            reportRow("exported by", src.app + " " + src.app_version),
            /* The tool, not the host, and spelled like the row above it. The
             * file stores a bare number; a record sits next to a project and
             * has to say whose. Absent from every file written before the
             * member existed, where a missing row would read as the record
             * forgetting rather than the file never saying. */
            reportRow("exported with", src.tool_version
                      ? RB.NAME + " " + src.tool_version : "not recorded"),
            reportRow("format", ".rbj version " + reportInt(record.version)),
            reportRow("source comp", reportInt(src.width) + " x "
                      + reportInt(src.height) + " at " + reportNum(src.fps)
                      + " fps, pixel aspect " + reportNum(src.pixel_aspect)),
            reportRow("source frames", reportInt(first) + " to "
                      + reportInt(last)),
            reportRow("placed at", reportInt(first + offset) + " to "
                      + reportInt(last + offset) + " (offset "
                      + reportInt(offset) + ")"),
            reportRow("tolerance", reportTolerance(record.tolerance)),
            "",
            String(shapes.length) + " shape(s):"
        ];
        for (i = 0; i < shapes.length; i++) {
            lines[lines.length] = reportShapeLine(shapes[i]);
        }
        lines[lines.length] = "";
        reportWarnings(lines, "recorded when the file was written",
                       record.file_warnings);
        lines[lines.length] = "";
        reportWarnings(lines, "from this import", record.import_warnings);
        lines[lines.length] = "";
        return lines.join("\n") + "\n";
    };

    return RB;
}());

/* Under node for the test harness; inert inside ExtendScript, which has no
 * `module`. This is what lets the port be verified before After Effects sees
 * it. */
if (typeof module !== "undefined" && module.exports) { module.exports = RB; }
