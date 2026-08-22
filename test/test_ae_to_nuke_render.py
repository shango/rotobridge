"""Phase 5, the Nuke half: compare a rendered matte, not a document.

Needs Nuke. Invocation is in test/probe/README.md under "Phase 5 render".

`test/test_ae_to_nuke.py` proves an After Effects .rbj opens in Nuke and comes
back out with the geometry intact. It cannot say what the shapes *render* as,
and acceptance criterion 2 is written in rendered pixels: "a matte difference
under 1% of pixels at >0.01 alpha delta". Two of the three things still open in
this project are only observable there - `ff`, and whether an anchored feather
lands where After Effects puts it (spec/rbj-v2-draft.md section 6.4).

**This file is the half that needs no one.** It builds the Nuke matte from
`test/golden/ae_scene.rbj` and measures it. Pointed at a matte sequence
rendered out of After Effects it measures the crossing itself; without one it
still runs, and what it runs is the part that decides whether the measurement
can be trusted at all:

  1  The chain against itself. The same file imported twice must differ
     nowhere. A chain that cannot report zero would call every later number
     into question.
  2  The chain against a known offset. A square moved 4 px has a difference
     area anyone can compute by hand - 2 edges x 4 px x 400 px - so the
     measured fraction is checked against arithmetic rather than against Nuke.
     Section 1 alone would pass on a chain that always reports zero, which is
     the failure mode that would quietly declare the crossing perfect.
  3  What the default drift tolerance costs the matte. Criterion 4 bounds the
     drift pass in pixels of geometry and is met; nothing until now has said
     what that is worth in rendered pixels, which is the unit criterion 2 is
     written in and the only one an artist sees.

**Nothing is written to disk but the report.** The measurement runs in memory
through CurveTool, so nothing here depends on what Nuke NC will and will not
put in an image file.

**The 10-node limit is a design constraint, not a footnote.** Non-commercial
Nuke hands Python at most 10 `Node` objects per script, cumulatively - a
`nuke.toNode` on a node already held costs another one, and deleting a node
does not give the budget back. `nuke.scriptClear()` is the only reset. So each
section builds one small tree, caches every node in a local, and clears before
the next. Measured in probe `nodelimit`, 2026-08-22.
"""
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "nuke"))
sys.path.insert(0, REPO)

import nuke
import nuke.rotopaint as rp
from core import rbj
import rotobridge_import as rbi

out = sys.argv[1] if len(sys.argv) > 1 else HERE
ae_matte = sys.argv[2] if len(sys.argv) > 2 else None
ae_offset = int(sys.argv[3]) if len(sys.argv) > 3 else 0

GOLDEN = os.path.join(REPO, "test", "golden", "ae_scene.rbj")

# Criterion 2, verbatim: "a matte difference under 1% of pixels at >0.01 alpha
# delta". Both numbers live here so the report can quote them.
ALPHA_DELTA = 0.01
PIXEL_BUDGET = 0.01

lines = []


def say(t=""):
    lines.append(t)
    sys.stdout.write(t + "\n")
    sys.stdout.flush()


def load():
    handle = open(GOLDEN, "r")
    try:
        return rbj.loads(handle.read())
    finally:
        handle.close()


def black():
    """A full-format black to ground a Roto on.

    A Roto with no input carries only its own shapes' bounding box, and
    sampling or averaging outside that is not zero - it raises, or the average
    is taken over the wrong area. Grounding it makes the frame the frame.
    """
    node = nuke.createNode("Constant", inpanel=False)
    node["color"].setValue(0.0)
    return node


def imported(doc, ground, tolerance=0.0, subset=None):
    """The document as a Roto node, grounded, at the given tolerance."""
    node, warnings, _ = rbi.import_document(doc, tolerance=tolerance,
                                            subset=subset)
    node.setInput(0, ground)
    return node, warnings


