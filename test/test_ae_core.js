/*
 * Tests for the ExtendScript core, run under plain node.
 *
 * `ae/lib/rotobridge_core.jsx` and `ae/lib/rotobridge_rbj.jsx` touch no host, exactly
 * as `core/` touches no host, so both are testable without the application.
 * That is the point of the split: After Effects cannot be driven from CI, and a
 * port verified only by running it inside After Effects is a port verified once
 * a day by hand.
 *
 * The vectors here are deliberately the same ones `test/test_core.py` uses.
 * Two implementations of one spec are worth having only if they are checked
 * against the same cases, and the drift fixture below is the Python's
 * `FakeHost` line for line - a destination that interpolates linearly while
 * truth is a parabola, which is the shape of the error a real host produces
 * when the interpolation translation was not exact.
 *
 * Run:  node test/test_ae_core.js
 */

var path = require("path");
var fs = require("fs");

var ROOT = path.dirname(__dirname);
global.RB = require(path.join(ROOT, "ae", "lib", "rotobridge_core.jsx"));
require(path.join(ROOT, "ae", "lib", "rotobridge_rbj.jsx"));

var timing = RB.timing;
var geom = RB.geom;
var interp = RB.interp;
var drift = RB.drift;
var rbj = RB.rbj;

/* --- a test harness small enough to read ------------------------------- */

var failures = [];
var count = 0;
var suite = "";

function describe(name, body) { suite = name; body(); }

function it(name, body) {
    count += 1;
    try {
        body();
    } catch (e) {
        failures.push(suite + ": " + name + "\n    " + (e.message || e));
    }
}

function fail(message) { throw new Error(message); }

function eq(got, want, note) {
    if (got !== want) {
        fail((note ? note + ": " : "") + "got " + show(got) + ", want " + show(want));
    }
}

function near(got, want, places, note) {
    var tol = Math.pow(10, -places) / 2;
    if (!(Math.abs(got - want) <= tol)) {
        fail((note ? note + ": " : "") + "got " + got + ", want " + want
             + " (within " + tol + ")");
    }
}

function deepEq(got, want, note) {
    var g = JSON.stringify(got);
    var w = JSON.stringify(want);
    if (g !== w) { fail((note ? note + ": " : "") + g + " !== " + w); }
}

function throws(body, note) {
    try {
        body();
    } catch (e) {
        return e;
    }
    fail((note ? note + ": " : "") + "expected a throw, got none");
}

function show(v) { return typeof v === "string" ? '"' + v + '"' : String(v); }

/* --- timing ------------------------------------------------------------ */

describe("timing", function () {
    it("rounds a host time up rather than truncating", function () {
        // After Effects reported 8.333333 s for frame 200 at 24 fps, which
        // truncation turns into 199.
        eq(timing.secondsToFrame(8.333333, 24), 200);
    });

    it("rounds half up, not half to even", function () {
        // Python's built-in round() would send 2.5 to 2 and 3.5 to 4, so a key
        // at exactly x.5 frames would snap in a direction that depends on the
        // parity of the frame number.
        eq(timing.snapFrame(2.5), 3);
        eq(timing.snapFrame(3.5), 4);
    });

    it("converts frames to seconds against a start frame", function () {
        near(timing.frameToSeconds(25, 25, 1), 0.96, 12);
    });

    it("round trips a frame through seconds", function () {
        for (var f = -30; f <= 300; f++) {
            eq(timing.secondsToFrame(timing.frameToSeconds(f, 23.976, 1),
                                     23.976, 1), f, "frame " + f);
        }
    });

    it("reports how far off the grid a key sits", function () {
        near(timing.subframeResidual(0.5 / 24, 24), 0.5 - 1, 12);
        near(timing.subframeResidual(1 / 24, 24), 0.0, 12);
    });

    it("builds an inclusive range", function () {
        deepEq(timing.frameRange(3, 6), [3, 4, 5, 6]);
        deepEq(timing.frameRange(2, 2), [2]);
    });

    it("refuses a descending range", function () {
        throws(function () { timing.frameRange(5, 1); });
    });

    it("offsets in the direction it says it does", function () {
        var offset = timing.offsetToStart(1001, 1);
        eq(1001 + offset, 1);
    });
});

/* --- geometry ---------------------------------------------------------- */

describe("geom", function () {
    it("flips Y about the comp height", function () {
        deepEq(geom.compToCanonicalPoint([10, 20], 100), [10, 80]);
    });

    it("is its own inverse", function () {
        var there = geom.compToCanonicalPoint([12.5, 33.25], 1080);
        deepEq(geom.canonicalToCompPoint(there, 1080), [12.5, 33.25]);
    });

    it("flips a tangent without the height", function () {
        // Tangents are vertex-relative, so the origin never enters into it.
        deepEq(geom.compToCanonicalTangent([4, -7]), [4, 7]);
        deepEq(geom.canonicalToCompTangent([4, 7]), [4, -7]);
    });

    it("converts a whole point object", function () {
        var pt = { "c": [10, 20], "in": [-5, 5], "out": [5, -5] };
        deepEq(geom.aePointToCanonical(pt, 100),
               { "c": [10, 80], "in": [-5, -5], "out": [5, 5] });
    });

    it("carries a feather scalar through untouched", function () {
        // It is a signed distance along the path normal; there is no Y
        // component in it to flip.
        var pt = { "c": [0, 0], "in": [0, 0], "out": [0, 0], "feather": -3.5 };
        eq(geom.aePointToCanonical(pt, 100)["feather"], -3.5);
        eq(geom.canonicalPointToAe(pt, 100)["feather"], -3.5);
    });

    it("drops feather_offset going into After Effects", function () {
        // Nuke's tangential component has no AE representation (spec 11.1).
        var pt = { "c": [0, 0], "in": [0, 0], "out": [0, 0],
                   "feather": 1.0, "feather_offset": [1, 2] };
        eq(RB.util.hasOwn(geom.canonicalPointToAe(pt, 100), "feather_offset"),
           false);
    });
});

describe("geom affine", function () {
    // Probe section F, reproduced arithmetically: a comp-sized solid on a
    // 1920x1080 comp (so anchor [960, 540]) at position [700, 400], scale
    // [150, 220], rotation 30 degrees. The probe read layer [200, 300] back as
    // comp [-23.269, -627.261] and a [40, 0] tangent as [51.962, 30]. Those two
    // readings are the only oracle there is for this, so the fixture is the
    // host's own composition order rather than a convenient one.
    function host(p) {
        var scale = [1.5, 2.2];
        var anchor = [960, 540];
        var position = [700, 400];
        var r = 30 * Math.PI / 180;
        var x = (p[0] - anchor[0]) * scale[0];
        var y = (p[1] - anchor[1]) * scale[1];
        return [position[0] + x * Math.cos(r) - y * Math.sin(r),
                position[1] + x * Math.sin(r) + y * Math.cos(r)];
    }

    function derived() {
        var s = geom.AFFINE_SPAN;
        return geom.affineFromProbes(host([0, 0]), host([s, 0]), host([0, s]));
    }

    it("reproduces the vertex the probe measured", function () {
        var v = geom.applyAffinePoint(derived(), [200, 300]);
        near(v[0], -23.269, 3);
        near(v[1], -627.261, 3);
    });

    it("reproduces the tangent the probe measured", function () {
        // Rotated AND non-uniformly scaled, which is what makes this the case
        // that separates a real transform from a copied one.
        var t = geom.applyAffineTangent(derived(), [40, 0]);
        near(t[0], 51.962, 3);
        near(t[1], 30, 3);
    });

    it("agrees with the host at a point it never probed", function () {
        // Three probes fix an affine map completely; this is the claim the
        // whole optimisation rests on, so it is measured rather than argued.
        var m = derived();
        var pts = [[0, 0], [200, 300], [1919, 1079], [-500, 2000]];
        for (var i = 0; i < pts.length; i++) {
            var off = geom.affineDisagreement(m, pts[i], host(pts[i]));
            if (!(off < 1e-9)) {
                fail("point " + pts[i] + " disagreed by " + off + " px");
            }
        }
    });

    it("matches transform-then-subtract on tangents", function () {
        // prd.md section 9.1's rule, done with host calls, must give the same
        // answer as the linear part alone - otherwise the saving is a change.
        var m = derived();
        var vertex = [321, 654];
        var tangent = [-17.5, 42.25];
        var moved = host([vertex[0] + tangent[0], vertex[1] + tangent[1]]);
        var base = host(vertex);
        var byHost = [moved[0] - base[0], moved[1] - base[1]];
        var byAffine = geom.applyAffineTangent(m, tangent);
        near(byAffine[0], byHost[0], 9);
        near(byAffine[1], byHost[1], 9);
    });

    it("handles an identity transform", function () {
        var m = geom.affineFromProbes([0, 0], [geom.AFFINE_SPAN, 0],
                                      [0, geom.AFFINE_SPAN]);
        deepEq(geom.applyAffinePoint(m, [12, 34]), [12, 34]);
        deepEq(geom.applyAffineTangent(m, [12, 34]), [12, 34]);
    });
});

