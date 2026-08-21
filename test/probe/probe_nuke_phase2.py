"""RotoBridge Phase 2 probe - Nuke write path.

Run:  nuke --nc -t probe_nuke_phase2.py [output_dir]

Phase 0 answered what the API *is*. This answers the three things the dense
adapter pair has to do and that Phase 0 left as assumptions:

  70  How do you apply a shape transform to a point? prd.md 9.2 step 5 says
      "take .getMatrix() and apply that to every point", but CMatrix4's public
      surface is all mutators - makeIdentity, rotate, scale, translate - with
      no multiply and no element access. If there is no way to apply it from
      Python, the export must either compose the affine from CTransform's
      components or refuse non-identity transforms.
  71  How do you key a control point per frame? Three candidate signatures
      exist and Phase 0 burned twice on introspected signatures that lie
      (getMatrixAt, AnimAttributes.addKey). The dense importer writes a key on
      every point on every frame, so this is its inner loop.
  72  Which attribute values mean what? Blend mode `bm` and the closed flag
      have no documented enum, and .rbj needs both mapped.

Separate from probe_nuke.py on purpose: that script's golden output is Phase 0's
record, and re-running it would churn every file (object reprs carry addresses).
"""

import os
import sys
import traceback

import nuke
import nuke.rotopaint as rp

SQUARE = [(100.0, 100.0), (500.0, 100.0), (500.0, 400.0), (100.0, 400.0)]

CASES = []


def case(name):
    def register(fn):
        CASES.append((name, fn))
        return fn
    return register


def out_dir():
    if len(sys.argv) > 1:
        d = sys.argv[1]
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        d = os.path.join(here, "..", "golden", "nuke_probe",
                         nuke.NUKE_VERSION_STRING, "phase2")
    d = os.path.abspath(d)
    if not os.path.isdir(d):
        os.makedirs(d)
    return d


def write(name, text):
    f = open(os.path.join(OUT, name), "w")
    f.write(text)
    f.close()
    print("  wrote %s" % name)


def new_roto():
    # NC caps Python-visible nodes at 10, and deleted nodes still count.
    nuke.scriptClear()
    return nuke.createNode("RotoPaint", inpanel=False)


def add_square(node):
    knob = node["curves"]
    shape = rp.Shape(knob)
    for x, y in SQUARE:
        shape.append(rp.ShapeControlPoint(x, y))
    knob.rootLayer.append(shape)
    return knob, shape


def try_(lines, label, fn):
    """Run fn, record the result or the exception. Never raises."""
    try:
        lines.append("  %-46s -> %r" % (label, fn()))
        return True
    except Exception as exc:
        lines.append("  %-46s -> FAILED: %s: %s"
                     % (label, type(exc).__name__, exc))
        return False


@case("70_matrix_application")
def case_70():
    lines = ["How to apply a shape transform to a point (prd.md 9.2 step 5).", ""]

    node = new_roto()
    knob, shape = add_square(node)

    xf = shape.getTransform()
    xf.addTranslationKey(1, 200.0, 50.0, 0.0)
    ct = xf.evaluate(1)
    mat = ct.getMatrix()

    lines.append("CTransform.getMatrix() -> %s" % type(mat).__name__)
    lines.append("")
    lines.append("full dir(CMatrix4), dunders included - the public surface in")
    lines.append("00_api_surface.txt has no multiply, so if one exists it is an")
    lines.append("operator:")
    lines.append("  %s" % ", ".join(sorted(dir(mat))))
    lines.append("")

    lines.append("candidate ways to read the matrix out:")
    try_(lines, "str(mat)", lambda: str(mat))
    try_(lines, "mat[0]", lambda: mat[0])
    try_(lines, "mat[0][0]", lambda: mat[0][0])
    try_(lines, "mat[0, 0]", lambda: mat[0, 0])
    try_(lines, "list(mat)", lambda: list(mat))
    lines.append("")

    vec = rp.CVec3(10.0, 20.0, 1.0)
    lines.append("candidate ways to apply it to CVec3(10, 20, 1):")
    try_(lines, "mat * vec", lambda: mat * vec)
    try_(lines, "vec * mat", lambda: vec * mat)
    try_(lines, "mat.transform(vec)", lambda: mat.transform(vec))
    try_(lines, "mat.multVecMatrix(vec)", lambda: mat.multVecMatrix(vec))
    lines.append("")

    lines.append("fallback path - compose the affine from CTransform components,")
    lines.append("which are documented and readable:")
    for name in ("translation", "rotation", "scale", "skew", "pivotPoint",
                 "rotationOrder", "transformOrder"):
        try_(lines, "ct.%s" % name, lambda n=name: getattr(ct, n))
    lines.append("")

    lines.append("CVec2 / CVec3 component access - the Phase 0 probe parsed the")
    lines.append("repr with a regex, which is not something an adapter should do:")
    lines.append("  dir(CVec3): %s" % ", ".join(
        n for n in sorted(dir(vec)) if not n.startswith("__")))
    for expr, fn in (("vec.x", lambda: vec.x), ("vec[0]", lambda: vec[0]),
                     ("vec.getX()", lambda: vec.getX()),
                     ("tuple(vec)", lambda: tuple(vec))):
        try_(lines, expr, fn)
    lines.append("")

    lines.append("does an animated transform move the points getPosition reports,")
    lines.append("or is getPosition pre-transform? This decides whether the export")
    lines.append("has to bake at all:")
    lines.append("  isDefault()          -> %r" % xf.isDefault())
    lines.append("  cp0 getPosition(1)   -> %s" % shape[0].center.getPosition(1))
    lines.append("  (translation key was +200, +50 at frame 1; SQUARE[0] is %r)"
                 % (SQUARE[0],))
    lines.append("")
    lines.append("If getPosition still reports (100, 100) the transform is a")
    lines.append("separate layer the export must bake. If it reports (300, 150)")
    lines.append("the bake is already done and step 5 is unnecessary.")

    return "\n".join(lines)


