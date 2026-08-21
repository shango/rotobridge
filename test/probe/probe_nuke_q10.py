"""RotoBridge Q10 probe - what a subtractive roto layer actually stores.

Run:  nuke --nc -t probe_nuke_q10.py <script.nknc> [output_dir]

Phase 2 left Q10 open. Case 75 swept all 30 values of a Shape's `bm` while
sampling rendered alpha and found that none of them make one shape subtract
from another. Case 76 found a `Layer` has no `bm` attribute at all. Both were
built from Python, so both could only sweep what the Python API exposes - and
prd.md section 10 assumes union / difference / intersection exist somewhere.

This probe reads a script that was authored **in the UI** with a layer set to a
subtractive blend. The UI is the authority: whatever it wrote is by definition
the real control, whether or not Python can reach it by name.

NC saves are encrypted on disk, so the file cannot be diffed as text. Loading it
and serialising the knob from memory gives the plain form.

Four questions, in order of how much they settle:

  90  What does the tree look like, and which attribute on which element is not
      at its default? Every element is compared against a freshly constructed
      one of the same type, so "different from default" is measured, not
      eyeballed.
  91  What does the curves knob serialise to? That is the on-disk grammar in
      plain text, and case 73 showed it names things the Python API does not.
  92  Does it actually subtract? Sample the rendered alpha on a grid. Without
      this the other three cases only describe a file, not a behaviour.
  93  Which node knobs are off their defaults? If the control turns out to live
      on the node rather than in the tree, this is where it shows up.
"""

import os
import sys
import traceback

import nuke
import nuke.rotopaint as rp

CASES = []

# Cases that read a script authored in the UI; the rest build their own scene.
NEEDS_SCRIPT = ("90_authored_tree", "91_serialised_form", "92_rendered_alpha",
                "93_node_knobs")


def case(name):
    def register(fn):
        CASES.append((name, fn))
        return fn
    return register


def try_(lines, label, fn):
    """Run fn, record the result or the exception. Never raises."""
    try:
        lines.append("  %-46s -> %r" % (label, fn()))
        return True
    except Exception as exc:
        lines.append("  %-46s -> FAILED: %s: %s"
                     % (label, type(exc).__name__, exc))
        return False


def write(name, text):
    f = open(os.path.join(OUT, name), "w")
    f.write(text)
    f.close()
    print("  wrote %s" % name)


def roto_node():
    """The one Roto/RotoPaint node in the loaded script."""
    found = [n for n in nuke.allNodes() if n.Class() in ("Roto", "RotoPaint")]
    if not found:
        raise ValueError("no Roto or RotoPaint node in %s; nodes are %s"
                         % (SCRIPT, [n.Class() for n in nuke.allNodes()]))
    return found[0]


def walk(element, depth=0, path=""):
    """Yield (depth, path, element) for the whole tree, root layer included."""
    name = getattr(element, "name", "?")
    here = "%s/%s" % (path, name) if path else name
    yield depth, here, element
    try:
        children = list(element)
    except TypeError:
        return
    for child in children:
        for item in walk(child, depth + 1, here):
            yield item


def attr_dump(element):
    """{name: value at frame 1} for every attribute the element admits.

    Enumerated with getName(i) rather than guessed: Phase 0 found getValue on
    an unknown name auto-vivifies and returns 0.0, so asking for a list of
    candidates cannot tell an unset attribute from a nonexistent one.
    """
    attrs = element.getAttributes()
    out = {}
    for i in range(attrs.numAttributes()):
        name = attrs.getName(i)
        try:
            out[name] = float(attrs.getValue(1, name, "main"))
        except Exception as exc:
            out[name] = "FAILED: %s" % exc
    return out


def defaults_for(element, knob):
    """Attributes of a fresh element of the same type, as the comparison base."""
    if isinstance(element, rp.Shape):
        fresh = rp.Shape(knob)
    elif isinstance(element, rp.Stroke):
        fresh = rp.Stroke(knob)
    else:
        fresh = rp.Layer(knob)
    return attr_dump(fresh)


