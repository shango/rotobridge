/*
 * The After Effects exporter, run under node against a mock host.
 *
 * `test/test_ae_core.js` covers the parts that touch nothing. This covers the
 * part that touches everything: the frame-major bake, the layer transform, the
 * feather resolution and the shape of the file that comes out. It cannot tell
 * you what After Effects does - `test/ae_mock.js` says what it does and does
 * not reproduce - but it can tell you the exporter does what it was written to
 * do, which is otherwise only discoverable by running it by hand.
 *
 * Two of these tests are about performance rather than correctness, and they
 * matter most. Acceptance criterion 11 is met by the frame-major loop and the
 * derived affine, and both are invisible in the output: an exporter that made
 * a host call per vertex would produce a byte-identical file and miss the
 * criterion by 20x. `timeAssignments` and `pointCalls` are what keep them
 * honest.
 *
 * Run:  node test/test_ae_export.js
 */

var path = require("path");
var fs = require("fs");
var vm = require("vm");

var ROOT = path.dirname(__dirname);
var mock = require(path.join(ROOT, "test", "ae_mock.js"));

/* --- harness ------------------------------------------------------------ */

var failures = [];
var count = 0;
var suite = "";

function describe(name, body) { suite = name; body(); }
function it(name, body) {
    count += 1;
    try { body(); } catch (e) {
        failures.push(suite + ": " + name + "\n    " + (e.stack || e.message || e));
    }
}
function fail(m) { throw new Error(m); }
function eq(got, want, note) {
    if (got !== want) {
        fail((note ? note + ": " : "") + "got " + got + ", want " + want);
    }
}
function near(got, want, places, note) {
    var tol = Math.pow(10, -places) / 2;
    if (!(Math.abs(got - want) <= tol)) {
        fail((note ? note + ": " : "") + "got " + got + ", want " + want);
    }
}
function ok(cond, note) { if (!cond) { fail(note || "expected true"); } }
function has(haystack, needle, note) {
    for (var i = 0; i < haystack.length; i++) {
        if (haystack[i].indexOf(needle) > -1) { return haystack[i]; }
    }
    fail((note ? note + ": " : "") + "no entry containing " + JSON.stringify(needle)
         + " in:\n      " + haystack.join("\n      "));
}
function hasNot(haystack, needle, note) {
    for (var i = 0; i < haystack.length; i++) {
        if (haystack[i].indexOf(needle) > -1) {
            fail((note ? note + ": " : "") + "unexpected entry containing "
                 + JSON.stringify(needle) + ": " + haystack[i]);
        }
    }
}
function deepEq(got, want, note) {
    var g = JSON.stringify(got);
    var w = JSON.stringify(want);
    if (g !== w) { fail((note ? note + ": " : "") + g + " !== " + w); }
}

/* --- loading the adapters ------------------------------------------------ */

function source(name) {
    /* `#include` is an ExtendScript preprocessor directive with no node
     * equivalent, so the includes are resolved here the same way the host
     * resolves them - relative to the including file, once each. */
    var seen = {};
    function read(file) {
        var full = path.join(ROOT, "ae", file);
        if (seen[full]) { return ""; }
        seen[full] = true;
        return fs.readFileSync(full, "utf8").replace(
            /^#include\s+"([^"]+)"\s*$/gm,
            function (_, inc) { return read(inc); });
    }
    return read(name);
}

function runExport(host) {
    /* Fresh globals per run: the adapters build `RB` at load time and the mock
     * replaces `app` per case. */
    delete global.RB;
    vm.runInThisContext(source("rotobridge_export.jsx"),
                        { filename: "rotobridge_export.jsx" });
    return host.written === null ? null : JSON.parse(host.written);
}

/* --- fixtures ------------------------------------------------------------ */

var SQUARE = {
    vertices: [[100, 100], [300, 100], [300, 250], [100, 250]],
    inTangents: [[-10, 0], [-10, 0], [10, 0], [10, 0]],
    outTangents: [[10, 0], [10, 0], [-10, 0], [-10, 0]]
};

function movingSquare(t) {
    /* Travels 100 px in x per second, so the dense layer has something in it
     * and a frozen read shows up as a flat file. */
    var dx = t * 100;
    return mock.makeShape({
        vertices: SQUARE.vertices.map(function (v) { return [v[0] + dx, v[1]]; }),
        inTangents: SQUARE.inTangents,
        outTangents: SQUARE.outTangents
    });
}

function basic(over) {
    var maskSpec = {
        name: "Mask 1",
        pathAt: movingSquare
    };
    var spec = {
        frameRate: 24,
        workAreaStart: 0,
        workAreaDuration: 5 / 24,        // frames 0..4
        layers: [{ name: "Solid 1", masks: [maskSpec] }]
    };
    if (over) {
        for (var k in over) {
            if (k === "mask") {
                for (var mk in over.mask) { maskSpec[mk] = over.mask[mk]; }
            } else if (k === "layer") {
                for (var lk in over.layer) { spec.layers[0][lk] = over.layer[lk]; }
            } else {
                spec[k] = over[k];
            }
        }
    }
    return spec;
}

