/*
 * Does After Effects preserve the order feather points were written in?
 *
 * The AE import of `feathered` from `test/golden/ae_scene.rbj` left exactly
 * 27.0000 px of drift that the pass could not remove. The file's per-vertex
 * feather is [30, -15, 0, 12], and 12 - (-15) = 27. `deviation()` in
 * rotobridge_import.jsx compares `featherRadii` element by element, which is
 * only meaningful if the host hands the array back in the order it was given.
 *
 * The hypothesis is that After Effects groups feather points by TYPE - outer
 * (non-negative) first, then inner - so [30, -15, 0, 12] with types
 * [0, 1, 0, 0] comes back as [30, 0, 12, -15]. Compared index by index against
 * the original that is 0, 15, 12 and 27: worst 27, which is the number.
 *
 * This writes that exact array and reads it straight back. No import, no drift
 * pass, nothing else in the way.
 *
 * Run: File > Scripts > Run Script File...  Needs an open comp.
 * ES3 only.
 */

(function () {
    var comp = app.project.activeItem;
    if (!comp || !(comp instanceof CompItem)) {
        alert("Open a comp first.");
        return;
    }

    function show(a) {
        var out = [];
        for (var i = 0; i < a.length; i++) { out[i] = a[i]; }
        return "[" + out.join(", ") + "]";
    }

    app.beginUndoGroup("RotoBridge feather order probe");

    var layer = comp.layers.addSolid([0.2, 0.2, 0.2], "feather order probe",
                                     comp.width, comp.height, comp.pixelAspect);
    var mask = layer.property("ADBE Mask Parade")
                    .addProperty("ADBE Mask Atom");
    var prop = mask.property("ADBE Mask Shape");

    var shape = new Shape();
    shape.vertices = [[100, 100], [300, 100], [300, 300], [100, 300]];
    shape.inTangents = [[0, 0], [0, 0], [0, 0], [0, 0]];
    shape.outTangents = [[0, 0], [0, 0], [0, 0], [0, 0]];
    shape.closed = true;

    /* One per vertex, pinned to the start of its own segment - exactly what
     * geom.featherPointsFromVertices builds on import. */
    var radii = [30, -15, 0, 12];
    var types = [0, 1, 0, 0];
    shape.featherSegLocs = [0, 1, 2, 3];
    shape.featherRelSegLocs = [0, 0, 0, 0];
    shape.featherRadii = radii;
    shape.featherTypes = types;
    shape.featherInterps = [0, 0, 0, 0];
    shape.featherTensions = [0, 0, 0, 0];
    shape.featherRelCornerAngles = [0, 0, 0, 0];

    var lines = ["Feather point order: written against read back", ""];
    lines[lines.length] = "WROTE";
    lines[lines.length] = "  segLocs    " + show(shape.featherSegLocs);
    lines[lines.length] = "  relSegLocs " + show(shape.featherRelSegLocs);
    lines[lines.length] = "  radii      " + show(radii);
    lines[lines.length] = "  types      " + show(types);
    lines[lines.length] = "";

    var err = null;
    try { prop.setValue(shape); } catch (e) { err = e.toString(); }

    if (err) {
        lines[lines.length] = "setValue FAILED: " + err;
    } else {
        var back = prop.value;
        lines[lines.length] = "READ BACK";
        lines[lines.length] = "  segLocs    " + show(back.featherSegLocs);
        lines[lines.length] = "  relSegLocs " + show(back.featherRelSegLocs);
        lines[lines.length] = "  radii      " + show(back.featherRadii);
        lines[lines.length] = "  types      " + show(back.featherTypes);
        lines[lines.length] = "";

        var same = back.featherRadii.length === radii.length;
        if (same) {
            for (var i = 0; i < radii.length; i++) {
                if (Number(back.featherRadii[i]) !== Number(radii[i])) {
                    same = false;
                }
            }
        }
        lines[lines.length] = same
            ? "VERDICT: order preserved. The 27 px has another cause."
            : "VERDICT: NOT the order written. Comparing featherRadii by index"
              + " is invalid, which is what the drift pass was doing.";

        if (!same) {
            var worst = 0;
            for (var j = 0; j < radii.length; j++) {
                var d = Math.abs(Number(back.featherRadii[j] || 0)
                                 - Number(radii[j]));
                if (d > worst) { worst = d; }
            }
            lines[lines.length] = "worst index-wise difference: " + worst
                                  + "   (the import reported 27.0000)";
        }
    }

    app.endUndoGroup();
    alert(lines.join("\n"), "RotoBridge");
})();