describe("geom.snapFeatherPoints", function () {
    // Probe run 3's real mask: four points on seven vertices, three
    // mid-segment, two on the same segment, one with a radius of exactly zero.
    var RUN3 = {
        segLocs: [3, 6, 1, 3],
        relLocs: [0.9029, 0.9715, 0.0975, 1.0],
        radii: [89.5565, 0, -46.6171, -1e-8],
        vertexCount: 7
    };

    function run3() {
        return geom.snapFeatherPoints(RUN3.segLocs, RUN3.relLocs, RUN3.radii,
                                      RUN3.vertexCount);
    }

    it("returns one scalar per vertex", function () {
        eq(run3().feather.length, 7);
    });

    it("lands run 3 where it should", function () {
        deepEq(run3().feather, [0, -46.6171, 0, 0, 89.5565, 0, 0]);
    });

    it("snaps a late point forward and an early one back", function () {
        eq(geom.snapFeatherPoints([3], [0.9029], [5], 7).feather[4], 5);
        eq(geom.snapFeatherPoints([3], [0.0975], [5], 7).feather[3], 5);
    });

    it("wraps the last segment to the first vertex", function () {
        // Segment 6 of a seven-vertex closed shape ends at vertex 0, not 7.
        eq(geom.snapFeatherPoints([6], [0.9715], [5], 7).feather[0], 5);
    });

    it("does not report a point already sitting on a vertex", function () {
        deepEq(geom.snapFeatherPoints([2], [0.0], [1], 7).snapped, []);
        deepEq(geom.snapFeatherPoints([2], [1.0], [1], 7).snapped, []);
        deepEq(run3().snapped, [0, 1, 2]);
    });

    it("keeps the larger magnitude on a collision", function () {
        var dropped = run3().dropped;
        eq(dropped.length, 1);
        eq(dropped[0].index, 3);
        eq(dropped[0].vertex, 4);
        eq(dropped[0].kept, 89.5565);
    });

    it("lets magnitude decide regardless of sign", function () {
        eq(geom.snapFeatherPoints([0, 0], [0, 0], [3, -9], 4).feather[0], -9);
    });

    it("leaves the first point holding the vertex on a tie", function () {
        // Otherwise the result would depend on the order the host read them in.
        var got = geom.snapFeatherPoints([0, 0], [0, 0], [4, -4], 4);
        eq(got.feather[0], 4);
        eq(got.dropped[0].index, 1);
    });

    it("treats a zero radius as an authored point", function () {
        // It pins the feather back to zero width and is load-bearing.
        var got = geom.snapFeatherPoints([0], [0], [0], 4);
        deepEq(got.dropped, []);
        deepEq(got.feather, [0, 0, 0, 0]);
    });

    it("leaves every vertex at zero when there are no points", function () {
        var got = geom.snapFeatherPoints([], [], [], 5);
        deepEq(got.feather, [0, 0, 0, 0, 0]);
    });
});

describe("geom.featherAnchors", function () {
    // spec/rbj-v2-draft.md section 6.4. The Python mirror is
    // TestFeatherAnchors, over the same vectors.

    it("keeps every anchor of the run 3 shape where it was", function () {
        var got = geom.featherAnchors([0, 0, 2, 3], [0.25, 0.75, 0.5, 0.0],
                                      [30, -15, 12, 0], 7);
        deepEq(got, [{ t: 0.25, feather: 30 }, { t: 0.75, feather: -15 },
                     { t: 2.5, feather: 12 }, { t: 3.0, feather: 0 }]);
    });

    it("keeps both anchors that share one segment", function () {
        var got = geom.featherAnchors([2, 2], [0.25, 0.75], [8, -3], 5);
        deepEq([got[0].t, got[1].t], [2.25, 2.75]);
    });

    it("reads the two spellings of a vertex as one anchor", function () {
        // AE renames a point written at (i, 0) to (i-1, 1).
        deepEq(geom.featherAnchors([4], [0.0], [5], 7),
               geom.featherAnchors([3], [1.0], [5], 7));
    });

    it("wraps the last segment's end to zero on a closed shape", function () {
        eq(geom.featherAnchors([6], [1.0], [5], 7)[0].t, 0);
    });

    it("does not wrap on an open shape", function () {
        eq(geom.featherAnchors([5], [1.0], [5], 7, false)[0].t, 6);
    });

    it("orders by t ascending whatever the read order", function () {
        var got = geom.featherAnchors([4, 0, 2], [0.5, 0.5, 0.5], [1, 2, 3], 6);
        deepEq([got[0].t, got[1].t, got[2].t], [0.5, 2.5, 4.5]);
    });

    it("gives one file whichever way the host grouped its arrays", function () {
        deepEq(geom.featherAnchors([0, 2, 4], [0.5, 0.5, 0.5], [1, 2, 3], 6),
               geom.featherAnchors([4, 2, 0], [0.5, 0.5, 0.5], [3, 2, 1], 6));
    });

    it("orders two anchors at one t deterministically", function () {
        deepEq(geom.featherAnchors([1, 1], [0, 0], [12, 0], 5),
               geom.featherAnchors([1, 1], [0, 0], [0, 12], 5));
    });

    it("carries a zero radius as an authored anchor", function () {
        deepEq(geom.featherAnchors([3], [0.0], [0], 7),
               [{ t: 3, feather: 0 }]);
    });

    it("reads no feather points as an empty list", function () {
        eq(geom.featherAnchors([], [], [], 7).length, 0);
    });

    it("puts every t inside the range the validator enforces", function () {
        var rels = [0.0, 0.25, 0.5, 0.75, 1.0];
        for (var seg = 0; seg < 7; seg++) {
            for (var r = 0; r < rels.length; r++) {
                var t = geom.featherAnchors([seg], [rels[r]], [1], 7)[0].t;
                eq(t >= 0 && t < 7, true, "seg " + seg + " rel " + rels[r]
                   + " gave t " + t);
            }
        }
    });
});