/* --- the file that comes out --------------------------------------------- */

describe("export shape", function () {
    it("writes a file that validates", function () {
        var host = mock.install(basic());
        var doc = runExport(host);
        ok(doc !== null, "nothing was written; alerts: " + host.alerts.join(" | "));
        eq(doc.format, "rotobridge");
        eq(RB.rbj.validate(doc).length, 0,
           RB.rbj.validate(doc).join(" | "));
    });

    it("ends the file with a newline like the Nuke exporter does", function () {
        // Diffability is spec section 2.1's goal, and `diff` flags a missing
        // final newline on every comparison. Nuke's export_to_file writes
        // text + "\n"; the adapter is where the AE side matches it, because
        // stringify's bare output is byte-compared between implementations.
        var host = mock.install(basic());
        runExport(host);
        ok(host.written !== null, "nothing was written");
        eq(host.written.charAt(host.written.length - 1), "\n");
    });

    it("covers the work area exactly", function () {
        // The work area's end is the time after its last frame, so a range
        // built without the subtraction exports one frame too many.
        var doc = runExport(mock.install(basic()));
        eq(doc.range[0], 0);
        eq(doc.range[1], 4);
        var frames = Object.keys(doc.shapes[0].frames).sort();
        eq(frames.length, 5);
    });

    it("honours displayStartTime in the frame numbers", function () {
        // .rbj carries the frame numbers the artist sees (spec section 4).
        var doc = runExport(mock.install(basic({ displayStartTime: 100 / 24 })));
        eq(doc.range[0], 100);
        eq(doc.range[1], 104);
    });

    it("always writes a keys array, never omits it", function () {
        // An absent `keys` means "treat every frame as a key" (spec section 9),
        // which is a different claim from "this mask has no keys of its own".
        var doc = runExport(mock.install(basic()));
        eq(RB.util.isArray(doc.shapes[0].keys), true);
    });

    it("flips Y about the comp height", function () {
        var doc = runExport(mock.install(basic()));
        var c = doc.shapes[0].frames["0"].points[0].c;
        eq(c[0], 100);
        eq(c[1], 1080 - 100);
    });

    it("flips tangent Y without the height", function () {
        var doc = runExport(mock.install(basic()));
        var pt = doc.shapes[0].frames["0"].points[0];
        near(pt["in"][0], -10, 9);
        near(pt["in"][1], 0, 9);
        near(pt["out"][0], 10, 9);
    });

    it("bakes motion into the dense layer", function () {
        var doc = runExport(mock.install(basic()));
        var at0 = doc.shapes[0].frames["0"].points[0].c[0];
        var at4 = doc.shapes[0].frames["4"].points[0].c[0];
        near(at4 - at0, 4 / 24 * 100, 6);
    });

    it("converts opacity from a percentage to a fraction", function () {
        var doc = runExport(mock.install(basic({
            mask: { opacityAt: function () { return 40; } }
        })));
        near(doc.shapes[0].frames["0"].opacity, 0.4, 9);
    });

    it("reads uniform feather per frame because it animates", function () {
        // Run 6 measured a keyed maskFeather going 10 to 80. Read once per
        // shape it would freeze at the first frame.
        var doc = runExport(mock.install(basic({
            mask: {
                featherAt: function (t) { return [10 + t * 240, 5]; }
            }
        })));
        var a = doc.shapes[0].frames["0"].feather_uniform;
        var b = doc.shapes[0].frames["4"].feather_uniform;
        near(a[0], 10, 6);
        near(b[0], 10 + 4 / 24 * 240, 6);
        eq(a[1], 5, "the y component is independent, not a copy of x");
    });
});

/* --- the layer transform -------------------------------------------------- */

describe("layer transform", function () {
    var TRANSFORMED = {
        anchor: [960, 540], scale: [1.5, 2.2], rotation: 30,
        position: [700, 400]
    };

    function hostToComp(p) {
        var x = (p[0] - 960) * 1.5;
        var y = (p[1] - 540) * 2.2;
        var r = 30 * Math.PI / 180;
        return [700 + x * Math.cos(r) - y * Math.sin(r),
                400 + x * Math.sin(r) + y * Math.cos(r)];
    }

    it("applies rotation and non-uniform scale to vertices", function () {
        var doc = runExport(mock.install(basic({
            layer: { transform: TRANSFORMED }
        })));
        var want = hostToComp([100, 100]);
        var got = doc.shapes[0].frames["0"].points[0].c;
        near(got[0], want[0], 6);
        near(got[1], 1080 - want[1], 6);
    });

    it("applies it to tangents too", function () {
        // A tangent that came back unrotated would mean the transform was read
        // for positions and skipped for handles - a bug that looks fine until
        // the shape is curved.
        var doc = runExport(mock.install(basic({
            layer: { transform: TRANSFORMED }
        })));
        var moved = hostToComp([100 + 10, 100]);
        var base = hostToComp([100, 100]);
        var got = doc.shapes[0].frames["0"].points[0]["out"];
        near(got[0], moved[0] - base[0], 6);
        near(got[1], -(moved[1] - base[1]), 6);
    });
});