@case("71_point_keying")
def case_71():
    lines = ["How to key one control point across frames (dense import inner loop).",
             ""]

    node = new_roto()
    knob, shape = add_square(node)
    cp = shape[0]

    lines.append("dir(AnimControlPoint) candidates: addKey(time, cpOrDim, view),")
    lines.append("addPositionKey(time, positionOrDim, view),")
    lines.append("setPositionKey(time, index, value, id, view).")
    lines.append("Phase 0 found two introspected signatures that lie, so try each.")
    lines.append("")

    lines.append("addPositionKey with a CVec3:")
    try_(lines, "addPositionKey(1, CVec3(100,100,1))",
         lambda: cp.center.addPositionKey(1, rp.CVec3(100.0, 100.0, 1.0)))
    try_(lines, "addPositionKey(10, CVec3(300,200,1))",
         lambda: cp.center.addPositionKey(10, rp.CVec3(300.0, 200.0, 1.0)))
    try_(lines, "addPositionKey(20, CVec3(500,100,1))",
         lambda: cp.center.addPositionKey(20, rp.CVec3(500.0, 100.0, 1.0)))
    lines.append("")

    lines.append("read back:")
    for f in (1, 5, 10, 15, 20):
        try_(lines, "getPosition(%d)" % f, lambda ff=f: cp.center.getPosition(ff))
    try_(lines, "getControlPointKeyTimes()",
         lambda: cp.center.getControlPointKeyTimes())
    lines.append("")

    lines.append("A midpoint that is not the linear average means the point curve")
    lines.append("defaulted to curved (case 21), and the importer must set")
    lines.append("curveType per axis. Frame 5 linear would be x=200, y=150.")
    lines.append("")

    lines.append("per-axis curve access and curveType, the tier-1 linear control:")
    for d in range(cp.center.dim):
        try_(lines, "getPositionAnimCurve(%d).getNumberOfKeys()" % d,
             lambda dd=d: cp.center.getPositionAnimCurve(dd).getNumberOfKeys())
        try_(lines, "getPositionAnimCurve(%d).curveType" % d,
             lambda dd=d: cp.center.getPositionAnimCurve(dd).curveType)
    lines.append("")
    lines.append("  CurveType enum: %s" % ", ".join(
        "%s=%r" % (n, getattr(rp.CurveType, n))
        for n in sorted(dir(rp.CurveType)) if n.startswith("e")))
    lines.append("")

    lines.append("setting curveType to linear and re-reading the midpoint:")
    for d in range(cp.center.dim):
        try_(lines, "set curveType[%d] = eLinearCurveType" % d,
             lambda dd=d: setattr(cp.center.getPositionAnimCurve(dd),
                                  "curveType",
                                  getattr(rp.CurveType, "eLinearCurveType",
                                          rp.CurveType.eBezierCurveType)))
    try_(lines, "getPosition(5) after", lambda: cp.center.getPosition(5))
    lines.append("")

    lines.append("tangents animate too - same call on leftTangent:")
    try_(lines, "leftTangent.addPositionKey(1, CVec3(-60,0,0))",
         lambda: cp.leftTangent.addPositionKey(1, rp.CVec3(-60.0, 0.0, 0.0)))
    try_(lines, "leftTangent.addPositionKey(20, CVec3(-10,30,0))",
         lambda: cp.leftTangent.addPositionKey(20, rp.CVec3(-10.0, 30.0, 0.0)))
    try_(lines, "leftTangent.getPosition(20)",
         lambda: cp.leftTangent.getPosition(20))

    return "\n".join(lines)