@case("90_authored_tree")
def case_90():
    lines = ["The tree the UI wrote, and every attribute that is off default.",
             "",
             "Script: %s" % SCRIPT,
             ""]

    node = roto_node()
    knob = node["curves"]

    lines.append("node: %s (%s)" % (node.name(), node.Class()))
    lines.append("")
    lines.append("tree:")
    elements = list(walk(knob.rootLayer))
    for depth, path, element in elements:
        lines.append("  %s%s  (%s)"
                     % ("  " * depth, path, type(element).__name__))
    lines.append("")

    lines.append("attributes, compared against a fresh element of the same")
    lines.append("type. `bm` on a Shape defaults to 0.0; case 76 found a Layer")
    lines.append("reports no `bm` at all. If the UI wrote one anyway it appears")
    lines.append("here as an attribute the fresh element does not have.")
    lines.append("")

    for depth, path, element in elements:
        lines.append("%s  (%s)" % (path, type(element).__name__))
        try:
            got = attr_dump(element)
        except Exception as exc:
            lines.append("  attribute read FAILED: %s: %s"
                         % (type(exc).__name__, exc))
            lines.append("")
            continue
        try:
            base = defaults_for(element, knob)
        except Exception as exc:
            base = {}
            lines.append("  (no default baseline: %s)" % exc)

        lines.append("  %d attribute(s): %s"
                     % (len(got), ", ".join(sorted(got))))
        extra = sorted(set(got) - set(base))
        if extra:
            lines.append("  NOT ON A FRESH ELEMENT: %s" % ", ".join(extra))
        changed = []
        for name in sorted(got):
            if name not in base:
                changed.append((name, got[name], "(no default)"))
            elif got[name] != base[name]:
                changed.append((name, got[name], base[name]))
        if changed:
            lines.append("  off default:")
            for name, value, was in changed:
                lines.append("    %-6s = %-24r default %r" % (name, value, was))
        else:
            lines.append("  every attribute is at its default")

        # An attribute can also be animated rather than constant, which a
        # single frame-1 read would miss entirely.
        try:
            attrs = element.getAttributes()
            keyed = []
            for i in range(attrs.numAttributes()):
                name = attrs.getName(i)
                curve = attrs.getCurve(name, "main")
                n = curve.getNumberOfKeys()
                if n > 1:
                    keyed.append("%s(%d keys)" % (name, n))
            if keyed:
                lines.append("  animated: %s" % ", ".join(keyed))
        except Exception as exc:
            lines.append("  curve scan FAILED: %s" % exc)
        lines.append("")

    return "\n".join(lines)


@case("91_serialised_form")
def case_91():
    lines = ["The plain-text form of what the UI saved.", "",
             "Case 73 showed the serialised curvegroup names things the Python",
             "API does not. The .nknc on disk is encrypted, so this is the only",
             "way to read the grammar the UI wrote.",
             ""]

    node = roto_node()
    knob = node["curves"]

    lines.append("whole-knob serialisations:")
    for label, fn in (("knob.toScript()", lambda: knob.toScript()),
                      ("knob.serialise()", lambda: knob.serialise()),
                      ("rootLayer.serialise()",
                       lambda: knob.rootLayer.serialise())):
        try:
            text = fn()
        except Exception as exc:
            lines.append("  %-24s FAILED: %s: %s"
                         % (label, type(exc).__name__, exc))
            continue
        lines.append("  %s -> %d chars" % (label, len(text)))
        lines.append("")
        lines.append(text)
        lines.append("")
        lines.append("-" * 68)
        lines.append("")

    lines.append("per element, so a layer's own form can be read on its own:")
    lines.append("")
    for depth, path, element in walk(knob.rootLayer):
        lines.append("%s  (%s)" % (path, type(element).__name__))
        try:
            lines.append("  %s" % element.serialise())
        except Exception as exc:
            lines.append("  serialise() FAILED: %s: %s"
                         % (type(exc).__name__, exc))
        lines.append("")

    return "\n".join(lines)


