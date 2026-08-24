/*
 * Does After Effects give a mask an identity that survives renames and
 * reorders?
 *
 * .rbj shapes carry an optional `id` (spec/rbj-v3-draft.md section 5.2). The
 * Nuke exporter writes one ("Roto1/Bezier3") because node name plus shape
 * name is stable within a script. The After Effects exporter writes NONE,
 * because no stable mask identity has been measured - and this project does
 * not code against an unprobed host API.
 *
 * The candidate is `PropertyBase.id`, documented since AE 17.0 as "a unique
 * and persistent identification number used internally to identify a property
 * between sessions". Documented is not measured; `addProperty` invalidating
 * every sibling handle (prd.md section 18) is exactly the kind of behaviour
 * that makes "persistent" worth testing. This probe answers, for the mask
 * property group of the active comp's first masked layer:
 *
 *   1. Does `mask.id` exist and return a number?
 *   2. Does it survive renaming the mask?
 *   3. Does it survive reordering masks (moveTo)?
 *   4. Does it survive save, close and reopen? (Manual: run twice, compare.)
 *
 * If all four hold, the AE exporter can write `id: "<comp.id>/<mask.id>"` and
 * re-imports become unambiguous. Until then it writes none, which the format
 * permits.
 *
 * Run: File > Scripts > Run Script File...  Needs an open comp with at least
 * one mask. ES3 only.
 */

(function () {
    var comp = app.project.activeItem;
    if (!comp || !(comp instanceof CompItem)) {
        alert("Open a comp first.");
        return;
    }

    var layer = null;
    for (var i = 1; i <= comp.numLayers; i++) {
        var group = comp.layer(i).property("ADBE Mask Parade");
        if (group && group.numProperties > 0) { layer = comp.layer(i); break; }
    }
    if (layer === null) {
        alert("No masked layer in this comp.");
        return;
    }

    var masks = layer.property("ADBE Mask Parade");
    var mask = masks.property(1);
    var lines = ["mask id probe, comp '" + comp.name + "'"];

    var before;
    try {
        before = mask.id;
        lines[lines.length] = "1. mask.id exists: " + before
            + " (" + typeof before + ")";
    } catch (e) {
        alert(lines.join("\n") + "\n1. mask.id THREW: " + (e.message || e));
        return;
    }

    var oldName = mask.name;
    mask.name = oldName + " renamed";
    lines[lines.length] = "2. after rename: " + masks.property(1).id
        + (masks.property(1).id === before ? " (same)" : " (CHANGED)");
    mask.name = oldName;

    if (masks.numProperties > 1) {
        mask.moveTo(masks.numProperties);
        /* Handles go stale on reorder (prd.md section 18), so re-fetch by
         * position and look for the id, not through the old handle. */
        var found = null;
        for (var m = 1; m <= masks.numProperties; m++) {
            if (masks.property(m).id === before) { found = m; break; }
        }
        lines[lines.length] = "3. after moveTo: id " + before
            + (found !== null ? " found at index " + found : " NOT FOUND");
        masks.property(found !== null ? found : masks.numProperties).moveTo(1);
    } else {
        lines[lines.length] = "3. only one mask; add a second to test moveTo";
    }

    lines[lines.length] = "4. save, reopen, run again: id should still be "
        + before;
    alert(lines.join("\n"));
}());