@case("72_shape_attributes")
def case_72():
    lines = ["Shape attribute values .rbj has to map (blend, opacity, closed).", ""]

    node = new_roto()
    knob, shape = add_square(node)
    attrs = shape.getAttributes()

    lines.append("defaults on a fresh shape, read with getValue(t, name, view):")
    for name in ("opc", "bm", "inv", "fo", "fx", "fy", "ff", "ft",
                 "ltt", "ltn", "ltm", "vis"):
        try_(lines, "getValue(1, %r, 'main')" % name,
             lambda n=name: attrs.getValue(1, n, "main"))
    lines.append("")

    lines.append("blend mode: .rbj needs union | difference | intersection, and")
    lines.append("`bm` is an undocumented number. Sweep it and record what the")
    lines.append("node reports, so the mapping is measured and not guessed:")
    for v in range(0, 12):
        try_(lines, "set bm=%d then getValue" % v,
             lambda vv=v: (attrs.getCurve("bm", "main").removeAllKeys(),
                           attrs.getCurve("bm", "main").addKey(1, float(vv)),
                           attrs.getValue(1, "bm", "main"))[-1])
    lines.append("")
    lines.append("Compare against the RotoPaint UI's blend dropdown order.")
    lines.append("")

    lines.append("opacity, animated via getCurve + addKey (case 62's working route):")
    try_(lines, "opc curve addKey(1, 1.0)",
         lambda: attrs.getCurve("opc", "main").addKey(1, 1.0))
    try_(lines, "opc curve addKey(20, 0.25)",
         lambda: attrs.getCurve("opc", "main").addKey(20, 0.25))
    for f in (1, 10, 20):
        try_(lines, "getValue(%d, 'opc', 'main')" % f,
             lambda ff=f: attrs.getValue(ff, "opc", "main"))
    lines.append("")
    lines.append("A frame-10 value between 1.0 and 0.25 confirms opacity animates")
    lines.append("and belongs in the dense layer, as spec section 6 assumes.")
    lines.append("")

    lines.append("closed flag - FlagType has eOpenFlag, so closed is its inverse:")
    lines.append("  FlagType: %s" % ", ".join(
        "%s=%r" % (n, getattr(rp.FlagType, n))
        for n in sorted(dir(rp.FlagType)) if n.startswith("e")))
    try_(lines, "shape.getFlag(eOpenFlag)",
         lambda: shape.getFlag(rp.FlagType.eOpenFlag))
    try_(lines, "setFlag(eOpenFlag, True) then getFlag",
         lambda: (shape.setFlag(rp.FlagType.eOpenFlag, True),
                  shape.getFlag(rp.FlagType.eOpenFlag))[-1])
    try_(lines, "setFlag(eOpenFlag, False) then getFlag",
         lambda: (shape.setFlag(rp.FlagType.eOpenFlag, False),
                  shape.getFlag(rp.FlagType.eOpenFlag))[-1])
    lines.append("")

    lines.append("shape name round trip:")
    try_(lines, "shape.name", lambda: shape.name)
    try_(lines, "set name then read",
         lambda: (setattr(shape, "name", "arm_L"), shape.name)[-1])

    return "\n".join(lines)