/* --- the two performance decisions ---------------------------------------- */

describe("loop shape", function () {
    it("sets comp.time once per frame, not once per shape per frame", function () {
        // prd.md section 9.1 step 4. Mask-major would be 5 x 3 here and about
        // 31 s for ten shapes over 150 frames in the host.
        var spec = basic();
        spec.layers[0].masks = [
            { name: "Mask 1", pathAt: movingSquare },
            { name: "Mask 2", pathAt: movingSquare },
            { name: "Mask 3", pathAt: movingSquare }
        ];
        var host = mock.install(spec);
        runExport(host);
        // Five frames, plus the one assignment that restores the playhead.
        eq(host.timeAssignments, 6);
    });

    it("probes the layer transform per frame, not per vertex", function () {
        // Three probes fix the affine and a fourth checks it, so the count is
        // flat in vertex count. Per-vertex conversion would be 3 per vertex.
        var host = mock.install(basic());
        runExport(host);
        eq(host.pointCalls, 4 * 5, "4 probes x 5 frames");
    });

    it("shares one probe across every mask on a layer", function () {
        var spec = basic();
        spec.layers[0].masks = [
            { name: "Mask 1", pathAt: movingSquare },
            { name: "Mask 2", pathAt: movingSquare }
        ];
        var host = mock.install(spec);
        runExport(host);
        eq(host.pointCalls, 4 * 5, "two masks, one transform");
    });

    it("stays flat as the shape gets bigger", function () {
        // The whole point: cost independent of vertex count.
        var many = [];
        for (var i = 0; i < 64; i++) { many.push([i * 3, i * 5]); }
        var spec = basic({
            mask: {
                pathAt: function () {
                    return mock.makeShape({
                        vertices: many,
                        inTangents: many.map(function () { return [0, 0]; }),
                        outTangents: many.map(function () { return [0, 0]; })
                    });
                }
            }
        });
        var host = mock.install(spec);
        var doc = runExport(host);
        eq(doc.shapes[0].frames["0"].points.length, 64);
        eq(host.pointCalls, 4 * 5, "64 vertices must cost the same as 4");
    });
});

/* --- feather --------------------------------------------------------------- */

