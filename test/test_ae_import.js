/*
 * The After Effects importer, run under node against a mock host, and the
 * round trip through both adapters.
 *
 * The round trip is the point. `test/test_nuke_roundtrip.py` is the Nuke side's
 * acceptance test and needs a licence; this is the part of the same idea that
 * can be had without one - export a comp, import the file back, export again,
 * and compare the two files. Everything that survives that is a path where the
 * two conversions are genuine inverses.
 *
 * What it cannot establish is anything resting on how After Effects interpolates
 * between keys, because `test/ae_mock.js` deliberately refuses to guess at that
 * (it throws rather than invent a value). Every frame is keyed on the dense
 * path, so nothing here needs it - but the drift pass will, and that is a
 * measurement for the host, not for this file.
 *
 * Run:  node test/test_ae_import.js
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
        if (String(haystack[i]).indexOf(needle) > -1) { return haystack[i]; }
    }
    fail((note ? note + ": " : "") + "no entry containing " + JSON.stringify(needle)
         + " in:\n      " + haystack.join("\n      "));
}

/* --- loading ------------------------------------------------------------ */

function source(name) {
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

function run(script, host) {
    delete global.RB;
    vm.runInThisContext(source(script), { filename: script });
    return host;
}

function runImport(host) { return run("rotobridge_import.jsx", host); }
function runExport(host) {
    run("rotobridge_export.jsx", host);
    return host.written === null ? null : JSON.parse(host.written);
}

/* --- fixtures ------------------------------------------------------------ */

var SQUARE = {
    vertices: [[100, 100], [300, 100], [300, 250], [100, 250]],
    inTangents: [[-10, 0], [-10, 5], [10, 0], [10, -5]],
    outTangents: [[10, 0], [10, -5], [-10, 0], [-10, 5]]
};

function movingSquare(t) {
    var dx = t * 100;
    return mock.makeShape({
        vertices: SQUARE.vertices.map(function (v) { return [v[0] + dx, v[1]]; }),
        inTangents: SQUARE.inTangents,
        outTangents: SQUARE.outTangents
    });
}

var KEY_TIMES = [0, 4 / 24];

function keyed(maskSpec) {
    /* Two LINEAR path keys, at the ends of the work area. That is what an
     * artist actually authors, and it is what the mock can interpolate between
     * - probe run 6 section H measured AE's linear mask-path interpolation, and
     * `ae_mock` reproduces only that. The fixture's motion is linear in time,
     * so the frames between the two keys read exactly as `pathAt` would have. */
    var seed = [];
    for (var i = 0; i < KEY_TIMES.length; i++) {
        seed[i] = { t: KEY_TIMES[i], value: maskSpec.pathAt(KEY_TIMES[i]) };
    }
    maskSpec.pathKeys = seed;
    return maskSpec;
}

function sourceComp(over) {
    var maskSpec = {
        name: "Mask 1",
        pathAt: movingSquare,
        opacityAt: function (t) { return 100 - t * 48; },
        featherAt: function (t) { return [10 + t * 24, 5]; }
    };
    var spec = {
        frameRate: 24,
        workAreaStart: 0,
        workAreaDuration: 5 / 24,
        layers: [{ name: "Solid 1", masks: [maskSpec] }]
    };
    if (over) {
        for (var k in over) {
            if (k === "mask") {
                for (var mk in over.mask) { maskSpec[mk] = over.mask[mk]; }
            } else if (k === "layer") {
                for (var lk in over.layer) { spec.layers[0][lk] = over.layer[lk]; }
            } else { spec[k] = over[k]; }
        }
    }
    keyed(maskSpec);
    return spec;
}

function exported(over) {
    /* A .rbj written by the exporter, as text - the only kind of input the
     * importer is ever asked to read in anger. */
    var host = mock.install(sourceComp(over));
    runExport(host);
    if (host.written === null) {
        fail("the fixture export produced nothing: " + host.alerts.join(" | "));
    }
    return host.written;
}

function emptyComp(over) {
    var spec = {
        frameRate: 24,
        workAreaStart: 0,
        workAreaDuration: 5 / 24,
        layers: [],
        selected: []
    };
    for (var k in (over || {})) { spec[k] = over[k]; }
    return spec;
}

function importInto(text, over) {
    var spec = emptyComp(over);
    spec.readable = text;
    var host = mock.install(spec);
    runImport(host);
    return host;
}

/* --- building masks ------------------------------------------------------- */

describe("import", function () {
    it("creates a solid and a mask when nothing is selected", function () {
        var host = importInto(exported());
        eq(host.alerts.length, 1, "expected the report alert: "
                                  + host.alerts.join(" | "));
        has(host.alerts, "Imported 1 shape(s)");
        eq(host.comp.numLayers, 1);
        eq(host.comp.layer(1).name, "RotoBridge");
        eq(host.comp.layer(1)._masks.length, 1);
    });

    it("names the mask from the file", function () {
        var host = importInto(exported());
        eq(host.comp.layer(1)._masks[0].name, "Mask 1");
    });

    it("keys only the frames the file authored", function () {
        // The fixture is keyed at both ends and moves linearly between them, so
        // the drift pass finds nothing to pin and 41 frames of dense layer come
        // back as the two keys an artist can actually edit.
        var host = importInto(exported());
        var mask = host.comp.layer(1)._masks[0];
        eq(mask.property("ADBE Mask Shape").numKeys, 2);
        has(host.alerts, "2 authored key(s), 0 corrective");
    });

    it("collapses an attribute that never changes to one key", function () {
        // An artist opening a shape whose feather was never animated should
        // find one key on it, not one per frame. Opacity moves in this fixture
        // and stays dense; feather y does not.
        var host = importInto(exported({ mask: {
            opacityAt: function (t) { return 100 - t * 48; },
            featherAt: function () { return [12, 5]; }
        } }));
        var mask = host.comp.layer(1)._masks[0];
        eq(mask.property("ADBE Mask Opacity").numKeys, 5);
        eq(mask.property("ADBE Mask Feather").numKeys, 1);
    });

    it("sets a corrective key linear rather than leaving the host default", function () {
        // A bezier key left at the default eases in sub-frame space, which
        // shows up under motion blur and on a retime. Tolerance 0 keys every
        // frame, so every key past the two authored ones is corrective.
        var host = importInto(exported(), { answers: ["0", "", "0"] });
        var prop = host.comp.layer(1)._masks[0].property("ADBE Mask Shape");
        eq(prop.numKeys, 5);
        for (var i = 1; i <= prop.numKeys; i++) {
            eq(prop.keyInInterpolationType(i), 6612, "key " + i + " in");
            eq(prop.keyOutInterpolationType(i), 6612, "key " + i + " out");
        }
    });

    it("adds masks to a selected layer instead of making a solid", function () {
        var spec = emptyComp();
        spec.layers = [{ name: "Plate", masks: [] }];
        spec.selected = [0];
        spec.readable = exported();
        var host = mock.install(spec);
        runImport(host);
        eq(host.comp.numLayers, 1, "no solid should have been created");
        eq(host.comp.layer(1)._masks.length, 1);
    });

    it("refuses an ambiguous multi-layer selection", function () {
        var spec = emptyComp();
        spec.layers = [{ name: "A", masks: [] }, { name: "B", masks: [] }];
        spec.selected = [0, 1];
        spec.readable = exported();
        var host = mock.install(spec);
        runImport(host);
        has(host.alerts, "select one layer");
    });

    it("puts the playhead back", function () {
        var host = mock.install((function () {
            var s = emptyComp();
            s.readable = exported();
            return s;
        }()));
        host.comp.time = 0.25;
        runImport(host);
        eq(host.comp.time, 0.25);
    });

    it("does nothing when the open dialog is cancelled", function () {
        var spec = emptyComp();
        spec.openPath = null;
        var host = mock.install(spec);
        runImport(host);
        eq(host.alerts.length, 0);
        eq(host.comp.numLayers, 0);
    });
});

/* --- the round trip -------------------------------------------------------- */

describe("round trip", function () {
    function roundTrip(over) {
        var first = exported(over);
        var host = importInto(first);
        ok(host.comp.numLayers > 0,
           "the import produced nothing: " + host.alerts.join(" | "));
        /* Export the comp the import just built. Its work area already matches,
         * and its one layer is selected by default because `selected` is
         * unset - the mock selects everything, as an artist with no selection
         * would get. */
        host.comp.selectedLayers = [host.comp.layer(1)];
        host.savePath = "/tmp/again.rbj";
        host.written = null;
        var second = runExport(host);
        return { first: JSON.parse(first), second: second };
    }

    it("returns every vertex to where it started", function () {
        var r = roundTrip();
        var a = r.first.shapes[0].frames;
        var b = r.second.shapes[0].frames;
        var worst = 0;
        for (var key in a) {
            if (!Object.prototype.hasOwnProperty.call(a, key)) { continue; }
            var pa = a[key].points;
            var pb = b[key].points;
            eq(pb.length, pa.length, "vertex count at frame " + key);
            for (var i = 0; i < pa.length; i++) {
                var members = ["c", "in", "out"];
                for (var m = 0; m < members.length; m++) {
                    var d = Math.sqrt(
                        Math.pow(pa[i][members[m]][0] - pb[i][members[m]][0], 2) +
                        Math.pow(pa[i][members[m]][1] - pb[i][members[m]][1], 2));
                    if (d > worst) { worst = d; }
                }
            }
        }
        ok(worst < 1e-9, "worst deviation " + worst + " px");
    });

    it("returns opacity and uniform feather unchanged", function () {
        var r = roundTrip();
        var a = r.first.shapes[0].frames;
        var b = r.second.shapes[0].frames;
        for (var key in a) {
            if (!Object.prototype.hasOwnProperty.call(a, key)) { continue; }
            near(b[key].opacity, a[key].opacity, 9, "opacity at " + key);
            near(b[key].feather_uniform[0], a[key].feather_uniform[0], 9,
                 "feather x at " + key);
            near(b[key].feather_uniform[1], a[key].feather_uniform[1], 9,
                 "feather y at " + key);
        }
    });

    it("keeps the shape name, blend and falloff", function () {
        var r = roundTrip({ mask: { maskMode: 6814, falloff: 7212 } });
        eq(r.second.shapes[0].name, r.first.shapes[0].name);
        eq(r.first.shapes[0].blend, "difference");
        eq(r.second.shapes[0].blend, "difference");
        eq(r.second.shapes[0].feather_falloff, "smooth");
    });

    it("keeps per-point feather, signs included", function () {
        var r = roundTrip({
            mask: {
                pathAt: function (t) {
                    var s = movingSquare(t);
                    s.featherSegLocs = [0, 2];
                    s.featherRelSegLocs = [0.0, 0.0];
                    s.featherRadii = [30, -15];
                    return s;
                }
            }
        });
        eq(r.first.shapes[0].feather_model, "per_point");
        eq(r.second.shapes[0].feather_model, "per_point");
        var pts = r.second.shapes[0].frames["0"].points;
        eq(pts[0].feather, 30);
        eq(pts[2].feather, -15);
        eq(pts[1].feather, 0);
    });

    it("survives a transformed source layer", function () {
        // The export goes layer -> comp and the import comes back comp ->
        // layer. If either affine were wrong the geometry would land somewhere
        // else, and only a non-identity transform can show it.
        var r = roundTrip({
            layer: {
                transform: { anchor: [960, 540], scale: [1.5, 2.2],
                             rotation: 30, position: [700, 400] }
            }
        });
        var a = r.first.shapes[0].frames["3"].points[1];
        var b = r.second.shapes[0].frames["3"].points[1];
        near(b["c"][0], a["c"][0], 6);
        near(b["c"][1], a["c"][1], 6);
        near(b["out"][0], a["out"][0], 6);
        near(b["out"][1], a["out"][1], 6);
    });

    it("carries the whole file through unchanged", function () {
        // Everything above, in one assertion, on the members that must be
        // byte-stable. `source` and `warnings` legitimately differ - the second
        // file was written from a different comp.
        var r = roundTrip();
        eq(JSON.stringify(r.second.range), JSON.stringify(r.first.range));
        eq(JSON.stringify(r.second.shapes), JSON.stringify(r.first.shapes));
    });
});

/* --- offset, subset and mismatch -------------------------------------------- */

describe("options", function () {
    it("offsets every frame to the requested start", function () {
        var host = importInto(exported(), { answers: ["100", "", "0"] });
        var prop = host.comp.layer(1)._masks[0].property("ADBE Mask Shape");
        eq(prop.numKeys, 5);
        near(prop.keyTime(1), 100 / 24, 9);
        near(prop.keyTime(5), 104 / 24, 9);
        has(host.alerts, "frames 100 to 104");
    });

    it("imports only the named shapes", function () {
        var spec = sourceComp();
        spec.layers[0].masks.push(keyed({ name: "Mask 2",
                                          pathAt: movingSquare }));
        var eh = mock.install(spec);
        runExport(eh);
        var host = importInto(eh.written, { answers: ["0", "Mask 2"] });
        eq(host.comp.layer(1)._masks.length, 1);
        eq(host.comp.layer(1)._masks[0].name, "Mask 2");
    });

    it("names a requested shape that is not in the file", function () {
        var host = importInto(exported(), { answers: ["0", "Mask 1, Nope"] });
        has(host.alerts, "no shape named 'Nope'");
        eq(host.comp.layer(1)._masks.length, 1);
    });

    it("fails when no requested name matches", function () {
        var host = importInto(exported(), { answers: ["0", "Nope"] });
        has(host.alerts, "none of the requested shape names");
    });

    it("warns about a comp size mismatch rather than rescaling", function () {
        var host = importInto(exported(), { width: 1280, height: 720 });
        has(host.alerts, "not rescaled");
    });

    it("warns about a frame rate mismatch", function () {
        var host = importInto(exported(), { frameRate: 25 });
        has(host.alerts, "fps");
    });

    it("honours a real Nuke export's sparse layer", function () {
        // `sparse.rbj` is a genuine Nuke export: one shape keyed on 5 frames of
        // 41. Those 5 keys are what an artist gets back, plus whatever the
        // drift pass had to pin - which is the whole point of the sparse path.
        var text = fs.readFileSync(path.join(ROOT, "test", "golden",
                                             "sparse.rbj"), "utf8");
        var host = importInto(text, { workAreaDuration: 60 / 24 });
        var prop = host.comp.layer(1)._masks[0].property("ADBE Mask Shape");
        ok(prop.numKeys >= 5 && prop.numKeys < 41,
           "expected a sparse result, got " + prop.numKeys + " keys");
        has(host.alerts, "5 authored key(s)");
    });

    it("reports the warnings the exporter recorded in the file", function () {
        var host = importInto(exported({ mask: { inverted: true } }));
        has(host.alerts, "when the file was written");
        has(host.alerts, "inverted flag");
    });

    it("rejects a file that is not valid .rbj", function () {
        var host = importInto('{"format": "nope"}');
        has(host.alerts, "expected \"rotobridge\"");
    });
});

/* --- the sparse layer and the drift pass ----------------------------------- */

describe("import keys", function () {
    var LINEAR = 6612, BEZIER = 6613, HOLD = 6614;

    var LAST = 24;

    function curvedDoc(keys, span, last) {
        /* A hand-built document, not an export: the point is a dense layer that
         * curves under a sparse layer that says `linear`, which is exactly what
         * a foreign exporter's tier-2 output looks like and is the only shape
         * of file that gives the drift pass anything to do. It is also how
         * `test/test_nuke_roundtrip.py` exercises the same pass on the Nuke
         * side, for the same reason.
         *
         * The parabola is in x. `span` scales how far it bows away from the
         * chord, so a test can choose a deviation the pass must find. */
        span = span === undefined ? 6 : span;
        last = last === undefined ? LAST : last;
        var frames = {};
        for (var f = 0; f <= last; f++) {
            var u = f / last;
            var bow = span * u * (1 - u) * 4;
            var pts = [];
            for (var i = 0; i < 3; i++) {
                pts[i] = { "c": [100 + i * 50 + bow, 200 + i * 30],
                           "in": [-10, 0], "out": [10, 0] };
            }
            frames[String(f)] = { "opacity": 1.0, "feather_uniform": [0, 0],
                                  "points": pts };
        }
        return JSON.stringify({
            "format": "rotobridge", "version": 1,
            "source": { "app": "test", "app_version": "1", "width": 1920,
                        "height": 1080, "pixel_aspect": 1, "fps": 24 },
            "range": [0, last], "warnings": [],
            "shapes": [{ "name": "bowed", "closed": true, "blend": "union",
                         "feather_model": "none", "feather_falloff": "linear",
                         "frames": frames, "keys": keys }]
        });
    }

    function straightKeys(last) {
        last = last === undefined ? LAST : last;
        return [{ "frame": 0, "interp": { "in": "linear", "out": "linear" } },
                { "frame": last, "interp": { "in": "linear", "out": "linear" } }];
    }

    function pathOf(host) {
        return host.comp.layer(1)._masks[0].property("ADBE Mask Shape");
    }

    function importedWith(text, tolerance) {
        return importInto(text, { answers: ["0", "", String(tolerance)],
                                  workAreaDuration: (LAST + 1) / 24 });
    }

    it("adds corrective keys where the host leaves the dense layer", function () {
        // Two straight keys over a curve that bows 40 px. Nothing about the
        // authored keys is wrong - they are what the file says - so the only
        // thing that can hold the geometry is tier 3.
        var host = importedWith(curvedDoc(straightKeys()), 0.5);
        var prop = pathOf(host);
        ok(prop.numKeys > 2, "the pass added nothing");
        ok(prop.numKeys < LAST + 1,
           "the pass keyed everything: " + prop.numKeys);
        has(host.alerts, "2 authored key(s), " + (prop.numKeys - 2)
                         + " corrective");
    });

    it("leaves the authored keys exactly where the file put them", function () {
        // Spec section 10.4: authored keys always survive verbatim. A pass that
        // moved one would be editing the artist's animation, not correcting it.
        var host = importedWith(curvedDoc(straightKeys()), 0.5);
        var prop = pathOf(host);
        var seen = {};
        for (var i = 1; i <= prop.numKeys; i++) {
            seen[Math.round(prop.keyTime(i) * 24)] = true;
        }
        ok(seen[0] && seen[LAST], "an authored key went missing");
    });

    it("gets under the tolerance it was given", function () {
        var host = importedWith(curvedDoc(straightKeys()), 0.5);
        var prop = pathOf(host);
        var target = JSON.parse(curvedDoc(straightKeys())).shapes[0].frames;
        var worst = 0;
        for (var f = 0; f <= LAST; f++) {
            var got = prop.valueAtTime(f / 24, false);
            var want = target[String(f)].points;
            for (var i = 0; i < want.length; i++) {
                // The comp is 1080 tall and the target layer is a fresh solid
                // with an identity transform, so canonical y maps straight back.
                var d = Math.abs(got.vertices[i][0] - want[i]["c"][0]);
                if (d > worst) { worst = d; }
            }
        }
        ok(worst <= 0.5, "worst residual " + worst + " px");
    });

    it("keys nothing extra when the file already fits", function () {
        // The same two keys over a dense layer that really is straight. A pass
        // that added keys here would be manufacturing work.
        var host = importedWith(curvedDoc(straightKeys(), 0), 0.5);
        eq(pathOf(host).numKeys, 2);
        has(host.alerts, "0 corrective");
    });

    it("keys every frame at tolerance 0", function () {
        var host = importedWith(curvedDoc(straightKeys()), 0);
        eq(pathOf(host).numKeys, LAST + 1);
    });

    it("keys only what the file authored at tolerance inf", function () {
        var host = importedWith(curvedDoc(straightKeys()), "inf");
        eq(pathOf(host).numKeys, 2);
    });

    it("says so when it runs out of passes", function () {
        // The pass bisects, so eight of them reach at most 257 keys. On a
        // 601-frame range that leaves gaps, and a tolerance of 1e-9 px means
        // every one of them still counts. The alternative to warning here is a
        // shape that is quietly wrong.
        var host = importInto(curvedDoc(straightKeys(600), 6, 600),
                              { answers: ["0", "", "1e-9"] });
        has(host.alerts, "ran out of passes");
    });

    it("rejects a tolerance that is not a number", function () {
        var host = importedWith(curvedDoc(straightKeys()), "soonish");
        has(host.alerts, "not a drift tolerance");
    });

    it("sets each authored side to the type the file asked for", function () {
        var keys = [{ "frame": 0, "interp": { "in": "linear", "out": "hold" } },
                    { "frame": LAST, "interp": { "in": "ease", "out": "linear" } }];
        var prop = pathOf(importedWith(curvedDoc(keys, 0), "inf"));
        eq(prop.keyInInterpolationType(1), LINEAR);
        eq(prop.keyOutInterpolationType(1), HOLD);
        eq(prop.keyInInterpolationType(2), BEZIER);
        eq(prop.keyOutInterpolationType(2), LINEAR);
    });

    it("puts the ease back into the host's own units", function () {
        var keys = [{ "frame": 0, "interp": { "in": "linear", "out": "ease" },
                      "ease": { "out": [0.91176, 2.5] } },
                    { "frame": LAST, "interp": { "in": "linear", "out": "linear" } }];
        var prop = pathOf(importedWith(curvedDoc(keys, 0), "inf"));
        near(prop.keyOutTemporalEase(1)[0].influence, 91.176, 3);
        near(prop.keyOutTemporalEase(1)[0].speed, 2.5, 9);
    });

    it("keeps a hold side from being smoothed by the ease it sets", function () {
        // `setTemporalEaseAtKey` forces the key to BEZIER, so the adapter has
        // to set the ease first and the types after. The other order leaves a
        // hold side rendering smooth, which is a wrong matte, not a wrong knob.
        var keys = [{ "frame": 0, "interp": { "in": "ease", "out": "hold" },
                      "ease": { "in": [0.5, 0] } },
                    { "frame": LAST, "interp": { "in": "linear", "out": "linear" } }];
        var prop = pathOf(importedWith(curvedDoc(keys, 0), "inf"));
        eq(prop.keyOutInterpolationType(1), HOLD);
        near(prop.keyInTemporalEase(1)[0].influence, 50, 9);
    });

    it("clamps an influence of zero to what the host will accept", function () {
        // Spec section 10.3 bounds the stored fraction at 0.0, and After
        // Effects raises below 0.1%. Degrading beats throwing on a legal file.
        var keys = [{ "frame": 0, "interp": { "in": "linear", "out": "ease" },
                      "ease": { "out": [0.0, 0] } },
                    { "frame": LAST, "interp": { "in": "linear", "out": "linear" } }];
        var prop = pathOf(importedWith(curvedDoc(keys, 0), "inf"));
        near(prop.keyOutTemporalEase(1)[0].influence, 0.1, 9);
    });

    it("gives a bare ease side the host's own default influence", function () {
        // A side that is `ease` with no parameters is spec section 10.3's
        // "smooth, parameters unknown" - which is every eased key a Nuke source
        // produces, so it is the common case, not the odd one.
        var keys = [{ "frame": 0, "interp": { "in": "linear", "out": "ease" } },
                    { "frame": LAST, "interp": { "in": "linear", "out": "linear" } }];
        var prop = pathOf(importedWith(curvedDoc(keys, 0), "inf"));
        near(prop.keyOutTemporalEase(1)[0].influence, 16.667, 3);
    });

    it("does not ask about tolerance when the file is dense", function () {
        // A dense document keys every frame whatever the answer is, and a
        // question whose answer changes nothing is worse than no question.
        var text = curvedDoc(null);
        var doc = JSON.parse(text);
        delete doc.shapes[0].keys;
        var host = importInto(JSON.stringify(doc));
        eq(pathOf(host).numKeys, LAST + 1);
        for (var i = 0; i < host.prompts.length; i++) {
            ok(String(host.prompts[i]).indexOf("tolerance") === -1,
               "it asked anyway: " + host.prompts[i]);
        }
    });

    it("does nothing when the tolerance prompt is cancelled", function () {
        var spec = emptyComp();
        spec.readable = curvedDoc(straightKeys());
        spec.answers = ["0", "", null];
        var host = mock.install(spec);
        runImport(host);
        eq(host.alerts.length, 0);
        eq(host.comp.numLayers, 0);
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
