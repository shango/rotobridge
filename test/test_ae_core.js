/*
 * Tests for the ExtendScript core, run under plain node.
 *
 * `ae/rotobridge_core.jsx` and `ae/rotobridge_rbj.jsx` touch no host, exactly
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
global.RB = require(path.join(ROOT, "ae", "rotobridge_core.jsx"));
require(path.join(ROOT, "ae", "rotobridge_rbj.jsx"));

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