def closed_names(doc):
    """The shapes both applications can put a matte on the frame for.

    After Effects produces no alpha at all from an open mask path and Nuke
    draws one as a stroke at the node's default width, which is measured and
    recorded in spec/rbj-v2-draft.md section 8. So an open spline in this
    comparison contributes a Nuke-only stroke against an empty region of the
    After Effects render: a large, known difference that says nothing about
    the crossing and would read as a Phase 5 failure. It is held out here and
    named in the report rather than silently dropped.
    """
    return [s["name"] for s in doc["shapes"] if s["closed"]]


def square(ground, dx=0.0):
    """A 500 x 400 axis-aligned square, optionally moved dx to the right.

    Axis-aligned and on whole pixels on purpose: the difference area of a
    horizontal offset is then two rectangles and the expected fraction is
    arithmetic, with no antialiased edge to argue about.
    """
    node = nuke.createNode("Roto", inpanel=False)
    node.setInput(0, ground)
    knob = node["curves"]
    shape = rp.Shape(knob)
    for x, y in ((400, 400), (900, 400), (900, 800), (400, 800)):
        shape.append(rp.ShapeControlPoint(float(x) + dx, float(y)))
    knob.rootLayer.append(shape)
    return node


def scalar(value):
    """One number out of a knob that answers with a channel list.

    `intensitydata` is rgba and `maxlumapixvalue` is rgb, but which of the two
    forms a knob hands back depends on how it is read - `value()` returns the
    list and `valueAt()` a single component. Both are read here, and every
    channel carries the same number by construction, so the largest is the
    number either way.
    """
    if isinstance(value, (list, tuple)):
        return max(float(v) for v in value)
    return float(value)


def comparison(a, b):
    """The measuring tree over two alpha sources. Returns a `measure(frame)`.

    Six nodes, which is the whole budget this section gets. `measure` runs the
    tree twice per frame with the Expression reconfigured between the passes -
    the same node doing two jobs, because an eighth node is affordable and a
    twelfth is not:

      pass 1  threshold, averaged: the fraction of pixels past ALPHA_DELTA,
              which is criterion 2's number directly. The average of a 1/0
              image over the whole frame IS the fraction.
      pass 2  the raw difference, as luma: the worst alpha delta anywhere and
              the pixel carrying it, which is what makes a failure actionable.
    """
    fmt = nuke.root().format()
    roi = [0, 0, fmt.width(), fmt.height()]

    diff = nuke.createNode("Merge2", inpanel=False)
    diff["operation"].setValue("difference")
    diff.setInput(0, a)
    diff.setInput(1, b)

    expr = nuke.createNode("Expression", inpanel=False)
    expr.setInput(0, diff)

    tool = nuke.createNode("CurveTool", inpanel=False)
    tool.setInput(0, expr)
    tool["ROI"].setValue(roi)

    def write_expression(text):
        for i in range(4):
            expr["expr%d" % i].setValue(text)

    def measure(frame):
        write_expression("fabs(a) > %r ? 1 : 0" % ALPHA_DELTA)
        tool["operation"].setValue("Avg Intensities")
        nuke.execute(tool, frame, frame)
        fraction = scalar(tool["intensitydata"].value())

        write_expression("fabs(a)")
        tool["operation"].setValue("Max Luma Pixel")
        nuke.execute(tool, frame, frame)
        worst = scalar(tool["maxlumapixvalue"].value())
        at = tool["maxlumapixdata"].value()

        return fraction, worst, [int(at[0]), int(at[1])]

    return measure