describe("geom.featherPointsFromAnchors", function () {
    // spec/rbj-v2-draft.md section 6, back into After Effects. The Python
    // mirror is TestFeatherPointsFromAnchors.

    it("splits t into the segment and the fraction", function () {
        var made = geom.featherPointsFromAnchors([{ t: 2.5, feather: 12 }]);
        deepEq([made.segLocs, made.relLocs, made.radii, made.types],
               [[2], [0.5], [12], [0]]);
    });

    it("pins an integral t to the start of its own segment", function () {
        var made = geom.featherPointsFromAnchors([{ t: 3.0, feather: 1 }]);
        deepEq([made.segLocs, made.relLocs], [[3], [0]]);
    });

    it("takes the type from the sign", function () {
        var made = geom.featherPointsFromAnchors(
            [{ t: 0, feather: 5 }, { t: 1, feather: -5 },
             { t: 2, feather: 0 }]);
        deepEq(made.types, [0, 1, 0]);
    });

    it("keeps both anchors that share one t", function () {
        var made = geom.featherPointsFromAnchors(
            [{ t: 3, feather: 0 }, { t: 3, feather: 12 }]);
        deepEq([made.segLocs, made.radii], [[3, 3], [0, 12]]);
    });

    it("round trips with featherAnchors", function () {
        var anchors = [{ t: 0.25, feather: 30 }, { t: 0.75, feather: -15 },
                       { t: 2.5, feather: 12 }, { t: 3.0, feather: 0 }];
        var made = geom.featherPointsFromAnchors(anchors);
        deepEq(geom.featherAnchors(made.segLocs, made.relLocs, made.radii, 7),
               anchors);
    });

    it("survives the host's rename of a vertex anchor", function () {
        // AE hands (i, 0) back as (i-1, 1). Reading that must give the t that
        // was written, or a re-export moves every vertex anchor.
        var anchors = [{ t: 4.0, feather: 5 }];
        var made = geom.featherPointsFromAnchors(anchors);
        deepEq(geom.featherAnchors([made.segLocs[0] - 1], [1.0],
                                   made.radii, 7), anchors);
    });

    it("gives four empty arrays for no anchors", function () {
        var made = geom.featherPointsFromAnchors([]);
        deepEq([made.segLocs, made.relLocs, made.radii, made.types],
               [[], [], [], []]);
    });
});

describe("geom.featherPointsFromVertices", function () {
    it("pins each vertex to the start of its own segment", function () {
        var got = geom.featherPointsFromVertices([1.0, -2.0]);
        deepEq(got.segLocs, [0, 1]);
        deepEq(got.relLocs, [0, 0]);
        deepEq(got.radii, [1.0, -2.0]);
    });

    it("agrees the type with the sign", function () {
        // A point's direction cannot be changed after it is created, so the
        // host has to be given the right one up front.
        deepEq(geom.featherPointsFromVertices([5, -5, 0]).types, [0, 1, 0]);
    });

    it("emits zeros rather than skipping them", function () {
        deepEq(geom.featherPointsFromVertices([0, 3, 0]).radii, [0, 3, 0]);
    });

    it("round trips through the snapper", function () {
        var want = [1.5, 0.0, -3.25, 7.0];
        var made = geom.featherPointsFromVertices(want);
        var back = geom.snapFeatherPoints(made.segLocs, made.relLocs,
                                          made.radii, want.length);
        deepEq(back.feather, want);
        deepEq(back.snapped, []);
        deepEq(back.dropped, []);
    });
});

/* --- interpolation ------------------------------------------------------ */

describe("interp", function () {
    it("maps the three types one to one", function () {
        eq(interp.sideFromAe(interp.AE_HOLD), "hold");
        eq(interp.sideFromAe(interp.AE_LINEAR), "linear");
        eq(interp.sideFromAe(interp.AE_BEZIER), "ease");
    });

    it("keeps LINEAR as the lowest constant", function () {
        // Read off the host in probe runs 2 and 4. The menu shows them in the
        // other order, so this is the easy one to invert from memory.
        eq(interp.AE_LINEAR, 6612);
        eq(interp.AE_BEZIER, 6613);
        eq(interp.AE_HOLD, 6614);
    });

    it("degrades an unknown type to ease rather than failing", function () {
        eq(interp.sideFromAe(9999), "ease");
    });

    it("round trips every side", function () {
        var sides = ["hold", "linear", "ease"];
        for (var i = 0; i < sides.length; i++) {
            eq(interp.sideFromAe(interp.sideToAe(sides[i])), sides[i]);
        }
    });

    it("scales influence and leaves speed alone", function () {
        // Run 6 read the first real authored ease off a mask: 91.176 in.
        deepEq(interp.easeFromAe(91.176, 0), [0.91176, 0]);
        eq(interp.easeFromAe(50, 1.5)[1], 1.5);
    });

    it("round trips the host default influence", function () {
        var pair = interp.easeFromAe(interp.AE_DEFAULT_INFLUENCE, 0);
        near(interp.easeToAe(pair)[0], interp.AE_DEFAULT_INFLUENCE, 9);
    });

    it("clamps an influence the host would reject", function () {
        // Spec 10.3 allows 0.0; After Effects does not accept it.
        eq(interp.easeToAe([0.0, 0])[0], 0.1);
        eq(interp.easeToAe([2.0, 0])[0], 100.0);
    });
});

/* --- drift -------------------------------------------------------------- */

function parabola(frame) { return Math.pow(frame - 1.0, 2) / 10.0; }

function FakeHost(truth) {
    /* A destination that interpolates linearly between the keys it holds.
     * Line for line the Python's fixture, so both implementations are driven
     * by identical arithmetic. */
    this.truth = truth;
    this.applied = null;
    this.applications = 0;
}

FakeHost.prototype.applyKeys = function (keyFrames) {
    this.applied = keyFrames.slice(0);
    this.applications += 1;
};

FakeHost.prototype.evaluate = function (frame) {
    var keys = this.applied;
    if (frame <= keys[0]) { return this.truth(keys[0]); }
    if (frame >= keys[keys.length - 1]) {
        return this.truth(keys[keys.length - 1]);
    }
    for (var i = 0; i + 1 < keys.length; i++) {
        var a = keys[i];
        var b = keys[i + 1];
        if (a <= frame && frame <= b) {
            var t = (frame - a) / (b - a);
            return this.truth(a) + t * (this.truth(b) - this.truth(a));
        }
    }
    throw new Error("frame " + frame + " outside the key span");
};

FakeHost.prototype.measure = function (frame) {
    return Math.abs(this.evaluate(frame) - this.truth(frame));
};

function runDrift(frames, keys, tolerance, maxPasses) {
    var host = new FakeHost(parabola);
    var result = drift.correct(frames, keys,
                               function (k) { host.applyKeys(k); },
                               function (f) { return host.measure(f); },
                               tolerance, maxPasses);
    result.host = host;
    return result;
}

describe("drift.gaps", function () {
    it("returns maximal runs in order", function () {
        deepEq(drift.gaps([1, 2, 3, 4, 5, 6], [1, 4, 6]), [[2, 3], [5]]);
    });

    it("treats no keys as one run", function () {
        deepEq(drift.gaps([1, 2, 3], []), [[1, 2, 3]]);
    });

    it("returns nothing when every frame is a key", function () {
        deepEq(drift.gaps([1, 2, 3], [1, 2, 3]), []);
    });
});