describe("feather", function () {
    function withFeatherPoints(spec) {
        return basic({
            mask: {
                pathAt: function (t) {
                    var s = movingSquare(t);
                    s.featherSegLocs = spec.segLocs;
                    s.featherRelSegLocs = spec.relLocs;
                    s.featherRadii = spec.radii;
                    if (spec.interps) { s.featherInterps = spec.interps; }
                    if (spec.tensions) { s.featherTensions = spec.tensions; }
                    if (spec.cornerAngles) {
                        s.featherRelCornerAngles = spec.cornerAngles;
                    }
                    return s;
                }
            }
        });
    }

    it("says none when there are no feather points", function () {
        var doc = runExport(mock.install(basic()));
        eq(doc.shapes[0].feather_model, "none");
        eq(RB.util.hasOwn(doc.shapes[0].frames["0"].points[0], "feather"), false,
           "a zero under 'none' is indistinguishable from an authored zero");
    });

    it("warns when tension, corner angle or interp shaping is authored",
       function () {
        // prd.md section 9.3 names featherInterps, featherTensions and
        // featherRelCornerAngles as readable; .rbj has no member for any of
        // them. Dropping them is the accepted loss - dropping them silently
        // is not, any more than it is for maskExpansion or the inverted flag.
        var doc = runExport(mock.install(withFeatherPoints({
            segLocs: [1], relLocs: [0.0], radii: [12.5],
            tensions: [0.6], cornerAngles: [0.3]
        })));
        var said = doc.warnings.join(" | ");
        has(doc.warnings, "tension");
        has(doc.warnings, "corner angle");
        eq(said.indexOf("interpolation") === -1, true,
           "interp was left at its default; warning about it would be noise");
    });

    it("says nothing about shaping left at its defaults", function () {
        var doc = runExport(mock.install(withFeatherPoints({
            segLocs: [1], relLocs: [0.0], radii: [12.5],
            interps: [0], tensions: [0], cornerAngles: [0]
        })));
        hasNot(doc.warnings, "tension");
    });

    it("says per_point and resolves onto vertices", function () {
        var doc = runExport(mock.install(withFeatherPoints({
            segLocs: [1], relLocs: [0.0], radii: [12.5]
        })));
        eq(doc.shapes[0].feather_model, "per_point");
        eq(doc.shapes[0].frames["0"].points[1].feather, 12.5);
        eq(doc.shapes[0].frames["0"].points[0].feather, 0,
           "unclaimed vertices are filled, since per_point requires every one");
    });

    it("keeps the sign, which carries the direction", function () {
        var doc = runExport(mock.install(withFeatherPoints({
            segLocs: [2], relLocs: [0.0], radii: [-30]
        })));
        eq(doc.shapes[0].frames["2"].points[2].feather, -30);
    });

    it("resolves feather by anchor when the host has reordered it", function () {
        // The fixtures above read an unkeyed path, so the host hands the
        // feather back renamed but in written order. A real mask is keyed, and
        // between two keys After Effects also regroups the points by type -
        // non-negative before negative - which
        // test/probe/probe_ae_feather_interpolated.jsx measured for LINEAR keys
        // as well as BEZIER.
        //
        // The export is frame-major and bakes every frame, so most of the
        // frames it reads are exactly those in-between ones. It survives that
        // because `snapFeatherPoints` resolves each point through its own
        // anchor rather than trusting the array order. If that is ever
        // "simplified" to index-by-index, every non-key frame of a feathered
        // shape starts exporting scrambled radii, and only this test says so.
        var withFeather = function (t) {
            var s = movingSquare(t);
            s.featherSegLocs = [0, 1, 2, 3];
            s.featherRelSegLocs = [0, 0, 0, 0];
            s.featherRadii = [30, -15, 0, 12];
            s.featherTypes = [0, 1, 0, 0];
            return s;
        };
        var spec = basic({ mask: { pathAt: withFeather } });
        spec.layers[0].masks[0].pathKeys = [
            { t: 0, value: withFeather(0) },
            { t: 4 / 24, value: withFeather(4 / 24) }
        ];
        var doc = runExport(mock.install(spec));
        var pts = doc.shapes[0].frames["2"].points;   // between the two keys
        eq(pts[0].feather, 30, "vertex 0");
        eq(pts[1].feather, -15, "vertex 1");
        eq(pts[2].feather, 0, "vertex 2");
        eq(pts[3].feather, 12, "vertex 3");
    });

    it("says anchored when a point was mid-segment", function () {
        // spec/rbj-v2-draft.md section 6.7. Under v1 this was snapped to the
        // nearer vertex and warned about; the anchor is now carried where the
        // artist put it, and the price is that the file is version 2.
        var doc = runExport(mock.install(withFeatherPoints({
            segLocs: [0], relLocs: [0.7], radii: [5]
        })));
        eq(doc.shapes[0].feather_model, "anchored");
        eq(doc.version, 2);
        deepEq(doc.shapes[0].frames["0"].feather_points,
               [{ t: 0.7, feather: 5 }]);
        eq(RB.util.hasOwn(doc.shapes[0].frames["0"].points[0], "feather"),
           false, "anchored means no point carries feather");
        has(doc.warnings, "a version 1 reader will refuse it");
        hasNot(doc.warnings, "snapped to the nearer vertex");
    });

    it("says anchored when two points share a vertex", function () {
        // The case that decided the design: v1 kept the larger radius and
        // discarded the other, so an authored zero-width point disappeared.
        var doc = runExport(mock.install(withFeatherPoints({
            segLocs: [0, 0], relLocs: [0.0, 0.0], radii: [2, -9]
        })));
        eq(doc.shapes[0].feather_model, "anchored");
        deepEq(doc.shapes[0].frames["0"].feather_points,
               [{ t: 0, feather: -9 }, { t: 0, feather: 2 }]);
        hasNot(doc.warnings, "two feather points resolved to");
    });

    it("stays per_point and version 1 when every anchor is on a vertex",
       function () {
        // The other half of section 6.7, and the more important half: the
        // compatibility cost is paid only by the files that were being
        // damaged. Nothing here needs anchoring, so nothing about the file
        // changes.
        var doc = runExport(mock.install(withFeatherPoints({
            segLocs: [0, 2], relLocs: [0.0, 1.0], radii: [4, -6]
        })));
        eq(doc.shapes[0].feather_model, "per_point");
        eq(doc.version, 1);
        eq(RB.util.hasOwn(doc.shapes[0].frames["0"], "feather_points"), false);
        eq(doc.shapes[0].frames["0"].points[0].feather, 4);
        eq(doc.shapes[0].frames["0"].points[3].feather, -6);
        hasNot(doc.warnings, "version 2");
    });

    it("falls back to the snap when the anchor count changes", function () {
        // Section 6.3 fixes the count across frames for the reason section 7.3
        // gives about vertices, so a shape that gains a feather point partway
        // cannot be anchored at all. v1's behaviour is the fallback, which is
        // why snapFeatherPoints does not go away, and it says so.
        var spec = basic({
            mask: {
                pathAt: function (t) {
                    var sh = movingSquare(t);
                    sh.featherSegLocs = t > 0 ? [0, 2] : [0];
                    sh.featherRelSegLocs = t > 0 ? [0.7, 0.0] : [0.7];
                    sh.featherRadii = t > 0 ? [5, 9] : [5];
                    return sh;
                }
            }
        });
        var doc = runExport(mock.install(spec));
        eq(doc.shapes[0].feather_model, "per_point");
        eq(doc.version, 1);
        has(doc.warnings, "number of feather points changes between frames");
        has(doc.warnings, "snapped to the nearer vertex");
    });

    it("keeps the anchor list ordered on every frame", function () {
        // The host regroups its arrays by type on in-between frames, and
        // section 6.3 requires ascending t, so every frame is sorted.
        var doc = runExport(mock.install(withFeatherPoints({
            segLocs: [3, 0, 2], relLocs: [0.5, 0.5, 0.5], radii: [1, 2, 3]
        })));
        var frames = doc.shapes[0].frames;
        for (var key in frames) {
            if (!RB.util.hasOwn(frames, key)) { continue; }
            var pts = frames[key].feather_points;
            deepEq([pts[0].t, pts[1].t, pts[2].t], [0.5, 2.5, 3.5],
                   "frame " + key);
        }
    });

    it("carries falloff once per shape", function () {
        // maskFeatherFalloff is an attribute, not a Property, so it cannot be
        // keyframed and has no place in the dense layer.
        eq(runExport(mock.install(basic())).shapes[0].feather_falloff, "linear");
        eq(runExport(mock.install(basic({ mask: { falloff: 7212 } })))
            .shapes[0].feather_falloff, "smooth");
    });
});

