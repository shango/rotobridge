"""Open a real After Effects export in Nuke. The AE-to-Nuke crossing.

Needs Nuke. Invocation is in test/probe/README.md under "AE to Nuke crossing".

Nothing else does this. `test/test_ae_crossapp.js` goes Nuke -> AE at the
document level with no host at all, and every Nuke round trip is Nuke -> Nuke,
which returns what it was given even if a convention were wrong at both ends.
This is the other direction and it uses a real host, so it is what decides
acceptance criterion 10 - "a .rbj written by either adapter is readable by the
other with no manual editing".

The source is `test/golden/ae_scene.rbj`, the real export After Effects wrote
from `test/probe/setup_ae_scene.jsx` on 2026-08-21.

**It imports three times on purpose**, because each mode answers a different
question and none of them answers another's:

- tolerance 0 is dense mode, so every frame is a key by definition (prd.md
  section 8). It says everything about geometry and nothing about keys.
- tolerance 0.5 is the default an artist gets, and the only mode where the
  drift pass actually runs.
- tolerance inf keeps only the authored keys, which is the one that can speak
  to acceptance criterion 3.

Reading the key list off the dense import and calling it key preservation is
the mistake this docstring exists to prevent.
"""
import math, os, sys, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "nuke"))
sys.path.insert(0, REPO)

import nuke
import nuke.rotopaint as rp
from core import rbj
import rotobridge_import as rbi
import rotobridge_export as rbx

out = sys.argv[1] if len(sys.argv) > 1 else HERE

def tag():
    """Report name, so a second source does not overwrite the first's."""
    if len(sys.argv) > 2:
        return "ae_to_nuke_" + os.path.splitext(
            os.path.basename(sys.argv[2]))[0]
    return "ae_to_nuke"
lines = []
def say(t=""):
    lines.append(t)
    sys.stdout.write(t + "\n")

def bezier(points, i, j, u):
    """One .rbj segment at parameter u, straight from the Bernstein form.

    Deliberately not the de Casteljau the importer splits with: a split that
    is wrong in its own terms must not be able to pass by agreeing with
    itself.
    """
    b0 = points[i]["c"]
    b1 = [points[i]["c"][k] + points[i]["out"][k] for k in (0, 1)]
    b2 = [points[j]["c"][k] + points[j]["in"][k] for k in (0, 1)]
    b3 = points[j]["c"]
    v = 1.0 - u
    return [v * v * v * b0[k] + 3 * v * v * u * b1[k]
            + 3 * v * u * u * b2[k] + u * u * u * b3[k] for k in (0, 1)]


def expected_centres(spec, record):
    """Where every Nuke control point of one frame should sit.

    For most shapes that is the file's own vertices, in order. For an
    `anchored` one it is not: Nuke can only anchor feather at a vertex, so the
    importer inserts one at every mid-segment anchor (spec/rbj-v2-draft.md
    section 6.5) and the ring comes back longer than the file's point list.
    Comparing index by index there measures the mismatch and nothing else -
    which it did, at 379 px, until this existed.
    """
    points = record["points"]
    if spec["feather_model"] != "anchored":
        return [p["c"] for p in points]
    n = len(points)
    anchors = sorted(record["feather_points"], key=lambda a: a["t"])
    out = []
    for i in range(n):
        out.append(points[i]["c"])
        for anchor in anchors:
            t = float(anchor["t"])
            segment = int(math.floor(t))
            if segment == i and t != segment:
                out.append(bezier(points, i, (i + 1) % n, t - segment))
    return out


def compare_centres(spec, el, failures, where):
    """Worst centre error over every frame, and the frame it happened on."""
    worst, at = 0.0, None
    for key, record in spec["frames"].items():
        want = expected_centres(spec, record)
        if len(want) != len(el):
            failures.append("shape '%s' has %d point(s) in Nuke, wanted %d "
                            "at frame %s (%s)"
                            % (spec["name"], len(el), len(want), key, where))
            return worst, at
        t = float(int(key))
        for i, centre in enumerate(want):
            pos = el[i].center.getPosition(t)
            d = max(abs(pos.x - centre[0]), abs(pos.y - centre[1]))
            if d > worst:
                worst, at = d, int(key)
    return worst, at