describe("drift.correct", function () {
    it("adds nothing when the endpoints already fit", function () {
        var r = runDrift([1, 2, 3], [1, 3], 100.0);
        deepEq(r.keys, [1, 3]);
    });

    it("keys every frame at tolerance zero without measuring", function () {
        var frames = timing.frameRange(1, 20);
        var measured = 0;
        var r = drift.correct(frames, [1, 20], function () {},
                              function () { measured += 1; return 0; }, 0.0);
        deepEq(r.keys, frames);
        eq(measured, 0, "dense mode must not measure");
        eq(r.at, null);
    });

    it("brings a parabola inside tolerance", function () {
        var frames = timing.frameRange(1, 21);
        var r = runDrift(frames, [1, 21], 0.5);
        if (!(r.worst <= 0.5)) { fail("worst " + r.worst + " exceeds 0.5"); }
        if (!(r.keys.length > 2)) { fail("no corrective keys were added"); }
        if (!(r.keys.length < frames.length)) { fail("it keyed everything"); }
    });

    it("lands fewer keys as tolerance loosens", function () {
        var frames = timing.frameRange(1, 41);
        var tight = runDrift(frames, [1, 41], 0.1).keys.length;
        var loose = runDrift(frames, [1, 41], 2.0).keys.length;
        if (!(tight > loose)) {
            fail("tight " + tight + " should exceed loose " + loose);
        }
    });

    it("keeps every authored key", function () {
        var frames = timing.frameRange(1, 21);
        var authored = [1, 7, 21];
        var r = runDrift(frames, authored, 0.2);
        for (var i = 0; i < authored.length; i++) {
            if (RB.util.indexOf(r.keys, authored[i]) === -1) {
                fail("authored key " + authored[i] + " was dropped");
            }
        }
    });

    it("leaves the host holding exactly the keys it returns", function () {
        // A caller must never have to guess whether the host is a pass behind.
        var frames = timing.frameRange(1, 21);
        var r = runDrift(frames, [1, 21], 0.3);
        deepEq(r.host.applied, r.keys);
    });

    it("names the frame carrying the worst deviation", function () {
        var frames = timing.frameRange(1, 21);
        var r = runDrift(frames, [1, 21], 0.5);
        near(r.host.measure(r.at), r.worst, 9);
    });

    it("reports honestly when it runs out of passes", function () {
        var frames = timing.frameRange(1, 41);
        var r = runDrift(frames, [1, 41], 0.001, 2);
        if (!(r.worst > 0.001)) {
            fail("two passes should not have converged; worst " + r.worst);
        }
        // Still applied and re-measured, so `worst` describes what the host
        // actually holds rather than the pass before.
        deepEq(r.host.applied, r.keys);
    });

    it("refuses a run with no frames", function () {
        throws(function () {
            drift.correct([], [1], function () {}, function () { return 0; }, 0.5);
        });
    });

    it("refuses keys that all sit outside the range", function () {
        throws(function () {
            drift.correct([1, 2, 3], [90, 91], function () {},
                          function () { return 0; }, 0.5);
        });
    });

    it("ignores keys outside the range when some are inside", function () {
        var r = runDrift([1, 2, 3], [1, 3, 99], 100.0);
        deepEq(r.keys, [1, 3]);
    });
});

function HoldingHost(truth, held) {
    /* A destination whose outgoing side at `held` freezes the rest of its gap,
     * so the deviation climbs steadily and the worst frame of the gap is always
     * its LAST. Line for line the Python's fixture. */
    this.truth = truth;
    this.held = held;
    this.applied = null;
}

HoldingHost.prototype.applyKeys = function (keyFrames) {
    this.applied = keyFrames.slice(0);
};

HoldingHost.prototype.evaluate = function (frame) {
    var keys = this.applied;
    if (frame <= keys[0]) { return this.truth(keys[0]); }
    if (frame >= keys[keys.length - 1]) {
        return this.truth(keys[keys.length - 1]);
    }
    for (var i = 0; i + 1 < keys.length; i++) {
        var a = keys[i];
        var b = keys[i + 1];
        if (a <= frame && frame <= b) {
            if (a === this.held) { return this.truth(a); }
            return this.truth(a) +
                ((frame - a) / (b - a)) * (this.truth(b) - this.truth(a));
        }
    }
    throw new Error("frame " + frame + " outside the key span");
};

HoldingHost.prototype.measure = function (frame) {
    return Math.abs(this.evaluate(frame) - this.truth(frame));
};

describe("drift.linearFit", function () {
    /* The export-side pass: what a LINEAR sparse layer costs. The vectors are
     * the ones `TestLinearFit` uses in test_core.py, because two
     * implementations of one rule are worth having only if the same cases run
     * through both. */

    function bow(peak, count) {
        if (count === undefined) { count = 25; }
        var frames = [], dense = {};
        var middle = (count - 1) / 2.0;
        for (var f = 0; f < count; f++) {
            frames[f] = f;
            dense[String(f)] = [f * 10.0,
                                peak * (1.0 - Math.pow((f - middle) / middle, 2))];
        }
        return { frames: frames, dense: dense };
    }

    it("leaves a straight line at two keys", function () {
        var frames = [], dense = {};
        for (var f = 0; f < 25; f++) {
            frames[f] = f;
            dense[String(f)] = [f * 10.0, 0.0];
        }
        var got = drift.linearFit(frames, dense, [0, 24], 0.5);
        deepEq(got.keys, [0, 24]);
        eq(got.worst, 0.0);
        eq(got.at, null);
    });

    it("leaves a bow inside tolerance alone too", function () {
        var b = bow(0.4);
        var got = drift.linearFit(b.frames, b.dense, [0, 24], 0.5);
        deepEq(got.keys, [0, 24]);
        near(got.worst, 0.4, 6);
    });

    it("scales the key count with the bow, not with the range", function () {
        var peaks = [2.0, 10.0, 144.0];
        var counts = [];
        for (var i = 0; i < peaks.length; i++) {
            var b = bow(peaks[i]);
            counts[i] = drift.linearFit(b.frames, b.dense, [0, 24], 0.5)
                             .keys.length;
        }
        deepEq(counts, [3, 9, 25]);
    });

    it("measures every component, not only the first", function () {
        // Tangents and feather ride in the same flat vector as the vertex and
        // are held to the same tolerance.
        var frames = [0, 1, 2, 3, 4], dense = {};
        for (var f = 0; f < 5; f++) {
            dense[String(f)] = [0, 0, 0, 0, 0, f === 2 ? 10.0 : 0.0];
        }
        var got = drift.linearFit(frames, dense, [0, 4], 0.5);
        eq(RB.util.indexOf(got.keys, 2) > -1, true);
    });

    it("charges nothing for a held segment, and everything without the hold",
       function () {
        // Without `holds` the fit prices a held segment as a straight line to
        // the next key and buys keys to flatten what is already flat - which
        // is how a conform meant to preserve holds would destroy them.
        var frames = [0, 1, 2, 3, 4];
        var dense = { "0": [0.0], "1": [0.0], "2": [0.0], "3": [0.0],
                      "4": [100.0] };
        // One key, not three: bisection reaches [0, 2, 3, 4] and the sweep
        // gives 2 back, because the line from 0 to 3 already lands on 1 and 2.
        deepEq(drift.linearFit(frames, dense, [0, 4], 0.5).keys, [0, 3, 4]);
        deepEq(drift.linearFit(frames, dense, [0, 4], 0.5, [0]).keys, [0, 4]);
    });

    it("still measures a hold the bake contradicts", function () {
        var frames = [0, 1, 2, 3, 4], dense = {};
        for (var f = 0; f < 5; f++) { dense[String(f)] = [f * 25.0]; }
        var got = drift.linearFit(frames, dense, [0, 4], 0.5, [0]);
        eq(got.keys.length > 2, true);
        eq(got.worst <= 0.5, true);
    });

    it("keys every frame at tolerance zero", function () {
        var b = bow(144.0);
        var got = drift.linearFit(b.frames, b.dense, [0, 24], 0.0);
        deepEq(got.keys, b.frames);
        eq(got.at, null);
    });
});