@case("92_rendered_alpha")
def case_92():
    lines = ["Does it actually subtract? The render is the authority.", "",
             "Case 75's sweep found no shape `bm` that subtracts. If this file",
             "renders a hole, the control is somewhere the sweep never touched,",
             "and case 90 says where.",
             ""]

    node = roto_node()
    nuke.frame(1)

    fmt = nuke.root().format()
    w, h = fmt.width(), fmt.height()
    lines.append("format %dx%d, frame 1" % (w, h))
    lines.append("")

    step_x = max(1, w // 48)
    step_y = max(1, h // 24)
    lines.append("alpha map, '#' >= 0.9, '+' >= 0.5, '.' > 0.01, ' ' none.")
    lines.append("x from 0 step %d, y from top down, step %d." % (step_x, step_y))
    lines.append("A hole inside a filled region is a subtraction; that is the")
    lines.append("whole question.")
    lines.append("")

    def alpha(x, y):
        return nuke.sample(node, "alpha", float(x), float(y))

    try:
        for y in range(h - 1, -1, -step_y):
            row = []
            for x in range(0, w, step_x):
                a = alpha(x, y)
                row.append("#" if a >= 0.9 else
                           "+" if a >= 0.5 else
                           "." if a > 0.01 else " ")
            lines.append("  |%s|" % "".join(row))
    except Exception as exc:
        lines.append("  sampling FAILED: %s: %s" % (type(exc).__name__, exc))
        return "\n".join(lines)

    lines.append("")
    lines.append("alpha range over the sampled grid:")
    values = []
    for y in range(h - 1, -1, -step_y):
        for x in range(0, w, step_x):
            values.append(alpha(x, y))
    lines.append("  min %.6f  max %.6f  distinct(rounded to 3dp) %s"
                 % (min(values), max(values),
                    sorted(set(round(v, 3) for v in values))[:12]))
    return "\n".join(lines)


@case("93_node_knobs")
def case_93():
    lines = ["Node knobs that are off their defaults.", "",
             "If the subtractive control turns out to live on the node rather",
             "than in the curves tree, it shows up here and nowhere else.",
             ""]

    node = roto_node()
    reference = nuke.createNode(node.Class(), inpanel=False)

    for name in sorted(node.knobs()):
        if name == "curves":
            continue
        try:
            got = node[name].value()
        except Exception:
            continue
        try:
            base = reference[name].value()
        except Exception:
            base = "(absent on a fresh node)"
        if got != base:
            lines.append("  %-24s = %-28r default %r" % (name, got, base))

    lines.append("")
    lines.append("full knob list, for the record:")
    lines.append("  %s" % ", ".join(sorted(node.knobs())))
    return "\n".join(lines)



def new_roto():
    """A fresh RotoPaint. NC caps Python-visible nodes at 10, deleted included."""
    nuke.scriptClear()
    return nuke.createNode("RotoPaint", inpanel=False)


def add_shape(knob, parent, name, x0, y0, x1, y1):
    """A rectangle, re-fetched live: append() copies (case 76)."""
    shape = rp.Shape(knob)
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        shape.append(rp.ShapeControlPoint(float(x), float(y)))
    shape.name = name
    parent.append(shape)
    return parent[len(parent) - 1]


def add_layer(knob, name):
    layer = rp.Layer(knob)
    layer.name = name
    knob.rootLayer.append(layer)
    return knob.rootLayer[len(knob.rootLayer) - 1]


def select_only(knob, wanted):
    """Select exactly one element of the tree, deselecting everything else.

    The blending-mode knob is a proxy for the selection, so what is selected
    when it changes decides where the value lands.
    """
    for _, _, element in walk(knob.rootLayer):
        try:
            element.setFlag(rp.FlagType.eSelectedFlag, element is wanted)
        except Exception:
            pass
    try:
        wanted.setFlag(rp.FlagType.eSelectedFlag, True)
    except Exception:
        pass


def bm_of(element):
    try:
        return element.getAttributes().getValue(1, "bm", "main")
    except Exception as exc:
        return "FAILED: %s" % exc


@case("94_blending_knob_anatomy")
def case_94():
    lines = ["What the `blending_mode` node knob is, and what it accepts.", "",
             "Case 93 found it by diffing a UI-authored script against a fresh",
             "node. Cases 73 and 75 missed it because both searched the curves",
             "tree, where it does not live.",
             ""]

    node = new_roto()

    for name in ("blending_mode", "toolbar_blending_mode"):
        if name not in node.knobs():
            lines.append("%s: not on this node" % name)
            lines.append("")
            continue
        knob = node[name]
        lines.append("%s: %s" % (name, knob.Class()))
        try_(lines, "  value()", lambda k=knob: k.value())
        try_(lines, "  getValue()", lambda k=knob: k.getValue())
        try:
            values = list(knob.values())
        except Exception as exc:
            values = []
            lines.append("  values() FAILED: %s: %s" % (type(exc).__name__, exc))
        if values:
            lines.append("  %d value(s):" % len(values))
            for i, v in enumerate(values):
                lines.append("    %2d  %s" % (i, v))
        lines.append("")

    lines.append("Case 73's Merge operation list, for comparison. If the two")
    lines.append("agree in order then `bm` is an index into it after all; the")
    lines.append("default already says otherwise (`bm` 0.0 against `over`).")
    try:
        merge = nuke.createNode("Merge2", inpanel=False)
        ops = list(merge["operation"].values())
        lines.append("  Merge2.operation has %d value(s):" % len(ops))
        for i, v in enumerate(ops):
            lines.append("    %2d  %s" % (i, v))
    except Exception as exc:
        lines.append("  Merge2 FAILED: %s: %s" % (type(exc).__name__, exc))

    return "\n".join(lines)


def _sweep(lines, node, knob, target, probes):
    """Set blending_mode to each legal value; record `bm` and rendered alpha.

    `probes` is [(label, x, y)]. The render is what settles it: case 75 wrote
    `bm` by hand across all 30 values and the overlap never dropped below 1.0.
    """
    values = list(node["blending_mode"].values())
    header = "  %-16s %-12s %s" % ("blending_mode", "bm", "  ".join(
        "%-9s" % label for label, _, _ in probes))
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))

    seen = {}
    for value in values:
        try:
            node["blending_mode"].setValue(value)
            knob.changed()
            nuke.frame(1)
            got = bm_of(target)
            samples = [nuke.sample(node, "alpha", float(x), float(y))
                       for _, x, y in probes]
        except Exception as exc:
            lines.append("  %-16s FAILED: %s: %s"
                         % (value, type(exc).__name__, exc))
            continue
        lines.append("  %-16s %-12s %s"
                     % (value, got, "  ".join("%-9.4f" % s for s in samples)))
        seen[value] = (got, tuple(round(s, 4) for s in samples))
    return seen


