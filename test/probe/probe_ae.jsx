/*
 * RotoBridge Phase 0 probe - After Effects side.
 *
 * Run: File > Scripts > Run Script File...
 * Requires: an open comp with one layer selected that has at least one mask.
 *
 * Read-only against your mask. The transform and interpolation tests build a
 * temporary layer and delete it again, all inside one undo group.
 *
 * Answers the AE questions in prd.md section 12. Writes a text report.
 *
 * ES3 only - no Array.forEach, no let/const (see prd.md 9.1).
 */

(function () {
    var lines = [];

    function say(s) {
        lines.push(s);
    }

    function head(s) {
        say("");
        say("=== " + s + " ===");
    }

    function fmt(n) {
        return Math.round(n * 1000) / 1000;
    }

    function pair(p) {
        return "[" + fmt(p[0]) + ", " + fmt(p[1]) + "]";
    }

    function tryIt(label, fn) {
        try {
            say(label + ": " + fn());
        } catch (e) {
            say(label + ": FAILED - " + e.toString());
        }
    }

    // ---------------------------------------------------------------- checks
    var comp = app.project.activeItem;
    if (!comp || !(comp instanceof CompItem)) {
        alert("Open a comp first.");
        return;
    }
    if (comp.selectedLayers.length !== 1) {
        alert("Select exactly one layer (with at least one mask).");
        return;
    }
    var layer = comp.selectedLayers[0];
    var masks = layer.property("ADBE Mask Parade");
    if (!masks || masks.numProperties < 1) {
        alert("The selected layer has no masks.");
        return;
    }

    app.beginUndoGroup("RotoBridge Phase 0 probe");

    // ------------------------------------------------------------ A. context
    head("A. Environment");
    say("AE version:        " + app.version);
    say("comp:              " + comp.name);
    say("size:              " + comp.width + " x " + comp.height);
    say("pixelAspect:       " + comp.pixelAspect);
    say("frameRate:         " + comp.frameRate);
    say("displayStartTime:  " + comp.displayStartTime);
    say("duration (s):      " + comp.duration);
    say("workArea (s):      " + comp.workAreaStart + " -> " +
        (comp.workAreaStart + comp.workAreaDuration));
    say("layer:             " + layer.name);
    say("layer.threeDLayer: " + layer.threeDLayer);
    say("layer.parent:      " + (layer.parent ? layer.parent.name : "none"));

    // ------------------------------------------------- B. mask path structure
    head("B. maskPath value structure");
    var mask = masks.property(1);
    var path = mask.property("ADBE Mask Shape");
    var t = comp.time;
    var shape = path.valueAtTime(t, false);

    say("mask name:         " + mask.name);
    say("maskMode:          " + mask.maskMode);
    say("inverted:          " + mask.inverted);
    say("closed:            " + shape.closed);
    say("vertex count:      " + shape.vertices.length);
    say("inTangents count:  " + shape.inTangents.length);
    say("outTangents count: " + shape.outTangents.length);
    say("");
    say("first 3 vertices (layer space, Y-down):");
    var n = Math.min(3, shape.vertices.length);
    for (var i = 0; i < n; i++) {
        say("  v" + i + " c=" + pair(shape.vertices[i]) +
            " in=" + pair(shape.inTangents[i]) +
            " out=" + pair(shape.outTangents[i]));
    }
    say("");
    say("Confirm: are tangents vertex-RELATIVE (small numbers) or absolute?");

    // ------------------------------------------------------- C. keyframe read
    head("C. Reading keyframes off maskPath (prd.md 5.4, 9.1 step 3)");
    say("numKeys:           " + path.numKeys);
    if (path.numKeys === 0) {
        say("(static mask - key it on a few frames and re-run to see key times)");
    }
    for (var k = 1; k <= path.numKeys && k <= 10; k++) {
        var kt = path.keyTime(k);
        var frame = Math.round((kt - comp.displayStartTime) * comp.frameRate);
        var inT = "?";
        var outT = "?";
        try {
            inT = path.keyInInterpolationType(k);
            outT = path.keyOutInterpolationType(k);
        } catch (e) {
            inT = "err: " + e.toString();
        }
        say("  key " + k + "  t=" + fmt(kt) + "s  frame=" + frame +
            "  in=" + inT + " out=" + outT);
    }
    say("");
    say("KeyframeInterpolationType.LINEAR = " + KeyframeInterpolationType.LINEAR);
    say("KeyframeInterpolationType.BEZIER = " + KeyframeInterpolationType.BEZIER);
    say("KeyframeInterpolationType.HOLD   = " + KeyframeInterpolationType.HOLD);

    // ----------------------------------------------- D. interpolation validity
    head("D. Interpolation types legal on maskPath (prd.md 7, tier 1)");
    say("If BEZIER or HOLD is false here, tier-1 ease is unreachable and every");
    say("interval falls back to tier-3 drift correction.");
    tryIt("LINEAR valid", function () {
        return path.isInterpolationTypeValid(KeyframeInterpolationType.LINEAR);
    });
    tryIt("BEZIER valid", function () {
        return path.isInterpolationTypeValid(KeyframeInterpolationType.BEZIER);
    });
    tryIt("HOLD valid  ", function () {
        return path.isInterpolationTypeValid(KeyframeInterpolationType.HOLD);
    });

    // ------------------------------------------------------------- E. feather
    head("E. Feather reachability (prd.md 10)");
    tryIt("maskFeather value", function () {
        var v = mask.maskFeather.value;
        return "[" + v.toString() + "]  (" +
            (v.length ? v.length + "-D, NOT a scalar" : "scalar") + ")";
    });
    say("prd.md 9.1 step 6 says 'write maskFeather mean'. If this is 2-D the");
    say("spec must say which component, or how x and y combine.");
    say("");
    say("Uniform feather is a SECOND, independent mechanism. Set the mask's");
    say("Mask Feather to something anisotropic (e.g. 20,5) and key it on two");
    say("frames before running, or this section proves nothing.");
    tryIt("maskFeather numKeys", function () {
        return mask.maskFeather.numKeys;
    });
    tryIt("maskFeather is animated", function () {
        return mask.maskFeather.numKeys > 0 ? "YES - see below" : "no (static)";
    });
    if (mask.maskFeather.numKeys > 0) {
        var ft0 = mask.maskFeather.keyTime(1);
        var ftN = mask.maskFeather.keyTime(mask.maskFeather.numKeys);
        var fmid = (ft0 + ftN) / 2;
        say("  maskFeather @first key t=" + ft0 + ": [" +
            mask.maskFeather.valueAtTime(ft0, false).toString() + "]");
        say("  maskFeather @midpoint  t=" + fmid + ": [" +
            mask.maskFeather.valueAtTime(fmid, false).toString() + "]");
        say("  maskFeather @last key  t=" + ftN + ": [" +
            mask.maskFeather.valueAtTime(ftN, false).toString() + "]");
        say("");
        say("  If the midpoint differs from both ends, uniform feather ANIMATES.");
        say("  prd.md 9.1 step 6 reads feather once per shape, which would");
        say("  silently freeze it at frame 1. That is a spec bug, not a gap.");
    }
    say("");
    tryIt("maskFeatherFalloff", function () {
        var ff = mask.maskFeatherFalloff;
        return ff + "  (LINEAR=" + MaskFeatherFalloff.FFO_LINEAR +
            " SMOOTH=" + MaskFeatherFalloff.FFO_SMOOTH + ")";
    });
    say("maskFeatherFalloff is an ATTRIBUTE, not a Property, so it cannot be");
    say("keyframed. Cheap to carry, but .rbj has no field for it today.");
    say("");
    tryIt("maskExpansion value", function () {
        return mask.maskExpansion.value + "  (numKeys=" +
            mask.maskExpansion.numKeys + ")";
    });
    say("maskExpansion is animatable and prd.md never mentions it. Not feather,");
    say("but the same class of silent per-mask drop.");
    say("");
    say("MaskMode constants: NONE=" + MaskMode.NONE + " ADD=" + MaskMode.ADD +
        " SUBTRACT=" + MaskMode.SUBTRACT + " INTERSECT=" + MaskMode.INTERSECT +
        " LIGHTEN=" + MaskMode.LIGHTEN + " DARKEN=" + MaskMode.DARKEN +
        " DIFFERENCE=" + MaskMode.DIFFERENCE);
    say("");
    say("Variable-width feather lives on the Shape object returned by maskPath,");
    say("NOT as a property on the mask group. Run 2 looked in the wrong place.");
    var fshape = path.valueAtTime(comp.time, false);
    var fattrs = ["featherSegLocs", "featherRelSegLocs", "featherRadii",
                  "featherTypes", "featherInterps", "featherTensions",
                  "featherRelCornerAngles"];
    for (var fi = 0; fi < fattrs.length; fi++) {
        var v = fshape[fattrs[fi]];
        say("  Shape." + fattrs[fi] + ": " +
            (v === undefined ? "undefined" :
             ("[" + v.toString() + "]  (length " + v.length + ")")));
    }
    say("");
    say("A non-empty featherRadii means AE CAN carry per-segment feather, and");
    say("prd.md must map it rather than collapsing Nuke feather to a mean.");
    say("Add feather points to the mask in the UI and re-run to see real values.");
    say("");
    say("Feather points and maskFeather COMPOSE - both are non-zero above if");
    say("the mask was set up as instructed, which means .rbj must carry both");
    say("layers, not choose between them. prd.md 9.3 currently treats them as");
    say("exclusive ('no feather points present -> uniform from the mean').");
    say("");
    say("All properties on this mask, for reference:");
    for (var mi = 1; mi <= mask.numProperties; mi++) {
        var pr = mask.property(mi);
        say("  [" + mi + "] " + pr.name + "  (matchName=" + pr.matchName + ")");
    }

    // ------------------------------------------- E2. feather, self-contained
    // Four AE runs failed to exercise uniform feather because it depends on
    // manual UI setup. Build our own mask instead and answer it outright.
    head("E2. Feather, on a mask this probe builds itself (prd.md 15 Q8)");
    var tmpF = null;
    try {
        tmpF = comp.layers.addSolid([0, 0, 1], "RB_PROBE_FEATHER",
            comp.width, comp.height, comp.pixelAspect);
        var mF = tmpF.property("ADBE Mask Parade").addProperty("ADBE Mask Atom");
        var pF = mF.property("ADBE Mask Shape");

        var sF = new Shape();
        sF.vertices = [[100, 100], [400, 100], [400, 400], [100, 400]];
        sF.closed = true;
        pF.setValue(sF);

        // --- 1. anisotropy: is [x,y] really independent per axis? ---
        mF.maskFeather.setValue([20, 5]);
        var fv = mF.maskFeather.value;
        say("1. anisotropic write [20,5] -> [" + fv.toString() + "]");
        say("   " + (fv[0] !== fv[1]
            ? "INDEPENDENT - x and y differ, so .rbj needs a 2-D field"
            : "COLLAPSED to " + fv[0] + " - AE forced them equal"));
        say("");

        // --- 2. does uniform feather animate? ---
        var tA = comp.displayStartTime;
        var tB = comp.displayStartTime + 100 / comp.frameRate;
        var tMid = (tA + tB) / 2;
        mF.maskFeather.setValueAtTime(tA, [10, 10]);
        mF.maskFeather.setValueAtTime(tB, [80, 80]);
        say("2. keyed [10,10]@" + tA + " -> [80,80]@" + tB +
            "; numKeys=" + mF.maskFeather.numKeys);
        say("   valueAtTime midpoint t=" + tMid + ": [" +
            mF.maskFeather.valueAtTime(tMid, false).toString() + "]");
        say("   " + (mF.maskFeather.numKeys > 0
            ? "ANIMATES - so uniform feather belongs in the dense frames layer,"
            : "static - reading it once per shape would be safe,"));
        say("   not read once per shape (prd.md 9.1 step 6, 9.2 step 7).");
        say("");

        // --- 3. can feather POINTS be written from script? ---
        // Everything so far only READ them. The AE importer has to write them,
        // and that path has never been exercised.
        var sG = new Shape();
        sG.vertices = [[100, 100], [400, 100], [400, 400], [100, 400]];
        sG.closed = true;
        sG.featherSegLocs = [0, 2];
        sG.featherRelSegLocs = [0.5, 0.25];
        sG.featherRadii = [30, -15];          // one outward, one inward
        sG.featherTypes = [0, 1];
        sG.featherInterps = [0, 0];
        sG.featherTensions = [0, 0];
        sG.featherRelCornerAngles = [0, 0];
        tryIt("3. write feather points then read back", function () {
            pF.setValue(sG);
            var back = pF.value;
            return "radii=[" + back.featherRadii.toString() +
                "] types=[" + back.featherTypes.toString() +
                "] relSegLocs=[" + back.featherRelSegLocs.toString() + "]";
        });
        say("   If radii come back [30,-15] the Nuke->AE per-point path works.");
        say("   If they come back empty or unsigned, prd.md 9.3's Nuke-to-AE");
        say("   rule is unimplementable and per-point feather is read-only.");
        say("");

        // --- 4. do the two layers compose? ---
        say("4. composition - feather points AND maskFeather on one mask:");
        say("   maskFeather now [" + mF.maskFeather.value.toString() +
            "], feather points length " +
            (pF.value.featherRadii ? pF.value.featherRadii.length : "n/a"));
        say("   Both non-empty => independent layers, .rbj carries both.");
        say("   Nuke case 62 already showed they are independent there.");
    } catch (eF) {
        say("E2 FAILED: " + eF.toString());
    }
    if (tmpF) {
        tmpF.remove();
    }
    say("");

    // ----------------------------------------------------------- F. transform
    head("F. sourcePointToComp under scale + rotation (prd.md 9.1 step 4)");
    var tmp = null;
    try {
        tmp = comp.layers.addSolid([1, 0, 0], "RB_PROBE_TMP",
            comp.width, comp.height, comp.pixelAspect);
        tmp.property("ADBE Transform Group").property("ADBE Scale").setValue([150, 220]);
        tmp.property("ADBE Transform Group").property("ADBE Rotate Z").setValue(30);
        tmp.property("ADBE Transform Group").property("ADBE Position").setValue([700, 400]);

        var vtx = [200, 300];
        var tan = [40, 0];

        // sourcePointToComp takes ONE argument and evaluates at the CURRENT
        // comp time, so the time must be set before converting each frame.
        var savedTime = comp.time;
        comp.time = 0;

        var vComp = tmp.sourcePointToComp(vtx);
        var vtComp = tmp.sourcePointToComp([vtx[0] + tan[0], vtx[1] + tan[1]]);
        var tanComp = [vtComp[0] - vComp[0], vtComp[1] - vComp[1]];
        var backV = tmp.compPointToSource(vComp);

        say("scale [150,220], rotation 30deg, position [700,400]");
        say("vertex  layer " + pair(vtx) + "  -> comp " + pair(vComp));
        say("vertex  comp  " + pair(vComp) + "  -> layer " + pair(backV));
        say("round-trip error: " + fmt(Math.abs(backV[0] - vtx[0])) + ", " +
            fmt(Math.abs(backV[1] - vtx[1])) + "  (want < 0.001)");
        say("");
        say("tangent " + pair(tan) + " via transform-then-subtract -> " + pair(tanComp));
        say("tangent length layer=" + fmt(Math.sqrt(tan[0] * tan[0] + tan[1] * tan[1])) +
            "  comp=" + fmt(Math.sqrt(tanComp[0] * tanComp[0] + tanComp[1] * tanComp[1])));
        say("");
        say("Expect the comp tangent to be rotated AND non-uniformly scaled.");
        say("If it merely equals the layer tangent, sourcePointToComp is not");
        say("applying the transform and the AE export needs rework.");

        // Animate the layer, then confirm the conversion tracks comp.time.
        var rot = tmp.property("ADBE Transform Group").property("ADBE Rotate Z");
        rot.setValueAtTime(0, 0);
        rot.setValueAtTime(2, 90);
        say("");
        say("With rotation animated 0deg@0s -> 90deg@2s, same layer point:");
        var tStart = new Date().getTime();
        for (var ti = 0; ti < 3; ti++) {
            comp.time = ti;
            say("  comp.time=" + ti + "s -> comp " + pair(tmp.sourcePointToComp(vtx)));
        }
        var reps = 100;
        var t1 = new Date().getTime();
        for (var tj = 0; tj < reps; tj++) {
            comp.time = (tj % 50) / comp.frameRate;
            tmp.sourcePointToComp(vtx);
        }
        var setCost = new Date().getTime() - t1;
        say("");
        say(reps + " x (set comp.time + sourcePointToComp) took " + setCost +
            " ms  (" + fmt(setCost / reps) + " ms each)");
        say("This is the real dense-bake cost - the export must set comp.time");
        say("per frame, so this dominates, not valueAtTime.");

        comp.time = savedTime;
    } catch (e) {
        say("FAILED - " + e.toString());
    }
    if (tmp) {
        tmp.remove();
    }

    app.endUndoGroup();

    // ------------------------------------------------- G. temporal ease read
    head("G. Temporal ease on maskPath keys (prd.md 7, tier 1)");
    say("AE ease = influence (%) + speed (value-units/sec). Only influence");
    say("normalizes across control points; see the .rbj ease param question.");
    if (path.numKeys === 0) {
        say("(no keys on this mask - key it and re-run to capture ease values)");
    }
    for (var e = 1; e <= path.numKeys && e <= 6; e++) {
        try {
            var ei = path.keyInTemporalEase(e);
            var eo = path.keyOutTemporalEase(e);
            say("  key " + e + " in : " + ei.length + " dim, [0] speed=" +
                fmt(ei[0].speed) + " influence=" + fmt(ei[0].influence));
            say("  key " + e + " out: " + eo.length + " dim, [0] speed=" +
                fmt(eo[0].speed) + " influence=" + fmt(eo[0].influence));
        } catch (err) {
            say("  key " + e + ": FAILED - " + err.toString());
        }
    }
    say("");
    say("Note the dimension count above. If ease is 1-D on a shape property,");
    say("a single shape-wide ease is what .rbj must store.");

    // ------------------------------------------- H. write round-trip + timing
    head("H. Key write round-trip and drift-pass cost (prd.md 15 Q6)");
    var tmp2 = null;
    try {
        tmp2 = comp.layers.addSolid([0, 1, 0], "RB_PROBE_TMP2",
            comp.width, comp.height, comp.pixelAspect);
        var m2 = tmp2.property("ADBE Mask Parade").addProperty("ADBE Mask Atom");
        var p2 = m2.property("ADBE Mask Shape");

        var sA = new Shape();
        sA.vertices = [[100, 100], [300, 100], [300, 300], [100, 300]];
        sA.closed = true;
        var sB = new Shape();
        sB.vertices = [[500, 200], [700, 200], [700, 400], [500, 400]];
        sB.closed = true;

        var f0 = comp.displayStartTime;
        var f100 = comp.displayStartTime + 100 / comp.frameRate;
        p2.setValueAtTime(f0, sA);
        p2.setValueAtTime(f100, sB);
        say("set 2 keys; numKeys now = " + p2.numKeys);

        tryIt("setInterpolationTypeAtKey(1, BEZIER)", function () {
            p2.setInterpolationTypeAtKey(1, KeyframeInterpolationType.BEZIER);
            return "ok, reads back as " + p2.keyInInterpolationType(1);
        });
        tryIt("setInterpolationTypeAtKey(1, HOLD)  ", function () {
            p2.setInterpolationTypeAtKey(1, KeyframeInterpolationType.HOLD);
            return "ok, reads back as " + p2.keyInInterpolationType(1);
        });

        // midpoint value under LINEAR: the drift pass reads exactly like this
        p2.setInterpolationTypeAtKey(1, KeyframeInterpolationType.LINEAR);
        p2.setInterpolationTypeAtKey(2, KeyframeInterpolationType.LINEAR);
        var mid = p2.valueAtTime(comp.displayStartTime + 50 / comp.frameRate, false);
        say("");
        say("midpoint vertex 0 under LINEAR: " + pair(mid.vertices[0]) +
            "   (halfway between [100,100] and [500,200] = [300,150])");

        var t0 = new Date().getTime();
        var samples = 100;
        for (var q = 0; q < samples; q++) {
            p2.valueAtTime(comp.displayStartTime + q / comp.frameRate, false);
        }
        var elapsed = new Date().getTime() - t0;
        say("");
        say(samples + " valueAtTime read-backs took " + elapsed + " ms  (" +
            fmt(elapsed / samples) + " ms each)");
        say("Extrapolate: a 150-frame shape needs ~150 reads per drift iteration");
        say("per shape. That is the prd.md 15 Q6 budget.");
    } catch (err) {
        say("FAILED - " + err.toString());
    }
    if (tmp2) {
        tmp2.remove();
    }

    // -------------------------------------------------------------- Z. output
    var report = "RotoBridge Phase 0 probe - After Effects\n" + lines.join("\n") + "\n";
    var f = File.saveDialog("Save probe report", "*.txt");
    if (f) {
        if (f.name.indexOf(".") === -1) {
            f = new File(f.fsName + ".txt");
        }
        f.open("w");
        f.write(report);
        f.close();
        alert("Probe complete.\n\nReport written to:\n" + f.fsName);
    } else {
        alert(report);
    }
})();