@case("73_blend_mode_identity")
def case_73():
    lines = ["What `bm` numbers actually mean (case 72 could only echo them back).",
             ""]

    node = new_roto()
    knob, shape = add_square(node)
    attrs = shape.getAttributes()

    lines.append("Nuke roto shapes do not have a union/difference/intersection")
    lines.append("enum the way .rbj assumes; the per-shape blending mode is drawn")
    lines.append("from the Merge operation list. Dump that list so the mapping in")
    lines.append("prd.md 10 is measured rather than assumed:")
    try:
        merge = nuke.createNode("Merge2", inpanel=False)
        values = list(merge["operation"].values())
        for i, v in enumerate(values):
            lines.append("  %3d  %s" % (i, v))
        lines.append("")
        lines.append("  count = %d" % len(values))
    except Exception as exc:
        lines.append("  FAILED: %s" % exc)
    lines.append("")

    lines.append("serialise() the shape at several bm values - the saved form")
    lines.append("names things the Python API does not:")
    for v in (0.0, 1.0, 2.0, 3.0):
        try:
            curve = attrs.getCurve("bm", "main")
            curve.removeAllKeys()
            curve.addKey(1, v)
            text = shape.serialise()
            lines.append("  bm=%s -> %s" % (v, text[:400].replace("\n", " | ")))
        except Exception as exc:
            lines.append("  bm=%s -> FAILED: %s" % (v, exc))
    lines.append("")
    lines.append("If the serialised form carries a name next to bm, that name is")
    lines.append("the mapping. If it carries only the number, .rbj cannot express")
    lines.append("Nuke blending faithfully and prd.md 10 needs revisiting.")

    return "\n".join(lines)


@case("74_linear_point_curve")
def case_74():
    lines = ["How to actually get linear interpolation on a point curve.", ""]

    lines.append("Case 71 found CurveType has NO linear member:")
    lines.append("  %s" % ", ".join(
        "%s=%r" % (n, getattr(rp.CurveType, n))
        for n in sorted(dir(rp.CurveType)) if n.startswith("e")))
    lines.append("")
    lines.append("So prd.md 7 and 9.2 step 3 are wrong to say 'set curveType")
    lines.append("explicitly for linear' - curveType is the spline basis. Case 63")
    lines.append("found the real control is per key: interpolationType = the")
    lines.append("InterpolationType enum PLUS ONE. Case 63 measured that on a")
    lines.append("scalar curve; confirm it on a point POSITION curve, which is")
    lines.append("what the shape importer writes.")
    lines.append("")
    lines.append("  InterpolationType: %s" % ", ".join(
        "%s=%r" % (n, getattr(rp.InterpolationType, n))
        for n in sorted(dir(rp.InterpolationType)) if n.startswith("e")))
    lines.append("")

    node = new_roto()
    knob, shape = add_square(node)
    cp = shape[0]

    cp.center.addPositionKey(1, rp.CVec3(100.0, 100.0, 1.0))
    cp.center.addPositionKey(10, rp.CVec3(300.0, 200.0, 1.0))
    cp.center.addPositionKey(20, rp.CVec3(500.0, 100.0, 1.0))

    lines.append("Keys sit at 1, 10 and 20, so the linear value at frame 5 is")
    lines.append("4/9 of the way from key 1 to key 2: (188.889, 144.444). At")
    lines.append("frame 15 it is halfway from key 2 to key 3: (400, 150).")
    lines.append("")
    lines.append("default (untouched):")
    try_(lines, "getPosition(5)", lambda: cp.center.getPosition(5))
    lines.append("")

    linear = rp.InterpolationType.eLinearInterpolationType
    lines.append("setting every key's interpolationType = eLinear + 1 = %d "
                 "on both axes:" % (linear + 1))
    for d in (0, 1):
        curve = cp.center.getPositionAnimCurve(d)
        for k in range(curve.getNumberOfKeys()):
            key = curve.getKey(k)
            try_(lines, "axis %d key %d: %r -> %d"
                 % (d, k, key.interpolationType, linear + 1),
                 lambda kk=key: setattr(kk, "interpolationType", linear + 1))
    lines.append("")
    try_(lines, "getPosition(5) after", lambda: cp.center.getPosition(5))
    try_(lines, "getPosition(15) after", lambda: cp.center.getPosition(15))
    lines.append("")
    lines.append("Landing on (188.889, 144.444) and (400, 150) means the")
    lines.append("key-level enum+1 is the linear control on point curves too, and")
    lines.append("curveType never needs touching. Note the untouched keys report")
    lines.append("interpolationType 256, the unset sentinel case 63 found.")

    return "\n".join(lines)


