"""RotoBridge Phase 0 probe - Nuke side.

Run:  nuke -t probe_nuke.py [output_dir]

Answers the Nuke questions in prd.md section 12, in risk order. Case 10
(tangent persistence) is existential: if bezier tangents do not survive the API
write path in this Nuke version, the Nuke importer cannot ship as specified.

Stage 1 (introspection) uses only dir()/getattr and always succeeds; it reports
the real API. Stage 2 makes calls whose signatures are not yet confirmed, so
each case is guarded - a wrong guess reports itself and the run continues.
"""

import os
import re
import sys
import traceback

import nuke
import nuke.rotopaint as rp


def out_dir():
    if len(sys.argv) > 1:
        d = sys.argv[1]
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        d = os.path.join(here, "..", "golden", "nuke_probe", nuke.NUKE_VERSION_STRING)
    d = os.path.abspath(d)
    if not os.path.isdir(d):
        os.makedirs(d)
    return d


def write(name, text):
    f = open(os.path.join(OUT, name), "w")
    f.write(text)
    f.close()
    print("  wrote %s" % name)


# --------------------------------------------------------------------------
# Stage 1: API surface. Cannot fail - this is what unblocks writing stage 2.
# --------------------------------------------------------------------------

def describe(obj, label):
    lines = ["=== %s ===" % label]
    for name in sorted(dir(obj)):
        if name.startswith("__"):
            continue
        try:
            attr = getattr(obj, name)
        except Exception as exc:
            lines.append("  %-32s <unreadable: %s>" % (name, exc))
            continue
        doc = (getattr(attr, "__doc__", None) or "").strip().split("\n")[0]
        lines.append("  %-32s %s" % (name, doc[:110]))
    return "\n".join(lines) + "\n\n"


def dump_api():
    text = "Nuke %s\n\n" % nuke.NUKE_VERSION_STRING
    for label in ("Shape", "Stroke", "Layer", "Element", "ShapeControlPoint",
                  "AnimControlPoint", "AnimAttributes", "AnimCurve", "AnimCurveKey",
                  "CurveKnob", "AnimCTransform", "CTransform", "CMatrix4",
                  "FlagType", "CurveType", "InterpolationType", "ExtrapolationType"):
        cls = getattr(rp, label, None)
        if cls is None:
            text += "=== %s === NOT PRESENT in nuke.rotopaint\n\n" % label
        else:
            text += describe(cls, "nuke.rotopaint." + label)
    write("00_api_surface.txt", text)


def dump_attribute_names():
    """Authoritative attribute names: feather (PRD 12) and lifetime."""
    lines = []
    for mod_name in ("nuke.rotopaint", "nuke.curvelib"):
        try:
            mod = __import__(mod_name, fromlist=["x"])
        except Exception as exc:
            lines.append("%s: import failed: %s" % (mod_name, exc))
            continue
        attrs = getattr(mod, "AnimAttributes", None)
        if attrs is None:
            continue
        lines.append("=== %s.AnimAttributes constants ===" % mod_name)
        for name in sorted(dir(attrs)):
            if name.startswith("k"):
                lines.append("  %-40s = %r" % (name, getattr(attrs, name)))
        lines.append("")
    write("01_attribute_names.txt", "\n".join(lines) + "\n")


# --------------------------------------------------------------------------
# Stage 2: behavioural cases, in risk order.
# --------------------------------------------------------------------------

SQUARE = [(100.0, 100.0), (500.0, 100.0), (500.0, 400.0), (100.0, 400.0)]
TANGENT = (60.0, 0.0)

CASES = []


def case(name):
    def register(fn):
        CASES.append((name, fn))
        return fn
    return register


def new_roto(node_class="RotoPaint"):
    # Non-commercial Nuke caps Node objects reachable from Python at 10, and
    # deleted nodes still count. Clear the whole script between cases.
    nuke.scriptClear()
    return nuke.createNode(node_class, inpanel=False)