def main():
    # A second golden can be named on the command line. `ae_static_ease.rbj`
    # is the one that isolates ease: its layer does not move, so nothing the
    # drift pass does can be blamed on a baked ancestor transform.
    src = (sys.argv[2] if len(sys.argv) > 2
           else os.path.join(REPO, "test", "golden", "ae_scene.rbj"))
    say("AE -> Nuke crossing, %s" % nuke.NUKE_VERSION_STRING)
    say("source: %s" % src)
    say()

    text = open(src).read()
    doc = rbj.loads(text)
    say("--- the file ---")
    say("  version %d from %s %s, %d shape(s), frames %d-%d"
        % (doc["version"], doc["source"]["app"], doc["source"]["app_version"],
           len(doc["shapes"]), doc["range"][0], doc["range"][1]))
    for s in doc["shapes"]:
        say("  %-10s closed=%-5s feather=%-9s falloff=%s"
            % (s["name"], s["closed"], s["feather_model"], s["feather_falloff"]))
    say()

    failures = []

    say("--- import at tolerance 0 (dense: the ground truth mode) ---")
    nuke.scriptClear()
    nuke.root()["first_frame"].setValue(doc["range"][0])
    nuke.root()["last_frame"].setValue(doc["range"][1])
    node, warnings, reports = rbi.import_document(doc, tolerance=0.0)
    knob = node["curves"]
    say("  built %d shape(s)" % len(reports))
    for r, spec in zip(reports, doc["shapes"]):
        say("    %-10s %d authored, %d corrective"
            % (r["name"], r["authored"], r["corrective"]))
    for w in warnings:
        say("  warning: %s" % w)
    say()

    say("--- did the open spline arrive open? ---")
    shapes = dict()
    for i in range(len(knob.rootLayer)):
        el = knob.rootLayer[i]
        shapes[el.name] = el
    for name in ("linear", "opened"):
        el = shapes.get(name)
        if el is None:
            failures.append("shape '%s' is missing after import" % name)
            continue
        is_open = el.getFlag(rp.FlagType.eOpenFlag)
        say("  %-10s open=%s" % (name, is_open))
    if shapes.get("opened") is not None and \
            not shapes["opened"].getFlag(rp.FlagType.eOpenFlag):
        failures.append("the open spline arrived closed")
    if shapes.get("linear") is not None and \
            shapes["linear"].getFlag(rp.FlagType.eOpenFlag):
        failures.append("a closed shape arrived open")
    say()

    say("--- geometry: every point of every shape on every frame ---")
    worst_all = 0.0
    worst_where = None
    for spec in doc["shapes"]:
        el = shapes.get(spec["name"])
        if el is None:
            continue
        worst, _ = compare_centres(spec, el, failures, "dense import")
        extra = len(el) - len(spec["frames"][str(doc["range"][0])]["points"])
        note = "" if not extra else "  (+%d %s inserted to hold feather " \
                                    "anchors)" \
                                    % (extra,
                                       "vertex" if extra == 1 else "vertices")
        say("  %-10s worst %.4e px%s" % (spec["name"], worst, note))
        if worst > worst_all:
            worst_all, worst_where = worst, spec["name"]
    say("  worst overall %.4e px (%s)" % (worst_all, worst_where))
    if worst_all > 1e-3:
        failures.append("AE geometry did not survive into Nuke: %.4e px"
                        % worst_all)
    say()

    say("--- import at tolerance 0.5: the default, what an artist gets ---")
    say("  This is the only mode where the drift pass actually runs, so it is")
    say("  the one that can expose a sparse layer the dense layer contradicts.")
    nuke.scriptClear()
    nuke.root()["first_frame"].setValue(doc["range"][0])
    nuke.root()["last_frame"].setValue(doc["range"][1])
    d_node, d_warn, d_reports = rbi.import_document(doc, tolerance=0.5)
    d_knob = d_node["curves"]
    d_shapes = dict()
    for i in range(len(d_knob.rootLayer)):
        el = d_knob.rootLayer[i]
        d_shapes[el.name] = el
    for r in d_reports:
        line = "    %-10s %d authored, %d corrective" % (
            r["name"], r["authored"], r["corrective"])
        if r.get("worst_frame") is not None:
            line += "; worst %.4f px at frame %s" % (r["residual"],
                                                     r["worst_frame"])
        say(line)
    for w in d_warn:
        if "drift" in w or "unaccounted" in w:
            say("  warning: %s" % w)
    say("  measured against the dense layer:")
    for spec in doc["shapes"]:
        el = d_shapes.get(spec["name"])
        if el is None:
            continue
        worst, at = compare_centres(spec, el, failures, "tolerance 0.5")
        flag = "  <-- OVER TOLERANCE" if worst > 0.5 else ""
        say("    %-10s worst %.4f px at frame %s%s"
            % (spec["name"], worst, at, flag))
        if worst > 0.5:
            failures.append("shape '%s' left %.4f px at frame %s, over the 0.5 "
                            "px tolerance" % (spec["name"], worst, at))
    say()

    say("--- import at tolerance inf: what the SPARSE layer preserves ---")
    say("  Tolerance 0 above keys every frame by definition (prd.md section 8),")
    say("  so it says nothing about key preservation. This keeps only the")
    say("  authored keys, which is acceptance criterion 3.")
    nuke.scriptClear()
    nuke.root()["first_frame"].setValue(doc["range"][0])
    nuke.root()["last_frame"].setValue(doc["range"][1])
    node, warnings, reports = rbi.import_document(doc, tolerance=float("inf"))
    knob = node["curves"]
    shapes = dict()
    for i in range(len(knob.rootLayer)):
        el = knob.rootLayer[i]
        shapes[el.name] = el
    for r in reports:
        say("    %-10s %d authored, %d corrective"
            % (r["name"], r["authored"], r["corrective"]))
    say()

    say("--- back out again: Nuke's export of an AE-sourced file ---")
    back = rbx.export_node(node, doc["range"][0], doc["range"][1],
                           doc["source"]["width"], doc["source"]["height"],
                           doc["source"]["pixel_aspect"], doc["source"]["fps"])
    say("  version %d, %d shape(s)" % (back["version"], len(back["shapes"])))
    errs = rbj.validate(back)
    if errs:
        failures.append("the re-export is not valid .rbj")
        for e in errs[:5]:
            say("  INVALID: %s" % e)
    else:
        say("  the re-export validates")
    for s in back["shapes"]:
        say("    %-10s closed=%-5s feather=%-9s falloff=%s"
            % (s["name"], s["closed"], s["feather_model"], s["feather_falloff"]))
    for w in back["warnings"]:
        say("  warning: %s" % w)
    handle = open(os.path.join(out, "%s_back.rbj" % tag()), "w")
    handle.write(rbj.dumps(back) + "\n")
    handle.close()
    say()

    say("--- what the crossing changed, field by field ---")
    a = dict((s["name"], s) for s in doc["shapes"])
    b = dict((s["name"], s) for s in back["shapes"])
    for name in a:
        if name not in b:
            say("  %-10s LOST" % name)
            failures.append("shape '%s' did not come back" % name)
            continue
        for field in ("closed", "feather_model", "feather_falloff", "blend"):
            if a[name][field] != b[name][field]:
                say("  %-10s %-16s %r -> %r"
                    % (name, field, a[name][field], b[name][field]))
        ka = a[name].get("keys") or []
        kb = b[name].get("keys") or []
        fa = [k["frame"] for k in ka]
        fb = [k["frame"] for k in kb]
        if fa != fb:
            say("  %-10s keys %s -> %s" % (name, fa, fb))
        for k1, k2 in zip(ka, kb):
            if k1["interp"] != k2["interp"]:
                say("  %-10s frame %-3d interp %s -> %s"
                    % (name, k1["frame"], k1["interp"], k2["interp"]))
    say()

    say("=== VERDICT ===")
    if failures:
        say("FAIL")
        for f in failures:
            say("  - %s" % f)
    else:
        say("PASS - an After Effects .rbj opens in Nuke and comes back out")
    return failures

try:
    main()
except Exception:
    say("EXCEPTION")
    say(traceback.format_exc())

handle = open(os.path.join(out, "%s_report.txt" % tag()), "w")
handle.write("\n".join(lines) + "\n")
handle.close()