@case("75_blend_mode_semantics")
def case_75():
    lines = ["Which `bm` value is union, difference, intersection - by rendering.",
             "",
             "Case 73 showed `bm` is an opaque float and the Python API never",
             "names it. The only authority is what the node actually composites,",
             "so build two overlapping squares and sample the alpha in three",
             "places while sweeping the second shape's blending mode.",
             ""]

    node = new_roto()
    knob = node["curves"]

    def add(name, x0, y0, x1, y1):
        shape = rp.Shape(knob)
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            shape.append(rp.ShapeControlPoint(float(x), float(y)))
        shape.name = name
        knob.rootLayer.append(shape)
        return shape

    add("A", 100, 100, 300, 300)
    b = add("B", 200, 200, 400, 400)
    attrs = b.getAttributes()

    a_only = (150, 150)
    overlap = (250, 250)
    b_only = (350, 350)

    lines.append("A covers (100,100)-(300,300), B covers (200,200)-(400,400).")
    lines.append("Sample points: A only %s, overlap %s, B only %s."
                 % (a_only, overlap, b_only))
    lines.append("")
    lines.append("Reference readings, with B at its default:")
    lines.append("  union        -> A 1, overlap 1, B 1")
    lines.append("  difference   -> A 1, overlap 0, B 0   (B cuts A away)")
    lines.append("  intersection -> A 0, overlap 1, B 0")
    lines.append("")
    lines.append("  %-4s  %-9s  %-9s  %-9s  %s"
                 % ("bm", "A only", "overlap", "B only", "reads as"))

    def alpha(x, y):
        return nuke.sample(node, "alpha", float(x), float(y))

    for v in range(0, 30):
        try:
            curve = attrs.getCurve("bm", "main")
            curve.removeAllKeys()
            curve.addKey(1, float(v))
            node["curves"].changed()
            nuke.frame(1)
            sa = alpha(*a_only)
            so = alpha(*overlap)
            sb = alpha(*b_only)
        except Exception as exc:
            lines.append("  %-4d  FAILED: %s" % (v, exc))
            continue

        def near(got, want):
            return abs(got - want) < 0.01

        if near(sa, 1) and near(so, 1) and near(sb, 1):
            reads = "UNION"
        elif near(sa, 1) and near(so, 0) and near(sb, 0):
            reads = "DIFFERENCE"
        elif near(sa, 0) and near(so, 1) and near(sb, 0):
            reads = "INTERSECTION"
        else:
            reads = ""
        lines.append("  %-4d  %-9.4f  %-9.4f  %-9.4f  %s" % (v, sa, so, sb, reads))

    lines.append("")
    lines.append("The three labelled rows are the mapping prd.md 10 needs. If no")
    lines.append("row reads as one of them, Nuke's roto blending does not contain")
    lines.append("the three operations .rbj assumes and the format's `blend` enum")
    lines.append("is wrong, not the adapter.")

    return "\n".join(lines)