def add_square(node, with_tangents=True):
    """Build a closed 4-point shape. Constructor form is unconfirmed - if this
    raises, read 00_api_surface.txt for the real signature."""
    knob = node["curves"]
    shape = rp.Shape(knob)
    for x, y in SQUARE:
        cp = rp.ShapeControlPoint(x, y)
        if with_tangents:
            cp.leftTangent = rp.CVec2(-TANGENT[0], -TANGENT[1])
            cp.rightTangent = rp.CVec2(TANGENT[0], TANGENT[1])
        shape.append(cp)
    knob.rootLayer.append(shape)
    return knob, shape


def vec_xy(v):
    """CVec repr is '{ x, y, w }'. Return (x, y) as floats."""
    nums = re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", str(v))
    return (float(nums[0]), float(nums[1])) if len(nums) >= 2 else (None, None)


def read_tangents(shape, frame=1):
    out = []
    for i in range(len(shape)):
        cp = shape[i]
        out.append((vec_xy(cp.center.getPosition(frame)),
                    vec_xy(cp.leftTangent.getPosition(frame)),
                    vec_xy(cp.rightTangent.getPosition(frame))))
    return out


@case("10_tangent_persistence_CRITICAL")
def _():
    """EXISTENTIAL (prd.md 9.2 'Known API risk'). Write a bezier shape through
    the API, save, reload, and confirm tangents are not flattened to a polyline.
    If this fails, the Nuke importer cannot ship as specified."""
    node = new_roto()
    knob, shape = add_square(node, with_tangents=True)
    before = read_tangents(shape)

    # Non-commercial Nuke only saves .nknc; scriptSaveAs(".nk") silently
    # writes nothing under NC, so pick the extension from the licence mode.
    ext = ".nknc" if nuke.env.get("nc") else ".nk"
    path = os.path.join(OUT, "_tangent_roundtrip" + ext)
    nuke.scriptSaveAs(path, overwrite=1)
    if not os.path.exists(path):
        return "ABORT: scriptSaveAs wrote no file at %s" % path
    nuke.scriptClear()
    nuke.scriptOpen(path)

    node2 = None
    for n in nuke.allNodes():
        if n.Class() in ("Roto", "RotoPaint"):
            node2 = n
    shape2 = node2["curves"].rootLayer[0]
    after = read_tangents(shape2)

    lines = ["wrote tangents L=%r R=%r on every point" % (
        (-TANGENT[0], -TANGENT[1]), TANGENT)]
    flattened = 0
    changed = 0
    for i in range(len(before)):
        same = before[i] == after[i]
        if not same:
            changed += 1
        lines.append("  pt%d  before c=%s L=%s R=%s" % ((i,) + before[i]))
        lines.append("       after  c=%s L=%s R=%s   %s" % (
            after[i][0], after[i][1], after[i][2], "OK" if same else "CHANGED"))
        lt, rt = after[i][1], after[i][2]
        if lt == (0.0, 0.0) and rt == (0.0, 0.0):
            flattened += 1
    lines.append("")
    if flattened:
        lines.append("VERDICT: FAIL - %d/%d points came back with zero tangents." % (
            flattened, len(before)))
        lines.append("Bezier shapes degrade to polylines through this write path.")
        lines.append("The Nuke importer needs a different write pattern. STOP AND REPORT.")
    elif changed:
        lines.append("VERDICT: PARTIAL - tangents survived but %d/%d points changed"
                     % (changed, len(before)))
        lines.append("value. Inspect the numbers above before trusting the path.")
    else:
        lines.append("VERDICT: PASS - tangents survived the save/reload round trip")
        lines.append("unchanged. The Nuke importer can write beziers through this path.")
    os.remove(path)
    return "\n".join(lines)


