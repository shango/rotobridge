/*
 * RotoBridge - dev launcher. Not in the drop; this machine only.
 *
 * Sits in `ScriptUI Panels` in place of a copied panel and evaluates the real
 * panel straight out of the repo over the WSL share, with `this` rebound so
 * it still docks. A copy in AppData goes stale the moment the repo moves -
 * it happened, and diagnosing it cost a day - so the launcher's whole job is
 * to make sure the only panel that can open is the one in the repo.
 *
 * It also points the panel's remembered scripts folder at the repo `lib` on
 * every launch, for the same reason: the repo is the only home.
 */

(function (thisObj) {
    var REPO = "\\\\wsl.localhost\\Ubuntu-24.04\\home\\sgold\\dev\\repos"
        + "\\rotobridge";
    var panel = new File(REPO + "\\ae\\rotobridge_panel.jsx");
    if (!panel.exists) {
        alert("RotoBridge dev launcher: cannot reach the repo panel at\n\n"
              + panel.fsName + "\n\nIs WSL running?", "RotoBridge dev");
        return;
    }
    app.settings.saveSetting("RotoBridge", "scriptsFolder",
                             REPO + "\\ae\\lib");
    panel.encoding = "UTF8";
    if (!panel.open("r")) {
        alert("RotoBridge dev launcher: the repo panel exists but could not"
              + " be opened:\n\n" + panel.fsName, "RotoBridge dev");
        return;
    }
    var text = panel.read();
    panel.close();
    /* `$.evalFile` would leave the evaluated file's top-level `this` as the
     * global, and the panel docks only when its closing `(this)` is the
     * Panel object - so evaluate with `this` rebound instead. */
    (function () { eval(text); }).call(thisObj);
}(this));
