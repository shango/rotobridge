/*
 * Nuke's own files, through the After Effects adapters, with neither
 * application present.
 *
 * Every other round trip in this project is same-app: Nuke out and back in
 * (`test/test_nuke_roundtrip.py`), or After Effects out and back in
 * (`test/test_ae_import.js`). A same-app round trip cannot see an error it
 * makes in both directions. If canonical space were Y-down instead of Y-up, or
 * feather's sign were inverted, or ease were stored a factor of 100 out, each
 * side would still return exactly what it was given - which is the same reason
 * Nuke to Nuke does not drift.
 *
 * This is the crossing itself, which is what Phase 5 measures in pixels. What
 * can be had without a host is the file: read a .rbj that Nuke really wrote,
 * build the masks in the mock, export them back out, and compare the two
 * documents. Everything that survives is a place where the two applications'
 * conventions genuinely agree rather than cancel.
 *
 * It is not a substitute for Phase 5. `test/ae_mock.js` answers the After
 * Effects API but is not After Effects, and nothing here renders a pixel. What
 * it does establish is that if Phase 5 finds a mismatch, the mismatch is in the
 * host and not in the conversion - or, if one of these fails first, the other
 * way round.
 *
 * Run:  node test/test_ae_crossapp.js
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

/* --- the crossing --------------------------------------------------------- */

function golden(name) {
    return fs.readFileSync(path.join(ROOT, "test", "golden", name + ".rbj"),
                           "utf8");
}

function cross(name, tolerance) {
    /* Import a real Nuke file into an empty comp built to match it, then export
     * the result straight back out. The comp is the one an artist would set up
     * to receive the file: same size, same rate, same frame numbering, so
     * nothing here is testing the mismatch warnings - those are the import
     * suite's. */
    var text = golden(name);
    var doc = JSON.parse(text);
    var src = doc.source;
    var first = doc.range[0], last = doc.range[1];

    var host = mock.install({
        width: src.width,
        height: src.height,
        pixelAspect: src.pixel_aspect,
        frameRate: src.fps,
        displayStartTime: first / src.fps,
        workAreaStart: 0,
        workAreaDuration: (last - first + 1) / src.fps,
        layers: [],
        selected: [],
        readable: text,
        // start frame, shape subset, drift tolerance
        answers: [String(first), "", String(tolerance)]
    });

    run("rotobridge_import.jsx", host);
    var imported = host.alerts.slice(0);
    if (host.comp.numLayers === 0) {
        fail("the import built nothing: " + imported.join(" | "));
    }

    host.alerts = [];
    host.written = null;
    run("rotobridge_export.jsx", host);
    if (host.written === null) {
        fail("the re-export produced nothing: " + host.alerts.join(" | "));
    }

    return { doc: doc, out: JSON.parse(host.written), host: host,
             imported: imported, exported: host.alerts.slice(0) };
}

function worst(before, after, pick) {
    /* The largest deviation `pick` reports over every frame of the first shape,
     * as {d, where} so a failure names the frame rather than just a number. */
    var a = before.shapes[0], b = after.shapes[0];
    var out = { d: 0, where: "nowhere" };
    for (var f = before.range[0]; f <= before.range[1]; f++) {
        var fa = a.frames[String(f)], fb = b.frames[String(f)];
        if (!fb) { fail("the re-export dropped frame " + f); }
        pick(fa, fb, function (d, what) {
            if (d > out.d) { out.d = d; out.where = what + " at frame " + f; }
        });
    }
    return out;
}

function geometry(fa, fb, note) {
    var parts = ["c", "in", "out"];
    for (var p = 0; p < fa.points.length; p++) {
        for (var k = 0; k < parts.length; k++) {
            for (var j = 0; j < 2; j++) {
                note(Math.abs(fa.points[p][parts[k]][j]
                              - fb.points[p][parts[k]][j]),
                     "point " + p + " " + parts[k] + "[" + j + "]");
            }
        }
    }
}

function feather(fa, fb, note) {
    for (var p = 0; p < fa.points.length; p++) {
        note(Math.abs(fa.points[p].feather - fb.points[p].feather),
             "point " + p + " feather");
    }
}

