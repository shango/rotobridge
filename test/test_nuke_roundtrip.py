"""Phase 2 and 3 acceptance: Nuke -> .rbj -> Nuke, dense and sparse.

Run:  nuke --nc -t test/test_nuke_roundtrip.py [output_dir]

Phase 2 (prd.md section 12): "Export and import with tolerance 0, validated
against golden .rbj files." This builds a shape whose every awkward feature is
present at once - beziers, a baked non-identity transform, per-point feather,
animated opacity and animated uniform feather - exports it, reimports it, and
compares every point on every frame.

Phase 3 adds the sparse layer: that a shape keyed on five frames comes back as
five keys the artist can grab, that an animated transform counts as shape
animation even with no point keyed, and that the drift pass holds acceptance
criterion 4's bound on a file whose sparse layer cannot reproduce its own dense
layer.

It also checks two things the pure tests cannot: that `core.geom`'s matrix
arithmetic agrees with Nuke's own `matrix * vector`, and that the export and
import stay inside acceptance criterion 11's time budget.

Non-commercial Nuke caps Python-visible nodes at 10 and counts deleted ones, so
the script clears between stages rather than holding both nodes at once.
"""

import copy
import math
import os
import sys
import time
import traceback

import nuke
import nuke.rotopaint as rp

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for path in (ROOT, os.path.join(ROOT, "nuke")):
    if path not in sys.path:
        sys.path.insert(0, path)

from core import geom, rbj  # noqa: E402
from rotobridge_nuke import point_members, set_curve_linear  # noqa: E402
import rotobridge_export as rbx  # noqa: E402
import rotobridge_import as rbi  # noqa: E402

FIRST, LAST = 1001, 1020

# prd.md section 8's default import mode.
TOLERANCE = 0.5

# Nuke stores control point positions as float32: the serialised form in Phase 2
# case 73 carries eight-hex-digit values (x42c80000 is 100.0f). float32 epsilon
# at these coordinate magnitudes is about 3e-05 px, so "tolerance 0" means exact
# to Nuke's own storage, not bit-identical to the float64 in the file. Anything
# above this floor is real error and the test should fail.
FLOAT32_FLOOR = 1e-4

lines = []


def say(text=""):
    print(text)
    lines.append(text)


def out_dir():
    if len(sys.argv) > 1:
        d = sys.argv[1]
    else:
        d = os.path.join(HERE, "golden", "nuke_probe",
                         nuke.NUKE_VERSION_STRING, "phase3")
    d = os.path.abspath(d)
    if not os.path.isdir(d):
        os.makedirs(d)
    return d


def set_shape_linear(shape):
    """Author every key on every point curve as explicitly linear.

    The tier-1 exact case: a linear Nuke key reports `interpolationType` 2 and
    translates to `{in: linear, out: linear}` with nothing lost, so the sparse
    round trip should need no corrective keys at all.
    """
    for i in range(len(shape)):
        for member in point_members(shape[i]):
            for d in range(member.dim):
                set_curve_linear(member.getPositionAnimCurve(d))


