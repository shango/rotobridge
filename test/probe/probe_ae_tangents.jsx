/*
 * What does After Effects actually report for this mask's tangents?
 *
 * Select the layer holding the mask, then File > Scripts > Run Script File...
 * Reads only. Writes nothing, changes nothing.
 */
(function () {
    var comp = app.project.activeItem;
    if (!comp || !(comp instanceof CompItem)) {
        alert("Open a comp first."); return;
    }
    var sel = comp.selectedLayers;
    if (!sel.length) { alert("Select the layer holding the mask."); return; }

    var out = [];
    out.push("comp: " + comp.name + "   time: " + comp.time.toFixed(4));
    for (var L = 0; L < sel.length; L++) {
        var layer = sel[L];
        var masks = layer.property("ADBE Mask Parade");
        out.push("");
        out.push("layer: " + layer.name + "  (" + (masks ? masks.numProperties : 0)
                 + " mask(s))");
        if (!masks) { continue; }
        for (var m = 1; m <= masks.numProperties; m++) {
            var mask = masks.property(m);
            var prop = mask.property("ADBE Mask Shape");
            var shape = prop.valueAtTime(comp.time, false);
            var vin = 0, vout = 0, n = shape.vertices.length;
            for (var i = 0; i < n; i++) {
                vin = Math.max(vin, Math.abs(shape.inTangents[i][0]),
                                    Math.abs(shape.inTangents[i][1]));
                vout = Math.max(vout, Math.abs(shape.outTangents[i][0]),
                                     Math.abs(shape.outTangents[i][1]));
            }
            out.push("  " + mask.name + ": " + n + " vertices, closed="
                     + shape.closed + ", rotoBezier=" + mask.rotoBezier);
            out.push("    largest |inTangent| = " + vin.toFixed(4)
                     + "   largest |outTangent| = " + vout.toFixed(4));
            out.push("    vertex[0] = [" + shape.vertices[0][0].toFixed(3) + ", "
                     + shape.vertices[0][1].toFixed(3) + "]"
                     + "  in[0] = [" + shape.inTangents[0][0].toFixed(3) + ", "
                     + shape.inTangents[0][1].toFixed(3) + "]"
                     + "  out[0] = [" + shape.outTangents[0][0].toFixed(3) + ", "
                     + shape.outTangents[0][1].toFixed(3) + "]");
            out.push("    keys on the path: " + prop.numKeys);
        }
    }
    alert(out.join("\n"));
})();