/* --- blend, warnings and failures ------------------------------------------ */

describe("mapping and failures", function () {
    it("maps the three mask modes that have equivalents", function () {
        eq(runExport(mock.install(basic({ mask: { maskMode: 6813 } })))
            .shapes[0].blend, "union");
        eq(runExport(mock.install(basic({ mask: { maskMode: 6814 } })))
            .shapes[0].blend, "difference");
        eq(runExport(mock.install(basic({ mask: { maskMode: 6815 } })))
            .shapes[0].blend, "intersection");
    });

    it("names the mask mode it could not map", function () {
        var doc = runExport(mock.install(basic({ mask: { maskMode: 6817 } })));
        eq(doc.shapes[0].blend, "union");
        has(doc.warnings, "'Darken'");
    });

    it("warns that the inverted flag was dropped", function () {
        has(runExport(mock.install(basic({ mask: { inverted: true } }))).warnings,
            "inverted flag was dropped");
    });

    it("warns about a mask expansion it has nowhere to put", function () {
        var doc = runExport(mock.install(basic({
            mask: { expansionAt: function () { return 12; } }
        })));
        has(doc.warnings, "mask expansion");
    });

    it("does not warn about a zero expansion", function () {
        var doc = runExport(mock.install(basic()));
        for (var i = 0; i < doc.warnings.length; i++) {
            ok(doc.warnings[i].indexOf("expansion") === -1,
               "warned about the default: " + doc.warnings[i]);
        }
    });

    it("deduplicates a warning raised on every frame", function () {
        // Otherwise a 150-frame shape buries everything else under 150 copies.
        var doc = runExport(mock.install(basic({ mask: { maskMode: 6817 } })));
        var seen = 0;
        for (var i = 0; i < doc.warnings.length; i++) {
            if (doc.warnings[i].indexOf("Darken") > -1) { seen += 1; }
        }
        eq(seen, 1);
    });

    it("refuses a 3D layer", function () {
        var host = mock.install(basic({ layer: { threeD: true } }));
        eq(runExport(host), null);
        has(host.alerts, "is 3D");
    });

    it("refuses a parented layer", function () {
        var host = mock.install(basic({ layer: { parent: { name: "Null 1" } } }));
        eq(runExport(host), null);
        has(host.alerts, "parented to");
    });

    it("exports an open spline, and stamps the file version 2", function () {
        // spec/rbj-v2-draft.md section 2: the bump belongs to the file. A
        // closed export from the same adapter still says 1, which every other
        // case here asserts by reading a v1 document.
        var doc = runExport(mock.install(basic({
            mask: {
                pathAt: function (t) {
                    var s = movingSquare(t);
                    s.closed = false;
                    return s;
                }
            }
        })));
        eq(doc.shapes[0].closed, false);
        eq(doc.version, 2);
        has(doc.warnings, "is an open spline");
    });

    it("refuses a spline that opens partway through", function () {
        // One `closed` for the whole shape, and no correct reading of a path
        // that changes: the same argument as a changing vertex count.
        var host = mock.install(basic({
            mask: {
                pathAt: function (t) {
                    var s = movingSquare(t);
                    s.closed = t < 0.1;
                    return s;
                }
            }
        }));
        eq(runExport(host), null);
        has(host.alerts, "open/closed state per shape");
    });

    it("refuses a vertex count that changes", function () {
        var host = mock.install(basic({
            mask: {
                pathAt: function (t) {
                    var s = movingSquare(t);
                    if (t > 0.1) {
                        s.vertices = s.vertices.slice(0, 3);
                        s.inTangents = s.inTangents.slice(0, 3);
                        s.outTangents = s.outTangents.slice(0, 3);
                    }
                    return s;
                }
            }
        }));
        eq(runExport(host), null);
        has(host.alerts, "vertices at frame");
    });

    it("warns when two masks share a name", function () {
        var spec = basic();
        spec.layers.push({
            name: "Solid 2",
            masks: [{ name: "Mask 1", pathAt: movingSquare }]
        });
        var doc = runExport(mock.install(spec));
        has(doc.warnings, "both named 'Mask 1'");
        eq(doc.shapes.length, 2);
    });

    it("puts the playhead back where it found it", function () {
        // The export moves it once per frame and the artist did not ask for it.
        var host = mock.install(basic());
        host.comp.time = 3.5;
        runExport(host);
        eq(host.comp.time, 3.5);
    });

    it("writes nothing when the save dialog is cancelled", function () {
        var host = mock.install(basic({ savePath: null }));
        eq(runExport(host), null);
        eq(host.alerts.length, 0, "cancelling is not an error");
    });
});