describe("drift.correct over a monotone gap", function () {
    /* The gap whose worst frame is its own end. A key there shortens the run
     * instead of splitting it, so without the midpoint the pass walks backwards
     * one frame per pass and runs out of them - which is what the After Effects
     * import reported in the host against held_over_moving_layer.rbj. */

    function runHeld(tolerance) {
        var host = new HoldingHost(function (f) { return 20.0 * f; }, 12);
        var r = drift.correct(timing.frameRange(0, 24), [0, 12, 24],
                              function (k) { host.applyKeys(k); },
                              function (f) { return host.measure(f); },
                              tolerance);
        r.host = host;
        return r;
    }

    it("converges instead of running out of passes", function () {
        var r = runHeld(0.5);
        if (!(r.worst <= 0.5)) { fail("worst " + r.worst + " exceeds 0.5"); }
    });

    it("splits the gap rather than walking back from its end", function () {
        var r = runHeld(0.5);
        var corrective = [];
        for (var i = 0; i < r.keys.length; i++) {
            var f = r.keys[i];
            if (f !== 0 && f !== 12 && f !== 24) { corrective.push(f); }
        }
        if (!(corrective.length < 8)) {
            fail("one key per pass is the degenerate walk, not a split");
        }
        // The midpoint that splits the gap is survey()'s doing and is asserted
        // against survey() directly. It is deliberately not asserted here:
        // splitting the run is how the pass converges, but once it has, sweep()
        // hands back whatever the split turned out not to need, and on this gap
        // a single key does the whole job.
        if (!(corrective.length <= 3)) {
            fail("the split converges, then the sweep gives back: "
                 + corrective.join(","));
        }
    });

    it("gives back the keys the split turned out not to need", function () {
        // The split is what converges; the sweep is what keeps the result from
        // converging above the floor. Before it, this gap cost six corrective
        // keys - measured against an exact minimum in
        // test/probe/probe_key_minimality.py.
        var r = runHeld(0.5);
        var corrective = [];
        for (var i = 0; i < r.keys.length; i++) {
            var f = r.keys[i];
            if (f !== 0 && f !== 12 && f !== 24) { corrective.push(f); }
        }
        deepEq(corrective, [13]);
    });

    it("never gives back a key the caller asked for", function () {
        // Every one of these holds the shape without the others, so tolerance
        // alone would drop four of the five. They are the artist's.
        var host = new HoldingHost(function (f) { return 20.0 * f; }, 12);
        var r = drift.correct(timing.frameRange(0, 24), [0, 6, 12, 18, 24],
                              function (k) { host.applyKeys(k); },
                              function (f) { return host.measure(f); }, 0.5);
        var wanted = [0, 6, 12, 18, 24];
        for (var i = 0; i < wanted.length; i++) {
            if (r.keys.indexOf(wanted[i]) < 0) {
                fail("authored key " + wanted[i] + " was swept: "
                     + r.keys.join(","));
            }
        }
    });

    it("gives back a seeded end the geometry does not need", function () {
        // The importer's case: the file names the artist's own frames, and
        // seeds it does not name - an exporter's pinned endpoints - come home
        // only if the geometry needs them. A constant needs none of them.
        var host = new HoldingHost(function (f) { return 7.0; }, null);
        var r = drift.correct(timing.frameRange(0, 10), [0, 5, 10],
                              function (k) { host.applyKeys(k); },
                              function (f) { return host.measure(f); },
                              0.5, undefined, [5]);
        deepEq(r.keys, [5]);
        eq(r.worst, 0.0);
        deepEq(host.applied, r.keys);
    });

    it("keeps a seeded end the geometry still needs", function () {
        // Dropping an end truncates the keyed span and the host holds the
        // nearest key beyond it - on a moving line that hold is exactly what
        // the window past the surviving neighbour measures.
        var host = new HoldingHost(function (f) { return 10.0 * f; }, null);
        var r = drift.correct(timing.frameRange(0, 10), [0, 5, 10],
                              function (k) { host.applyKeys(k); },
                              function (f) { return host.measure(f); },
                              0.5, undefined, [5]);
        deepEq(r.keys, [0, 5, 10]);
    });

    it("leaves every unkeyed frame inside tolerance", function () {
        var r = runHeld(0.5);
        var frames = timing.frameRange(0, 24);
        for (var i = 0; i < frames.length; i++) {
            if (r.keys.indexOf(frames[i]) < 0 &&
                    r.host.measure(frames[i]) > 0.5) {
                fail("frame " + frames[i] + " drifts " +
                     r.host.measure(frames[i]));
            }
        }
    });
});

/* --- the schema --------------------------------------------------------- */

var GOLDEN = path.join(ROOT, "test", "golden");

function goldenFiles() {
    var out = [];
    var names = fs.readdirSync(GOLDEN);
    for (var i = 0; i < names.length; i++) {
        if (/\.rbj$/.test(names[i])) { out.push(names[i]); }
    }
    out.sort();
    return out;
}