@case("76_layer_blend_semantics")
def case_76():
    lines = ["Blending is a property of the LAYER, not the shape.", "",
             "Case 75 swept the shape attribute and found nothing subtracts.",
             "The reason: in RotoPaint the blending mode belongs to the layer a",
             "spline sits on, and a node can hold several layers. Redo case 75",
             "one level up - two layers, one shape each, sweep the upper",
             "layer's bm and sample the rendered alpha.",
             ""]

    node = new_roto()
    knob = node["curves"]

    # append() COPIES into the tree: the object you passed goes stale and
    # touching it later raises "associated c++ object is NULL". Always re-fetch
    # the live child out of its parent after appending.
    def add_layer(name):
        layer = rp.Layer(knob)
        layer.name = name
        knob.rootLayer.append(layer)
        return knob.rootLayer[len(knob.rootLayer) - 1]

    def add_shape(parent, name, x0, y0, x1, y1):
        shape = rp.Shape(knob)
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            shape.append(rp.ShapeControlPoint(float(x), float(y)))
        shape.name = name
        parent.append(shape)
        return parent[len(parent) - 1]

    lower = add_layer("lower")
    upper = add_layer("upper")
    add_shape(lower, "A", 100, 100, 300, 300)
    add_shape(upper, "B", 200, 200, 400, 400)

    lines.append("append() copies into the tree, so every handle here is")
    lines.append("re-fetched from its parent; the passed-in object goes stale.")
    lines.append("  rootLayer holds %d element(s): %s"
                 % (len(knob.rootLayer),
                    ", ".join("%s(%s)" % (getattr(e, "name", "?"),
                                          type(e).__name__)
                              for e in knob.rootLayer)))
    lines.append("  'lower' holds %d, 'upper' holds %d"
                 % (len(lower), len(upper)))
    lines.append("")
    lines.append("A on layer 'lower' covers (100,100)-(300,300).")
    lines.append("B on layer 'upper' covers (200,200)-(400,400).")
    lines.append("")
    lines.append("  union        -> A 1, overlap 1, B 1")
    lines.append("  difference   -> A 1, overlap 0, B 0")
    lines.append("  intersection -> A 0, overlap 1, B 0")
    lines.append("")
    lines.append("step by step, to find which call on a Layer fails:")
    live = knob.rootLayer[1]
    try_(lines, "type(rootLayer[1])", lambda: type(live).__name__)
    try_(lines, "rootLayer[1].name", lambda: live.name)
    try_(lines, "len(rootLayer[1])", lambda: len(live))
    ok_attrs = try_(lines, "rootLayer[1].getAttributes()",
                    lambda: live.getAttributes())
    if ok_attrs:
        la = live.getAttributes()
        try_(lines, "  getValue(1, 'bm', 'main')",
             lambda: la.getValue(1, "bm", "main"))
        try_(lines, "  getCurve('bm', 'main')",
             lambda: la.getCurve("bm", "main"))
        try_(lines, "  getNumberOfKeys('bm', 'main')",
             lambda: la.getNumberOfKeys("bm", "main"))
        names = []
        for i in range(64):
            try:
                names.append(la.getName(i))
            except Exception:
                break
        lines.append("  attribute names on the layer: %s"
                     % (", ".join(names) if names else "(none enumerable)"))
    lines.append("")
    lines.append("the same calls on the SHAPE inside that layer, for comparison")
    lines.append("- case 72 showed these work at the shape level:")
    try_(lines, "rootLayer[1][0].name", lambda: knob.rootLayer[1][0].name)
    try_(lines, "rootLayer[1][0] getValue(1, 'bm', 'main')",
         lambda: knob.rootLayer[1][0].getAttributes().getValue(1, "bm", "main"))
    lines.append("")

    lines.append("enumerate a SHAPE's attributes for comparison - if `bm` is")
    lines.append("here but not on the layer, blending is shape-level in this API")
    lines.append("whatever the UI presents:")
    sa_names = []
    sattrs = knob.rootLayer[1][0].getAttributes()
    for i in range(80):
        try:
            n = sattrs.getName(i)
        except Exception:
            break
        if n:
            sa_names.append(n)
    lines.append("  %s" % ", ".join(sa_names))
    lines.append("  'bm' present on shape: %s" % ("bm" in sa_names))
    lines.append("")
    lines.append("creating bm on the layer with add() instead of getCurve, since")
    lines.append("the layer has no such attribute to fetch a curve for:")
    try_(lines, "layer add('bm', 27.0)",
         lambda: knob.rootLayer[1].getAttributes().add("bm", 27.0))
    try_(lines, "layer getValue(1, 'bm', 'main')",
         lambda: knob.rootLayer[1].getAttributes().getValue(1, "bm", "main"))
    try:
        knob.changed()
        nuke.frame(1)
        lines.append("  alpha after add: A %.3f overlap %.3f B %.3f"
                     % (alpha(150, 150), alpha(250, 250), alpha(350, 350)))
    except Exception as exc:
        lines.append("  sampling FAILED: %s" % exc)
    lines.append("")

    lines.append("  %-4s  %-9s  %-9s  %-9s  %s"
                 % ("bm", "A only", "overlap", "B only", "reads as"))

    def alpha(x, y):
        return nuke.sample(node, "alpha", float(x), float(y))

    for v in range(0, 30):
        try:
            # Re-fetch every handle each pass. knob.changed() invalidates the
            # AnimAttributes object, and a stale one raises "associated c++
            # object is NULL" rather than returning anything wrong - the same
            # class of trap as append() copying.
            live = knob.rootLayer[1]
            curve = live.getAttributes().getCurve("bm", "main")
            curve.removeAllKeys()
            curve.addKey(1, float(v))
            knob.changed()
            nuke.frame(1)
            sa, so, sb = alpha(150, 150), alpha(250, 250), alpha(350, 350)
        except Exception as exc:
            lines.append("  %-4d  FAILED: %s" % (v, exc))
            continue

        def near(got, want):
            return abs(got - want) < 0.01

        if near(sa, 1) and near(so, 1) and near(sb, 1):
            reads = "UNION"
        elif near(sa, 1) and near(so, 0) and near(sb, 0):
            reads = "DIFFERENCE"
        elif near(sa, 0) and near(so, 1) and near(sb, 0):
            reads = "INTERSECTION"
        else:
            reads = ""
        lines.append("  %-4d  %-9.4f  %-9.4f  %-9.4f  %s" % (v, sa, so, sb, reads))

    lines.append("")
    lines.append("The labelled rows are the mapping .rbj `blend` needs. Because")
    lines.append("AE carries a mode per MASK and Nuke carries one per LAYER, the")
    lines.append("export must read a shape's blend from its parent layer, and the")
    lines.append("import must group shapes by blend into one layer each.")

    return "\n".join(lines)