function attributes(fa, fb, note) {
    note(Math.abs(fa.opacity - fb.opacity), "opacity");
    for (var i = 0; i < 2; i++) {
        note(Math.abs(fa.feather_uniform[i] - fb.feather_uniform[i]),
             "feather_uniform[" + i + "]");
    }
}

function keyFrames(doc) {
    var out = [];
    var keys = doc.shapes[0].keys;
    for (var i = 0; i < keys.length; i++) { out[i] = keys[i].frame; }
    return out;
}

/* --- dense ---------------------------------------------------------------- */

describe("a dense Nuke file through the AE adapters", function () {
    /* `roundtrip.rbj` is a real Nuke export carrying every v1 field: a keyed
     * bezier with a baked non-identity transform, per-point feather including a
     * deliberately off-normal point, animated opacity and animated uniform
     * feather. Tolerance 0 because the question here is the conversion, not the
     * drift pass - every frame is keyed, so nothing is interpolated and any
     * deviation is arithmetic. */
    var trip = cross("roundtrip", 0);

    it("crosses with no geometric loss at all", function () {
        var w = worst(trip.doc, trip.out, geometry);
        eq(w.d, 0, "exact, but deviated by " + w.d + " at " + w.where);
    });

    it("crosses with no loss in the per-frame attributes", function () {
        var w = worst(trip.doc, trip.out, attributes);
        eq(w.d, 0, "exact, but deviated by " + w.d + " at " + w.where);
    });

    it("crosses with no loss in per-point feather", function () {
        // Signed, and the sign is the direction: a magnitude taken anywhere in
        // the pipeline would flip this file's inward points outward.
        var w = worst(trip.doc, trip.out, feather);
        eq(w.d, 0, "exact, but deviated by " + w.d + " at " + w.where);
    });

    it("carries the shape's own attributes across", function () {
        var a = trip.doc.shapes[0], b = trip.out.shapes[0];
        eq(b.name, a.name);
        eq(b.closed, a.closed);
        eq(b.blend, a.blend);
        eq(b.feather_model, a.feather_model);
        // The one mapping still resting on a guess is Nuke's half of this, and
        // that guess is not exercised here: the file already says `smooth`.
        eq(b.feather_falloff, a.feather_falloff);
        eq(String(trip.out.range), String(trip.doc.range));
    });

    it("drops feather_offset and nothing else", function () {
        /* The documented loss, and the only one. Nuke's feather centre carries
         * a tangential component that a signed scalar cannot express; the file
         * says so in its own warnings, and After Effects has nowhere to put it.
         * Everything else in a point survives, which is what makes this a
         * single known omission rather than a lossy crossing. */
        var a = trip.doc.shapes[0].frames["1001"].points;
        var b = trip.out.shapes[0].frames["1001"].points;
        var carried = 0;
        for (var p = 0; p < a.length; p++) {
            if (a[p].feather_offset !== undefined) { carried += 1; }
            ok(b[p].feather_offset === undefined,
               "point " + p + " came back with a feather_offset");
            for (var k in a[p]) {
                if (k === "feather_offset") { continue; }
                ok(b[p][k] !== undefined, "point " + p + " lost " + k);
            }
            for (var j in b[p]) {
                ok(a[p][j] !== undefined, "point " + p + " gained " + j);
            }
        }
        ok(carried > 0, "the fixture no longer carries a feather_offset");
    });

    it("puts the mask in After Effects' space, not the file's", function () {
        /* The assertion the round trip cannot make, because it undoes it.
         * Canonical space is Nuke's - origin bottom left, Y up - and this file
         * puts its first vertex at y 365 in a 1556-high comp. After Effects
         * counts down from the top, so the mask really has to sit at 1191 for
         * the crossing to mean anything. */
        var mask = trip.host.comp.layer(1)._masks[0];
        // Frame 1001 is comp time zero: the comp's displayStartTime is what
        // makes the timeline read 1001 there, exactly as the artist's would.
        var shape = mask.property("ADBE Mask Shape").valueAtTime(0, false);
        eq(shape.vertices[0][0], 720, "x is untouched");
        eq(shape.vertices[0][1], 1556 - 365, "y is flipped about the height");
    });

    it("no longer hands a bare ease back as a curve nobody drew", function () {
        /* This used to be the one thing the crossing changed, and it was the
         * honest reading at the time: Nuke writes `ease` with no parameters -
         * spec section 10.3's "smooth, parameters unknown" - the AE importer
         * has to put some real curve on the key, so it used AE's own default,
         * and exporting that back wrote influence 16.667 into the file. A file
         * that crossed twice was no longer parameterless.
         *
         * The export conform ends that. Nothing it writes carries an `ease`
         * block at all, so a parameterless key stays parameterless, and the
         * curve the destination draws is the one the fit measured rather than
         * a default that arrived by accident. */
        var keys = trip.out.shapes[0].keys;
        for (var i = 0; i < keys.length; i++) {
            eq(keys[i].interp["in"], "linear", "key " + i);
            eq(RB.util.hasOwn(keys[i], "ease"), false, "key " + i);
        }
    });

    it("says nothing on either leg but its report and the file's warning",
       function () {
        // One alert each way. The import folds its report and the file's
        // recorded warnings into a single message rather than stacking dialogs.
        eq(trip.imported.length, 1, trip.imported.join(" | "));
        has(trip.imported, "Imported 1 shape(s)");
        has(trip.imported, "feather offsets depart from the path normal");
        eq(trip.exported.length, 1, trip.exported.join(" | "));
        has(trip.exported, "Exported 1 shape(s)");
    });
});

