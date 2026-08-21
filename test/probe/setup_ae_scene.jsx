/*
 * Builds the After Effects scene the Phase 4 by-hand checklist asks for.
 *
 * Run: File > Scripts > Run Script File...
 * Requires: an open comp, at least 25 frames long.
 *
 * Adds one solid, "RotoBridge test", carrying five masks - one per row of the
 * checklist in `test/probe/README.md` that needs something authored. Then run
 * the exporter over it, run the importer on what it wrote, and compare. The
 * point of scripting it is that the same scene comes back every time: a
 * hand-drawn mask differs run to run, and a difference in the fixture reads
 * exactly like a difference in the adapters.
 *
 * It builds inside one undo group, so ctrl+Z removes the whole thing.
 *
 * What it does NOT do is check anything. It authors, and the report at the end
 * says what to look for. Everything here that can be verified without a host
 * already is - see `test/run.sh`.
 *
 * ES3 only, like every other script in this project - no let/const, no JSON,
 * no Array.forEach, no Array.indexOf.
 */

(function () {
    var FIRST = 0, LAST = 24;

    var comp = app.project.activeItem;
    if (!comp || !(comp instanceof CompItem)) {
        alert("Open a comp first.");
        return;
    }
    if (comp.duration * comp.frameRate < LAST + 1) {
        alert("This comp is shorter than " + (LAST + 1) + " frames.\n\n"
              + "The scene is built over frames " + FIRST + " to " + LAST + ".");
        return;
    }

    function t(frame) {
        return comp.displayStartTime + frame / comp.frameRate;
    }

    function square(x, y, w, h) {
        var s = new Shape();
        s.vertices = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]];
        s.inTangents = [[-20, 0], [-20, 8], [20, 0], [20, -8]];
        s.outTangents = [[20, 0], [20, -8], [-20, 0], [-20, 8]];
        s.closed = true;
        return s;
    }

    function addMask(layer, name) {
        var mask = layer.property("ADBE Mask Parade")
                        .addProperty("ADBE Mask Atom");
        mask.name = name;
        return mask;
    }

    var notes = [];
    function note(s) { notes.push(s); }

    function tryIt(label, fn) {
        /* An author step that fails is the interesting result, not a reason to
         * abandon the rest of the scene - so it is recorded and the build goes
         * on. `setTemporalEaseAtKey` is the one call here that no probe run has
         * ever exercised in the host. */
        try { fn(); } catch (e) { note("FAILED - " + label + ": " + e.toString()); }
    }

    app.beginUndoGroup("RotoBridge test scene");

    var layer = comp.layers.addSolid([0.2, 0.2, 0.25], "RotoBridge test",
                                     comp.width, comp.height, comp.pixelAspect);

    /* A non-identity affine, and a keyed one. The export derives the layer
     * transform from three probes rather than asking per vertex, so a layer
     * that is rotated and scaled is the only kind that can catch a wrong
     * derivation. Keying the rotation also makes the layer contribute key times
     * to every shape on it, which is a rule the export has to honour and no
     * static layer exercises. */
    var xform = layer.property("ADBE Transform Group");
    xform.property("ADBE Scale").setValue([110, 90, 100]);
    var rot = xform.property("ADBE Rotate Z");
    rot.setValueAtTime(t(6), 0);
    rot.setValueAtTime(t(18), 12);

    /* 1. The baseline: linear motion, animated opacity, animated uniform
     *    feather. Everything the dense layer carries, moving at once. */
    var linear = addMask(layer, "linear");
    var pLinear = linear.property("ADBE Mask Shape");
    pLinear.setValueAtTime(t(FIRST), square(100, 100, 200, 150));
    pLinear.setValueAtTime(t(LAST), square(500, 260, 200, 150));
    pLinear.setInterpolationTypeAtKey(1, KeyframeInterpolationType.LINEAR);
    pLinear.setInterpolationTypeAtKey(2, KeyframeInterpolationType.LINEAR);
    linear.maskOpacity.setValueAtTime(t(FIRST), 100);
    linear.maskOpacity.setValueAtTime(t(LAST), 40);
    linear.maskFeather.setValueAtTime(t(FIRST), [10, 5]);
    linear.maskFeather.setValueAtTime(t(LAST), [30, 5]);

    /* 2. Bezier ease, the one interpolation `test/ae_mock.js` refuses to guess
     *    at. Deliberately asymmetric and nowhere near the 16.667 default, so a
     *    value that survives the round trip cannot have come from a default. */
    var eased = addMask(layer, "eased");
    var pEased = eased.property("ADBE Mask Shape");
    pEased.setValueAtTime(t(FIRST), square(700, 100, 180, 180));
    pEased.setValueAtTime(t(12), square(900, 400, 180, 180));
    pEased.setValueAtTime(t(LAST), square(1200, 150, 180, 180));
    tryIt("setTemporalEaseAtKey on the eased mask", function () {
        for (var k = 1; k <= pEased.numKeys; k++) {
            pEased.setTemporalEaseAtKey(k, [new KeyframeEase(0, 91.176)],
                                           [new KeyframeEase(0, 33.333)]);
        }
    });

    /* 3. A hold side next to an eased one. `setTemporalEaseAtKey` is documented
     *    to force a key to BEZIER, so the importer sets ease first and per-side
     *    types after; this is the shape of mask that shows whether the second
     *    call keeps the first one's ease. The symptom is key 2 rendering smooth
     *    on its way out instead of freezing. */
    var mixed = addMask(layer, "mixed");
    var pMixed = mixed.property("ADBE Mask Shape");
    pMixed.setValueAtTime(t(FIRST), square(100, 500, 160, 160));
    pMixed.setValueAtTime(t(12), square(400, 700, 160, 160));
    pMixed.setValueAtTime(t(LAST), square(100, 900, 160, 160));
    tryIt("ease then type on the mixed mask", function () {
        pMixed.setTemporalEaseAtKey(2, [new KeyframeEase(0, 75)],
                                       [new KeyframeEase(0, 75)]);
        pMixed.setInterpolationTypeAtKey(2, KeyframeInterpolationType.LINEAR,
                                            KeyframeInterpolationType.HOLD);
    });

    /* 4. Feather points where run 3 found real ones: mid-segment, two on the
     *    same segment, and signed radii - one outward, one inward, one pinned
     *    to zero width, which is an authored point and not an absent one. */
    var feathered = addMask(layer, "feathered");
    var pFeathered = feathered.property("ADBE Mask Shape");
    var shape = square(1300, 500, 300, 300);
    shape.featherSegLocs = [0, 0, 2, 3];
    shape.featherRelSegLocs = [0.25, 0.75, 0.5, 0];
    shape.featherRadii = [30, -15, 12, 0];
    shape.featherTypes = [0, 1, 0, 0];
    shape.featherInterps = [0, 0, 0, 0];
    shape.featherTensions = [0, 0, 0, 0];
    shape.featherRelCornerAngles = [0, 0, 0, 0];
    tryIt("write feather points", function () { pFeathered.setValue(shape); });
    tryIt("maskFeatherFalloff = SMOOTH", function () {
        feathered.maskFeatherFalloff = MaskFeatherFalloff.FFO_SMOOTH;
    });

    /* 5. A key off the frame grid. The export has to snap it and say so - spec
     *    section 9 requires every keys[].frame to name a frame that exists in
     *    `frames`, and After Effects will happily put one between two. */
    var offgrid = addMask(layer, "offgrid");
    var pOffgrid = offgrid.property("ADBE Mask Shape");
    pOffgrid.setValueAtTime(t(FIRST), square(1500, 100, 140, 140));
    pOffgrid.setValueAtTime(t(10.4), square(1600, 250, 140, 140));
    pOffgrid.setValueAtTime(t(LAST), square(1700, 100, 140, 140));
    for (var k = 1; k <= pOffgrid.numKeys; k++) {
        pOffgrid.setInterpolationTypeAtKey(k, KeyframeInterpolationType.LINEAR);
    }

    /* The export reads the work area, so the scene has to be inside it or four
     * of these five masks are only half exported. */
    comp.workAreaStart = t(FIRST);
    comp.workAreaDuration = (LAST - FIRST + 1) / comp.frameRate;

    app.endUndoGroup();

    alert("RotoBridge test scene built on layer 'RotoBridge test'.\n"
          + "Frames " + FIRST + " to " + LAST + ", work area set to match.\n"
          + (notes.length ? "\n" + notes.join("\n") + "\n" : "")
          + "\nNow: export it, then import what it wrote, and look for\n\n"
          + "1. linear    - the baseline. Anything wrong here is wrong\n"
          + "               everywhere; check the report's drift figure first.\n"
          + "2. eased     - influence 91.176 in / 33.333 out should survive as\n"
          + "               ease [0.91176, 0] and [0.33333, 0] in the file. If\n"
          + "               the reimport drifts, .rbj's ease is not reproducing\n"
          + "               AE's curve and spec 10.3 is what to look at.\n"
          + "3. mixed     - key 2 must still FREEZE on its way out after the\n"
          + "               import. If it renders smooth, the type call lost\n"
          + "               the ease that preceded it.\n"
          + "4. feathered - radii [30, -15, 12, 0] with the signs intact, and\n"
          + "               the zero still there rather than dropped.\n"
          + "5. offgrid   - the export must WARN that a key was snapped, and\n"
          + "               the file must have no key at frame 10.4.\n\n"
          + "Also worth reading: any warning naming the layer as not affine.\n"
          + "The layer is scaled and rotating, so that path is live here.");
})();