describe("rbj", function () {
    it("finds golden files to read", function () {
        if (!goldenFiles().length) { fail("no .rbj files under test/golden"); }
    });

    it("accepts every golden file the Python writer produced", function () {
        // The real cross-check between the two implementations: these files
        // were written by `core/rbj.py` and are read here by the ES3 port.
        var files = goldenFiles();
        for (var i = 0; i < files.length; i++) {
            var doc = rbj.parse(fs.readFileSync(path.join(GOLDEN, files[i]),
                                                "utf8"));
            eq(doc.format, "rotobridge", files[i]);
        }
    });

    it("round trips a golden file through its own writer", function () {
        var files = goldenFiles();
        for (var i = 0; i < files.length; i++) {
            var text = fs.readFileSync(path.join(GOLDEN, files[i]), "utf8");
            var once = rbj.parse(text);
            var twice = rbj.parse(rbj.stringify(once));
            deepEq(twice, once, files[i]);
        }
    });

    it("keeps arrays of numbers on one line", function () {
        // The format is meant to be diffable (spec 2.1); one element per line
        // turns a coordinate pair into three lines.
        var text = rbj.stringify(minimal());
        if (text.indexOf("[1, 2]") === -1) {
            fail("expected an inline number array:\n" + text);
        }
    });

    it("refuses to write a file it would refuse to read", function () {
        var doc = minimal();
        doc.shapes[0].closed = false;
        var e = throws(function () { rbj.stringify(doc); });
        eq(e.name, "RbjError");
    });

    it("reports every problem at once, not just the first", function () {
        var e = throws(function () { rbj.parse("{}"); });
        if (!(e.errors.length > 3)) {
            fail("expected several errors, got " + e.errors.length);
        }
    });

    it("rejects a version newer than it implements", function () {
        var doc = minimal();
        doc.version = 99;
        var e = throws(function () { rbj.stringify(doc); });
        eq(e.errors[0].indexOf("newer than this reader") > -1, true);
    });

    it("folds a held span into references and pays version 3", function () {
        // The Python mirror is TestFrameRefs; spec/rbj-v3-draft.md section 3.
        var doc = held();
        var folded = rbj.foldFrames(doc);
        deepEq(folded.shapes[0].frames["2"], { same_as: 1 });
        deepEq(folded.shapes[0].frames["6"], { same_as: 1 });
        eq(folded.version, 3);
        eq(rbj.validate(folded).length, 0,
           rbj.validate(folded).join(" | "));
        eq(doc.version, 1, "fold must not mutate its input");
    });

    it("does not fold a moving shape, which stays version 1", function () {
        // minimal()'s two frames are identical, so give it actual motion.
        var doc = minimal();
        doc.shapes[0].frames["2"].points[0].c = [5, 5];
        var folded = rbj.foldFrames(doc);
        deepEq(folded, doc);
        eq(folded.version, 1);
    });

    it("expands references on parse, with copies", function () {
        var doc = held();
        var back = rbj.parse(rbj.stringify(rbj.foldFrames(doc)));
        deepEq(back.shapes, doc.shapes);
        back.shapes[0].frames["2"].opacity = 0.25;
        eq(back.shapes[0].frames["1"].opacity, 1.0,
           "editing an expanded frame edited its source");
    });

    it("rejects a reference in a file that says version 1", function () {
        var folded = rbj.foldFrames(held());
        folded.version = 1;
        var errs = rbj.validate(folded);
        eq(errs.join(" | ").indexOf("same_as needs version 3") > -1, true,
           errs.join(" | "));
    });

    it("rejects a forward or chained reference", function () {
        var folded = rbj.foldFrames(held());
        folded.shapes[0].frames["2"] = { same_as: 3 };
        var errs = rbj.validate(folded);
        eq(errs.join(" | ").indexOf("does not point at an earlier frame") > -1,
           true, errs.join(" | "));
        folded = rbj.foldFrames(held());
        folded.shapes[0].frames["3"] = { same_as: 2 };
        errs = rbj.validate(folded);
        eq(errs.join(" | ").indexOf("itself a reference") > -1, true,
           errs.join(" | "));
    });

    it("caps interp errors with the rest of the key errors", function () {
        // The Python mirror is test_interp_errors_are_capped_with_the_rest.
        var doc = minimal();
        var keys = [];
        for (var i = 0; i < 50; i++) {
            keys[keys.length] = { frame: 1,
                                  interp: { "in": "bezier", "out": "bezier" } };
        }
        doc.shapes[0].keys = keys;
        var errs = rbj.validate(doc);
        eq(errs.length < 12, true, "got " + errs.length + " errors");
        eq(errs.join(" | ").indexOf("suppressed") > -1, true);
    });

    it("accepts authored_frames, empty included, and checks what it names",
       function () {
        // The Python mirrors are the three authored_frames tests in
        // TestValidate; spec/rbj-v3-draft.md section 5.2.
        var doc = minimal();
        doc.shapes[0].keys = [
            { frame: 1, interp: { "in": "linear", "out": "linear" } },
            { frame: 2, interp: { "in": "linear", "out": "linear" } }
        ];
        doc.shapes[0].authored_frames = [1];
        eq(rbj.validate(doc).length, 0, rbj.validate(doc).join(" | "));
        doc.shapes[0].authored_frames = [];
        eq(rbj.validate(doc).length, 0, rbj.validate(doc).join(" | "));
        doc.shapes[0].authored_frames = [3];
        var errs = rbj.validate(doc);
        eq(errs.join(" | ").indexOf("no such frame in the dense layer") > -1,
           true, errs.join(" | "));
        doc.shapes[0].authored_frames = [2, 1];
        errs = rbj.validate(doc);
        eq(errs.join(" | ").indexOf("not sorted ascending") > -1, true,
           errs.join(" | "));
        doc.shapes[0].keys = [doc.shapes[0].keys[1]];
        doc.shapes[0].authored_frames = [1];
        errs = rbj.validate(doc);
        eq(errs.join(" | ").indexOf("not present in keys") > -1, true,
           errs.join(" | "));
    });

    it("validates authored_attributes with the keys machinery", function () {
        // The Python mirrors are the three authored_attributes tests in
        // TestValidate; spec/rbj-v3-draft.md section 5.3.
        var doc = minimal();
        doc.shapes[0].authored_attributes = {
            opacity: [{ frame: 1, interp: { "in": "linear", "out": "ease" },
                        ease: { out: [0.5, 0.0] } }],
            feather_uniform: [{ frame: 2,
                                interp: { "in": "hold", "out": "linear" } }]
        };
        eq(rbj.validate(doc).length, 0, rbj.validate(doc).join(" | "));
        doc.shapes[0].authored_attributes = { expansion: [] };
        var errs = rbj.validate(doc);
        eq(errs.join(" | ").indexOf("unexpected attribute") > -1, true,
           errs.join(" | "));
        doc.shapes[0].authored_attributes = { opacity: [] };
        errs = rbj.validate(doc);
        eq(errs.join(" | ").indexOf("omit the entry instead") > -1, true,
           errs.join(" | "));
        doc.shapes[0].authored_attributes = {
            opacity: [{ frame: 3,
                        interp: { "in": "linear", "out": "linear" } }]
        };
        errs = rbj.validate(doc);
        eq(errs.join(" | ").indexOf("no such frame in the dense layer") > -1,
           true, errs.join(" | "));
    });

    it("accepts an open spline at version 2", function () {
        // spec/rbj-v2-draft.md section 3. The Python mirror of this is
        // TestOpenSplines.test_an_open_shape_validates_at_version_2.
        var doc = minimal();
        doc.version = 2;
        doc.shapes[0].closed = false;
        eq(rbj.validate(doc).length, 0, rbj.validate(doc).join(" | "));
    });

    it("rejects an open spline in a file that says version 1", function () {
        var doc = minimal();
        doc.shapes[0].closed = false;
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("needs version 2") > -1, true, joined(e));
    });

    it("rejects a closed that is not a boolean", function () {
        var doc = minimal();
        doc.shapes[0].closed = "yes";
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("expected a boolean") > -1, true, joined(e));
    });

    it("rejects a tool_version that is present and empty", function () {
        // Absent is legal - every file written before the member existed
        // omits it. Present and empty is not the same thing: it says the
        // writer tried to name itself and failed.
        var doc = minimal();
        doc.source.tool_version = "";
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("tool_version") > -1, true, joined(e));
    });

    it("accepts a file with no tool_version", function () {
        var doc = minimal();
        delete doc.source.tool_version;
        eq(rbj.validate(doc).length, 0, rbj.validate(doc).join(" | "));
    });

    it("versionFor stamps the lowest version that expresses the file",
       function () {
        eq(rbj.versionFor(minimal().shapes), 1);
        var open = minimal().shapes;
        open[0].closed = false;
        eq(rbj.versionFor(open), 2);
        eq(rbj.versionFor(minimal().shapes.concat(open)), 2);
    });

    it("rejects a dense layer that does not cover the range", function () {
        var doc = minimal();
        delete doc.shapes[0].frames["2"];
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("missing 1 frame(s)") > -1, true, joined(e));
    });

    it("rejects a key pointing at a frame that is not there", function () {
        var doc = minimal();
        doc.shapes[0].keys = [
            { frame: 1, interp: { "in": "linear", "out": "linear" } },
            { frame: 9, interp: { "in": "linear", "out": "linear" } }
        ];
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("no such frame") > -1, true, joined(e));
    });

    it("rejects keys out of order", function () {
        var doc = minimal();
        doc.shapes[0].keys = [
            { frame: 2, interp: { "in": "linear", "out": "linear" } },
            { frame: 1, interp: { "in": "linear", "out": "linear" } }
        ];
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("not sorted ascending") > -1, true, joined(e));
    });

    it("rejects an ease entry on a side that is not ease", function () {
        var doc = minimal();
        doc.shapes[0].keys = [{
            frame: 1,
            interp: { "in": "linear", "out": "linear" },
            ease: { "out": [0.5, 0] }
        }];
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("not 'ease'") > -1, true, joined(e));
    });

    it("rejects a vertex count that changes across frames", function () {
        var doc = minimal();
        doc.shapes[0].frames["2"].points.push(point(9, 9));
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("vertex count changes") > -1, true, joined(e));
    });

    it("rejects feather under feather_model none", function () {
        var doc = minimal();
        doc.shapes[0].frames["1"].points[0].feather = 0.0;
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("feather_model") > -1, true, joined(e));
    });

    it("accepts anchored feather at version 2", function () {
        // spec/rbj-v2-draft.md section 6. The Python mirror of this whole
        // block is TestAnchoredFeather.
        var doc = anchored();
        eq(rbj.validate(doc).length, 0, rbj.validate(doc).join(" | "));
    });

    it("accepts two anchors on one segment", function () {
        // The case that decided the design: no per-point field can hold two
        // values for one point, so this is not a field that could be widened.
        var doc = anchored([{ t: 1.25, feather: 30 }, { t: 1.75, feather: -15 }]);
        eq(rbj.validate(doc).length, 0, rbj.validate(doc).join(" | "));
    });

    it("rejects anchored feather in a file that says version 1", function () {
        var doc = anchored();
        doc.version = 1;
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("needs version 2") > -1, true, joined(e));
    });

    it("versionFor stamps 2 on an anchored shape", function () {
        eq(rbj.versionFor(anchored().shapes), 2);
    });

    it("versionFor leaves a per_point file at 1", function () {
        // Section 6.7: only the files that were being damaged pay the
        // compatibility cost.
        var doc = minimal();
        doc.shapes[0].feather_model = "per_point";
        eachPoint(doc, function (pt) { pt.feather = 4; });
        eq(rbj.versionFor(doc.shapes), 1);
        eq(rbj.validate(doc).length, 0, rbj.validate(doc).join(" | "));
    });

    it("rejects a point carrying feather under anchored", function () {
        var doc = anchored();
        doc.shapes[0].frames["1"].points[0].feather = 3;
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("two places to look") > -1, true, joined(e));
    });

    it("rejects a frame with no feather_points under anchored", function () {
        var doc = anchored();
        delete doc.shapes[0].frames["2"].feather_points;
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("missing feather_points") > -1, true, joined(e));
    });

    it("rejects feather_points on a shape that is not anchored", function () {
        var doc = minimal();
        doc.shapes[0].frames["1"].feather_points = [];
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("not 'anchored'") > -1, true, joined(e));
    });

    it("rejects an anchor count that changes across frames", function () {
        var doc = anchored();
        doc.shapes[0].frames["2"].feather_points.pop();
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("feather_points count changes") > -1, true,
           joined(e));
        eq(joined(e).indexOf("2 at frame 1") > -1, true, joined(e));
        eq(joined(e).indexOf("1 at frame 2") > -1, true, joined(e));
    });

    it("accepts zero anchors as a count", function () {
        var doc = anchored([]);
        eq(rbj.validate(doc).length, 0, rbj.validate(doc).join(" | "));
    });

    it("rejects t at the vertex count on a closed shape", function () {
        // Section 6.4: t = n names the same anchor as t = 0 and must be
        // written as 0, so the upper bound is exclusive.
        var doc = anchored([{ t: 3, feather: 1 }]);
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("expected 0 to 3") > -1, true, joined(e));
    });

    it("accepts t just below the vertex count on a closed shape", function () {
        var doc = anchored([{ t: 2.999, feather: 1 }]);
        eq(rbj.validate(doc).length, 0, rbj.validate(doc).join(" | "));
    });

    it("accepts t at the last vertex on an open shape", function () {
        // One segment fewer, and the path genuinely ends there.
        var doc = anchored([{ t: 2, feather: 1 }]);
        doc.shapes[0].closed = false;
        eq(rbj.validate(doc).length, 0, rbj.validate(doc).join(" | "));
    });

    it("rejects t past the last vertex on an open shape", function () {
        var doc = anchored([{ t: 2.5, feather: 1 }]);
        doc.shapes[0].closed = false;
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("expected 0 to 2") > -1, true, joined(e));
    });

    it("rejects a negative t", function () {
        var doc = anchored([{ t: -0.5, feather: 1 }]);
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("expected 0 to 3") > -1, true, joined(e));
    });

    it("rejects anchors out of t order", function () {
        var doc = anchored([{ t: 2.5, feather: 1 }, { t: 0.5, feather: 2 }]);
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("ordered by t ascending") > -1, true, joined(e));
    });

    it("accepts two anchors sharing one t", function () {
        // Ascending, not strictly ascending. Two anchors at one vertex is
        // precisely what section 6.1 says v1 cannot express.
        var doc = anchored([{ t: 1, feather: 12 }, { t: 1, feather: 0 }]);
        eq(rbj.validate(doc).length, 0, rbj.validate(doc).join(" | "));
    });

    it("rejects an anchor with no t", function () {
        var doc = anchored([{ feather: 1 }]);
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("missing t") > -1, true, joined(e));
    });

    it("rejects an anchor with no feather", function () {
        var doc = anchored([{ t: 1 }]);
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("missing feather") > -1, true, joined(e));
    });

    it("accepts a feather_offset on an anchor", function () {
        var doc = anchored([{ t: 1.5, feather: 4, feather_offset: [1, -2] }]);
        eq(rbj.validate(doc).length, 0, rbj.validate(doc).join(" | "));
    });

    it("rejects a malformed feather_offset on an anchor", function () {
        var doc = anchored([{ t: 1.5, feather: 4, feather_offset: [1] }]);
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("two-element array") > -1, true, joined(e));
    });

    it("rejects a non-finite t", function () {
        var doc = anchored([{ t: Infinity, feather: 1 }]);
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("not finite") > -1, true, joined(e));
    });

    it("rejects feather_points that is not an array", function () {
        var doc = anchored();
        doc.shapes[0].frames["1"].feather_points = { t: 1 };
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("expected an array") > -1, true, joined(e));
    });

    it("rejects a non-finite number rather than writing NaN", function () {
        // Neither NaN nor Infinity is legal JSON (spec 2.2), and no parser is
        // required to accept them.
        var doc = minimal();
        doc.shapes[0].frames["1"].points[0].c = [0, Infinity];
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("not finite") > -1, true, joined(e));
    });

    it("rejects a malformed frame key", function () {
        var doc = minimal();
        doc.shapes[0].frames["01"] = doc.shapes[0].frames["1"];
        var e = throws(function () { rbj.stringify(doc); });
        eq(joined(e).indexOf("plain decimal integer") > -1, true, joined(e));
    });

    it("escapes a shape name that would break the file", function () {
        var doc = minimal();
        doc.shapes[0].name = 'quo"te\\back\nnewline';
        var reread = rbj.parse(rbj.stringify(doc));
        eq(reread.shapes[0].name, 'quo"te\\back\nnewline');
    });
});