/* --- sparse --------------------------------------------------------------- */

describe("a sparse Nuke file through the AE adapters", function () {
    /* `sparse.rbj` is the same shape keyed on 5 frames of 41, all linear. This
     * is the crossing an artist actually wants: the keys they authored in Nuke
     * arriving as keys they can drag in After Effects. */
    var trip = cross("sparse", 0.5);

    it("brings the artist's own key frames back, and no others", function () {
        eq(String(keyFrames(trip.out)), String([1, 11, 21, 31, 41]));
    });

    it("needs no corrective keys to hold the tolerance", function () {
        // The drift pass measured every frame and found nothing worth pinning,
        // which is the strong result: AE's linear interpolation and Nuke's
        // agree closely enough that a straight crossing needs no repair.
        has(trip.imported, "5 authored key(s), 0 corrective");
    });

    it("keeps every key linear on both sides", function () {
        var keys = trip.out.shapes[0].keys;
        for (var i = 0; i < keys.length; i++) {
            eq(keys[i].interp["in"], "linear", "key " + i);
            eq(keys[i].interp["out"], "linear", "key " + i);
            ok(keys[i].ease === undefined,
               "key " + i + " grew an ease it has no use for");
        }
    });

    it("lands interpolated frames on Nuke's float32 storage floor", function () {
        /* The 36 frames between the keys are not in the file's keys at all -
         * After Effects rebuilds them by interpolating, and they are compared
         * against what Nuke's own interpolation wrote. They agree to 3.05e-05
         * px, which is where float32 storage of a coordinate this size runs
         * out, and is the same floor `test_nuke_roundtrip.py` hits. So the two
         * applications' `linear` is the same line, not merely a similar one. */
        var w = worst(trip.doc, trip.out, geometry);
        ok(w.d < 1e-4, "worst geometry " + w.d + " " + w.where);
    });

    it("keeps interpolated feather inside the tolerance it was given",
       function () {
        // Feather is measured by the drift pass along with position, so it is
        // bounded by the same 0.5 px. It lands two orders under it.
        var w = worst(trip.doc, trip.out, feather);
        ok(w.d < 0.5, "worst feather " + w.d + " " + w.where);
    });

    it("reproduces the file exactly at tolerance 0", function () {
        // The other end of the control: every frame keyed, nothing inferred,
        // and the crossing is as exact as the dense file's.
        var exact = cross("sparse", 0);
        eq(keyFrames(exact.out).length, 41);
        var g = worst(exact.doc, exact.out, geometry);
        eq(g.d, 0, "geometry deviated by " + g.d + " at " + g.where);
        var f = worst(exact.doc, exact.out, feather);
        eq(f.d, 0, "feather deviated by " + f.d + " at " + f.where);
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