/* --- the sparse layer ------------------------------------------------------ */

describe("export keys", function () {
    var LINEAR = 6612, BEZIER = 6613, HOLD = 6614;

    function ease(speed, influence) {
        return new mock.KeyframeEase(speed, influence);
    }

    function keyedAt(seed, over) {
        /* A mask whose path carries real keyframes, which is the only thing
         * `keys` is read from. */
        var spec = basic(over);
        spec.layers[0].masks[0].pathKeys = seed;
        return spec;
    }

    function at(t, over) {
        var spec = { t: t / 24, value: movingSquare(t / 24) };
        for (var k in (over || {})) { spec[k] = over[k]; }
        return spec;
    }

    function keysOf(spec) { return runExport(mock.install(spec)).shapes[0].keys; }

    it("reads the frames the artist keyed", function () {
        var keys = keysOf(keyedAt([at(0), at(2), at(4)]));
        eq(keys.length, 3);
        eq(keys[0].frame, 0);
        eq(keys[1].frame, 2);
        eq(keys[2].frame, 4);
    });

    it("maps each side of a key independently", function () {
        // Run 6 read `in=LINEAR, out=HOLD` off a real mask on its first try, so
        // a single-valued interp would have been wrong from the first file.
        var keys = keysOf(keyedAt([at(0), at(2, { inType: LINEAR,
                                                  outType: HOLD }), at(4)]));
        eq(keys[1].interp["in"], "linear");
        eq(keys[1].interp["out"], "hold");
    });

    function everyFrame(over) {
        /* A key on all five frames, the middle one carrying whatever is under
         * test. The dense bake still has to read every frame, and `ae_mock`
         * refuses to interpolate a bezier segment - so leaving no gap is what
         * lets a bezier key be tested at all here. */
        return keyedAt([at(0), at(1), at(2, over), at(3), at(4)]);
    }

    it("conforms an unrecognised interpolation type rather than failing", function () {
        // Spec section 10.3's bare `ease` is "smooth, parameters unknown", and
        // a type this adapter has never seen is exactly that. Nuke reads any
        // ease as cubic, so what leaves here is linear either way.
        var keys = keysOf(everyFrame({ inType: 9999, outType: 9999 }));
        eq(keys[2].interp["in"], "linear");
        eq(keys[2].interp["out"], "linear");
    });

    it("strips the ease block a bezier key produced", function () {
        // Reading it is still right and still tested - test_ae_core covers the
        // factor of 100 and the speed passing through untouched. What changed
        // is that the parameters no longer reach the file: Nuke's roto curves
        // have no vocabulary for them, so the exporter spends the keys here
        // instead of leaving a compositor to wonder why the shape is dense.
        var keys = keysOf(everyFrame({
            inType: BEZIER, outType: BEZIER,
            inEase: ease(0, 91.176), outEase: ease(1, 100)
        }));
        eq(keys[2].interp["in"], "linear");
        eq(RB.util.hasOwn(keys[2], "ease"), false);
    });

    it("conforms the eased side and leaves the held one alone", function () {
        // The rule is narrow on purpose. `hold` crosses losslessly - it maps
        // to Nuke's step - so rewriting it as linear would turn a frozen
        // interval into a slide and then buy a key on every frame of it to
        // flatten it again: paying keys to destroy something that was free.
        var keys = keysOf(everyFrame({ inType: BEZIER, outType: HOLD,
                                       inEase: ease(0, 91.176) }));
        eq(keys[2].interp["in"], "linear");
        eq(keys[2].interp["out"], "hold");
        eq(RB.util.hasOwn(keys[2], "ease"), false);
    });

    it("says what it conformed, and only when the artist authored it", function () {
        var authored = mock.install(everyFrame({
            inType: BEZIER, outType: BEZIER, inEase: ease(0, 91.176),
            outEase: ease(0, 33.333)
        }));
        has(runExport(authored).warnings, "carried temporal ease");

        // A pinned endpoint carries `ease` too, because nothing was authored
        // there to read. Warning about that would report damage the file did
        // not take.
        var plain = runExport(mock.install(keyedAt([at(0), at(4)])));
        var quiet = true;
        for (var i = 0; i < plain.warnings.length; i++) {
            if (/carried temporal ease/.test(plain.warnings[i])) { quiet = false; }
        }
        eq(quiet, true, "an unauthored ease is not reported as one");
    });

    it("leaves a shape with no eased side untouched", function () {
        // Nothing to conform, nothing added, nothing said.
        var keys = keysOf(everyFrame({ inType: LINEAR, outType: LINEAR }));
        eq(keys.length, 5);
        eq(keys[2].interp["out"], "linear");
    });

    it("pins both ends of the exported range", function () {
        // A shape keyed only in the middle would otherwise claim to be static
        // at the edges, where the dense layer says it is not.
        var keys = keysOf(keyedAt([at(2)]));
        eq(keys.length, 3);
        eq(keys[0].frame, 0);
        eq(keys[2].frame, 4);
        eq(keys[0].interp["out"], "linear",
           "a pinned end has nothing authored, and conforms to linear");
    });

    it("drops keys outside the exported range", function () {
        // A key outside the range still drives the values inside it, but spec
        // section 9 requires every keys[].frame to exist in `frames`.
        var keys = keysOf(keyedAt([at(-30), at(2), at(90)]));
        eq(keys.length, 3);
        eq(keys[0].frame, 0);
        eq(keys[1].frame, 2);
        eq(keys[2].frame, 4);
    });

    it("snaps an off-grid key and says it did", function () {
        var host = mock.install(keyedAt([at(0), { t: 2.4 / 24,
                                                  value: movingSquare(2.4 / 24) },
                                         at(4)]));
        var doc = runExport(host);
        eq(doc.shapes[0].keys[1].frame, 2);
        has(doc.warnings, "off the grid");
    });

    it("takes the layer transform's keys as the shape's own", function () {
        // The transform is baked into the exported points, so a layer that
        // moves animates the geometry even when the path never does - the same
        // reason case 77 made the Nuke side walk its layer chain.
        var spec = keyedAt([at(0), at(4)]);
        spec.layers[0].transformKeys = { "ADBE Position": [1 / 24, 3 / 24] };
        var keys = keysOf(spec);
        eq(keys.length, 4);
        eq(keys[1].frame, 1);
        eq(keys[2].frame, 3);
        eq(keys[1].interp["out"], "linear",
           "nothing was authored on the path, and it conforms to linear");
    });

    it("calls a synthetic key inside a held segment a hold", function () {
        // The defect this pins: a transform key landing inside a held path
        // segment is labelled `ease` because nothing was authored on the path
        // there - but the bake right next to it says the shape does not move.
        // Nuke's step is outgoing-only and `interp.to_nuke` reports `out: hold`
        // exact, so the whole path from measurement to Nuke already exists and
        // only this label is wrong. Measured on the real crossing: frames 19-23
        // of `mixed` in `test/golden/ae_scene.rbj` are byte-identical and the
        // key at 18 claims `ease`, which costs five corrective keys and tells a
        // Nuke artist the shape ramps where After Effects freezes.
        var spec = keyedAt([at(0, { outType: HOLD }), at(4)]);
        spec.layers[0].transformKeys = { "ADBE Position": [2 / 24] };
        var doc = runExport(mock.install(spec));
        var frames = doc.shapes[0].frames;

        // The control, and it has to come first: if the mock ever stopped
        // baking a hold as a hold, the assertion below would pass for the
        // wrong reason and this test would be measuring nothing.
        eq(JSON.stringify(frames["3"].points),
           JSON.stringify(frames["2"].points),
           "the bake holds across the segment");
        var moved = JSON.stringify(frames["4"].points)
                 !== JSON.stringify(frames["2"].points);
        eq(moved, true, "and releases at the next path key");

        var keys = doc.shapes[0].keys;
        eq(keys.length, 3);
        eq(keys[1].frame, 2);
        eq(keys[1].interp["out"], "hold");
    });

    it("does not call a synthetic key on a moving segment a hold", function () {
        // The other half of the same rule, and the reason it cannot simply be
        // "synthetic keys hold". Same shape of scene, no hold authored: the
        // bake moves on every frame, so the segment is not flat. It leaves as
        // `linear` rather than `ease` because the conform runs after.
        var spec = keyedAt([at(0), at(4)]);
        spec.layers[0].transformKeys = { "ADBE Position": [2 / 24] };
        var doc = runExport(mock.install(spec));
        var frames = doc.shapes[0].frames;
        var moved = JSON.stringify(frames["3"].points)
                 !== JSON.stringify(frames["2"].points);
        eq(moved, true, "the bake moves across the segment");
        eq(doc.shapes[0].keys[1].interp["out"], "linear");
    });

    it("refuses a hold the layer's motion contradicts", function () {
        // The mirror of the test above, and the larger of the two errors.
        // The artist authored `out: HOLD` on the path, but the layer moves
        // underneath it, so the SHAPE is not flat - and spec section 10.2 is
        // about the segment, not about which property was keyed: "when
        // `A.interp.out` is `hold` the segment is flat". `frames` carries the
        // composite, so a `hold` here is a claim the dense layer next to it
        // contradicts. Measured on the real crossing: `mixed` frames 13-17 of
        // `test/golden/ae_scene.rbj` move about 11 px per frame under an
        // authored hold, and Nuke steps them ~66 px wrong until the drift pass
        // pays to put it back.
        var held = [at(0, { outType: HOLD }), at(4)];

        // Control, and the whole test rests on it: the SAME path with a static
        // layer must still say `hold`. Without this, a rule that simply never
        // wrote `hold` would pass.
        var stillSpec = keyedAt(held);
        stillSpec.layers[0].transformKeys = { "ADBE Position": [0, 4 / 24] };
        eq(keysOf(stillSpec)[0].interp["out"], "hold",
           "a real hold over a still layer is still a hold");

        var spec = keyedAt(held);
        spec.layers[0].transformKeys = { "ADBE Position": [0, 4 / 24] };
        spec.layers[0].transform = {
            position: function (t) { return [t * 2400, 0]; }
        };
        var doc = runExport(mock.install(spec));
        var frames = doc.shapes[0].frames;
        var moved = JSON.stringify(frames["2"].points)
                 !== JSON.stringify(frames["1"].points);
        eq(moved, true, "the layer really moves the held path");

        var keys = doc.shapes[0].keys;
        eq(keys[0].interp["out"], "linear", "the contradicted hold is gone");
        has(doc.warnings, "hold");

        // And the conform pays for the contradiction here rather than leaving
        // it to the destination. The path is frozen while the layer moves, so
        // the composite is not the straight line two keys would claim, and the
        // fit puts keys in until it is. Before this the sparse layer said
        // "straight from 0 to 4" and the importer's drift pass bought the
        // same keys at the far end, where nobody could see why.
        eq(keys.length > 2, true, "keys were added to match the bake");
    });

    it("ignores a transform property that cannot move geometry", function () {
        // Layer opacity lives in the same group. Keying it would otherwise
        // plant a key in the middle of a shape that never moved.
        var spec = keyedAt([at(0), at(4)]);
        spec.layers[0].transformKeys = { "ADBE Opacity": [2 / 24] };
        eq(keysOf(spec).length, 2);
    });

    it("gives an unkeyed mask two keys, not none", function () {
        // A static shape needs no key between them, so the conform adds
        // nothing and the two endpoints leave as linear.
        var keys = keysOf(basic());
        eq(keys.length, 2);
        eq(keys[0].interp["in"], "linear");
        eq(keys[1].interp["out"], "linear");
    });
});