@case("20_animcurve_key_introspection")
def _():
    """Key times, interpolation type, and per-key tangent slopes (PRD 12).
    Feeds the key union and tier-1 ease conversion."""
    node = new_roto()
    knob, shape = add_square(node)
    cp = shape[0]
    cp.center.addPositionKey(1, rp.CVec2(100.0, 100.0))
    cp.center.addPositionKey(50, rp.CVec2(200.0, 180.0))
    cp.center.addPositionKey(100, rp.CVec2(300.0, 250.0))

    lines = ["center is %s" % type(cp.center).__name__]
    lines.append("dim: %r" % (cp.center.dim,))
    lines.append("getControlPointKeyTimes(): %r" % (cp.center.getControlPointKeyTimes(),))
    lines.append("")
    lines.append("This is the key-time source for the prd.md 9.2 step 3 union.")
    lines.append("")
    for d in range(2):
        try:
            curve = cp.center.getPositionAnimCurve(d)
        except Exception as exc:
            lines.append("--- dim %d: getPositionAnimCurve FAILED: %s ---" % (d, exc))
            continue
        lines.append("--- dim %d: %s ---" % (d, type(curve).__name__))
        lines.append("  dir: %s" % ", ".join(
            [n for n in sorted(dir(curve)) if not n.startswith("__")]))
        for meth in ("getNumberOfKeys", "getKeyTimes", "keys"):
            try:
                lines.append("  %s() -> %r" % (meth, getattr(curve, meth)()))
            except Exception as exc:
                lines.append("  %s() -> FAILED: %s" % (meth, exc))
    return "\n".join(lines)


@case("21_hermite_tangent_semantics")
def _():
    """Weighted vs unweighted slopes on point curves, for tier-1 ease (PRD 12)."""
    node = new_roto()
    knob, shape = add_square(node)
    cp = shape[0]
    # Two collinear keys look linear under ANY interpolation, so use three
    # keys with a deliberately off-line middle value.
    cp.center.addPositionKey(1, rp.CVec2(0.0, 0.0))
    cp.center.addPositionKey(50, rp.CVec2(20.0, 0.0))
    cp.center.addPositionKey(100, rp.CVec2(100.0, 0.0))
    lines = ["Keys: f1=0, f50=20, f100=100 (deliberately non-collinear).",
             "Piecewise-linear predicts the 'linear' column exactly.",
             "Overshoot or smoothing means the default is a curve, not linear.",
             ""]
    for f in (1, 12, 25, 37, 50, 62, 75, 87, 100):
        pos = vec_xy(cp.center.getPosition(f))[0]
        if f <= 50:
            lin = (f - 1) / 49.0 * 20.0
        else:
            lin = 20.0 + (f - 50) / 50.0 * 80.0
        lines.append("  f=%3d  x=%9.4f   linear would be %9.4f   delta %+8.4f"
                     % (f, pos, lin, pos - lin))
    return "\n".join(lines)


@case("30_shape_transform_matrix")
def _():
    """getTransform().getMatrixAt() signature and return type (PRD 12)."""
    node = new_roto()
    knob, shape = add_square(node)
    xf = shape.getTransform()
    lines = ["getTransform() -> %s" % type(xf).__name__]
    lines.append("")
    lines.append("prd.md 9.2 step 5 specifies getMatrixAt(frame). That method does")
    lines.append("not exist on AnimCTransform. Finding the real path:")
    lines.append("")
    for call in ("isDefault()", "getTransformKeyTimes()", "getTranslationKeyTimes()",
                 "getRotationKeyTimes()", "getScaleKeyTimes()",
                 "getNumberOfTransformKeys()", "evaluate(1)"):
        try:
            r = eval("xf." + call)
            lines.append("  xf.%-28s -> %r  (type %s)" % (call, r, type(r).__name__))
        except Exception as exc:
            lines.append("  xf.%-28s -> FAILED: %s" % (call, exc))
    try:
        ev = xf.evaluate(1)
        lines.append("")
        lines.append("dir(evaluate(1)) i.e. %s:" % type(ev).__name__)
        lines.append("  %s" % ", ".join(
            [n for n in sorted(dir(ev)) if not n.startswith("__")]))
    except Exception as exc:
        lines.append("  evaluate(1) unusable: %s" % exc)
    return "\n".join(lines)