def sweep(measure, frames, label, failures, budget=None):
    """Measure every frame, report it, and return the worst line."""
    say("  %-7s %-12s %-12s %s" % ("frame", "over delta", "worst delta",
                                   "at"))
    worst_fraction, worst_at_frame = 0.0, frames[0]
    for frame in frames:
        fraction, worst, at = measure(frame)
        say("  %-7d %-12.6f %-12.6f (%d, %d)"
            % (frame, fraction, worst, at[0], at[1]))
        if fraction > worst_fraction:
            worst_fraction, worst_at_frame = fraction, frame
    say("  worst frame %d at %.6f of pixels past %g alpha"
        % (worst_at_frame, worst_fraction, ALPHA_DELTA))
    if budget is not None and worst_fraction > budget:
        failures.append("%s: %.4f of pixels differ by more than %g alpha on "
                        "frame %d, against a budget of %.4f"
                        % (label, worst_fraction, ALPHA_DELTA, worst_at_frame,
                           budget))
    return worst_fraction


def main():
    failures = []
    doc = load()
    first, last = doc["range"]
    frames = list(range(int(first), int(last) + 1))
    nuke.root()["first_frame"].setValue(frames[0])
    nuke.root()["last_frame"].setValue(frames[-1])
    fmt = nuke.root().format()

    say("Phase 5, the Nuke half: a rendered matte, measured")
    say("=" * 70)
    say("source   %s" % os.path.basename(GOLDEN))
    say("         %d shape(s), frames %d to %d, exported by %s %s"
        % (len(doc["shapes"]), first, last, doc["source"]["app"],
           doc["source"]["app_version"]))
    say("format   %dx%d = %d pixels" % (fmt.width(), fmt.height(),
                                        fmt.width() * fmt.height()))
    say("criteria acceptance criterion 2: under %g of pixels past %g alpha "
        "delta" % (PIXEL_BUDGET, ALPHA_DELTA))
    say()

    say("--- 1. the chain against itself ---")
    say("  The same file imported twice. Anything but zero everywhere means")
    say("  the measurement is wrong, and every later number with it.")
    ground = black()
    a, warnings = imported(doc, ground)
    b, _ = imported(doc, ground)
    identity = sweep(comparison(a, b), frames, "identity", failures)
    if identity != 0.0:
        failures.append("the same file imported twice differs from itself by "
                        "%.6f of pixels" % identity)
    for warning in warnings:
        say("  import warning: %s" % warning)
    say()

    nuke.scriptClear()
    nuke.root()["first_frame"].setValue(frames[0])
    nuke.root()["last_frame"].setValue(frames[-1])

    say("--- 2. the chain against arithmetic ---")
    say("  A 500 x 400 square against itself moved 4 px. The difference is")
    say("  two 4 x 400 rectangles, which is a number this file computes")
    say("  without asking Nuke. Section 1 alone would pass on a chain that")
    say("  always says zero; this is what rules that out.")
    dx, height = 4.0, 400.0
    expected = (2.0 * dx * height) / (fmt.width() * fmt.height())
    ground = black()
    measured = sweep(comparison(square(ground), square(ground, dx)),
                     frames[:1], "offset square", failures)
    say("  expected %.8f (2 x %g x %g px), measured %.8f"
        % (expected, dx, height, measured))
    if expected == 0.0 or abs(measured - expected) / expected > 0.05:
        failures.append("a 4 px offset measured %.8f where arithmetic says "
                        "%.8f" % (measured, expected))
    say()

    nuke.scriptClear()
    nuke.root()["first_frame"].setValue(frames[0])
    nuke.root()["last_frame"].setValue(frames[-1])

    say("--- 3. what the default tolerance costs the matte ---")
    say("  The same file at tolerance 0 against tolerance 0.5. Criterion 4")
    say("  bounds the drift pass in pixels of GEOMETRY and is met; this is")
    say("  the same question asked in rendered pixels, which is the unit the")
    say("  artist actually sees and the one criterion 2 is written in.")
    ground = black()
    dense, _ = imported(doc, ground, tolerance=0.0)
    sparse, _ = imported(doc, ground, tolerance=0.5)
    cost = sweep(comparison(dense, sparse), frames, "drift cost", failures,
                 budget=PIXEL_BUDGET)
    say("  the default tolerance costs %.6f of the frame at its worst, "
        "against a %g budget" % (cost, PIXEL_BUDGET))
    say()

    nuke.scriptClear()
    nuke.root()["first_frame"].setValue(frames[0])
    nuke.root()["last_frame"].setValue(frames[-1])

    say("--- 4. against After Effects' own render ---")
    if not ae_matte:
        say("  NOT RUN. No matte sequence was given, so the crossing itself")
        say("  is still unmeasured and Phase 5 is still open.")
        say()
        say("  What is needed, from the comp test/probe/setup_ae_scene.jsx")
        say("  built - the same one ae_scene.rbj was exported from:")
        say("    - render frames %d to %d of the layer 'RotoBridge test'"
            % (first, last))
        say("      ALONE, soloed. The comp also carries 'RotoBridge static',")
        say("      whose masks are not in this file, and their alpha would")
        say("      measure as geometry Nuke was never given;")
        say("    - a matte sequence, straight alpha, 16-bit or float;")
        say("    - EXR or PNG, numbered by the comp's own frame numbers;")
        say("    - re-run this file with the pattern as the second argument,")
        say("      for example ...\\ae_matte_####.exr, and a frame offset as")
        say("      the third if the numbering does not start at %d." % first)
        say()
        say("  test/probe/probe_ae_phase5.jsx does all of that in one run and")
        say("  reports the pattern and the offset to pass back here.")
        say()
        say("  The comparison is against ALPHA, and a render with none does")
        say("  not quietly pass: measured in Nuke 17.1v1 on 2026-08-22, a")
        say("  matte carrying no alpha reads as 0.0708 of the frame differing")
        say("  on frame 12, seven times the budget. A wrong render fails")
        say("  loudly. What it does not do is fail INFORMATIVELY, so check")
        say("  the channels line above before reading a failure as geometry.")
        return failures

    say("  matte    %s" % ae_matte)
    wanted = closed_names(doc)
    held = [s["name"] for s in doc["shapes"] if not s["closed"]]
    if held:
        say("  held out %s - After Effects renders no alpha from an open mask"
            % ", ".join(held))
        say("           path and Nuke strokes one, so the difference would be")
        say("           that limitation rather than the crossing")
    ground = black()
    nuke_side, _ = imported(doc, ground, subset=wanted)
    read = nuke.createNode("Read", inpanel=False)
    read["file"].setValue(ae_matte)
    read["first"].setValue(frames[0] + ae_offset)
    read["last"].setValue(frames[-1] + ae_offset)
    # Raw, never sRGB: a LUT on the way in would move every value before the
    # comparison and the difference would be the LUT, not the geometry.
    read["colorspace"].setValue("linear")
    if ae_offset:
        read["frame_mode"].setValue("offset")
        read["frame"].setValue(str(-ae_offset))
    say("  read     %dx%d, channels %s"
        % (read.width(), read.height(), read.channels()[:8]))
    if read.width() != fmt.width() or read.height() != fmt.height():
        failures.append("the matte is %dx%d and the .rbj was exported from a "
                        "%dx%d comp; the comparison is not like for like"
                        % (read.width(), read.height(), fmt.width(),
                           fmt.height()))
    sweep(comparison(nuke_side, read), frames, "the crossing", failures,
          budget=PIXEL_BUDGET)
    return failures


try:
    failures = main()
    say()
    say("=== VERDICT ===")
    if failures:
        say("FAIL")
        for f in failures:
            say("  - %s" % f)
    elif ae_matte:
        say("PASS - an After Effects matte and Nuke's matte agree inside "
            "criterion 2")
    else:
        say("PASS - the measurement is sound; the crossing itself is not yet "
            "measured")
except Exception:
    say("EXCEPTION")
    say(traceback.format_exc())

handle = open(os.path.join(out, "ae_to_nuke_render_report.txt"), "w")
handle.write("\n".join(lines) + "\n")
handle.close()