/* --- the by-hand fixture --------------------------------------------------- */

describe("the scene builder for the host run", function () {
    /* `test/probe/setup_ae_scene.jsx` authors the comp the Phase 4 checklist
     * needs. It is run by hand in After Effects, so nothing here can say what
     * the host makes of it - but a typo in it is only discovered after a trip
     * to another machine, and that is worth one test.
     *
     * The scene cannot be exported under the mock, deliberately: its `eased`
     * mask is bezier on every side, and the dense bake would have to
     * interpolate one, which is exactly the thing the mock refuses to guess
     * at. That refusal is why the fixture exists. */

    function built() {
        var host = mock.install({
            width: 1920, height: 1080, frameRate: 24,
            workAreaStart: 0, workAreaDuration: 25 / 24, duration: 60 / 24,
            layers: [], selected: []
        });
        vm.runInThisContext(
            fs.readFileSync(path.join(ROOT, "test", "probe",
                                      "setup_ae_scene.jsx"), "utf8"),
            { filename: "setup_ae_scene.jsx" });
        return host;
    }

    it("runs start to finish and authors one mask per checklist row",
       function () {
        var host = built();
        var masks = host.comp.layer(1)._masks;
        var names = [];
        for (var i = 0; i < masks.length; i++) { names[i] = masks[i].name; }
        eq(String(names),
           String(["linear", "eased", "mixed", "feathered", "offgrid",
                   "opened"]));
        // The control masks live on a second, static solid - see the builder.
        var flat = host.comp.layer(2)._masks;
        eq(String([flat[0].name, flat[1].name]),
           String(["eased_static", "linear_static"]));
        // A failed authoring step is reported rather than thrown, so an alert
        // naming one is the thing that would otherwise pass unnoticed.
        eq(host.alerts.length, 1);
        ok(String(host.alerts[0]).indexOf("FAILED") === -1, host.alerts[0]);
    });

    it("puts a key where no frame is, for the export to snap", function () {
        var host = built();
        var prop = host.comp.layer(1)._masks[4].property("ADBE Mask Shape");
        near(prop.keyTime(2) * 24, 10.4, 6, "the off-grid key");
    });

    it("authors the open spline open", function () {
        // The one mask in the scene whose whole point is a boolean, so a
        // builder that quietly wrote a closed path would look identical.
        var host = built();
        var prop = host.comp.layer(1)._masks[5].property("ADBE Mask Shape");
        eq(prop.value.closed, false);
    });

    it("eases nowhere near the default, so a default cannot pass for it",
       function () {
        // 16.667 is what After Effects reports on a key nobody eased, so an
        // ease that survives the round trip has to be distinguishable from it.
        var host = built();
        var prop = host.comp.layer(1)._masks[1].property("ADBE Mask Shape");
        near(prop.keyInTemporalEase(1)[0].influence, 91.176, 3);
        near(prop.keyOutTemporalEase(1)[0].influence, 33.333, 3);
    });
});

/* --- report ---------------------------------------------------------------- */

if (failures.length) {
    for (var i = 0; i < failures.length; i++) {
        process.stdout.write("FAIL  " + failures[i] + "\n");
    }
    process.stdout.write("\n" + failures.length + " of " + count + " failed\n");
    process.exit(1);
}
process.stdout.write("Ran " + count + " tests\n\nOK\n");
