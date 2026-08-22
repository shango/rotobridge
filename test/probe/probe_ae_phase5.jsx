/*
 * The one After Effects visit this project has left.
 *
 * Everything still open in RotoBridge needs a person in front of After
 * Effects, and it is four separate things. Four visits is three too many, so
 * this does all of them in one run and writes one report.
 *
 *   1. The Phase 5 matte. `test/test_ae_to_nuke_render.py` measures Nuke's
 *      matte in the unit acceptance criterion 2 is written in and has never
 *      had an After Effects matte to measure against. This builds the render
 *      queue item, configures the output module, renders if you say so, and
 *      then reads the folder back to report the exact pattern and frame offset
 *      to hand the Nuke test. The settings are the part worth scripting: a
 *      sequence with no alpha, or a premultiplied one, or one carrying the
 *      wrong layers, produces a difference that measures the render rather
 *      than the geometry - and that difference is not small, so it reads as a
 *      Phase 5 failure rather than as a mistake in the setup.
 *   2. `File.open("a")`. The import record appends, and appending is the one
 *      call in the adapters no test can reach: `test/ae_mock.js` honours "a"
 *      because the JavaScript Tools Guide documents it, not because a host has
 *      ever done it.
 *   3. The `mixed` mask's hold key. `setTemporalEaseAtKey` forces a key to
 *      BEZIER and the importer sets the per-side types afterwards. If that
 *      ordering fails the symptom is a hold that renders smooth, and the drift
 *      pass corrects the positions either way - so no number in the import
 *      report can show it. It has to be read off the key.
 *   4. The eight-shape golden, which needs no code and is at the end of the
 *      report.
 *
 * Sections 2 and 3 are read-only. Section 1 adds a render queue item and, if
 * you let it, renders. Nothing here touches a mask.
 *
 * Run: File > Scripts > Run Script File...
 * Needs the comp `test/probe/setup_ae_scene.jsx` built, open and frontmost.
 *
 * ES3 only - no JSON, no let/const, no Array.indexOf, no Array.forEach.
 */

