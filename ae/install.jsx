/*
 * RotoBridge - After Effects installer. Run once, from anywhere.
 *
 * Open this file with `File > Scripts > Run Script File...` and it copies the
 * panel and its five adapters into the version of After Effects that is
 * running, in the per-user scripts folder Adobe added in 17.1:
 *
 *     %APPDATA%\Adobe\After Effects\<major.minor>\Scripts\ScriptUI Panels
 *
 * That folder needs no administrator rights, and everything in it appears in
 * the Window menu as a dockable panel. After a restart, RotoBridge is a menu
 * item and nobody browses for a script file again - which is the point.
 * Running a newer installer over an older install replaces it, so this is
 * also the update path; the closing alert says which version it replaced.
 *
 * The payload is whatever sits beside this file: `rotobridge_panel.jsx` and
 * the `lib` folder. The installer reads the version out of the panel rather
 * than carrying its own copy, so it cannot report a number the panel would
 * not.
 *
 * ES3 only, like every other script in this project - no let/const, no JSON,
 * no Array.forEach, no Array.indexOf.
 */

(function () {
    var TITLE = "RotoBridge installer";
    var PANEL = "rotobridge_panel.jsx";
    /* The name the panel takes on when installed. After Effects labels the
     * Window-menu entry with the file name, and `RotoBridge.jsx` reads better
     * there than the payload name does. */
    var INSTALLED_AS = "RotoBridge.jsx";
    var LIB = "lib";
    var ADAPTERS = ["rotobridge_ae.jsx", "rotobridge_core.jsx",
                    "rotobridge_export.jsx", "rotobridge_import.jsx",
                    "rotobridge_rbj.jsx"];

    var PREF_PATH = "Edit > Preferences > Scripting & Expressions >\n"
        + "Allow Scripts to Write Files and Access Network";

    var HERE = File($.fileName).parent;

    function fail(message) {
        alert(message, TITLE);
        /* A thrown string stops the script without ExtendScript's "error
         * dialog on top of our alert" habit that Error objects trigger in
         * some hosts. */
        throw new Error(message);
    }

    function canWriteFiles() {
        /* Same probe as the panel, for the same reason: measured, not asked.
         * The preference section holding the setting has been renamed across
         * releases, so reading it can lie; writing a file cannot. */
        var probe = new File(Folder.temp.fsName + "/rotobridge_write_probe.txt");
        try {
            if (!probe.open("w")) { return false; }
            probe.write("RotoBridge");
            probe.close();
            probe.remove();
            return true;
        } catch (e) {
            return false;
        }
    }

    function versionIn(file) {
        /* The panel declares `var VERSION = "X.Y.Z";` near the top; the
         * installed copy did too. Null when the file is unreadable or the
         * line is not there, and the caller words around that. */
        var text, match;
        try {
            if (!file.exists || !file.open("r")) { return null; }
            text = file.read();
            file.close();
        } catch (e) {
            return null;
        }
        match = text.match(/var VERSION = "([0-9.]+)"/);
        return match ? match[1] : null;
    }

    function mustCopy(src, destPath) {
        if (!src.copy(destPath)) {
            fail("Could not copy\n\n" + src.fsName + "\n\nto\n\n" + destPath
                 + "\n\nIs After Effects allowed to write files?\n\n"
                 + PREF_PATH);
        }
    }

    /* -- The payload ------------------------------------------------------ */

    var payloadPanel = new File(HERE.fsName + "/" + PANEL);
    var payloadLib = new Folder(HERE.fsName + "/" + LIB);
    var missing = [];
    if (!payloadPanel.exists) { missing[missing.length] = PANEL; }
    for (var i = 0; i < ADAPTERS.length; i++) {
        if (!File(payloadLib.fsName + "/" + ADAPTERS[i]).exists) {
            missing[missing.length] = LIB + "/" + ADAPTERS[i];
        }
    }
    if (missing.length > 0) {
        fail("This installer copies the files sitting next to it, and "
             + (missing.length === 1 ? "one is" : missing.length + " are")
             + " missing:\n\n" + missing.join("\n")
             + "\n\nUnzip the whole download first, then run this from the"
             + " unzipped copy - Windows will not let it work from inside"
             + " the .zip.");
    }

    var version = versionIn(payloadPanel);

    if (!canWriteFiles()) {
        fail("After Effects is not allowed to write files, so nothing can be"
             + " installed - and RotoBridge itself needs the permission"
             + " anyway, to write the .rbj.\n\nTurn this preference on and"
             + " run the installer again:\n\n" + PREF_PATH);
    }

    /* -- The destination -------------------------------------------------- */

    /* `app.version` reads like "25.6x101"; the per-user folder is named by
     * the part before the build suffix. Everything up to `Adobe/After
     * Effects/<major.minor>` already exists - the running AE keeps its
     * preferences there - so only `Scripts/ScriptUI Panels` may need
     * creating, and `Folder.create` makes one level at a time. */
    var appFolder = app.version.match(/^\d+\.\d+/)[0];
    var base = new Folder(Folder.userData.fsName + "/Adobe/After Effects/"
                          + appFolder);
    if (!base.exists) {
        fail("Expected this folder to exist, and it does not:\n\n"
             + base.fsName + "\n\nThat is worth a bug report as it stands,"
             + " with your After Effects version (" + app.version
             + ") in it.");
    }
    var scripts = new Folder(base.fsName + "/Scripts");
    var target = new Folder(scripts.fsName + "/ScriptUI Panels");
    if ((!scripts.exists && !scripts.create())
            || (!target.exists && !target.create())) {
        fail("Could not create:\n\n" + target.fsName);
    }

    if (target.fsName.toLowerCase() === HERE.fsName.toLowerCase()) {
        fail("This installer is already running from the installed location:"
             + "\n\n" + target.fsName + "\n\nNothing to do. To update, run"
             + " the installer from a newly unzipped download instead.");
    }

    /* -- What is being replaced, before it is gone ------------------------ */

    var existing = new File(target.fsName + "/" + INSTALLED_AS);
    var oldName = new File(target.fsName + "/" + PANEL);
    var replaced = versionIn(existing) || versionIn(oldName);

    /* -- Install ---------------------------------------------------------- */

    mustCopy(payloadPanel, target.fsName + "/" + INSTALLED_AS);

    /* A hand-made install may have left the panel under its payload name;
     * with the copy above in place that would put two RotoBridge entries in
     * the Window menu, so the old spelling goes. */
    if (oldName.exists) { oldName.remove(); }

    var targetLib = new Folder(target.fsName + "/" + LIB);
    if (!targetLib.exists && !targetLib.create()) {
        fail("Could not create:\n\n" + targetLib.fsName);
    }
    /* Mirror, not merge, like the Nuke installer's /MIR: reinstalling an
     * older build must leave nothing of a newer one behind. Only .jsx files
     * are swept - the folder is ours, but a stray note someone kept in it
     * is not. */
    var stale = targetLib.getFiles("*.jsx");
    for (i = 0; i < stale.length; i++) { stale[i].remove(); }
    for (i = 0; i < ADAPTERS.length; i++) {
        mustCopy(new File(payloadLib.fsName + "/" + ADAPTERS[i]),
                 targetLib.fsName + "/" + ADAPTERS[i]);
    }

    /* -- Report ----------------------------------------------------------- */

    alert("Installed RotoBridge " + (version || "(version unknown)")
          + (replaced ? ", replacing " + replaced + "," : "") + " to:\n\n"
          + target.fsName
          + "\n\nRestart After Effects, then open it from the Window menu:"
          + "\n\nWindow > RotoBridge.jsx", TITLE);
}());
