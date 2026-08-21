/*
 * Builds the After Effects scene the Phase 4 by-hand checklist asks for.
 *
 * Run: File > Scripts > Run Script File...
 * Requires: an open comp, at least 25 frames long.
 *
 * Adds one solid, "RotoBridge test", carrying six masks - one per row of the
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

    /* 6. An open spline (spec/rbj-v2-draft.md). Nothing in probe runs 1-6 ever
     *    authored one, so what After Effects RENDERS an open mask path as is
     *    the single unmeasured thing standing between that draft and a freeze.
     *    The geometry side is already covered host-free; this mask exists to
     *    be looked at. */
    var opened = addMask(layer, "opened");
    var pOpened = opened.property("ADBE Mask Shape");
    var line = new Shape();
    line.vertices = [[200, 700], [400, 820], [700, 760], [900, 900]];
    line.inTangents = [[0, 0], [-40, 0], [-40, 0], [0, 0]];
    line.outTangents = [[40, 0], [40, 0], [40, 0], [0, 0]];
    line.closed = false;
    tryIt("write an open mask path", function () {
        pOpened.setValueAtTime(t(FIRST), line);
    });

    /* 7 and 8. THE CONTROL, on a second solid with a STATIC transform.
     *
     *    The masks above all sit on a scaled and rotating layer, which is what
     *    makes them exercise the derived affine - and which also makes them
     *    useless for judging interpolation. The layer transform is baked into
     *    the exported points, so the canonical geometry never moves the way any
     *    key type says it does: `linear` above bows 13.2 px off the straight
     *    chord between its own LINEAR keys, and `eased` bows 49.2 px. Every
     *    mask on that layer therefore needs corrective keys no matter how
     *    perfect the interpolation mapping is, and a corrective count there
     *    measures the rotation, not the ease.
     *
     *    These two are the same masks with nothing moving underneath them. Here
     *    a corrective count means what it appears to mean: `eased_static` is
     *    the real test of whether `.rbj` ease reproduces After Effects' own
     *    curve, and `linear_static` is the calibration that says the rig is
     *    sound, because linear-to-linear must come back with ZERO corrective
     *    keys or something is wrong before ease is even reached. */
    var flat = comp.layers.addSolid([0.25, 0.2, 0.2], "RotoBridge static",
                                    comp.width, comp.height, comp.pixelAspect);

    var easedFlat = addMask(flat, "eased_static");
    var pEasedFlat = easedFlat.property("ADBE Mask Shape");
    pEasedFlat.setValueAtTime(t(FIRST), square(100, 100, 180, 180));
    pEasedFlat.setValueAtTime(t(12), square(400, 400, 180, 180));
    pEasedFlat.setValueAtTime(t(LAST), square(800, 150, 180, 180));
    tryIt("setTemporalEaseAtKey on the static eased mask", function () {
        for (var q = 1; q <= pEasedFlat.numKeys; q++) {
            pEasedFlat.setTemporalEaseAtKey(q, [new KeyframeEase(0, 91.176)],
                                               [new KeyframeEase(0, 33.333)]);
        }
    });

    var linearFlat = addMask(flat, "linear_static");
    var pLinearFlat = linearFlat.property("ADBE Mask Shape");
    pLinearFlat.setValueAtTime(t(FIRST), square(1000, 100, 180, 180));
    pLinearFlat.setValueAtTime(t(LAST), square(1600, 500, 180, 180));
    pLinearFlat.setInterpolationTypeAtKey(1, KeyframeInterpolationType.LINEAR);
    pLinearFlat.setInterpolationTypeAtKey(2, KeyframeInterpolationType.LINEAR);

    /* The export reads the work area, so the scene has to be inside it or five
     * of these six masks are only half exported. */
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
          + "               the file must have no key at frame 10.4.\n"
          + "6. opened    - the file must say closed: false and version: 2,\n"
          + "               and the reimport must come back still open. Then\n"
          + "               LOOK at the matte: whether AE fills an open path,\n"
          + "               and how, is the one thing spec/rbj-v2-draft.md\n"
          + "               section 5 could not measure.\n"
          + "\nOn the SECOND solid, 'RotoBridge static', which does not move:\n"
          + "7. linear_static - must reimport with ZERO corrective keys. This\n"
          + "               is the calibration; if it needs any, stop and read\n"
          + "               that before looking at 8.\n"
          + "8. eased_static  - the real ease test. Corrective keys here mean\n"
          + "               .rbj ease does not reproduce AE's own curve, and\n"
          + "               spec 10.3 is what to look at. The masks on the\n"
          + "               moving layer CANNOT answer this: the baked rotation\n"
          + "               makes even 'linear' bow 13.2 px off its own chord.\n\n"
          + "Also worth reading: any warning naming the layer as not affine.\n"
          + "The layer is scaled and rotating, so that path is live here.");
})();