function joined(e) { return e.errors.join(" | "); }

function point(x, y) {
    return { "c": [x, y], "in": [0, 0], "out": [0, 0] };
}

function minimal() {
    /* The smallest legal v1 file: one closed shape over two frames. */
    function frame() {
        return {
            opacity: 1.0,
            feather_uniform: [1, 2],
            points: [point(0, 0), point(10, 0), point(10, 10)]
        };
    }
    return {
        format: "rotobridge",
        version: 1,
        source: {
            app: "test", app_version: "0",
            width: 100, height: 100, pixel_aspect: 1.0, fps: 24.0
        },
        range: [1, 2],
        warnings: [],
        shapes: [{
            name: "Shape 1",
            closed: true,
            blend: "union",
            feather_model: "none",
            feather_falloff: "linear",
            frames: { "1": frame(), "2": frame() }
        }]
    };
}

function held(count) {
    /* `minimal()` holding one pose over `count` frames (default 6). */
    if (count === undefined) { count = 6; }
    var doc = minimal();
    var rec = doc.shapes[0].frames["1"];
    var frames = {};
    for (var f = 1; f <= count; f++) {
        frames[String(f)] = JSON.parse(JSON.stringify(rec));
    }
    doc.shapes[0].frames = frames;
    doc.range = [1, count];
    return doc;
}