@case("40_lifetime_defaults")
def _():
    """Not in prd.md Phase 0, but shapes built via the API inherit a lifetime
    default; a wrong one makes shapes appear on a single frame."""
    node = new_roto()
    knob, shape = add_square(node)
    attrs = shape.getAttributes()
    lines = ["attribute count: %d" % len(attrs)]
    for i in range(len(attrs)):
        name = attrs.getName(i)
        try:
            val = attrs.getValue(1, i)
        except Exception as exc:
            val = "<%s>" % exc
        lines.append("  [%2d] %-6s = %r" % (i, name, val))
    lines.append("")
    lines.append("lifetime attrs: ltt=%r ltn=%r ltm=%r" % (
        attrs.getValue(1, "ltt"), attrs.getValue(1, "ltn"), attrs.getValue(1, "ltm")))
    lines.append("")
    lines.append("visibility sampled across frames:")
    for f in (1, 25, 50, 100, 500):
        try:
            lines.append("  f=%-4d getVisible=%s" % (f, shape.getVisible(f)))
        except Exception as exc:
            lines.append("  f=%-4d FAILED: %s" % (f, exc))
    return "\n".join(lines)


@case("50_element_type_dispatch")
def _():
    """Confirms Shape/Stroke/Layer isinstance dispatch for the export walk."""
    node = new_roto()
    knob, shape = add_square(node)
    layer = rp.Layer(knob)
    nested = rp.Shape(knob)
    for x, y in [(600.0, 600.0), (800.0, 600.0), (700.0, 800.0)]:
        nested.append(rp.ShapeControlPoint(x, y))
    layer.append(nested)
    knob.rootLayer.append(layer)

    lines = []
    for elem in knob.rootLayer:
        lines.append("  %-24s type=%-10s Shape=%s Stroke=%s Layer=%s" % (
            getattr(elem, "name", "?"), type(elem).__name__,
            isinstance(elem, rp.Shape), isinstance(elem, rp.Stroke),
            isinstance(elem, rp.Layer)))
    return "rootLayer children:\n" + "\n".join(lines)


@case("60_feather_attributes")
def _():
    """Per-point feather attribute names, for .rbj feather_model per_point."""
    node = new_roto()
    knob, shape = add_square(node)
    cp = shape[0]
    lines = ["dir(ShapeControlPoint instance):"]
    for name in sorted(dir(cp)):
        if name.startswith("__"):
            continue
        try:
            lines.append("  %-28s = %r" % (name, getattr(cp, name)))
        except Exception as exc:
            lines.append("  %-28s <unreadable: %s>" % (name, exc))
    return "\n".join(lines)


@case("61_feather_representation")
def _():
    """prd.md 6 stores feather as a per-point SCALAR. Nuke gives each control
    point a featherCenter plus its own tangents - a full bezier offset. Check
    whether a scalar can represent it."""
    node = new_roto()
    knob, shape = add_square(node)
    cp = shape[0]
    lines = ["Every ShapeControlPoint member is an AnimControlPoint:",
             "  center, leftTangent, rightTangent,",
             "  featherCenter, featherLeftTangent, featherRightTangent", ""]
    lines.append("center       @1 = %r" % (vec_xy(cp.center.getPosition(1)),))
    lines.append("featherCenter@1 = %r" % (vec_xy(cp.featherCenter.getPosition(1)),))
    lines.append("featherLeftT @1 = %r" % (vec_xy(cp.featherLeftTangent.getPosition(1)),))
    lines.append("featherRightT@1 = %r" % (vec_xy(cp.featherRightTangent.getPosition(1)),))
    lines.append("")
    try:
        cp.featherCenter.setPosition(rp.CVec2(12.0, 7.0))
        lines.append("after setPosition((12,7)):")
        lines.append("  featherCenter@1 = %r" % (vec_xy(cp.featherCenter.getPosition(1)),))
        lines.append("")
        lines.append("If featherCenter is a 2D OFFSET rather than a width scalar,")
        lines.append("the .rbj per-point `feather` float cannot round-trip it and")
        lines.append("prd.md section 6 needs a vector feather field.")
    except Exception as exc:
        lines.append("setPosition FAILED: %s" % exc)
    return "\n".join(lines)