def build_source(points=4, first=FIRST, last=LAST, feather=True, transform=True,
                 key_frames=None):
    """A shape that exercises every field .rbj v1 carries.

    `key_frames` keys only those frames instead of every one, and authors them
    linear - the sparse fixture. Everything between them is Nuke interpolating,
    which is what the dense layer then captures.
    """
    nuke.scriptClear()
    nuke.root()["first_frame"].setValue(first)
    nuke.root()["last_frame"].setValue(last)
    node = nuke.createNode("RotoPaint", inpanel=False)
    knob = node["curves"]

    shape = rp.Shape(knob)
    for i in range(points):
        angle = 2.0 * math.pi * i / points
        shape.append(rp.ShapeControlPoint(400.0 + 200.0 * math.cos(angle),
                                          400.0 + 200.0 * math.sin(angle)))
    shape.name = "round_trip"
    knob.rootLayer.append(shape)

    span = float(last - first)
    keyed = range(first, last + 1) if key_frames is None else key_frames
    for i in range(points):
        cp = shape[i]
        angle = 2.0 * math.pi * i / points
        for frame in keyed:
            t = (frame - first) / span
            # Drift each point on its own path so a transposed loop shows up.
            x = 400.0 + (200.0 + 40.0 * t) * math.cos(angle + 0.4 * t)
            y = 400.0 + (200.0 + 40.0 * t) * math.sin(angle + 0.4 * t)
            cp.center.addPositionKey(float(frame), rp.CVec3(x, y, 1.0))
            cp.leftTangent.addPositionKey(
                float(frame), rp.CVec3(-30.0 - 5.0 * t, 8.0 * t, 0.0))
            cp.rightTangent.addPositionKey(
                float(frame), rp.CVec3(30.0 + 5.0 * t, -8.0 * t, 0.0))
            if feather:
                # Deliberately off-normal on one point, so the tangential
                # component and its warning are exercised.
                fx = 6.0 + 2.0 * t if i != 1 else -9.0
                fy = 0.0 if i != 1 else 4.0
                cp.featherCenter.addPositionKey(
                    float(frame), rp.CVec3(fx, fy, 0.0))

    attrs = shape.getAttributes()
    opc = attrs.getCurve("opc", "main")
    opc.addKey(float(first), 1.0)
    opc.addKey(float(last), 0.25)
    for name, lo, hi in (("fx", 2.0, 18.0), ("fy", 5.0, 5.0)):
        curve = attrs.getCurve(name, "main")
        curve.addKey(float(first), lo)
        curve.addKey(float(last), hi)

    if transform:
        xf = shape.getTransform()
        xf.addTranslationKey(first, 120.0, -35.0, 0.0)
        xf.addTranslationKey(last, 260.0, 45.0, 0.0)

    if key_frames is not None:
        set_shape_linear(shape)

    return node, shape


def key_times(shape):
    """The frames the artist would see on the first control point's centre."""
    return [int(round(t)) for t in shape[0].center.getControlPointKeyTimes()]


def thin_keys(doc, frames):
    """A copy of `doc` whose sparse layer claims only `frames`, linear.

    Nuke to Nuke rarely drifts, and that is the round trip working: the same
    key type through the same key frames re-evaluates to the same curve. So to
    exercise tier 3 the file has to disagree with itself the way a foreign
    exporter's would - a dense layer that curves, over a sparse layer claiming
    two straight keys produced it. Every other adapter can emit exactly this.
    """
    thin = copy.deepcopy(doc)
    for shape in thin["shapes"]:
        shape["keys"] = [{"frame": f,
                          "interp": {"in": "linear", "out": "linear"}}
                         for f in frames]
    return thin


