/*
 * What an After Effects artist gets back when their eased mask makes the
 * round trip out to .rbj and in again.
 *
 * Read-only, no host. The exporter conforms every eased side to linear before
 * it writes (`conformEase`, and the reasoning is in its comment: Nuke has no
 * vocabulary for AE's temporal ease, so the cost is paid in the application
 * that created it). The authored keys are kept as `pre_conform_keys`. Nothing
 * reads them back.
 *
 * This imports the two goldens that bracket the conform - the same shape
 * before and after - and prints the keys an artist would find on the mask.
 * Then a third: the conformed file with the authored keys carried beside it as
 * `pre_conform_keys`, which is what the exporter writes today. The goldens
 * predate that member, so the third one has to be assembled here rather than
 * read; everything in it comes from the two files above.
 *
 * One caveat on the "before" file: `ae_mock` refuses to interpolate a bezier
 * segment (it says so, and why, in its own header), so the drift pass raises
 * partway through that import. The keys are set before the pass runs, so what
 * is printed is real - it is the alert that is an artefact of the mock, not
 * the host. The alerts are printed too rather than swallowed.
 *
 *     node test/probe/probe_ae_ease_roundtrip.js
 */

var path = require("path");
var fs = require("fs");
var vm = require("vm");

var ROOT = path.dirname(path.dirname(__dirname));
var mock = require(path.join(ROOT, "test", "ae_mock.js"));

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

var TYPE = {};
TYPE[6612] = "linear";
TYPE[6613] = "bezier";
TYPE[6614] = "hold";

function importText(text) {
    var host = mock.install({
        frameRate: 24,
        workAreaStart: 0,
        workAreaDuration: 25 / 24,
        layers: [],
        selected: [],
        readable: text
    });
    delete global.RB;
    vm.runInThisContext(source("rotobridge_import.jsx"),
                        { filename: "rotobridge_import.jsx" });
    return host;
}

function describeMask(mask) {
    var prop = mask.property("ADBE Mask Shape");
    var out = [];
    for (var i = 1; i <= prop.numKeys; i++) {
        var line = "f" + Math.round(prop.keyTime(i) * 24)
            + " " + TYPE[prop.keyInInterpolationType(i)]
            + "/" + TYPE[prop.keyOutInterpolationType(i)];
        var inf = prop.keyInTemporalEase(i)[0].influence;
        var out_ = prop.keyOutTemporalEase(i)[0].influence;
        line += " influence " + inf.toFixed(3) + "/" + out_.toFixed(3);
        out.push(line);
    }
    return { count: prop.numKeys, keys: out };
}

function golden(file) {
    return fs.readFileSync(path.join(ROOT, "test", "golden", file), "utf8");
}

function withProvenance() {
    /* The conformed file as today's exporter would have written it: the same
     * document, plus the authored keys it rewrote. */
    var conformed = JSON.parse(golden("ae_static_conformed.rbj"));
    var authored = JSON.parse(golden("ae_static_ease.rbj"));
    for (var i = 0; i < conformed.shapes.length; i++) {
        var was = authored.shapes[i];
        if (JSON.stringify(was.keys) !== JSON.stringify(conformed.shapes[i].keys)) {
            conformed.shapes[i].pre_conform_keys = was.keys;
        }
    }
    return JSON.stringify(conformed);
}

[["ae_static_ease.rbj", "as the artist authored it, before the conform",
  golden("ae_static_ease.rbj")],
 ["ae_static_conformed.rbj", "as the exporter wrote it before it kept provenance",
  golden("ae_static_conformed.rbj")],
 ["the same, with pre_conform_keys", "as the exporter writes it today",
  withProvenance()]
].forEach(function (pair) {
    var host = importText(pair[2]);
    console.log("== " + pair[0] + "   (" + pair[1] + ")");
    var masks = host.comp.layer(1)._masks;
    for (var m = 0; m < masks.length; m++) {
        var got = describeMask(masks[m]);
        console.log("   " + masks[m].name + ": " + got.count + " keys");
        if (got.count <= 6) {
            for (var k = 0; k < got.keys.length; k++) {
                console.log("      " + got.keys[k]);
            }
        } else {
            console.log("      " + got.keys.slice(0, 3).join("  |  ") + "  ...");
        }
    }
    for (var a = 0; a < host.alerts.length; a++) {
        console.log("   [alert] "
                    + String(host.alerts[a]).split("\n").join(" / "));
    }
    console.log("");
});
