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
function deepEq(got, want, note) {
    var g = JSON.stringify(got);
    var w = JSON.stringify(want);
    if (g !== w) { fail((note ? note + ": " : "") + g + " !== " + w); }
}
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
        var full = path.join(ROOT, "ae", "lib", file);
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

function pathOfMask(host) {
    return host.comp.layer(1)._masks[0].property("ADBE Mask Shape");
}

function keyFramesOf(prop) {
    var out = [];
    for (var i = 1; i <= prop.numKeys; i++) {
        out[out.length] = Math.round(prop.keyTime(i) * 24);
    }
    return out;
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
        // find one key on it, not one per frame.
        var host = importInto(exported({ mask: {
            featherAt: function () { return [12, 5]; }
        } }));
        var mask = host.comp.layer(1)._masks[0];
        eq(mask.property("ADBE Mask Feather").numKeys, 1);
    });

    it("collapses a straight ramp to the two keys that draw it", function () {
        // Opacity and uniform feather have no sparse layer in the file, so
        // they arrive one value per frame. An artist who ramped opacity
        // authored two keys and should get two back - the line between them
        // lands on every frame the file dropped.
        var host = importInto(exported({ mask: {
            opacityAt: function (t) { return 100 - t * 48; },
            featherAt: function (t) { return [10 + t * 24, 5]; }
        } }));
        var mask = host.comp.layer(1)._masks[0];
        eq(mask.property("ADBE Mask Opacity").numKeys, 2);
        eq(mask.property("ADBE Mask Feather").numKeys, 2);
    });

    it("keeps every attribute sample at tolerance 0", function () {
        // Tolerance 0 is the mode that reproduces the file exactly, so the
        // collapse steps aside: the line through two of these values is
        // arithmetic, not the bit-exact sample the artist asked for. A value
        // that never changes still collapses, because one key is every sample.
        var host = importInto(exported({ mask: {
            opacityAt: function (t) { return 100 - t * 48; },
            featherAt: function () { return [12, 5]; }
        } }), { answers: ["0", "", "0"] });
        var mask = host.comp.layer(1)._masks[0];
        eq(mask.property("ADBE Mask Opacity").numKeys, 5);
        eq(mask.property("ADBE Mask Feather").numKeys, 1);
    });

    it("leaves an attribute the line cannot follow dense", function () {
        // The other half of the rule: a value that curves is still carried
        // frame by frame, because dropping a sample there would change what
        // renders. Same policy the mask path gets from the drift pass.
        var host = importInto(exported({ mask: {
            opacityAt: function (t) { return 100 - 1152 * t * t; }
        } }));
        var prop = host.comp.layer(1)._masks[0].property("ADBE Mask Opacity");
        ok(prop.numKeys > 2, "the curve was flattened to its ends");
        eq(prop.valueAtTime(2 / 24, false), 100 - 1152 * (2 / 24) * (2 / 24));
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

describe("more than one shape", function () {
    /* After Effects invalidates a handle into the mask parade when the parade
     * changes, so a script that adds every mask up front and then writes into
     * what `addProperty` gave it is holding six stale references by the time it
     * writes. Measured in the host 2026-08-21: six shapes failed with "object
     * invalid", the same import restricted to one shape succeeded.
     *
     * Every other import fixture here is single-shape, which is exactly why
     * nothing caught it. */
    function twoShapes() {
        var doc = JSON.parse(exported());
        var second = JSON.parse(JSON.stringify(doc.shapes[0]));
        second.name = "Mask 2";
        doc.shapes[second.name === doc.shapes[0].name ? 0 : 1] = second;
        doc.shapes[1] = second;
        return JSON.stringify(doc);
    }

    it("imports two shapes without touching a stale handle", function () {
        var host = importInto(twoShapes());
        ok(host.comp.numLayers > 0,
           "the import produced nothing: " + host.alerts.join(" | "));
        eq(host.comp.layer(1)._masks.length, 2);
        has(host.alerts, "Imported 2 shape(s)");
    });

    it("builds a path into the FIRST mask, not just the last", function () {
        // A stale first handle is the failure; a run that silently wrote every
        // shape into the last mask would pass a count check and fail this.
        var host = importInto(twoShapes());
        var masks = host.comp.layer(1)._masks;
        for (var i = 0; i < masks.length; i++) {
            ok(masks[i].property("ADBE Mask Shape").numKeys > 0,
               "mask " + i + " got no keys");
        }
    });
});

describe("open splines", function () {
    /* spec/rbj-v2-draft.md. */
    function openMask() {
        return { mask: { pathAt: function (t) {
            var path = movingSquare(t);
            path.closed = false;
            return path;
        } } };
    }

    it("builds a mask path that is still open", function () {
        var host = importInto(exported(openMask()));
        var path = host.comp.layer(1)._masks[0]
                       .property("ADBE Mask Shape").value;
        eq(path.closed, false);
    });

    it("survives an export, an import and an export again", function () {
        var host = importInto(exported(openMask()));
        host.comp.selectedLayers = [host.comp.layer(1)];
        host.savePath = "/tmp/again.rbj";
        host.written = null;
        var second = runExport(host);
        eq(second.shapes[0].closed, false);
        eq(second.version, 2);
    });

    it("warns that the mask will render nothing", function () {
        // After Effects produces no alpha from an open mask path at all, so
        // the geometry arriving exactly is not the same as the mask working.
        var host = importInto(exported(openMask()));
        has(host.alerts, "produces no alpha from an open mask path");
    });

    it("warns whatever application the file came from", function () {
        // This used to be gated on provenance, back when the question was
        // "unverified across applications". It is not a crossing question: an
        // open mask produces no alpha in After Effects whoever wrote the file,
        // including After Effects.
        var text = exported(openMask());
        var doc = JSON.parse(text);
        doc.source.app = "Nuke";
        var fromNuke = importInto(JSON.stringify(doc));
        has(fromNuke.alerts, "produces no alpha from an open mask path");
        var own = importInto(text);
        has(own.alerts, "produces no alpha from an open mask path");
    });

    it("says nothing of the sort about a closed spline", function () {
        var host = importInto(exported());
        for (var i = 0; i < host.alerts.length; i++) {
            ok(host.alerts[i].indexOf("open spline") === -1,
               "warned about a closed shape: " + host.alerts[i]);
        }
    });
});

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

    it("keeps anchored feather where the artist put it", function () {
        // spec/rbj-v2-draft.md section 6, both halves in one process. Under v1
        // the radius-12 anchor would have been dragged to vertex 3 on the way
        // out and would come back there, and the authored zero would be gone
        // entirely - so this is the round trip that could not be written
        // before.
        var r = roundTrip({
            mask: {
                pathAt: function (t) {
                    var sh = movingSquare(t);
                    sh.featherSegLocs = [0, 2, 3, 3];
                    sh.featherRelSegLocs = [0.25, 0.5, 0.0, 0.0];
                    sh.featherRadii = [30, 12, 0, -15];
                    return sh;
                }
            }
        });
        eq(r.first.shapes[0].feather_model, "anchored");
        eq(r.second.shapes[0].feather_model, "anchored");
        eq(r.first.version, 2);
        eq(r.second.version, 2);
        deepEq(r.second.shapes[0].frames["0"].feather_points,
               r.first.shapes[0].frames["0"].feather_points);
        deepEq(r.second.shapes[0].frames["0"].feather_points,
               [{ t: 0.25, feather: 30 }, { t: 2.5, feather: 12 },
                { t: 3, feather: -15 }, { t: 3, feather: 0 }]);
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

    it("selects a shape by its id as well as its name", function () {
        // Ids come from Nuke exports today ("Roto1/Bezier3"); the name is a
        // display label that may collide, the id may not (the validator
        // enforces it), and either is what the file shows the artist.
        var doc = JSON.parse(exported());
        doc.shapes[0].id = "Roto1/Mask 1";
        var text = JSON.stringify(doc);
        var host = importInto(text, { answers: ["0", "Roto1/Mask 1"] });
        eq(host.comp.layer(1)._masks.length, 1,
           "the id did not select the shape: " + host.alerts.join(" | "));
    });

    it("names a requested shape that is not in the file", function () {
        var host = importInto(exported(), { answers: ["0", "Mask 1, Nope"] });
        has(host.alerts, "[subset-missing] shape 'Nope'");
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

    it("converges on a hold its own dense layer contradicts", function () {
        // `held_over_moving_layer.rbj` is the case that made the drift pass's
        // bisection degenerate: `out: hold` at frame 12 over a dense layer that
        // keeps moving 20 px a frame, so the deviation climbs steadily and the
        // worst frame of the held gap is always its last one. Keying there
        // shortens the run by a frame instead of splitting it, and the pass
        // used to walk backwards from frame 23 and give up with 60.0000 px
        // still unaccounted for at frame 15 - which is exactly what the host
        // reported. `core.drift._survey` now adds the gap's midpoint too.
        //
        // The file is not synthetic in the way it looks: an outgoing `hold` is
        // a claim about LAYER space, and `.rbj` keys describe canonical space
        // with the ancestor transform already baked in, so any animated
        // ancestor makes the claim false. See HANDOFF.md.
        var text = fs.readFileSync(path.join(ROOT, "test", "golden",
                                             "held_over_moving_layer.rbj"),
                                   "utf8");
        var host = importInto(text, { workAreaDuration: 25 / 24 });
        has(host.alerts, "3 authored key(s)");
        for (var i = 0; i < host.alerts.length; i++) {
            if (String(host.alerts[i]).indexOf("ran out of passes") > -1) {
                fail("the drift pass gave up: " + host.alerts[i]);
            }
        }
        // And it converges without overshooting. Splitting the gap is what
        // makes it converge; the sweep is what stops it converging above the
        // floor, which here is one key - measured against an exact minimum in
        // test/probe/probe_key_minimality.py. Before the sweep this cost six.
        has(host.alerts, "3 authored key(s), 1 corrective");
        var frames = keyFramesOf(pathOfMask(host));
        deepEq(frames, [0, 12, 13, 24]);
    });

    it("leaves the mask holding exactly the keys the pass kept", function () {
        // The sweep has to apply a trial in order to measure it, so a refused
        // trial leaves the host one key away from the answer. The report is
        // built from what the pass returned, so a host that disagrees with it
        // describes a mask nobody has.
        var text = fs.readFileSync(path.join(ROOT, "test", "golden",
                                             "held_over_moving_layer.rbj"),
                                   "utf8");
        var host = importInto(text, { workAreaDuration: 25 / 24 });
        var report = has(host.alerts, "authored key(s)");
        var counts = /(\d+) authored key\(s\), (\d+) corrective/.exec(report);
        ok(counts !== null, "no key counts in the report: " + report);
        eq(pathOfMask(host).numKeys,
           Number(counts[1]) + Number(counts[2]),
           "the mask does not hold what the report claims");
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

/* --- per-point feather ----------------------------------------------------- */

describe("import per-point feather", function () {
    var LAST = 24;

    function featherDoc(radiusAt) {
        /* Four vertices that never move, so geometry contributes nothing to
         * the deviation and anything the drift pass reacts to is the feather.
         * `radiusAt(frame)` returns the four signed radii. */
        var frames = {};
        for (var f = 0; f <= LAST; f++) {
            var radii = radiusAt(f);
            var pts = [];
            for (var i = 0; i < 4; i++) {
                pts[i] = { "c": [100 + (i === 1 || i === 2 ? 200 : 0),
                                 100 + (i >= 2 ? 200 : 0)],
                           "in": [0, 0], "out": [0, 0], "feather": radii[i] };
            }
            frames[String(f)] = { "opacity": 1.0, "feather_uniform": [0, 0],
                                  "points": pts };
        }
        var sides = { "in": "linear", "out": "linear" };
        return JSON.stringify({
            "format": "rotobridge", "version": 1,
            "source": { "app": "test", "app_version": "1", "width": 1920,
                        "height": 1080, "pixel_aspect": 1, "fps": 24 },
            "range": [0, LAST], "warnings": [],
            "shapes": [{ "name": "feathered", "closed": true, "blend": "union",
                         "feather_model": "per_point",
                         "feather_falloff": "smooth",
                         "frames": frames,
                         "keys": [{ "frame": 0, "interp": sides },
                                  { "frame": LAST, "interp": sides }] }]
        });
    }

    var STATIC = function () { return [30, -15, 0, 12]; };

    function importFeather(radiusAt) {
        return importInto(featherDoc(radiusAt),
                          { workAreaDuration: (LAST + 1) / 24 });
    }

    it("does not chase drift that is only the host's array order", function () {
        // The regression this whole investigation was about. The feather is
        // [30, -15, 0, 12] on all 25 frames and the geometry never moves, so
        // there is nothing for the pass to correct. Comparing `featherRadii`
        // by array index instead of by anchor made it look like 27 px of drift
        // - the host regroups the points by type at an interpolated frame, and
        // 12 - (-15) = 27. It burned every pass and gave up.
        var host = importFeather(STATIC);
        has(host.alerts, "2 authored key(s), 0 corrective");
    });

    it("still measures feather that genuinely drifts", function () {
        // The fix must not simply stop looking at the feather. This bows one
        // radius parabolically between the two keys, which a straight line
        // between them cannot follow, so the pass has to add keys.
        var host = importFeather(function (f) {
            var u = f / LAST;
            return [30 + 40 * u * (1 - u) * 4, -15, 0, 12];
        });
        var report = has(host.alerts, "authored key(s)");
        if (report.indexOf("0 corrective") > -1) {
            fail("feather drift went unmeasured: " + report);
        }
    });

    it("reads the radii back grouped by type between keys", function () {
        // Guards the mock's model of the host rather than the adapters: if this
        // stops reordering, the test above stops proving anything. Measured in
        // After Effects by probe_ae_feather_interpolated.jsx.
        var host = importFeather(STATIC);
        var prop = host.comp.layer(1)._masks[0].property("ADBE Mask Shape");
        var onKey = prop.valueAtTime(0, false).featherRadii;
        var between = prop.valueAtTime(6 / 24, false).featherRadii;
        eq(onKey.join(","), "30,-15,0,12", "the written order, on a key");
        eq(between.join(","), "30,0,12,-15", "regrouped, between keys");
    });

    it("keeps each radius with its own anchor through the reorder", function () {
        // Why the anchor is a safe key and the array index is not: nothing is
        // lost in the reorder, so a comparison that resolves the anchor sees
        // the same four points either way.
        var host = importFeather(STATIC);
        var prop = host.comp.layer(1)._masks[0].property("ADBE Mask Shape");
        var got = prop.valueAtTime(6 / 24, false);
        var seen = {};
        for (var i = 0; i < got.featherRadii.length; i++) {
            var pos = (Number(got.featherSegLocs[i])
                       + Number(got.featherRelSegLocs[i])) % 4;
            seen[pos.toFixed(4)] = Number(got.featherRadii[i]);
        }
        eq(seen["0.0000"], 30, "vertex 0");
        eq(seen["1.0000"], -15, "vertex 1");
        eq(seen["2.0000"], 0, "vertex 2");
        eq(seen["3.0000"], 12, "vertex 3");
    });
});

/* --- anchored feather ----------------------------------------------------- */

describe("import anchored feather", function () {
    // spec/rbj-v2-draft.md section 6. Into After Effects this is the easy
    // direction: the host anchors feather anywhere along a segment, so every
    // entry lands where the file says and nothing is snapped or split. The
    // hard direction is Nuke's, section 6.5.
    var LAST = 4;

    function anchoredDoc(anchors) {
        var frames = {};
        for (var f = 0; f <= LAST; f++) {
            var pts = [];
            for (var i = 0; i < 4; i++) {
                pts[i] = { "c": [100 + (i === 1 || i === 2 ? 200 : 0),
                                 100 + (i >= 2 ? 200 : 0)],
                           "in": [0, 0], "out": [0, 0] };
            }
            frames[String(f)] = { "opacity": 1.0, "feather_uniform": [0, 0],
                                  "points": pts,
                                  "feather_points": anchors };
        }
        var sides = { "in": "linear", "out": "linear" };
        return JSON.stringify({
            "format": "rotobridge", "version": 2,
            "source": { "app": "test", "app_version": "1", "width": 1920,
                        "height": 1080, "pixel_aspect": 1, "fps": 24 },
            "range": [0, LAST], "warnings": [],
            "shapes": [{ "name": "anchored", "closed": true, "blend": "union",
                         "feather_model": "anchored",
                         "feather_falloff": "smooth",
                         "frames": frames,
                         "keys": [{ "frame": 0, "interp": sides },
                                  { "frame": LAST, "interp": sides }] }]
        });
    }

    function anchorsOnHost(host) {
        /* Keyed by seg + rel, which is invariant under the host's rename -
         * the same invariant the file stores and `deviation` compares on. */
        var prop = host.comp.layer(1)._masks[0].property("ADBE Mask Shape");
        var got = prop.valueAtTime(0, false);
        var seen = {};
        for (var i = 0; i < (got.featherRadii || []).length; i++) {
            var pos = (Number(got.featherSegLocs[i])
                       + Number(got.featherRelSegLocs[i])) % 4;
            seen[pos.toFixed(4)] = Number(got.featherRadii[i]);
        }
        return seen;
    }

    it("puts a mid-segment anchor where the file says", function () {
        // Under v1 this arrived at vertex 1, a quarter of a segment away.
        var host = importInto(anchoredDoc([{ t: 0.75, feather: 20 }]),
                              { workAreaDuration: (LAST + 1) / 24 });
        eq(anchorsOnHost(host)["0.7500"], 20);
    });

    it("keeps two anchors that share one vertex", function () {
        // The case v1 could not carry at all: it kept the larger radius and
        // discarded the other, which on the golden scene was an authored zero.
        var host = importInto(anchoredDoc([{ t: 3.0, feather: 0 },
                                           { t: 3.0, feather: 12 }]),
                              { workAreaDuration: (LAST + 1) / 24 });
        var prop = host.comp.layer(1)._masks[0].property("ADBE Mask Shape");
        var got = prop.valueAtTime(0, false);
        eq(got.featherRadii.length, 2);
    });

    it("carries the run 3 shape's anchors intact", function () {
        var host = importInto(anchoredDoc([{ t: 0.25, feather: 30 },
                                           { t: 0.75, feather: -15 },
                                           { t: 2.5, feather: 12 },
                                           { t: 3.0, feather: 0 }]),
                              { workAreaDuration: (LAST + 1) / 24 });
        var seen = anchorsOnHost(host);
        eq(seen["0.2500"], 30);
        eq(seen["0.7500"], -15);
        eq(seen["2.5000"], 12);
        eq(seen["3.0000"], 0);
    });

    it("sets the type from the sign, which cannot be changed later",
       function () {
        var host = importInto(anchoredDoc([{ t: 0.5, feather: 8 },
                                           { t: 1.5, feather: -8 }]),
                              { workAreaDuration: (LAST + 1) / 24 });
        var prop = host.comp.layer(1)._masks[0].property("ADBE Mask Shape");
        var got = prop.valueAtTime(0, false);
        eq(got.featherTypes.join(","), "0,1");
    });

    it("does not invent drift out of an anchored feather layer", function () {
        // The same trap `per_point` fell into: the host reorders its arrays
        // between keys, and a comparison by array index reads that as motion.
        // Nothing here moves, so the pass must find nothing to correct.
        var host = importInto(anchoredDoc([{ t: 0.25, feather: 30 },
                                           { t: 0.75, feather: -15 },
                                           { t: 2.5, feather: 12 }]),
                              { workAreaDuration: (LAST + 1) / 24 });
        has(host.alerts, "0 corrective");
    });

    it("leaves no point carrying feather", function () {
        // Under `anchored` the point layer is empty by definition, and a
        // per_point reading of the same file would have written zeros.
        var host = importInto(anchoredDoc([{ t: 0.5, feather: 8 }]),
                              { workAreaDuration: (LAST + 1) / 24 });
        eq(anchorsOnHost(host)["0.5000"], 8);
        var prop = host.comp.layer(1)._masks[0].property("ADBE Mask Shape");
        eq(prop.valueAtTime(0, false).featherRadii.length, 1,
           "one anchor in the file, one on the host");
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

describe("the import record", function () {
    function recorded(host) {
        var paths = [];
        for (var key in host.appended) {
            if (Object.prototype.hasOwnProperty.call(host.appended, key)) {
                paths[paths.length] = key;
            }
        }
        eq(paths.length, 1, "expected exactly one record file, got "
                            + paths.join(", "));
        return { path: paths[0], text: host.appended[paths[0]] };
    }

    it("writes one beside the .rbj when the project is unsaved", function () {
        var got = recorded(importInto(exported()));
        eq(got.path, "/tmp/in.rotobridge.txt");
        ok(got.text.indexOf(RB.report.RULE + "\nRotoBridge import record") === 0,
           "the record opens with its own rule and header");
        has([got.text], "Mask 1");
        has([got.text], "After Effects 25.6x101");
        has([got.text], "/tmp/in.rbj");
    });

    it("writes it beside the project once there is one", function () {
        // Where it belongs: the record is about the comp holding the masks,
        // and someone opening that comp should not have to know where the
        // .rbj came from to find out what happened.
        var got = recorded(importInto(exported(),
                                      { projectFile: "/shots/ab_010_v012.aep" }));
        eq(got.path, "/shots/ab_010_v012.rotobridge.txt");
    });

    it("names the record in the report alert", function () {
        var host = importInto(exported());
        has(host.alerts, "recorded in /tmp/in.rotobridge.txt");
    });

    it("carries what the drift pass measured", function () {
        var got = recorded(importInto(exported()));
        has([got.text], "1 shape(s):");
        // This fixture's feather is uniform, which lives in the dense layer
        // and not on a point, so the model really is `none`.
        has([got.text], "Mask 1: feather none, 4 point(s), 2 authored key(s),"
                        + " 0 corrective; nothing drifted from the file");
        has([got.text], "tolerance      0.5 px");
    });

    it("says so when nothing was lost, in both directions", function () {
        var got = recorded(importInto(exported()));
        has([got.text], "no warnings recorded when the file was written");
        has([got.text], "no warnings from this import");
    });

    it("does not erase the record of an earlier import", function () {
        // The second import into a comp is not entitled to erase the evidence
        // of the first, which is the whole difference between `"a"` and `"w"`.
        var spec = emptyComp();
        spec.readable = exported();
        var host = mock.install(spec);
        runImport(host);
        runImport(host);
        var text = host.appended["/tmp/in.rotobridge.txt"];
        eq(text.split("RotoBridge import record").length - 1, 2);
    });

    it("survives a folder it cannot write to", function () {
        // The masks are in the comp by the time the record is written. Losing
        // the import over a read-only folder would be a worse failure than the
        // one being reported.
        var host = importInto(exported(), { recordFails: true });
        eq(host.comp.layer(1)._masks.length, 1, "the masks still landed");
        has(host.alerts, "could not be written");
        for (var i = 0; i < host.alerts.length; i++) {
            ok(String(host.alerts[i]).indexOf("recorded in") < 0,
               "no record was claimed");
        }
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