@case("62_uniform_feather")
def _():
    """The OTHER feather. AE has a whole-mask 2-D feather (maskFeather [x,y])
    plus a static falloff mode, entirely separate from feather points.
    01_attribute_names.txt shows Nuke carries fo/fx/fy/ff/ft on the shape's
    AnimAttributes, which looks like the same thing. If it is, the uniform
    layer round-trips losslessly and prd.md 9.3's collapse-to-mean rule is
    unnecessary. Three questions: defaults, anisotropic writability, and
    whether it animates."""
    node = new_roto()
    knob, shape = add_square(node)
    attrs = shape.getAttributes()
    names = [("fo", "feather on"), ("fx", "feather x"), ("fy", "feather y"),
             ("ff", "feather falloff"), ("ft", "feather type")]

    lines = ["defaults at frame 1:"]
    for key, label in names:
        try:
            lines.append("  %s (%-15s) = %r" % (key, label, attrs.getValue(1, key)))
        except Exception as exc:
            lines.append("  %s (%-15s) <unreadable: %s>" % (key, label, exc))

    lines.append("")
    lines.append("anisotropic write - fx=20, fy=5, ff=1, fo=1:")
    try:
        for key, val in (("fo", 1.0), ("fx", 20.0), ("fy", 5.0), ("ff", 1.0)):
            attrs.add(key, val)
        for key, _ in names:
            lines.append("  %s = %r" % (key, attrs.getValue(1, key)))
        lines.append("")
        lines.append("If fx and fy read back 20 and 5 independently, Nuke has a")
        lines.append("2-D uniform feather and AE maskFeather [x,y] maps 1:1 -")
        lines.append("no mean, no anisotropy warning, one less lossy path.")
    except Exception as exc:
        lines.append("  add() FAILED: %s" % exc)

    lines.append("")
    lines.append("is it animatable? (AE maskFeather is a Property, so it is there)")
    lines.append("NOTE: AnimAttributes.addKey introspects as (time, name, value,")
    lines.append("view) but the binding takes 2 args. Go via getCurve instead -")
    lines.append("AnimCurve.addKey(time, value) is the signature that works.")
    for key in ("fx", "ff"):
        try:
            curve = attrs.getCurve(key)
        except Exception:
            try:
                curve = attrs.getCurve(key, 0)
            except Exception as exc:
                lines.append("  %s: getCurve FAILED: %s" % (key, exc))
                continue
        try:
            curve.addKey(1.0, 5.0)
            curve.addKey(50.0, 40.0)
            lines.append("  %s: %d keys, curveType=%r; "
                         "evaluate @1=%r @25=%r @50=%r" % (
                             key, curve.getNumberOfKeys(), curve.curveType,
                             curve.evaluate(1), curve.evaluate(25),
                             curve.evaluate(50)))
            lines.append("     attrs.getValue @1=%r @25=%r @50=%r" % (
                attrs.getValue(1, key), attrs.getValue(25, key),
                attrs.getValue(50, key)))
            # Decisive: is getCurve a live handle or a detached copy? If a
            # re-fetch shows 0 keys, every animated attribute we write is
            # silently discarded and the Nuke importer needs another route.
            again = attrs.getCurve(key)
            lines.append("     re-fetched curve keys = %d  (%s)" % (
                again.getNumberOfKeys(),
                "LIVE" if again.getNumberOfKeys() == 2 else "DETACHED COPY"))
            lines.append("     isDefault=%r constantValue=%r" % (
                curve.isDefault(), curve.constantValue))
            try:
                lines.append("     getValue with explicit view @25 = %r" %
                             attrs.getValue(25, key, 0))
            except Exception as exc:
                lines.append("     getValue(t, name, view) FAILED: %s" % exc)
        except Exception as exc:
            lines.append("  %s: addKey FAILED: %s" % (key, exc))
    lines.append("")
    lines.append("A midpoint that is neither 5 nor 40 means uniform feather")
    lines.append("animates, and prd.md 9.1 step 6 reading it ONCE per shape")
    lines.append("silently freezes it. That would be a spec bug, not a gap.")

    # getValue returned the constant, not the curve. Either add() shadows the
    # curve or getValue needs a view. Isolate on a shape that never saw add().
    lines.append("")
    lines.append("clean shape, curve only, no add() call:")
    try:
        node2 = new_roto()
        knob2, shape2 = add_square(node2)
        attrs2 = shape2.getAttributes()
        c2 = attrs2.getCurve("fx")
        c2.addKey(1.0, 5.0)
        c2.addKey(50.0, 40.0)
        lines.append("  curve.evaluate  @1=%r @25=%r @50=%r" % (
            c2.evaluate(1), c2.evaluate(25), c2.evaluate(50)))
        lines.append("  attrs.getValue  @1=%r @25=%r @50=%r" % (
            attrs2.getValue(1, "fx"), attrs2.getValue(25, "fx"),
            attrs2.getValue(50, "fx")))
        views = nuke.views()
        lines.append("  nuke.views() = %r" % (views,))
        for v in views[:1]:
            try:
                lines.append("  getValue(25, 'fx', %r) = %r" % (
                    v, attrs2.getValue(25, "fx", v)))
            except Exception as exc:
                lines.append("  getValue with view %r FAILED: %s" % (v, exc))
        lines.append("")
        lines.append("  If getValue now tracks the curve, add() was shadowing it")
        lines.append("  and the importer must write keys OR a constant, never")
        lines.append("  both. If it still returns a constant, getValue is not")
        lines.append("  the read path and evaluate() is.")
    except Exception as exc:
        lines.append("  FAILED: %s" % exc)
        node = new_roto()
        knob, shape = add_square(node)
        attrs = shape.getAttributes()

    lines.append("")
    lines.append("does uniform feather compose with per-point featherCenter,")
    lines.append("or does one win? set both and record featherCenter:")
    try:
        cp = shape[0]
        cp.featherCenter.setPosition(rp.CVec2(12.0, 7.0))
        lines.append("  featherCenter@1 = %r  (fx/fy still %r/%r)" % (
            vec_xy(cp.featherCenter.getPosition(1)),
            attrs.getValue(1, "fx"), attrs.getValue(1, "fy")))
        lines.append("  Both readable at once => they are independent layers,")
        lines.append("  and .rbj must carry both, not pick one.")
    except Exception as exc:
        lines.append("  FAILED: %s" % exc)

    return "\n".join(lines)