@case("77_layer_transform")
def case_77():
    lines = ["Does a layer transform reach the points, and does it compose?", "",
             "prd.md 9.2 flattens nested layers to the root with a warning. If a",
             "layer carries its own transform that the export never bakes, then",
             "flattening moves the geometry - silently, which is worse than the",
             "blend loss because it is not a mapping question, it is wrong",
             "output.",
             ""]

    node = new_roto()
    knob = node["curves"]

    layer = rp.Layer(knob)
    layer.name = "moved"
    knob.rootLayer.append(layer)
    layer = knob.rootLayer[len(knob.rootLayer) - 1]

    shape = rp.Shape(knob)
    for x, y in ((100.0, 100.0), (300.0, 100.0), (300.0, 300.0), (100.0, 300.0)):
        shape.append(rp.ShapeControlPoint(x, y))
    shape.name = "inner"
    layer.append(shape)
    shape = layer[len(layer) - 1]

    lines.append("before any transform:")
    try_(lines, "shape[0].center.getPosition(1)",
         lambda: shape[0].center.getPosition(1))
    try_(lines, "layer.getTransform().isDefault()",
         lambda: layer.getTransform().isDefault())
    lines.append("")

    lines.append("put +500, +25 on the LAYER's transform:")
    lxf = layer.getTransform()
    try_(lines, "layer addTranslationKey(1, 500, 25, 0)",
         lambda: lxf.addTranslationKey(1, 500.0, 25.0, 0.0))
    try_(lines, "layer.getTransform().isDefault()", lambda: lxf.isDefault())
    try_(lines, "shape[0].center.getPosition(1)",
         lambda: shape[0].center.getPosition(1))
    try_(lines, "shape.getTransform().isDefault()",
         lambda: shape.getTransform().isDefault())
    try_(lines, "list(layer.getTransform().evaluate(1).getMatrix())",
         lambda: list(lxf.evaluate(1).getMatrix()))
    lines.append("")
    lines.append("If getPosition still reports (100, 100) and the SHAPE transform")
    lines.append("is still default, then the layer transform is a separate factor")
    lines.append("the export must multiply in. Flattening without it is a bug.")
    lines.append("")

    lines.append("now add +7, +9 on the SHAPE transform as well, to see whether")
    lines.append("the two compose and in which order:")
    sxf = shape.getTransform()
    try_(lines, "shape addTranslationKey(1, 7, 9, 0)",
         lambda: sxf.addTranslationKey(1, 7.0, 9.0, 0.0))
    try_(lines, "shape matrix", lambda: list(sxf.evaluate(1).getMatrix()))
    try_(lines, "layer matrix", lambda: list(lxf.evaluate(1).getMatrix()))
    lines.append("")
    lines.append("Neither matrix should contain the other's translation: the")
    lines.append("export has to walk the layer chain and multiply them itself.")
    lines.append("")

    lines.append("where does the rendered shape actually land? sample the alpha")
    lines.append("along y=200 to find the left edge. Authored x is 100; layer")
    lines.append("adds 500 and shape adds 7, so a composed transform puts the")
    lines.append("edge near 607:")
    try:
        knob.changed()
        nuke.frame(1)
        edges = []
        for x in range(90, 700, 1):
            if nuke.sample(node, "alpha", float(x), 200.0) > 0.5:
                edges.append(x)
                break
        lines.append("  first x with alpha > 0.5 on y=200: %s"
                     % (edges[0] if edges else "none found"))
    except Exception as exc:
        lines.append("  sampling FAILED: %s" % exc)

    return "\n".join(lines)