@case("95_shape_blending")
def case_95():
    lines = ["Setting `blending_mode` with a SHAPE selected.", "",
             "Two overlapping squares, B above A. If any value renders the",
             "overlap at 0 while A stays at 1, that is difference, and prd.md",
             "section 10 has a Nuke mapping after all.",
             "",
             "  union        -> A 1, overlap 1, B 1",
             "  difference   -> A 1, overlap 0, B 0",
             "  intersection -> A 0, overlap 1, B 0",
             ""]

    node = new_roto()
    knob = node["curves"]
    a = add_shape(knob, knob.rootLayer, "A", 100, 100, 300, 300)
    b = add_shape(knob, knob.rootLayer, "B", 200, 200, 400, 400)
    select_only(knob, b)

    lines.append("A covers (100,100)-(300,300), B covers (200,200)-(400,400).")
    lines.append("B is the selected element; `bm` column is B's.")
    lines.append("")

    probes = [("A only", 150, 150), ("overlap", 250, 250), ("B only", 350, 350)]
    seen = _sweep(lines, node, knob, b, probes)

    lines.append("")
    lines.append("A's bm after the sweep: %r (it was never selected)" % bm_of(a))
    lines.append("")
    lines.append("distinct rendered results: %d of %d values"
                 % (len(set(v[1] for v in seen.values())), len(seen)))
    for result in sorted(set(v[1] for v in seen.values())):
        names = sorted(k for k, v in seen.items() if v[1] == result)
        lines.append("  %s  <- %s" % (result, ", ".join(names)))
    lines.append("")
    lines.append("B serialised at the end, so the stored form is on record:")
    try_(lines, "b.serialise()", lambda: b.serialise())
    return "\n".join(lines)


@case("96_layer_blending")
def case_96():
    lines = ["Setting `blending_mode` with a LAYER selected.", "",
             "The saved script this probe read has its blending mode on a",
             "layer, and case 76 found a Layer carries no `bm` attribute. So",
             "either the knob writes somewhere else, or it writes through to",
             "the shapes inside.",
             ""]

    node = new_roto()
    knob = node["curves"]
    lower = add_layer(knob, "lower")
    upper = add_layer(knob, "upper")
    a = add_shape(knob, lower, "A", 100, 100, 300, 300)
    b = add_shape(knob, upper, "B", 200, 200, 400, 400)
    select_only(knob, upper)

    lines.append("A is on layer 'lower', B on layer 'upper'.")
    lines.append("'upper' is the selected element; `bm` column is the layer's.")
    lines.append("")

    probes = [("A only", 150, 150), ("overlap", 250, 250), ("B only", 350, 350)]
    seen = _sweep(lines, node, knob, upper, probes)

    lines.append("")
    lines.append("after the sweep:")
    lines.append("  upper layer bm : %r" % bm_of(upper))
    lines.append("  shape B bm     : %r" % bm_of(b))
    lines.append("  shape A bm     : %r" % bm_of(a))
    lines.append("")
    lines.append("distinct rendered results: %d of %d values"
                 % (len(set(v[1] for v in seen.values())), len(seen)))
    for result in sorted(set(v[1] for v in seen.values())):
        names = sorted(k for k, v in seen.items() if v[1] == result)
        lines.append("  %s  <- %s" % (result, ", ".join(names)))
    lines.append("")
    lines.append("the layer serialised at the end:")
    try_(lines, "upper.serialise()", lambda: upper.serialise())
    return "\n".join(lines)