(function () {
    var FIRST = 0, LAST = 24;
    var SCENE_LAYER = "RotoBridge test";
    var BASENAME = "ae_matte_";

    var lines = [];
    var summary = [];

    function say(s) { lines.push(s === undefined ? "" : s); }
    function head(s) { say(""); say("=== " + s + " ==="); say(""); }
    function both(s) { say(s); summary.push(s); }

    function attempt(label, fn) {
        /* A step that fails is a result, not a reason to abandon the other
         * three sections. Every host call in here is wrapped, because the
         * point of the run is to come back with answers rather than with one
         * exception. */
        try {
            fn();
            return true;
        } catch (e) {
            say("  FAILED - " + label + ": " + (e.message || e));
            return false;
        }
    }

    function dump(obj, indent) {
        /* Whatever the host has, rather than the keys this script expects.
         * `getSettings` returns nested objects one level deep. */
        var key, value;
        for (key in obj) {
            if (!obj.hasOwnProperty(key)) { continue; }
            value = obj[key];
            if (value !== null && typeof value === "object"
                && !(value instanceof Array)) {
                say(indent + key + ":");
                dump(value, indent + "  ");
            } else {
                say(indent + key + " = " + String(value));
            }
        }
    }

    var comp = app.project.activeItem;
    if (!comp || !(comp instanceof CompItem)) {
        alert("Open the RotoBridge test comp first.");
        return;
    }

    function t(frame) {
        return comp.displayStartTime + frame / comp.frameRate;
    }

    function frameOf(time) {
        return Math.round((time - comp.displayStartTime) * comp.frameRate);
    }

    say("RotoBridge - the last After Effects run");
    say("");
    say("After Effects " + app.version);
    say("comp          " + comp.name + "  " + comp.width + "x" + comp.height
        + "  " + comp.frameRate + " fps  pixel aspect " + comp.pixelAspect);
    say("project       " + (app.project.file ? app.project.file.fsName
                                             : "(never saved)"));

    /* ------------------------------------------------------------------ 1 */

    head("1. the Phase 5 matte");

    /* Colour management is reported rather than changed. The comparison in
     * `test_ae_to_nuke_render.py` is against ALPHA, and no working space
     * transform touches the alpha channel - so this cannot move the number,
     * and silently rewriting a project setting to fix something it does not
     * affect would be worse than saying what it is. */
    attempt("read the project colour settings", function () {
        say("  working space    "
            + (app.project.workingSpace === "" ? "(none)"
                                               : app.project.workingSpace));
        say("  bits per channel " + app.project.bitsPerChannel);
        say("  linear blending  " + app.project.linearBlending);
    });
    say("  The comparison is against alpha, which no working space transform");
    say("  touches, so none of the three above can move the measurement.");
    say("");

    var target = null;
    var others = [];
    var i, k;
    for (i = 1; i <= comp.numLayers; i++) {
        var layer = comp.layer(i);
        if (layer.name === SCENE_LAYER) { target = layer; }
        else { others.push(layer); }
    }

    if (!target) {
        both("  NO LAYER NAMED '" + SCENE_LAYER + "'. Section 1 skipped.");
        say("  test/golden/ae_scene.rbj is an export of that layer's six");
        say("  masks. Rendering a comp that does not contain it would compare");
        say("  Nuke's matte against something else entirely.");
    }

    var rendered = false;
    var pattern = null;
    var offset = 0;
    var soloed = [];

    if (target) {
        /* Solo, and this is not a nicety. The comp also carries 'RotoBridge
         * static' with masks 7 and 8, and may carry an imported 'RotoBridge'
         * layer from an earlier run. None of their shapes are in
         * ae_scene.rbj, so their alpha would be measured as Nuke having lost
         * geometry it was never given. */
        for (i = 0; i < others.length; i++) {
            if (others[i].solo) { soloed.push(others[i]); }
            attempt("unsolo " + others[i].name, function () {
                others[i].solo = false;
            });
        }
        var wasSolo = target.solo;
        attempt("solo " + SCENE_LAYER, function () { target.solo = true; });
        say("  soloed '" + SCENE_LAYER + "' - " + others.length
            + " other layer(s) held out of the render");

        comp.workAreaStart = t(FIRST);
        comp.workAreaDuration = (LAST - FIRST + 1) / comp.frameRate;
        say("  work area        frames " + FIRST + " to " + LAST);

        var folder = Folder.selectDialog("Where should the matte sequence go?");
        if (!folder) {
            both("  NO OUTPUT FOLDER CHOSEN. Section 1 stopped before the"
                 + " render queue.");
        } else {
            var rq = app.project.renderQueue;
            var item = rq.items.add(comp);
            item.render = true;
            attempt("set the render time span", function () {
                item.timeSpanStart = t(FIRST);
                item.timeSpanDuration = (LAST - FIRST + 1) / comp.frameRate;
            });
            attempt("applyTemplate('Best Settings')", function () {
                item.applyTemplate("Best Settings");
            });

            var om = item.outputModule(1);
            say("");
            say("  output module templates this host offers:");
            var templates = om.templates;
            var chosen = null, ext = null;
            for (i = 0; i < templates.length; i++) {
                say("    " + templates[i]);
                if (chosen === null && /exr/i.test(templates[i])) {
                    chosen = templates[i];
                    ext = ".exr";
                }
            }
            if (chosen === null) {
                for (i = 0; i < templates.length; i++) {
                    if (/png/i.test(templates[i])) {
                        chosen = templates[i];
                        ext = ".png";
                        break;
                    }
                }
            }
            say("");
            if (chosen === null) {
                both("  NO EXR OR PNG TEMPLATE. Set the format by hand: the"
                     + " sequence must carry a straight alpha.");
                ext = ".exr";
            } else {
                say("  applying template " + chosen);
                if (attempt("applyTemplate('" + chosen + "')", function () {
                        om.applyTemplate(chosen);
                    })) {
                    /* Documented: the OutputModule object is invalidated by a
                     * settings change and has to be fetched again. The same
                     * hazard as the stale mask handles that broke the first
                     * multi-shape import, in a different API. */
                    om = item.outputModule(1);
                }
            }

            /* Format is readable and not settable, which is why the template
             * above is what picks it. Channels and Color are settable and are
             * the two that decide whether the file carries an alpha at all and
             * whether it is straight. They are set separately so that a host
             * refusing one still applies the other. */
            attempt("Channels = RGB + Alpha", function () {
                om.setSettings({ "Channels": "RGB + Alpha" });
                om = item.outputModule(1);
            });
            attempt("Color = Straight (Unmatted)", function () {
                om.setSettings({ "Color": "Straight (Unmatted)" });
                om = item.outputModule(1);
            });

            var path = folder.fsName + "/" + BASENAME + "[####]" + ext;
            attempt("set the output path", function () {
                om.file = new File(path);
                om = item.outputModule(1);
            });

            say("");
            say("  output module settings, as the host reports them back:");
            attempt("read the output module settings", function () {
                dump(om.getSettings(GetSettingsFormat.STRING), "    ");
            });
            say("");
            say("  file             " + om.file.fsName);
            say("  time span        frame " + frameOf(item.timeSpanStart)
                + " for " + Math.round(item.timeSpanDuration * comp.frameRate)
                + " frame(s)");
            say("");

            var go = confirm("Render " + (LAST - FIRST + 1)
                + " frames now?\n\nAfter Effects will be busy until it"
                + " finishes.\n\nNo leaves the item in the render queue,"
                + " configured, for you to start by hand.");
            if (go) {
                if (attempt("render", function () { rq.render(); })) {
                    rendered = true;
                }
            } else {
                both("  RENDER NOT STARTED. The queue item is configured;"
                     + " press Render.");
            }

            if (rendered) {
                /* Read the folder rather than predict it. Whether After
                 * Effects numbers by the comp's frames or from zero is a
                 * setting, and the Nuke test takes an offset for exactly this
                 * reason - so measure the numbering instead of assuming it. */
                var written = folder.getFiles(function (f) {
                    return (f instanceof File)
                        && f.name.substring(0, BASENAME.length) === BASENAME;
                });
                written.sort();
                say("  wrote            " + written.length + " file(s)");
                if (written.length) {
                    say("  first            " + written[0].name);
                    say("  last             "
                        + written[written.length - 1].name);
                    var digits = String(written[0].name).match(
                        /([0-9]+)\.[A-Za-z]+$/);
                    if (digits) {
                        var hashes = "";
                        for (i = 0; i < digits[1].length; i++) {
                            hashes += "#";
                        }
                        pattern = folder.fsName + "\\" + BASENAME + hashes
                                  + ext;
                        offset = Number(digits[1]) - FIRST;
                    }
                }
                if (written.length !== LAST - FIRST + 1) {
                    both("  WROTE " + written.length + " FILES, EXPECTED "
                         + (LAST - FIRST + 1) + ".");
                }
                /* Solo was this script's doing and only for the render. */
                attempt("unsolo " + SCENE_LAYER, function () {
                    target.solo = wasSolo;
                });
                for (i = 0; i < soloed.length; i++) {
                    attempt("re-solo " + soloed[i].name, function () {
                        soloed[i].solo = true;
                    });
                }
                say("  solo restored to what it was before this ran");
            } else {
                both("  '" + SCENE_LAYER + "' IS LEFT SOLOED so that the"
                     + " render is of that layer alone. Unsolo it afterwards.");
            }
        }
    }

    say("");
    if (pattern) {
        both("  matte written. Hand it to the Nuke test:");
        say("");
        say("    \"/mnt/c/Program Files/Nuke17.1v1/Nuke17.1.exe\" --nc -t \\");
        say("        \"C:\\Users\\shann\\rotobridge\\rb\\test"
            + "\\test_ae_to_nuke_render.py\" \\");
        say("        \"C:\\Users\\shann\\rotobridge\\out\\run\" \\");
        say("        \"" + pattern + "\" " + offset);
        say("");
        say("  Sync the repo to that folder first - the block is in");
        say("  test/probe/README.md under 'Phase 5 render'.");
    } else {
        say("  No pattern to report. Section 4 of the Nuke test stays NOT RUN");
        say("  and Phase 5 stays open.");
    }

    /* ------------------------------------------------------------------ 2 */

    head("2. does File.open(\"a\") append in this host");

    var probe = new File(Folder.temp.fsName + "/rotobridge_append_probe.txt");
    attempt("remove an earlier probe file", function () {
        if (probe.exists) { probe.remove(); }
    });

    function append(text) {
        probe.encoding = "UTF-8";
        if (!probe.open("a")) {
            throw new Error("open(\"a\") refused: " + probe.error);
        }
        probe.write(text);
        probe.close();
    }

    var appended = attempt("append twice", function () {
        append("first record\n");
        append("second record\n");
    });

    if (appended) {
        var back = "";
        attempt("read it back", function () {
            probe.encoding = "UTF-8";
            probe.open("r");
            back = probe.read();
            probe.close();
        });
        say("  file             " + probe.fsName);
        say("  read back        " + back.length + " character(s)");
        if (back === "first record\nsecond record\n") {
            both("  APPEND WORKS. Both records are there, in order. The"
                 + " import record is sound.");
        } else if (back === "second record\n") {
            both("  APPEND OVERWRITES. \"a\" truncates in this host, so every"
                 + " import erases the record of the last one.");
            say("  The fix is read-then-write through ae.readText /");
            say("  ae.writeText in ae/rotobridge_ae.jsx - appendText is the");
            say("  only function that changes.");
        } else {
            both("  APPEND DID SOMETHING ELSE. Read the file itself.");
            say("  got: " + back);
        }
        attempt("tidy up", function () { probe.remove(); });
    } else {
        both("  open(\"a\") FAILED OUTRIGHT. See ae.appendText.");
    }

    /* ------------------------------------------------------------------ 3 */

    head("3. the mixed mask's hold key");

    say("  test/golden/ae_scene.rbj says mixed's key at frame 18 is");
    say("  {in: ease, out: hold}. On an imported mask that outgoing side must");
    say("  still be HOLD. If it reads BEZIER, setInterpolationTypeAtKey lost");
    say("  what setTemporalEaseAtKey had just set, and the mask renders");
    say("  smooth through an interval the artist froze.");
    say("");
    say("  The authored mask on '" + SCENE_LAYER + "' has three keys; an");
    say("  imported one has five. That is how to tell them apart below.");
    say("");

    function typeName(type) {
        if (type === KeyframeInterpolationType.LINEAR) { return "LINEAR"; }
        if (type === KeyframeInterpolationType.BEZIER) { return "BEZIER"; }
        if (type === KeyframeInterpolationType.HOLD) { return "HOLD"; }
        return String(type);
    }

    var found = 0;
    for (i = 1; i <= comp.numLayers; i++) {
        var lay = comp.layer(i);
        var group = null;
        attempt("read the masks of " + lay.name, function () {
            group = lay.property("ADBE Mask Parade");
        });
        if (!group) { continue; }
        for (var m = 1; m <= group.numProperties; m++) {
            var mask = group.property(m);
            if (mask.name !== "mixed") { continue; }
            found++;
            var prop = mask.property("ADBE Mask Shape");
            say("  layer '" + lay.name + "', mask '" + mask.name + "' - "
                + prop.numKeys + " key(s)");
            for (k = 1; k <= prop.numKeys; k++) {
                var frame = frameOf(prop.keyTime(k));
                var line = "    frame " + frame
                    + "   in " + typeName(prop.keyInInterpolationType(k))
                    + "   out " + typeName(prop.keyOutInterpolationType(k));
                attempt("read the ease at key " + k, function () {
                    var easeIn = prop.keyInTemporalEase(k)[0];
                    var easeOut = prop.keyOutTemporalEase(k)[0];
                    line += "   ease in " + easeIn.influence + "/"
                            + easeIn.speed + " out " + easeOut.influence + "/"
                            + easeOut.speed;
                });
                say(line);
                if (frame === 18) {
                    if (prop.keyOutInterpolationType(k)
                        === KeyframeInterpolationType.HOLD) {
                        both("  '" + lay.name + "' mixed: frame 18 is STILL A"
                             + " HOLD on its way out.");
                    } else {
                        both("  '" + lay.name + "' mixed: frame 18 is NOT a"
                             + " hold - it is "
                             + typeName(prop.keyOutInterpolationType(k))
                             + ". The ease-then-type ordering lost it.");
                    }
                }
            }
            say("");
        }
    }
    if (!found) {
        both("  NO MASK NAMED 'mixed'. Import test/golden/ae_scene.rbj and run"
             + " this again.");
    }

    /* ------------------------------------------------------------------ 4 */

    head("4. the eight-shape golden, if you want it");

    say("  Optional and not blocking. test/golden/ae_scene.rbj is a SIX-shape");
    say("  export and predates masks 7 and 8, whose export is a separate");
    say("  golden (ae_static_ease.rbj). Folding them in needs no script: the");
    say("  exporter already gathers every layer that carries a mask.");
    say("");
    say("  Run ae/rotobridge_export.jsx over this comp with nothing selected,");
    say("  save over test/golden/ae_scene.rbj, and re-run");
    say("  test/test_ae_to_nuke.py, which reads that file. The matte above");
    say("  would then need re-rendering with both layers in it.");

    /* ---------------------------------------------------------------------- */

    var reportFile = new File(
        (app.project.file ? app.project.file.parent.fsName
                          : Folder.desktop.fsName)
        + "/rotobridge_phase5_probe.txt");
    var wrote = attempt("write the report", function () {
        reportFile.encoding = "UTF-8";
        reportFile.open("w");
        reportFile.write(lines.join("\n") + "\n");
        reportFile.close();
    });

    alert((summary.length ? summary.join("\n\n") : "Nothing to report.")
          + "\n\n" + (wrote ? "Full report: " + reportFile.fsName
                            : "The report could not be written; it is above."),
          "RotoBridge");
}());
