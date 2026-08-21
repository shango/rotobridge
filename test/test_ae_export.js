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

    it("warns when a point was mid-segment", function () {
        var doc = runExport(mock.install(withFeatherPoints({
            segLocs: [0], relLocs: [0.7], radii: [5]
        })));
        has(doc.warnings, "snapped to the nearer vertex");
        eq(doc.shapes[0].frames["0"].points[1].feather, 5);
    });

    it("warns when two points collide, keeping the larger", function () {
        var doc = runExport(mock.install(withFeatherPoints({
            segLocs: [0, 0], relLocs: [0.0, 0.0], radii: [2, -9]
        })));
        has(doc.warnings, "two feather points resolved to");
        eq(doc.shapes[0].frames["0"].points[0].feather, -9);
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

    it("calls an unrecognised interpolation type ease, not an error", function () {
        // Spec section 10.3's bare `ease` is "smooth, parameters unknown, rely
        // on the drift pass", which is a truthful description of a type this
        // adapter has never seen.
        var keys = keysOf(everyFrame({ inType: 9999, outType: 9999 }));
        eq(keys[2].interp["in"], "ease");
        eq(keys[2].interp["out"], "ease");
    });

    it("divides ease influence by 100 and leaves speed alone", function () {
        // The two numbers scale differently on purpose: influence is a
        // percentage of the interval, speed is value-units per second.
        var keys = keysOf(everyFrame({
            inType: BEZIER, outType: BEZIER,
            inEase: ease(0, 91.176), outEase: ease(1, 100)
        }));
        eq(JSON.stringify(keys[2].ease["in"]), JSON.stringify([0.91176, 0]));
        eq(JSON.stringify(keys[2].ease["out"]), JSON.stringify([1, 1]));
    });

    it("writes an ease entry only for a side that is ease", function () {
        // After Effects reports an ease on every key whatever its type - run 6
        // read influence 16.667 off a LINEAR key - so reading unconditionally
        // would write parameters that describe nothing, and the validator
        // rejects an ease entry on a non-ease side.
        var keys = keysOf(everyFrame({ inType: LINEAR, outType: BEZIER,
                                       outEase: ease(0.5, 40) }));
        eq(RB.util.hasOwn(keys[2].ease, "in"), false);
        eq(JSON.stringify(keys[2].ease["out"]), JSON.stringify([0.4, 0.5]));
    });

    it("pins both ends of the exported range", function () {
        // A shape keyed only in the middle would otherwise claim to be static
        // at the edges, where the dense layer says it is not.
        var keys = keysOf(keyedAt([at(2)]));
        eq(keys.length, 3);
        eq(keys[0].frame, 0);
        eq(keys[2].frame, 4);
        eq(keys[0].interp["out"], "ease", "a pinned end has nothing authored");
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
        eq(keys[1].interp["out"], "ease", "nothing was authored on the path");
    });

    it("ignores a transform property that cannot move geometry", function () {
        // Layer opacity lives in the same group. Keying it would otherwise
        // plant a key in the middle of a shape that never moved.
        var spec = keyedAt([at(0), at(4)]);
        spec.layers[0].transformKeys = { "ADBE Opacity": [2 / 24] };
        eq(keysOf(spec).length, 2);
    });

    it("gives an unkeyed mask two ease keys, not none", function () {
        var keys = keysOf(basic());
        eq(keys.length, 2);
        eq(keys[0].interp["in"], "ease");
        eq(keys[1].interp["out"], "ease");
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