@case("97_bm_against_an_input")
def case_97():
    lines = ["Blending written numerically, sampling colour as well as alpha.",
             "",
             "Case 94 settled the numbering: `bm` runs 0 to 14, not the 0 to 29",
             "case 75 assumed from the Merge list. Case 75's sweep therefore",
             "spent half its range out of bounds, and read alpha only.",
             "",
             "Two things change here. The node gets an INPUT, because a blend",
             "has nothing to blend against without one; and every probe reads",
             "red as well as alpha, because a paint-model blend acts on colour.",
             ""]

    nuke.scriptClear()
    src = nuke.createNode("Constant", inpanel=False)
    src["color"].setValue([0.5, 0.5, 0.5, 1.0])
    node = nuke.createNode("RotoPaint", inpanel=False)
    node.setInput(0, src)

    knob = node["curves"]
    a = add_shape(knob, knob.rootLayer, "A", 100, 100, 300, 300)
    b = add_shape(knob, knob.rootLayer, "B", 200, 200, 400, 400)

    lines.append("input: Constant rgba = 0.5, 0.5, 0.5, 1.0")
    lines.append("A covers (100,100)-(300,300), B covers (200,200)-(400,400).")
    lines.append("B's `bm` is the swept value; A stays at its default.")
    lines.append("")
    for name in ("output", "premultiply", "rotoMode", "invert_mask"):
        if name in node.knobs():
            try_(lines, "node[%r].value()" % name,
                 lambda n=name: node[n].value())
    lines.append("")

    probes = [("A only", 150, 150), ("overlap", 250, 250), ("B only", 350, 350)]
    header = ("  %-5s %s" % ("bm", "  ".join("%-19s" % label
                                             for label, _, _ in probes)))
    lines.append("        " + "  ".join("%-19s" % "alpha / red"
                                        for _ in probes))
    lines.append(header)
    lines.append("  " + "-" * (len(header) + 4))

    names = {}
    for value in node["blending_mode"].values():
        label, _, number = value.partition("\t")
        if number.strip().isdigit():
            names[int(number.strip())] = label.strip()

    seen = {}
    for v in range(0, 15):
        try:
            curve = b.getAttributes().getCurve("bm", "main")
            curve.removeAllKeys()
            curve.addKey(1, float(v))
            knob.changed()
            nuke.frame(1)
            cells = []
            key = []
            for _, x, y in probes:
                alpha = nuke.sample(node, "alpha", float(x), float(y))
                red = nuke.sample(node, "red", float(x), float(y))
                cells.append("%-19s" % ("%.4f / %.4f" % (alpha, red)))
                key.append((round(alpha, 4), round(red, 4)))
        except Exception as exc:
            lines.append("  %-5d FAILED: %s: %s" % (v, type(exc).__name__, exc))
            continue
        lines.append("  %-5d %s   %s" % (v, "  ".join(cells),
                                         names.get(v, "?")))
        seen[v] = tuple(key)

    lines.append("")
    lines.append("distinct results: %d of %d values"
                 % (len(set(seen.values())), len(seen)))
    for result in sorted(set(seen.values())):
        which = sorted(k for k, r in seen.items() if r == result)
        lines.append("  %s" % (result,))
        lines.append("      <- bm %s" % ", ".join(
            "%d (%s)" % (k, names.get(k, "?")) for k in which))
    lines.append("")
    lines.append("A's bm is still %r, and the serialised B carries:" % bm_of(a))
    try_(lines, "b.serialise()", lambda: b.serialise())
    return "\n".join(lines)