@case("78_transform_chain_order")
def case_78():
    lines = ["In what order do layer and shape transforms compose?", "",
             "Case 77 showed they are separate matrices and that getPosition",
             "reports neither. The export has to multiply them itself, and with",
             "translation only the order is unobservable because translations",
             "commute. Use a ROTATION on the layer and a TRANSLATION on the",
             "shape, which do not.",
             ""]

    node = new_roto()
    knob = node["curves"]

    layer = rp.Layer(knob)
    layer.name = "spun"
    knob.rootLayer.append(layer)
    layer = knob.rootLayer[len(knob.rootLayer) - 1]

    shape = rp.Shape(knob)
    for x, y in ((100.0, 100.0), (300.0, 100.0), (300.0, 300.0), (100.0, 300.0)):
        shape.append(rp.ShapeControlPoint(x, y))
    shape.name = "inner"
    layer.append(shape)
    shape = layer[len(layer) - 1]

    layer.getTransform().addRotationKey(1, 0.0, 0.0, 0.5)
    shape.getTransform().addTranslationKey(1, 400.0, 0.0, 0.0)

    lm = list(knob.rootLayer[0].getTransform().evaluate(1).getMatrix())
    sm = list(knob.rootLayer[0][0].getTransform().evaluate(1).getMatrix())
    lines.append("layer matrix: %s" % [round(v, 4) for v in lm])
    lines.append("shape matrix: %s" % [round(v, 4) for v in sm])
    lines.append("")

    def mul(a, b):
        out = [0.0] * 16
        for r in range(4):
            for c in range(4):
                out[r * 4 + c] = sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4))
        return out

    def apply(m, p):
        return (m[0] * p[0] + m[1] * p[1] + m[3],
                m[4] * p[0] + m[5] * p[1] + m[7])

    authored = (100.0, 100.0)
    layer_then_shape = apply(mul(sm, lm), authored)
    shape_then_layer = apply(mul(lm, sm), authored)
    lines.append("authored point %s maps to:" % (authored,))
    lines.append("  layer applied first  (shape * layer) -> (%.4f, %.4f)"
                 % layer_then_shape)
    lines.append("  shape applied first  (layer * shape) -> (%.4f, %.4f)"
                 % shape_then_layer)
    lines.append("")

    lines.append("oracle: Shape.evaluate(curveNum, time) 'bakes out a curve for")
    lines.append("the shape's outline'. If that is world space it settles both")
    lines.append("the order and gives the round-trip test something to check")
    lines.append("the whole chain against.")
    try:
        curve = shape.evaluate(0, 1)
        lines.append("  type: %s" % type(curve).__name__)
        lines.append("  dir: %s" % ", ".join(
            n for n in sorted(dir(curve)) if not n.startswith("_")))
        for arg in (0, 1, 2, 3, 0.0, 0.25, 0.5, 1.0):
            try_(lines, "  getPoint(%r)" % (arg,),
                 lambda a=arg: curve.getPoint(a))
        lines.append("")
        lines.append("  The authored corners are (100,100) (300,100) (300,300)")
        lines.append("  (100,300). If getPoint returns values near 499/100.9 the")
        lines.append("  layer applies first; near 499/104.4 the shape does. If it")
        lines.append("  returns the authored numbers, evaluate() is pre-transform")
        lines.append("  too and is no oracle at all.")
    except Exception as exc:
        lines.append("  FAILED: %s: %s" % (type(exc).__name__, exc))
    lines.append("")

    lines.append("and where the shape actually renders, as an independent check:")
    try:
        knob.changed()
        nuke.frame(1)
        hits = []
        for x in range(0, 1000, 2):
            if nuke.sample(node, "alpha", float(x), 300.0) > 0.5:
                hits.append(x)
        if hits:
            lines.append("  alpha > 0.5 on y=300 spans x %d..%d"
                         % (hits[0], hits[-1]))
        else:
            lines.append("  no alpha found on y=300")
    except Exception as exc:
        lines.append("  sampling FAILED: %s" % exc)

    return "\n".join(lines)


OUT = out_dir()

print("RotoBridge Phase 2 probe -> %s" % OUT)
for name, fn in CASES:
    print("running %s" % name)
    try:
        write("%s.txt" % name, fn())
    except Exception:
        write("%s.FAILED.txt" % name, traceback.format_exc())
        print("  FAILED, traceback written")
print("done")
