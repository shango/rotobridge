/*
 * RotoBridge - After Effects panel. Two buttons over the two adapters.
 *
 * It does not reimplement them and does not ask for anything they ask for.
 * Each button evaluates the adapter file exactly as `File > Scripts > Run
 * Script File...` does, so what the panel runs is what the acceptance runs
 * have measured. A panel that collected its own parameters and passed them in
 * would be a second entry point to keep in step with the first, and the first
 * is the one every test and every host run goes through.
 *
 * Two ways to use it:
 *
 *   Quick, no install. Keep this file beside the five `rotobridge_*.jsx` and
 *   open it with `File > Scripts > Run Script File...`. It comes up as a
 *   floating palette.
 *
 *   Docked. Copy this file into `Scripts/ScriptUI Panels/` - rename the copy
 *   `RotoBridge.jsx` if you want that name in the Window menu, since After
 *   Effects labels the entry with the file name - and put the five adapters in
 *   a `rotobridge` folder beside it. AE lists every .jsx sitting *directly* in
 *   `ScriptUI Panels`, so keeping the adapters one level down is what stops
 *   five more entries appearing in the Window menu. The panel looks in that
 *   subfolder second, which is why the layout works with no configuration.
 *
 * **The panel shows the folder it is running from, and that is the point of
 * the footer.** The recurring failure in this project is a stale deployment:
 * the scripts run on the Windows side and the acceptance checks run in WSL,
 * nothing connects them, and an export from a copy one commit behind produces
 * a plausible file, a plausible alert and a diff whose natural reading is that
 * the fixture moved. It has happened. Being able to read the path off the
 * panel is the cheapest version of the `diff` that `test/probe/README.md`
 * insists on before every re-export.
 *
 * ES3 only, like every other script in this project - no let/const, no JSON,
 * no Array.forEach, no Array.indexOf.
 */

(function (thisObj) {
    var SECTION = "RotoBridge";
    var FOLDER_KEY = "scriptsFolder";
    var EXPORT = "rotobridge_export.jsx";
    var IMPORT = "rotobridge_import.jsx";

    /* Captured at load, deliberately. `$.fileName` inside a button callback
     * reports whatever is being evaluated at that moment, which after the
     * first click is an adapter rather than this file. */
    var HERE = File($.fileName).parent;

    function holdsAdapters(folder) {
        /* Both, not either. A folder with one of them is a half-copied
         * deployment, which is worth refusing rather than half-running. */
        return folder !== null && folder.exists
            && File(folder.fsName + "/" + EXPORT).exists
            && File(folder.fsName + "/" + IMPORT).exists;
    }

    function remembered() {
        if (!app.settings.haveSetting(SECTION, FOLDER_KEY)) { return null; }
        return new Folder(app.settings.getSetting(SECTION, FOLDER_KEY));
    }

    function locate() {
        /* Beside this file, then the `rotobridge` subfolder a docked install
         * uses, then wherever the artist pointed us last time. */
        var candidates = [HERE,
                          new Folder(HERE.fsName + "/rotobridge"),
                          remembered()];
        for (var i = 0; i < candidates.length; i++) {
            if (holdsAdapters(candidates[i])) { return candidates[i]; }
        }
        return null;
    }

    function chooseFolder() {
        var picked = Folder.selectDialog("Where are the RotoBridge scripts?"
                                         + " Pick the folder holding "
                                         + EXPORT);
        if (picked === null) { return null; }
        if (!holdsAdapters(picked)) {
            alert("That folder does not hold both adapters.\n\n"
                  + picked.fsName + "\n\nIt needs " + EXPORT + " and "
                  + IMPORT + ", and the three files they include.",
                  "RotoBridge");
            return null;
        }
        app.settings.saveSetting(SECTION, FOLDER_KEY, picked.fsName);
        return picked;
    }

    function run(folder, name) {
        var script = new File(folder.fsName + "/" + name);
        if (!script.exists) {
            /* Reachable: the folder held both adapters when the panel opened
             * and does not now. Say which file, not "something went wrong". */
            alert("Missing script:\n\n" + script.fsName, "RotoBridge");
            return;
        }
        /* The same call `Run Script File...` makes. Both adapters catch their
         * own failures and report them, so what reaches this catch is the file
         * failing to evaluate at all. */
        try {
            $.evalFile(script);
        } catch (e) {
            alert("RotoBridge could not run " + name + ":\n\n"
                  + (e.message || e)
                  + (e.line ? "\n\n(line " + e.line + ")" : ""), "RotoBridge");
        }
    }

    function build(host) {
        var win = (host instanceof Panel)
            ? host
            : new Window("palette", "RotoBridge", undefined,
                         { resizeable: true });
        win.orientation = "column";
        win.alignChildren = ["fill", "top"];
        win.spacing = 8;
        win.margins = 12;

        var exportBtn = win.add("button", undefined, "Export masks to .rbj");
        var importBtn = win.add("button", undefined,
                                "Import .rbj into this comp");

        var foot = win.add("group");
        foot.orientation = "row";
        foot.alignChildren = ["fill", "center"];
        foot.spacing = 6;
        var where = foot.add("statictext", undefined, "",
                             { truncate: "middle" });
        where.alignment = ["fill", "center"];
        var change = foot.add("button", undefined, "Change...");
        change.preferredSize.width = 84;

        var folder = locate();

        function refresh() {
            var found = folder !== null;
            where.text = found
                ? "scripts: " + folder.fsName
                : "scripts not found - use Change...";
            exportBtn.enabled = found;
            importBtn.enabled = found;
        }
        refresh();

        /* Both, because the two modes fire different ones: a docked Panel gets
         * `onResizing` as the dock is dragged, a palette gets `onResize` when
         * the drag ends. Without this the children keep the size they were laid
         * out at, which in the docked mode the header recommends means the
         * footer path stops filling the panel and stops re-truncating with it -
         * and reading that path is the whole reason the footer is there. */
        win.onResizing = win.onResize = function () { this.layout.resize(); };

        exportBtn.onClick = function () { run(folder, EXPORT); };
        importBtn.onClick = function () { run(folder, IMPORT); };
        change.onClick = function () {
            var picked = chooseFolder();
            if (picked !== null) { folder = picked; refresh(); }
        };

        return win;
    }

    var panel = build(thisObj);
    if (panel instanceof Window) {
        panel.center();
        panel.show();
    } else {
        panel.layout.layout(true);
    }
}(this));