@case("63_key_interp_asymmetry")
def _():
    """Q9. AE stores an INDEPENDENT interpolation type on each side of a key
    (run 6: key 3 is in=LINEAR out=HOLD). .rbj stores one `interp` per key.
    Nuke's AnimCurveKey introspects with a single `interpolationType` but
    separate lslope/rslope and la/ra. Measure what Nuke can actually express,
    since that bounds what .rbj needs to carry."""
    node = new_roto()
    knob, shape = add_square(node)
    attrs = shape.getAttributes()
    curve = attrs.getCurve("opc")
    curve.addKey(1.0, 0.0)
    curve.addKey(50.0, 1.0)
    curve.addKey(100.0, 0.0)

    lines = ["AnimCurve.curveType = %r, curveTension = %r" % (
        curve.curveType, curve.curveTension)]
    lines.append("kDefaultAnimCurveKeyInterpolation = %r" %
                 rp.AnimCurveKey.kDefaultAnimCurveKeyInterpolation)
    lines.append("")
    lines.append("nuke.rotopaint.InterpolationType values:")
    it = rp.InterpolationType
    for n in sorted(dir(it)):
        if n.startswith("e"):
            lines.append("  %-32s = %r" % (n, getattr(it, n)))
    lines.append("")
    lines.append("per-key state as authored:")
    for i in range(curve.getNumberOfKeys()):
        k = curve.getKey(i)
        lines.append("  key %d  t=%r v=%r interp=%r" % (
            i, k.time, k.value, k.interpolationType))
        lines.append("         lslope=%r rslope=%r la=%r ra=%r" % (
            k.lslope, k.rslope, k.la, k.ra))

    lines.append("")
    lines.append("Nuke has ONE interpolationType per key but SEPARATE")
    lines.append("lslope/rslope. Can the two sides be made to differ?")
    try:
        k = curve.getKey(1)
        k.lslope = 0.0
        k.rslope = 5.0
        again = curve.getKey(1)
        lines.append("  after lslope=0, rslope=5: lslope=%r rslope=%r" % (
            again.lslope, again.rslope))
        lines.append("  %s" % ("ASYMMETRIC slopes stick - Nuke can express a"
                              if again.lslope != again.rslope else
                              "slopes were forced equal - Nuke cannot express a"))
        lines.append("  different shape on each side of a key.")
    except Exception as exc:
        lines.append("  slope write FAILED: %s" % exc)

    # Reset the slopes so the sweep below is not reading the asymmetric write.
    k = curve.getKey(1)
    k.lslope = 0.0
    k.rslope = 0.0

    lines.append("")
    lines.append("interpolationType sweep. Reference behaviours on this curve")
    lines.append("(keys 0.0@1, 1.0@50, 0.0@100):")
    lines.append("  exact linear  -> evaluate(25)=0.4898 evaluate(75)=0.5")
    lines.append("  step/constant -> evaluate(75)=1.0 (outgoing held at key value)")
    lines.append("  cubic default -> evaluate(25)=0.6759 evaluate(75)=0.6875")
    lines.append("")
    lines.append("Hypothesis: the key field is the InterpolationType enum")
    lines.append("shifted by one, so eUndefine(-1) lands on 0.")
    lines.append("")
    for val in (-1, 0, 1, 2, 3, 4, 5, 256):
        try:
            k = curve.getKey(1)
            k.interpolationType = val
            e25 = round(curve.evaluate(25), 4)
            e75 = round(curve.evaluate(75), 4)
            if (e25, e75) == (0.4898, 0.5):
                label = "LINEAR"
            elif e75 == 1.0:
                label = "STEP"
            elif (e25, e75) == (0.6759, 0.6875):
                label = "CUBIC (= untouched default)"
            else:
                label = "other"
            lines.append("  set %4d -> reads %4r  eval(25)=%-8r eval(75)=%-8r  %s" % (
                val, curve.getKey(1).interpolationType, e25, e75, label))
        except Exception as exc:
            lines.append("  set %4d FAILED: %s" % (val, exc))

    lines.append("")
    lines.append("If 1=STEP, 2=LINEAR, 3=CUBIC then the field is simply the")
    lines.append("enum plus one and there is no mystery - just an undocumented")
    lines.append("offset. 256 would then be a separate 'unset' sentinel bit.")

    lines.append("")
    lines.append("If one type governs BOTH sides of a Nuke key, then AE's")
    lines.append("in=LINEAR/out=HOLD has no Nuke equivalent and .rbj can stay")
    lines.append("single-valued for the Nuke direction - but AE->AE round trips")
    lines.append("through .rbj would still lose it. That is the Q9 tradeoff.")
    return "\n".join(lines)


def main():
    print("RotoBridge Phase 0 probe - Nuke %s" % nuke.NUKE_VERSION_STRING)
    print("output: %s\n" % OUT)

    print("stage 1: API surface")
    dump_api()
    dump_attribute_names()

    print("\nstage 2: behaviour")
    failed = []
    for name, fn in CASES:
        try:
            write("%s.txt" % name, fn())
        except Exception:
            write("%s.FAILED.txt" % name, traceback.format_exc())
            failed.append(name)
            print("  !! %s failed" % name)

    print("\n%d/%d cases succeeded" % (len(CASES) - len(failed), len(CASES)))
    if failed:
        print("failed: %s" % ", ".join(failed))
        print("Read 00_api_surface.txt for the real signatures, then fix these.")
    print("\nRead 10_tangent_persistence_CRITICAL.txt first.")


OUT = out_dir()

if __name__ == "__main__":
    main()