def check_matrix_agreement(shape):
    """core.geom's matrix arithmetic against Nuke's own operator."""
    say("--- core.geom matrix vs Nuke's matrix * vector ---")
    xf = shape.getTransform()
    worst = 0.0
    for frame in (FIRST, (FIRST + LAST) // 2, LAST):
        ct = xf.evaluate(frame)
        mat = ct.getMatrix()
        flat = list(mat)
        for probe in ([10.0, 20.0], [-350.5, 812.25], [0.0, 0.0]):
            theirs = mat * rp.CVec3(probe[0], probe[1], 1.0)
            ours = geom.apply_matrix_point(flat, probe)
            worst = max(worst, abs(theirs.x - ours[0]), abs(theirs.y - ours[1]))
    say("  worst disagreement over 9 samples: %.3e" % worst)
    ok = worst < FLOAT32_FLOOR
    say("  %s" % ("OK" if ok else "FAIL - the row-major reading is wrong"))
    say()
    return ok


def compare(doc, shape, offset=0):
    """Every point on every frame of the reimported shape against the file."""
    spec = doc["shapes"][0]
    worst_c = worst_t = worst_f = 0.0
    for frame_key, record in spec["frames"].items():
        at = float(int(frame_key) + offset)
        for i, point in enumerate(record["points"]):
            cp = shape[i]
            c = cp.center.getPosition(at)
            worst_c = max(worst_c, abs(c.x - point["c"][0]),
                          abs(c.y - point["c"][1]))
            left = cp.leftTangent.getPosition(at)
            right = cp.rightTangent.getPosition(at)
            worst_t = max(worst_t, abs(left.x - point["in"][0]),
                          abs(left.y - point["in"][1]),
                          abs(right.x - point["out"][0]),
                          abs(right.y - point["out"][1]))
            if "feather_offset" in point:
                fc = cp.featherCenter.getPosition(at)
                worst_f = max(worst_f, abs(fc.x - point["feather_offset"][0]),
                              abs(fc.y - point["feather_offset"][1]))
    return worst_c, worst_t, worst_f


def compare_attributes(doc, shape, offset=0):
    spec = doc["shapes"][0]
    attrs = shape.getAttributes()
    worst = 0.0
    for frame_key, record in spec["frames"].items():
        at = float(int(frame_key) + offset)
        worst = max(worst,
                    abs(attrs.getValue(at, "opc", "main") - record["opacity"]),
                    abs(attrs.getValue(at, "fx", "main")
                        - record["feather_uniform"][0]),
                    abs(attrs.getValue(at, "fy", "main")
                        - record["feather_uniform"][1]))
    return worst


def main():
    out = out_dir()
    path = os.path.join(out, "roundtrip.rbj")
    failures = []

    say("RotoBridge Phase 2, 3 and 6 acceptance - Nuke round trip")
    say("Nuke %s, frames %d-%d" % (nuke.NUKE_VERSION_STRING, FIRST, LAST))
    say()

    node, shape = build_source()
    if not check_matrix_agreement(shape):
        failures.append("core.geom matrix disagrees with Nuke")

    say("--- export ---")
    started = time.time()
    doc = rbx.export_to_file(node, path, FIRST, LAST)
    export_seconds = time.time() - started
    say("  %d shape(s), %d frames, %d points"
        % (len(doc["shapes"]), len(doc["shapes"][0]["frames"]),
           len(doc["shapes"][0]["frames"][str(FIRST)]["points"])))
    say("  feather_model = %s, blend = %s, falloff = %s"
        % (doc["shapes"][0]["feather_model"], doc["shapes"][0]["blend"],
           doc["shapes"][0]["feather_falloff"]))
    say("  took %.3f s" % export_seconds)
    for w in doc["warnings"]:
        say("  warning: %s" % w)
    say()

    say("--- schema ---")
    errs = rbj.validate(doc)
    if errs:
        failures.append("exported document is not valid .rbj")
        for e in errs[:10]:
            say("  INVALID: %s" % e)
    else:
        say("  the exported document validates against the frozen v1 schema")
    say()

    say("--- the sparse layer (spec section 9) ---")
    keys = doc["shapes"][0].get("keys")
    say("  keys written: %s" % (len(keys) if keys is not None else "ABSENT"))
    if keys is None:
        failures.append("Phase 3 export must write a sparse keys layer")
    else:
        # This fixture is keyed on every frame, so the union is every frame.
        want = list(range(FIRST, LAST + 1))
        got = [k["frame"] for k in keys]
        if got != want:
            failures.append("key union is %s, wanted every frame %s"
                            % (got[:5], want[:5]))
        say("  interp on the first key: %s" % keys[0]["interp"])
    say()

    say("--- import at tolerance 0 ---")
    started = time.time()
    imported, warnings, reports, recorded = rbi.import_from_file(
        path, tolerance=0.0)
    import_seconds = time.time() - started
    back = imported["curves"].rootLayer[0]
    say("  rebuilt '%s' with %d points, closed=%s"
        % (back.name, len(back), not back.getFlag(rp.FlagType.eOpenFlag)))
    say("  took %.3f s" % import_seconds)
    say()

    say("--- the import record ---")
    # Written for every import, not on request, so this is the one place the
    # host proves it: the path is derived from the script name and this script
    # is unsaved, which is the branch that falls back to the .rbj.
    if recorded is None or not os.path.exists(recorded):
        failures.append("no import record was written (%s)" % recorded)
    else:
        text = open(recorded).read()
        say("  %s, %d bytes" % (os.path.basename(recorded), len(text)))
        for wanted in ("RotoBridge import record", back.name, "tolerance",
                       "warnings from this import"):
            if wanted not in text:
                failures.append("the import record does not mention %r"
                                % wanted)
        for line in text.splitlines()[:14]:
            say("  | " + line)
    say()

    say("--- geometry, every point on every frame ---")
    worst_c, worst_t, worst_f = compare(doc, back)
    say("  worst centre deviation:  %.3e px" % worst_c)
    say("  worst tangent deviation: %.3e px" % worst_t)
    say("  worst feather deviation: %.3e px" % worst_f)
    for label, value in (("centre", worst_c), ("tangent", worst_t),
                         ("feather", worst_f)):
        if value > FLOAT32_FLOOR:
            failures.append("%s deviation %.3e exceeds tolerance 0" % (label, value))
    say("  Criterion 1 wants corners within 0.1 px, criterion 2 wants")
    say("  tolerance 0 exact. The residual here is float32 epsilon at these")
    say("  magnitudes - Nuke stores point positions as float32 (case 73's")
    say("  serialised x42c80000 is 100.0f) - so it is the storage floor, not")
    say("  accumulated error. Tangents and feather land exactly because they")
    say("  are small numbers where float32 still resolves the float64 value.")
    say()

    say("--- attributes ---")
    worst_a = compare_attributes(doc, back)
    say("  worst opacity / uniform feather deviation: %.3e" % worst_a)
    if worst_a > FLOAT32_FLOOR:
        failures.append("attribute deviation %.3e exceeds tolerance 0" % worst_a)
    say()

    say("--- frame offset ---")
    nuke.scriptClear()
    offset_node, _, _, _ = rbi.import_from_file(path, offset=-1000,
                                                tolerance=0.0)
    offset_shape = offset_node["curves"].rootLayer[0]
    worst_o = compare(doc, offset_shape, offset=-1000)[0]
    say("  imported at offset -1000; worst centre deviation %.3e px" % worst_o)
    if worst_o > FLOAT32_FLOOR:
        failures.append("offset import deviation %.3e exceeds tolerance 0" % worst_o)
    say()

    say("--- acceptance criterion 11, 20 points over 150 frames ---")
    big_first, big_last = 1, 150
    node, shape = build_source(points=20, first=big_first, last=big_last)
    started = time.time()
    big = rbx.export_to_file(node, os.path.join(out, "roundtrip_20x150.rbj"),
                             big_first, big_last)
    big_export = time.time() - started
    say("  export: %.2f s  (budget 10 s)" % big_export)
    started = time.time()
    rbi.import_document(big, tolerance=0.0)
    big_import = time.time() - started
    say("  import at tolerance 0:   %.2f s  (budget 30 s)" % big_import)
    nuke.scriptClear()
    started = time.time()
    rbi.import_document(big, tolerance=TOLERANCE)
    big_sparse = time.time() - started
    say("  import at tolerance %.1f: %.2f s  (budget 30 s)"
        % (TOLERANCE, big_sparse))
    if big_export > 10.0:
        failures.append("20x150 export took %.2f s, over the 10 s budget" % big_export)
    for label, seconds in (("tolerance 0", big_import),
                           ("tolerance %.1f" % TOLERANCE, big_sparse)):
        if seconds > 30.0:
            failures.append("20x150 import at %s took %.2f s, over the 30 s "
                            "budget" % (label, seconds))
    say()

    say("--- Phase 3: a shape keyed on 5 frames ---")
    say("  The acceptance criterion: five authored keys survive as five keys")
    say("  the artist can grab, not as one key per frame.")
    nuke.scriptClear()
    sparse_first, sparse_last = 1, 41
    authored = [1, 11, 21, 31, 41]
    node, shape = build_source(first=sparse_first, last=sparse_last,
                               key_frames=authored)
    sparse_path = os.path.join(out, "sparse.rbj")
    sparse_doc = rbx.export_to_file(node, sparse_path, sparse_first, sparse_last)
    sparse_keys = [k["frame"] for k in sparse_doc["shapes"][0]["keys"]]
    say("  exported keys: %s" % sparse_keys)
    if sparse_keys != authored:
        failures.append("keyed on %s, exported %s" % (authored, sparse_keys))
    sides = set((k["interp"]["in"], k["interp"]["out"])
                for k in sparse_doc["shapes"][0]["keys"])
    say("  interp across all keys: %s" % sorted(sides))
    if sides != set([("linear", "linear")]):
        failures.append("explicitly linear keys exported as %s" % sorted(sides))

    nuke.scriptClear()
    sparse_node, _, sparse_reports, _ = rbi.import_from_file(
        sparse_path, tolerance=TOLERANCE)
    sparse_back = sparse_node["curves"].rootLayer[0]
    landed = key_times(sparse_back)
    report = sparse_reports[0]
    say("  imported keys: %s" % landed)
    say("  report: %d authored, %d corrective, worst %.3e px"
        % (report["authored"], report["corrective"], report["residual"]))
    if landed != authored:
        failures.append("5 authored keys imported as %d keys %s"
                        % (len(landed), landed))
    if report["corrective"]:
        failures.append("tier 1 linear should need no corrective keys; got %d"
                        % report["corrective"])
    worst_s = max(compare(sparse_doc, sparse_back))
    say("  worst deviation over every frame: %.3e px" % worst_s)
    if worst_s > FLOAT32_FLOOR:
        failures.append("sparse linear round trip drifted %.3e px" % worst_s)
    say()

    say("--- Phase 3: an animated transform is shape animation ---")
    say("  spec section 9 and prd.md section 9.2 step 5: the transform is")
    say("  baked into the points, so its keys are the shape's keys even when")
    say("  no control point is keyed at all.")
    nuke.scriptClear()
    nuke.root()["first_frame"].setValue(1)
    nuke.root()["last_frame"].setValue(20)
    node = nuke.createNode("RotoPaint", inpanel=False)
    knob = node["curves"]
    still = rp.Shape(knob)
    for x, y in ((100.0, 100.0), (300.0, 100.0), (300.0, 300.0), (100.0, 300.0)):
        still.append(rp.ShapeControlPoint(x, y))
    still.name = "static_points"
    knob.rootLayer.append(still)
    xf = still.getTransform()
    xf.addTranslationKey(1, 0.0, 0.0, 0.0)
    xf.addTranslationKey(20, 400.0, 0.0, 0.0)

    moved = rbx.export_node(node, 1, 20, 2048, 858, 1.0, 24.0)
    moved_keys = [k["frame"] for k in moved["shapes"][0]["keys"]]
    travel = (moved["shapes"][0]["frames"]["20"]["points"][0]["c"][0]
              - moved["shapes"][0]["frames"]["1"]["points"][0]["c"][0])
    say("  keys from the transform alone: %s" % moved_keys)
    say("  the baked first vertex travelled %.1f px" % travel)
    if moved_keys != [1, 20]:
        failures.append("an animated transform with no point keys exported "
                        "keys %s, wanted [1, 20]" % moved_keys)
    if abs(travel - 400.0) > FLOAT32_FLOOR:
        failures.append("baked transform travel was %.3f, wanted 400" % travel)
    say()

    say("--- Phase 3: the drift bound, acceptance criterion 4 ---")
    say("  Nuke to Nuke does not drift - the same keys re-evaluate to the")
    say("  same curve, which is the round trip working. So this thins the")
    say("  file's sparse layer to two straight keys over the same curved")
    say("  dense layer, which is what a foreign exporter's tier-2 output")
    say("  looks like, and checks the pass brings it back inside tolerance.")
    thin = thin_keys(doc, [FIRST, LAST])
    errs = rbj.validate(thin)
    if errs:
        failures.append("the thinned document is not valid .rbj")
        for e in errs[:5]:
            say("  INVALID: %s" % e)

    nuke.scriptClear()
    loose_node, _, loose_reports = rbi.import_document(thin,
                                                       tolerance=float("inf"))
    loose_worst = max(compare(doc, loose_node["curves"].rootLayer[0]))
    say("  tolerance inf: %d key(s), worst deviation %.3f px"
        % (len(key_times(loose_node["curves"].rootLayer[0])), loose_worst))
    if loose_worst <= TOLERANCE:
        failures.append("the thinned fixture does not actually drift (%.3f px), "
                        "so the bound below proves nothing" % loose_worst)

    nuke.scriptClear()
    tight_node, _, tight_reports = rbi.import_document(thin, tolerance=TOLERANCE)
    tight_back = tight_node["curves"].rootLayer[0]
    tight_worst = max(compare(doc, tight_back))
    landed = key_times(tight_back)
    say("  tolerance %.1f: %d key(s), worst deviation %.3f px"
        % (TOLERANCE, len(landed), tight_worst))
    say("  report: %d authored, %d corrective"
        % (tight_reports[0]["authored"], tight_reports[0]["corrective"]))
    if tight_worst > TOLERANCE:
        failures.append("drift pass left %.3f px, over the %.1f px bound"
                        % (tight_worst, TOLERANCE))
    if not tight_reports[0]["corrective"]:
        failures.append("the drift pass added no corrective keys")
    if len(landed) >= (LAST - FIRST + 1):
        failures.append("the drift pass degraded to dense: %d keys over %d "
                        "frames" % (len(landed), LAST - FIRST + 1))
    for frame in (FIRST, LAST):
        if frame not in landed:
            failures.append("authored key %d did not survive" % frame)
    say()

    say("--- Phase 3: mode switching, acceptance criterion 5 ---")
    say("  Re-importing the same file at tolerance 0 must reach the dense")
    say("  result with no trip back to the source application.")
    nuke.scriptClear()
    dense_node, _, _ = rbi.import_document(thin, tolerance=0.0)
    dense_back = dense_node["curves"].rootLayer[0]
    dense_worst = max(compare(doc, dense_back))
    say("  %d key(s), worst deviation %.3e px"
        % (len(key_times(dense_back)), dense_worst))
    if dense_worst > FLOAT32_FLOOR:
        failures.append("re-import at tolerance 0 drifted %.3e px" % dense_worst)
    say()

    say("--- a shape inside a transformed layer ---")
    say("  Nuke keeps a transform per layer AND per shape, neither aware of")
    say("  the other (case 77). Flattening without composing the chain moves")
    say("  the geometry, so check the layer translation actually lands.")
    nuke.scriptClear()
    nuke.root()["first_frame"].setValue(1)
    nuke.root()["last_frame"].setValue(2)
    node = nuke.createNode("RotoPaint", inpanel=False)
    knob = node["curves"]

    layer = rp.Layer(knob)
    layer.name = "moved"
    knob.rootLayer.append(layer)
    # append() copies into the tree; the passed object goes stale (case 76).
    layer = knob.rootLayer[len(knob.rootLayer) - 1]

    inner = rp.Shape(knob)
    corners = ((100.0, 100.0), (300.0, 100.0), (300.0, 300.0), (100.0, 300.0))
    for x, y in corners:
        inner.append(rp.ShapeControlPoint(x, y))
    inner.name = "inner"
    layer.append(inner)
    layer.getTransform().addTranslationKey(1, 500.0, 25.0, 0.0)

    layered = rbx.export_node(node, 1, 2, 2048, 858, 1.0, 24.0)
    got = layered["shapes"][0]["frames"]["1"]["points"][0]["c"]
    want = [corners[0][0] + 500.0, corners[0][1] + 25.0]
    say("  authored %s, layer translation (500, 25)" % (list(corners[0]),))
    say("  exported %s, expected %s" % ([round(v, 3) for v in got], want))
    drift = max(abs(got[0] - want[0]), abs(got[1] - want[1]))
    say("  deviation %.3e px" % drift)
    if drift > FLOAT32_FLOOR:
        failures.append("layer transform not baked: exported %s, wanted %s"
                        % (got, want))
    say("  flatten warnings: %s"
        % "; ".join(w for w in layered["warnings"] if "flatten" in w))
    say()

    say("--- Phase 6: an open spline (spec/rbj-v2-draft.md) ---")
    say("  Nuke carries open/closed as a shape FLAG (case 72), so the round")
    say("  trip has to keep it and the file has to declare version 2 to be")
    say("  allowed to say so at all.")
    nuke.scriptClear()
    nuke.root()["first_frame"].setValue(1)
    nuke.root()["last_frame"].setValue(2)
    node = nuke.createNode("RotoPaint", inpanel=False)
    knob = node["curves"]

    open_shape = rp.Shape(knob)
    line = ((100.0, 100.0), (200.0, 180.0), (320.0, 160.0), (400.0, 260.0))
    for x, y in line:
        open_shape.append(rp.ShapeControlPoint(x, y))
    open_shape.name = "open_spline"
    open_shape.setFlag(rp.FlagType.eOpenFlag, True)
    knob.rootLayer.append(open_shape)

    open_doc = rbx.export_node(node, 1, 2, 2048, 858, 1.0, 24.0)
    say("  exported closed=%s, version=%s"
        % (open_doc["shapes"][0]["closed"], open_doc["version"]))
    if open_doc["shapes"][0]["closed"] is not False:
        failures.append("an open spline exported as closed")
    if open_doc["version"] != rbj.VERSION_OPEN_SPLINES:
        failures.append("a file with an open spline declares version %r, "
                        "wanted %d" % (open_doc["version"],
                                       rbj.VERSION_OPEN_SPLINES))
    open_errs = rbj.validate(open_doc)
    if open_errs:
        failures.append("the open-spline document is not valid .rbj")
        for e in open_errs[:5]:
            say("  INVALID: %s" % e)
    render_warnings = [w for w in open_doc["warnings"] if "openspline_width" in w]
    say("  render-settings warning: %s"
        % (render_warnings[0] if render_warnings else "MISSING"))
    if not render_warnings:
        failures.append("no warning that the open-spline render settings are "
                        "node knobs and were not carried")

    nuke.scriptClear()
    open_back_node, _, _ = rbi.import_document(open_doc, tolerance=0.0)
    open_back = open_back_node["curves"].rootLayer[0]
    still_open = open_back.getFlag(rp.FlagType.eOpenFlag)
    say("  rebuilt '%s' with %d points, open=%s"
        % (open_back.name, len(open_back), still_open))
    if not still_open:
        failures.append("the open flag did not survive the round trip")
    open_worst = max(compare(open_doc, open_back))
    say("  worst deviation %.3e px" % open_worst)
    if open_worst > FLOAT32_FLOOR:
        failures.append("open spline drifted %.3e px" % open_worst)
    say("  The scalar-feather path on an open spline is arithmetic, not host")
    say("  behaviour, and test_core.py TestOpenSplines covers it. What is")
    say("  still unmeasured is what an OPEN mask renders as in After Effects")
    say("  (spec/rbj-v2-draft.md section 5).")
    say()

    say("--- Phase 7: anchored feather (spec/rbj-v2-draft.md section 6) ---")
    say("  Nuke anchors feather at a vertex and nowhere else, so an anchor")
    say("  the artist put mid-segment gets one: the segment is split with de")
    say("  Casteljau, which reproduces the curve exactly. The shape gains")
    say("  points and does not move. Nothing on the Nuke side WRITES such a")
    say("  file (section 6.6), so the fixture is built by hand.")
    nuke.scriptClear()
    nuke.root()["first_frame"].setValue(1)
    nuke.root()["last_frame"].setValue(2)

    curved = [{"c": [100.0, 100.0], "in": [-40.0, 0.0], "out": [40.0, 60.0]},
              {"c": [400.0, 100.0], "in": [-40.0, 60.0], "out": [40.0, 0.0]},
              {"c": [400.0, 400.0], "in": [40.0, 0.0], "out": [-40.0, 0.0]},
              {"c": [100.0, 400.0], "in": [40.0, 0.0], "out": [-40.0, 0.0]}]
    # 0.25 is mid-segment, 2.0 is a vertex, 2.5 is mid-segment on another
    # segment. Two need a vertex inserted and one does not.
    anchors = [{"t": 0.25, "feather": 30.0},
               {"t": 2.0, "feather": -15.0},
               {"t": 2.5, "feather": 12.0}]
    anchored_doc = {
        "format": "rotobridge", "version": 2,
        "source": {"app": "test", "app_version": "0", "width": 2048,
                   "height": 858, "pixel_aspect": 1.0, "fps": 24.0},
        "range": [1, 2], "warnings": [],
        "shapes": [{"name": "anchored", "closed": True, "blend": "union",
                    "feather_model": "anchored", "feather_falloff": "smooth",
                    "frames": dict(
                        (str(f), {"opacity": 1.0, "feather_uniform": [0.0, 0.0],
                                  "points": [dict((k, list(v))
                                                  for k, v in pt.items())
                                             for pt in curved],
                                  "feather_points": [dict(a) for a in anchors]})
                        for f in (1, 2)),
                    "keys": [{"frame": 1,
                              "interp": {"in": "linear", "out": "linear"}},
                             {"frame": 2,
                              "interp": {"in": "linear", "out": "linear"}}]}],
    }
    anchored_errs = rbj.validate(anchored_doc)
    if anchored_errs:
        failures.append("the hand-built anchored document is not valid .rbj")
        for e in anchored_errs[:5]:
            say("  INVALID: %s" % e)

    nuke.scriptClear()
    anchored_node, anchored_warnings, _ = rbi.import_document(anchored_doc,
                                                              tolerance=0.0)
    built = anchored_node["curves"].rootLayer[0]
    say("  4 points and 3 anchors in, %d points out (want 6)" % len(built))
    if len(built) != 6:
        failures.append("anchored import made %d points, wanted 6"
                        % len(built))

    inserted_warning = [w for w in anchored_warnings if "were inserted" in w]
    say("  insertion warning: %s"
        % (inserted_warning[0][:70] if inserted_warning else "MISSING"))
    if not inserted_warning:
        failures.append("no warning that vertices were inserted to hold "
                        "feather anchors")

    # The claim is that the shape did not move. The original vertices must be
    # exactly where the file put them, and each inserted vertex exactly on the
    # curve the file described - evaluated here from the Bernstein form rather
    # than from anything the importer used to place it.
    def on_curve(points, i, j, u):
        b0 = points[i]["c"]
        b1 = [points[i]["c"][k] + points[i]["out"][k] for k in (0, 1)]
        b2 = [points[j]["c"][k] + points[j]["in"][k] for k in (0, 1)]
        b3 = points[j]["c"]
        v = 1.0 - u
        return [v * v * v * b0[k] + 3 * v * v * u * b1[k]
                + 3 * v * u * u * b2[k] + u * u * u * b3[k] for k in (0, 1)]

    # After two insertions the ring is: v0, split(0.25), v1, v2, split(2.5), v3.
    wanted = [(0, curved[0]["c"]),
              (1, on_curve(curved, 0, 1, 0.25)),
              (2, curved[1]["c"]),
              (3, curved[2]["c"]),
              (4, on_curve(curved, 2, 3, 0.5)),
              (5, curved[3]["c"])]
    worst_anchor = 0.0
    for index, want in wanted:
        if index >= len(built):
            break
        got = built[index].center.getPosition(1.0)
        worst_anchor = max(worst_anchor, abs(got.x - want[0]),
                           abs(got.y - want[1]))
    say("  worst vertex placement %.3e px" % worst_anchor)
    if worst_anchor > FLOAT32_FLOOR:
        failures.append("anchored import moved the shape by %.3e px"
                        % worst_anchor)

    # Feather lands on the vertex the anchor named, and nowhere else. The
    # normals are unit length, so the offset's magnitude is the radius.
    if len(built) == 6:
        want_radius = {0: 0.0, 1: 30.0, 2: 0.0, 3: 15.0, 4: 12.0, 5: 0.0}
        worst_radius = 0.0
        for index, radius in want_radius.items():
            fc = built[index].featherCenter.getPosition(1.0)
            got = (float(fc.x) ** 2 + float(fc.y) ** 2) ** 0.5
            worst_radius = max(worst_radius, abs(got - radius))
        say("  worst feather radius error %.3e px" % worst_radius)
        if worst_radius > 1e-3:
            failures.append("anchored feather landed %.3e px off its radius"
                            % worst_radius)

    say("  What is still unmeasured is section 6.4's open question: whether")
    say("  After Effects' featherRelSegLocs is the bezier parameter this")
    say("  splits at or an arc-length fraction. On a curved segment the two")
    say("  differ, and only a rendered comparison can say. Until then an")
    say("  anchored AE file is better than the snap, not known to be exact.")
    say()

    say("=== VERDICT ===")
    if failures:
        say("FAIL")
        for f in failures:
            say("  - %s" % f)
    else:
        say("PASS - Nuke round trips through .rbj, dense, sparse, open"
            " and anchored")
    return failures


try:
    result = main()
except Exception:
    say("EXCEPTION")
    say(traceback.format_exc())
    result = ["exception"]

handle = open(os.path.join(out_dir(), "roundtrip_report.txt"), "w")
handle.write("\n".join(lines) + "\n")
handle.close()