function eachPoint(doc, fn) {
    var frames = doc.shapes[0].frames;
    for (var key in frames) {
        if (!Object.prototype.hasOwnProperty.call(frames, key)) { continue; }
        for (var i = 0; i < frames[key].points.length; i++) {
            fn(frames[key].points[i]);
        }
    }
}

function anchored(entries) {
    /* `minimal()` with its feather layer moved into feather_points. Defaults
     * to one mid-segment anchor and one on a later segment, which is the shape
     * of what run 3 read off a real After Effects mask. */
    if (entries === undefined) {
        entries = [{ t: 0.25, feather: 30 }, { t: 2.5, feather: -15 }];
    }
    var doc = minimal();
    doc.version = 2;
    doc.shapes[0].feather_model = "anchored";
    var frames = doc.shapes[0].frames;
    for (var key in frames) {
        if (!Object.prototype.hasOwnProperty.call(frames, key)) { continue; }
        var copy = [];
        for (var i = 0; i < entries.length; i++) {
            var out = {};
            for (var m in entries[i]) {
                if (Object.prototype.hasOwnProperty.call(entries[i], m)) {
                    out[m] = entries[i][m];
                }
            }
            copy[copy.length] = out;
        }
        frames[key].feather_points = copy;
    }
    return doc;
}

/* --- the import record --------------------------------------------------- */

function sampleRecord(changes) {
    /* The same record `TestImportRecord` uses in `test/test_core.py`, because
     * two implementations of one document are worth having only if they are
     * held to the same cases. `test_core.py` renders this one through node and
     * compares byte for byte. */
    var record = {
        written: "2026-08-22 09:14:03",
        host: "Nuke 17.1v1",
        target: "Roto1",
        source_file: "/shots/ab_010/roto/ab_010.rbj",
        source: { app: "After Effects", app_version: "25.6x101", width: 1920,
                  height: 1080, fps: 24.0, pixel_aspect: 1.0 },
        version: 2,
        range: [1, 25],
        offset: 0,
        tolerance: 0.5,
        shapes: [{ name: "feathered", feather_model: "anchored", points: 7,
                   authored: 25, corrective: 0, residual: 0.0,
                   worst_frame: 12 }],
        file_warnings: [],
        import_warnings: []
    };
    for (var key in (changes || {})) {
        if (RB.util.hasOwn(changes, key)) { record[key] = changes[key]; }
    }
    return record;
}

function contains(text, wanted, note) {
    if (text.indexOf(wanted) < 0) {
        fail((note ? note + ": " : "") + "not found: " + wanted);
    }
}

describe("report.render", function () {
    it("names the file, the application and the shape", function () {
        var text = RB.report.render(sampleRecord());
        contains(text, "/shots/ab_010/roto/ab_010.rbj");
        contains(text, "After Effects 25.6x101");
        contains(text, "Nuke 17.1v1");
        contains(text, "feathered");
        contains(text, ".rbj version 2");
        contains(text, "1920 x 1080 at 24 fps");
    });

    it("shows the offset as the frames it lands on", function () {
        var text = RB.report.render(sampleRecord({ offset: 100 }));
        contains(text, "source frames  1 to 25");
        contains(text, "placed at      101 to 125 (offset 100)");
    });

    it("names each import mode rather than printing it", function () {
        // `Infinity` is spelled `inf` by the Python, so no record carries
        // either spelling.
        contains(RB.report.render(sampleRecord({ tolerance: Infinity })),
                 "unbounded (authored keys only)");
        contains(RB.report.render(sampleRecord({ tolerance: 0.0 })),
                 "0 px (every frame keyed)");
        contains(RB.report.render(sampleRecord()), "tolerance      0.5 px");
    });

    it("says what arrived and how far it sits from the file", function () {
        var text = RB.report.render(sampleRecord({ shapes: [
            { name: "plain", feather_model: "per_point", points: 4,
              authored: 5, corrective: 3, residual: 0.42105, worst_frame: 9 }
        ] }));
        contains(text, "  plain: feather per_point, 4 point(s), 5 authored"
                 + " key(s), 3 corrective; worst drift 0.4211 px at frame 9");
    });

    it("rounds a pixel measurement half away from zero", function () {
        // Python's `%.4f` rounds half to even, so the rule is stated in both
        // implementations rather than inherited from either language.
        var text = RB.report.render(sampleRecord({ shapes: [
            { name: "tie", feather_model: "none", points: 4, authored: 5,
              corrective: 1, residual: 0.15625, worst_frame: 9 }
        ] }));
        contains(text, "worst drift 0.1563 px");
    });

    it("says so when a shape never drifted", function () {
        var text = RB.report.render(sampleRecord({ shapes: [
            { name: "dense", feather_model: "none", points: 4, authored: 25,
              corrective: 0, residual: 0.0, worst_frame: null }
        ] }));
        contains(text, "nothing drifted from the file");
        eq(text.indexOf("worst drift"), -1, "no measurement is claimed");
    });

    it("keeps the two warning sets apart", function () {
        var text = RB.report.render(sampleRecord({
            file_warnings: ["shape 'x': ease was dropped"],
            import_warnings: ["shape 'x': 3 vertices were inserted"]
        }));
        contains(text, "1 warning recorded when the file was written:");
        contains(text, "  - shape 'x': ease was dropped");
        contains(text, "1 warning from this import:");
        contains(text, "  - shape 'x': 3 vertices were inserted");
    });

    it("states silence rather than omitting it", function () {
        var text = RB.report.render(sampleRecord());
        contains(text, "no warnings recorded when the file was written");
        contains(text, "no warnings from this import");
    });

    it("appends cleanly to another record", function () {
        var twice = RB.report.render(sampleRecord())
            + RB.report.render(sampleRecord());
        eq(twice.split("RotoBridge import record").length - 1, 2);
        eq(twice.charAt(twice.length - 1), "\n");
    });
});

describe("report.pathFor", function () {
    it("sits beside whatever anchors it", function () {
        eq(RB.report.pathFor("/shots/ab_010/comp/ab_010_v012.aep"),
           "/shots/ab_010/comp/ab_010_v012.rotobridge.txt");
        eq(RB.report.pathFor("/shots/ab_010/roto/ab_010.rbj"),
           "/shots/ab_010/roto/ab_010.rotobridge.txt");
    });

    it("counts only a dot in the last component as an extension", function () {
        // A version folder called `v2.1` must not eat the file name, and a
        // leading dot is a name rather than an extension. `os.path.splitext`'s
        // rule, which the Python writes out for the same reason.
        eq(RB.report.pathFor("/shots/v2.1/ab_010"),
           "/shots/v2.1/ab_010.rotobridge.txt");
        eq(RB.report.pathFor("/shots/.rbj"), "/shots/.rbj.rotobridge.txt");
    });

    it("handles a Windows path, which is what Nuke reports there", function () {
        eq(RB.report.pathFor("C:\\shots\\ab_010\\ab_010_v012.nk"),
           "C:\\shots\\ab_010\\ab_010_v012.rotobridge.txt");
    });
});

/* --- report ------------------------------------------------------------- */

if (failures.length) {
    for (var i = 0; i < failures.length; i++) {
        process.stdout.write("FAIL  " + failures[i] + "\n");
    }
    process.stdout.write("\n" + failures.length + " of " + count
                         + " tests failed\n");
    process.exit(1);
}
process.stdout.write("Ran " + count + " tests\n\nOK\n");
