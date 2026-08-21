/*
 * Does After Effects hand feather points back in written order at an
 * INTERPOLATED frame?
 *
 * probe_ae_feather_order.jsx answered the static question and the answer was
 * yes: written [30, -15, 0, 12], read back [30, -15, 0, 12]. It also showed the
 * anchors get renamed - segLocs [0, 1, 2, 3] with relSegLocs [0, 0, 0, 0] came
 * back as segLocs [3, 0, 1, 2] with relSegLocs [1, 1, 1, 1], which is the same
 * four positions re-encoded as "end of the previous segment" instead of "start
 * of this one".
 *
 * But that probe set the value ONCE and read it straight back. The importer
 * does something different: it writes KEYS with setValueAtTime and then reads
 * with valueAtTime at frames BETWEEN them, which is a different path through
 * the host. The drift pass measures at exactly those in-between frames.
 *
 * Why it matters. Importing `feathered` from test/golden/ae_scene.rbj left
 * exactly 27.0000 px the pass could never remove, at frame 15. That shape's
 * geometry bows only 3.856 px off its own chord, the second easiest of the six
 * in that file, and Nuke converges the same shape to 0.2143 px while carrying
 * no feather at all. So the residual is the feather, and it is constant: the
 * file's feather is [30, -15, 0, 12] on every one of the 25 frames, which is
 * why no number of corrective keys moves it.
 *
 * Two orders both produce exactly 27 index-wise against [30, -15, 0, 12]:
 *
 *   [30, 0, 12, -15]   grouped by type, non-negative first   diffs 0, 15, 12, 27
 *   [30, 12, 0, -15]   sorted by radius, descending          diffs 0, 27, 0, 27
 *
 * This probe reads the array back on a key and between two keys, with BEZIER
 * keys (what `feathered` has - all four of its sides are `ease`) and again with
 * LINEAR, so "interpolated at all" and "interpolated as a bezier" come apart.
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

    var RADII = [30, -15, 0, 12];
    var TYPES = [0, 1, 0, 0];
    var LINEAR = KeyframeInterpolationType.LINEAR;
    var BEZIER = KeyframeInterpolationType.BEZIER;

    function show(a) {
        if (!a) { return "(none)"; }
        var out = [];
        for (var i = 0; i < a.length; i++) { out[i] = a[i]; }
        return "[" + out.join(", ") + "]";
    }

    function worstAgainstWritten(got) {
        /* Exactly what deviation() in rotobridge_import.jsx computes. */
        var worst = 0;
        for (var i = 0; i < RADII.length; i++) {
            var mine = (got && got.length > i) ? Number(got[i]) : 0;
            var d = Math.abs(mine - Number(RADII[i]));
            if (d > worst) { worst = d; }
        }
        return worst;
    }

    function shapeAt(dx) {
        var s = new Shape();
        s.vertices = [[100 + dx, 100], [300 + dx, 100],
                      [300 + dx, 300], [100 + dx, 300]];
        s.inTangents = [[0, 0], [0, 0], [0, 0], [0, 0]];
        s.outTangents = [[0, 0], [0, 0], [0, 0], [0, 0]];
        s.closed = true;
        /* One per vertex at the start of its own segment, which is what
         * geom.featherPointsFromVertices builds on import. Identical on both
         * keys, so anything that changes between them came from the host. */
        s.featherSegLocs = [0, 1, 2, 3];
        s.featherRelSegLocs = [0, 0, 0, 0];
        s.featherRadii = RADII;
        s.featherTypes = TYPES;
        s.featherInterps = [0, 0, 0, 0];
        s.featherTensions = [0, 0, 0, 0];
        s.featherRelCornerAngles = [0, 0, 0, 0];
        return s;
    }

    var lines = ["Feather point order at an interpolated frame", ""];
    lines[lines.length] = "WROTE, on both keys";
    lines[lines.length] = "  radii   " + show(RADII);
    lines[lines.length] = "  types   " + show(TYPES);
    lines[lines.length] = "  segLocs [0, 1, 2, 3]  relSegLocs [0, 0, 0, 0]";
    lines[lines.length] = "";

    app.beginUndoGroup("RotoBridge feather interpolation probe");

    function trial(label, type) {
        var layer = comp.layers.addSolid([0.2, 0.2, 0.2], "feather " + label,
                                         comp.width, comp.height,
                                         comp.pixelAspect);
        var mask = layer.property("ADBE Mask Parade")
                        .addProperty("ADBE Mask Atom");
        var prop = mask.property("ADBE Mask Shape");
        var fps = comp.frameRate;

        prop.setValueAtTime(0 / fps, shapeAt(0));
        prop.setValueAtTime(12 / fps, shapeAt(200));
        for (var k = 1; k <= prop.numKeys; k++) {
            prop.setInterpolationTypeAtKey(k, type, type);
        }

        lines[lines.length] = "=== " + label + " keys ===";
        var frames = [0, 6, 12];
        for (var f = 0; f < frames.length; f++) {
            var frame = frames[f];
            var got = prop.valueAtTime(frame / fps, false);
            var onKey = (frame === 0 || frame === 12);
            lines[lines.length] = "  frame " + frame
                                  + (onKey ? "  (on a key)" : "  (INTERPOLATED)");
            lines[lines.length] = "    radii      " + show(got.featherRadii);
            lines[lines.length] = "    types      " + show(got.featherTypes);
            lines[lines.length] = "    segLocs    " + show(got.featherSegLocs);
            lines[lines.length] = "    relSegLocs " + show(got.featherRelSegLocs);
            lines[lines.length] = "    worst index-wise vs written: "
                                  + worstAgainstWritten(got.featherRadii);
        }
        lines[lines.length] = "";
    }

    var err = null;
    try {
        trial("BEZIER", BEZIER);
        trial("LINEAR", LINEAR);
    } catch (e) {
        err = e.toString() + (e.line ? "  (line " + e.line + ")" : "");
        lines[lines.length] = "FAILED: " + err;
    }

    app.endUndoGroup();

    if (!err) {
        lines[lines.length] = "READ THIS AS:";
        lines[lines.length] = "  27 on an interpolated frame and 0 on a key ->"
                              + " the host reorders while interpolating, and";
        lines[lines.length] = "  deviation() must stop comparing featherRadii"
                              + " by index.";
        lines[lines.length] = "  0 everywhere -> the feather is NOT the 27 and"
                              + " the cause is still open.";
    }

    alert(lines.join("\n"), "RotoBridge");
})();