@case("98_shape_to_shape")
def case_98():
    lines = ["Does one shape subtract from another? Sweep each in turn.", "",
             "Case 97 found `bm` is live but read it in the wrong place. The",
             "overlap is covered by whichever shape draws on top with the",
             "default opaque `over`, which restores it no matter what the other",
             "shape did, so only the shape ON TOP can show a blend there.",
             "Which one that is has never been established, so sweep both.",
             "",
             "No input this time: case 97's Constant carried alpha 1.0",
             "everywhere, which is its own opaque background and hides exactly",
             "the effect being looked for.",
             "",
             "  union        -> A 1, overlap 1, B 1",
             "  difference   -> A 1, overlap 0, B 0   (the top shape cuts)",
             "  intersection -> A 0, overlap 1, B 0",
             ""]

    node = new_roto()
    knob = node["curves"]
    a = add_shape(knob, knob.rootLayer, "A", 100, 100, 300, 300)
    b = add_shape(knob, knob.rootLayer, "B", 200, 200, 400, 400)

    probes = [("A only", 150, 150), ("overlap", 250, 250), ("B only", 350, 350)]

    names = {}
    for value in node["blending_mode"].values():
        label, _, number = value.partition("\t")
        if number.strip().isdigit():
            names[int(number.strip())] = label.strip()

    def set_bm(shape, value):
        curve = shape.getAttributes().getCurve("bm", "main")
        curve.removeAllKeys()
        curve.addKey(1, float(value))

    def render():
        knob.changed()
        nuke.frame(1)
        return [nuke.sample(node, "alpha", float(x), float(y))
                for _, x, y in probes]

    lines.append("A was appended first, B second. rootLayer order: %s"
                 % ", ".join(e.name for e in knob.rootLayer))
    lines.append("at the defaults the render is %s"
                 % ["%.4f" % v for v in render()])
    lines.append("")

    for swept, other, label in ((a, b, "A"), (b, a, "B")):
        set_bm(other, 0.0)
        lines.append("sweeping %s's bm, the other shape left at over:" % label)
        header = "  %-5s %-10s %s" % ("bm", "mode", "  ".join(
            "%-9s" % name for name, _, _ in probes))
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))
        seen = {}
        for v in range(0, 15):
            try:
                set_bm(swept, v)
                samples = render()
            except Exception as exc:
                lines.append("  %-5d FAILED: %s: %s"
                             % (v, type(exc).__name__, exc))
                continue
            reads = _reads_as(samples)
            lines.append("  %-5d %-10s %s  %s"
                         % (v, names.get(v, "?"),
                            "  ".join("%-9.4f" % s for s in samples), reads))
            seen[v] = tuple(round(s, 4) for s in samples)
        set_bm(swept, 0.0)
        lines.append("")
        lines.append("  distinct: %d of %d" % (len(set(seen.values())), len(seen)))
        for result in sorted(set(seen.values())):
            which = sorted(k for k, r in seen.items() if r == result)
            lines.append("    %-28s <- %s" % (result, ", ".join(
                "%d %s" % (k, names.get(k, "?")) for k in which)))
        lines.append("")

    return "\n".join(lines)


def _reads_as(samples):
    """Name the boolean operation a triple of alpha readings corresponds to."""
    def near(got, want):
        return abs(got - want) < 0.01
    a_only, overlap, b_only = samples
    if near(a_only, 1) and near(overlap, 1) and near(b_only, 1):
        return "UNION"
    if near(a_only, 1) and near(overlap, 0) and near(b_only, 0):
        return "DIFFERENCE (B cut from A)"
    if near(a_only, 0) and near(overlap, 0) and near(b_only, 1):
        return "DIFFERENCE (A cut from B)"
    if near(a_only, 0) and near(overlap, 1) and near(b_only, 0):
        return "INTERSECTION"
    return ""


# The script is optional: cases 90-93 read one, 94-96 build their own scene.
args = sys.argv[1:]
SCRIPT = None
if args and args[0].lower().endswith((".nk", ".nknc")):
    SCRIPT = args.pop(0)
OUT = os.path.abspath(args[0] if args else ".")
if not os.path.isdir(OUT):
    os.makedirs(OUT)

print("RotoBridge Q10 probe: %s -> %s" % (SCRIPT or "(no script)", OUT))
if SCRIPT:
    nuke.scriptOpen(SCRIPT)
    print("loaded, %d node(s)" % len(nuke.allNodes()))
else:
    print("no script given; skipping the cases that read one")

for name, fn in CASES:
    if SCRIPT is None and name in NEEDS_SCRIPT:
        print("skipping %s (needs a script)" % name)
        continue
    print("running %s" % name)
    try:
        write("%s.txt" % name, fn())
    except Exception:
        write("%s.FAILED.txt" % name, traceback.format_exc())
        print("  FAILED, traceback written")
print("done")
