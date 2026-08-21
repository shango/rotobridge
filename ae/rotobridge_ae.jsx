/*
 * RotoBridge - shared host-side helpers for the After Effects adapters.
 *
 * Everything in here touches the host: `app`, `CompItem`, `MaskPropertyGroup`.
 * The geometry, timing, interpolation, drift and schema live in
 * `rotobridge_core.jsx` and `rotobridge_rbj.jsx`, which touch nothing, so they
 * stay testable with no After Effects present (prd.md section 5.1). This is the
 * ExtendScript counterpart of `nuke/rotobridge_nuke.py`.
 *
 * Every constant below was read off the host by the Phase 0 probe rather than
 * taken from documentation. Where a mapping is still unverified it says so at
 * the point of use, and the export records a warning in the file rather than
 * pretending.
 */

#include "rotobridge_core.jsx"
#include "rotobridge_rbj.jsx"

(function (RB) {
    var ae = {};
    RB.ae = ae;

    /* MaskMode, probe run 6. `.rbj` has three blend values and After Effects
     * has seven; the four with no equivalent degrade with a warning, which is
     * the soft failure of spec section 12.2. */
    ae.MASK_NONE = 6812;
    ae.MASK_ADD = 6813;
    ae.MASK_SUBTRACT = 6814;
    ae.MASK_INTERSECT = 6815;
    ae.MASK_LIGHTEN = 6816;
    ae.MASK_DARKEN = 6817;
    ae.MASK_DIFFERENCE = 6818;

    ae.MASK_MODE_NAMES = {};
    ae.MASK_MODE_NAMES[ae.MASK_NONE] = "None";
    ae.MASK_MODE_NAMES[ae.MASK_ADD] = "Add";
    ae.MASK_MODE_NAMES[ae.MASK_SUBTRACT] = "Subtract";
    ae.MASK_MODE_NAMES[ae.MASK_INTERSECT] = "Intersect";
    ae.MASK_MODE_NAMES[ae.MASK_LIGHTEN] = "Lighten";
    ae.MASK_MODE_NAMES[ae.MASK_DARKEN] = "Darken";
    ae.MASK_MODE_NAMES[ae.MASK_DIFFERENCE] = "Difference";

    /* MaskFeatherFalloff, probe run 6. Note it is an *attribute*, not a
     * Property, so unlike `maskFeather` it cannot be keyframed - which is why
     * `.rbj` carries falloff once per shape and uniform feather per frame. */
    ae.FFO_SMOOTH = 7212;
    ae.FFO_LINEAR = 7213;

    ae.blendFromMode = function (mode, warn, shapeName) {
        /* An After Effects `maskMode` to an .rbj blend value. */
        if (mode === ae.MASK_ADD) { return "union"; }
        if (mode === ae.MASK_SUBTRACT) { return "difference"; }
        if (mode === ae.MASK_INTERSECT) { return "intersection"; }
        var name = RB.util.hasOwn(ae.MASK_MODE_NAMES, mode)
            ? ae.MASK_MODE_NAMES[mode] : String(mode);
        warn("mask '" + shapeName + "': mask mode '" + name + "' has no .rbj"
             + " equivalent; wrote 'union'");
        return "union";
    };

    ae.modeFromBlend = function (blend) {
        /* An .rbj blend value to a `maskMode`. All three map exactly, which is
         * the direction that motivated the enum in the first place. */
        if (blend === "difference") { return ae.MASK_SUBTRACT; }
        if (blend === "intersection") { return ae.MASK_INTERSECT; }
        return ae.MASK_ADD;
    };

    ae.falloffToRbj = function (falloff) {
        return (falloff === ae.FFO_SMOOTH) ? "smooth" : "linear";
    };

    ae.falloffFromRbj = function (falloff) {
        return (falloff === "smooth") ? ae.FFO_SMOOTH : ae.FFO_LINEAR;
    };

    /* --- warnings --------------------------------------------------------- */

    ae.Warnings = function () {
        this.messages = [];
        this.seen = {};
    };

    ae.Warnings.prototype.add = function (message) {
        /* Deduplicated: a per-frame condition on a 150-frame shape would
         * otherwise fill the file's `warnings` array with 150 copies of one
         * sentence and bury everything else. */
        if (RB.util.hasOwn(this.seen, message)) { return; }
        this.seen[message] = true;
        this.messages[this.messages.length] = message;
    };

    ae.Warnings.prototype.fn = function () {
        /* A bare `warn(message)` to hand to code that should not know about
         * this object - `blendFromMode` above, and the core modules. */
        var self = this;
        return function (message) { self.add(message); };
    };

    /* --- project navigation ----------------------------------------------- */

    ae.activeComp = function () {
        /* The comp to work in, or an explanation of why there is not one. */
        if (!app.project) {
            throw new Error("open a project first");
        }
        var item = app.project.activeItem;
        if (!item || !(item instanceof CompItem)) {
            throw new Error("select a composition first - the active item is "
                            + (item ? "not a comp" : "nothing"));
        }
        return item;
    };

    ae.maskedLayers = function (comp) {
        /* Selected layers that carry masks, or every masked layer if the
         * selection is empty. Raises with a reason if there are none.
         *
         * A selection of layers that all have no masks is a different mistake
         * from no selection at all, and says so. */
        var candidates = comp.selectedLayers;
        var explicit = candidates.length > 0;
        if (!explicit) {
            candidates = [];
            for (var i = 1; i <= comp.numLayers; i++) {
                candidates[candidates.length] = comp.layer(i);
            }
        }

        var out = [];
        for (var j = 0; j < candidates.length; j++) {
            var layer = candidates[j];
            var masks = ae.maskGroup(layer);
            if (masks && masks.numProperties > 0) { out[out.length] = layer; }
        }
        if (!out.length) {
            throw new Error(explicit
                ? "the selected layer(s) have no masks"
                : "no layer in this comp has a mask");
        }
        return out;
    };

    ae.maskGroup = function (layer) {
        /* `Masks` is absent entirely on layer types that cannot hold one, so
         * this returns null rather than throwing - the caller is usually
         * surveying a whole comp and wants to skip, not stop. */
        try {
            return layer.property("ADBE Mask Parade");
        } catch (e) {
            return null;
        }
    };

    ae.checkLayer = function (layer) {
        /* prd.md section 11 makes these hard failures, not warnings: the
         * export has no way to resolve either transform, so the geometry it
         * would write is wrong rather than approximate. */
        if (layer.threeDLayer) {
            throw new Error("layer '" + layer.name + "' is 3D; .rbj v1 carries"
                            + " 2D layers only");
        }
        if (layer.parent !== null) {
            throw new Error("layer '" + layer.name + "' is parented to '"
                            + layer.parent.name + "'; unparent it or bake the"
                            + " transform first");
        }
    };

    /* --- mask properties -------------------------------------------------- */

    ae.MASK_PATH = "ADBE Mask Shape";
    ae.MASK_FEATHER = "ADBE Mask Feather";
    ae.MASK_OPACITY = "ADBE Mask Opacity";
    ae.MASK_EXPANSION = "ADBE Mask Offset";

    ae.maskProp = function (mask, matchName) {
        /* By matchName, never by display name: display names are localised and
         * a script keyed to them stops working in a French installation. */
        return mask.property(matchName);
    };

    /* --- geometry against the layer transform ------------------------------
     *
     * `sourcePointToComp` takes ONE argument and evaluates at the current
     * `comp.time` - there is no time parameter (probe section F). So the caller
     * sets `comp.time` first, which is exactly why the dense loop has to be
     * frame-major (prd.md section 9.1 step 4).
     */

    ae.pointToComp = function (layer, p) {
        return layer.sourcePointToComp([Number(p[0]), Number(p[1])]);
    };

    ae.tangentToComp = function (layer, vertex, tangent) {
        /* Transform `vertex + tangent`, then subtract the transformed vertex.
         * Probe section F confirmed this reproduces rotation and non-uniform
         * scale exactly - a [40, 0] layer tangent under scale [150, 220] and a
         * 30 degree rotation came out [51.962, 30] - so After Effects support
         * does not have to narrow to identity-transform layers. */
        var moved = ae.pointToComp(layer, [Number(vertex[0]) + Number(tangent[0]),
                                           Number(vertex[1]) + Number(tangent[1])]);
        var base = ae.pointToComp(layer, vertex);
        return [moved[0] - base[0], moved[1] - base[1]];
    };

    ae.pointToLayer = function (layer, p) {
        return layer.compPointToSource([Number(p[0]), Number(p[1])]);
    };

    ae.tangentToLayer = function (layer, vertex, tangent) {
        var moved = ae.pointToLayer(layer, [Number(vertex[0]) + Number(tangent[0]),
                                            Number(vertex[1]) + Number(tangent[1])]);
        var base = ae.pointToLayer(layer, vertex);
        return [moved[0] - base[0], moved[1] - base[1]];
    };

    /* --- timing against the comp ------------------------------------------- */

    ae.startFrame = function (comp) {
        /* The frame number sitting at time zero. `displayStartTime` is in
         * seconds, and every frame number .rbj carries is the one the artist
         * sees in the timeline (spec section 4). */
        return Math.round(comp.displayStartTime * comp.frameRate);
    };

    ae.workAreaFrames = function (comp) {
        /* [first, last] inclusive, in the comp's own frame numbering.
         *
         * The work area's end is the time *after* the last frame it contains,
         * the way a duration always is, so the last frame is one before it. A
         * range built without that subtraction exports one frame that After
         * Effects does not consider part of the work area. */
        var sf = ae.startFrame(comp);
        var first = RB.timing.secondsToFrame(comp.workAreaStart,
                                             comp.frameRate, sf);
        var end = RB.timing.secondsToFrame(comp.workAreaStart
                                           + comp.workAreaDuration,
                                           comp.frameRate, sf);
        var last = end - 1;
        if (last < first) { last = first; }
        return [first, last];
    };

    ae.frameToTime = function (comp, frame) {
        return RB.timing.frameToSeconds(frame, comp.frameRate,
                                        ae.startFrame(comp));
    };

    /* --- files -------------------------------------------------------------- */

    ae.readText = function (file) {
        file.encoding = "UTF-8";
        if (!file.open("r")) {
            throw new Error("cannot read " + file.fsName);
        }
        var text = file.read();
        file.close();
        return text;
    };

    ae.writeText = function (file, text) {
        file.encoding = "UTF-8";
        if (!file.open("w")) {
            throw new Error("cannot write " + file.fsName);
        }
        file.write(text);
        file.close();
    };

    ae.SOURCE_APP = "After Effects";

    ae.sourceBlock = function (comp) {
        return {
            "app": ae.SOURCE_APP,
            "app_version": String(app.version),
            "width": Math.round(comp.width),
            "height": Math.round(comp.height),
            "pixel_aspect": Number(comp.pixelAspect),
            "fps": Number(comp.frameRate)
        };
    };
}(RB));
