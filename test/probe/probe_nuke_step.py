"""What a Nuke step key does to the segment ARRIVING at it.

Needs Nuke. Invocation is in test/probe/README.md under "Nuke, the step key's
incoming side".

`.rbj` carries interpolation per side and Nuke carries one type per key, so
`core/interp.to_nuke` has to collapse `{in: linear, out: hold}` into one Nuke
key. It picks step, and until 2026-08-22 it reported that as exact on the
grounds that "Nuke's step governs only the outgoing interval, so there is no
incoming side to lose". Case 63 had already measured otherwise - `set 1 ->
eval(25)=0.6759`, the cubic default, where an exact linear reads 0.4898 - but
the inference written on top of it survived into two docstrings and prd.md.

This is that reading in pixels, on the file it actually costs something in, and
it answers the two questions the fix turned on:

  A  how far off is the arrival, as shipped?
  B  can Nuke be told to draw it straight without losing the freeze?

The fixture is `mixed` in `test/golden/ae_scene.rbj`: it holds from frame 18 to
23 and jumps at 24, and the segment 15 -> 18 arrives at that hold. Imported at
tolerance inf so nothing corrects anything - the drift pass would otherwise buy
the answer back before it could be measured.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "nuke"))
sys.path.insert(0, REPO)

import nuke
from core import rbj
import rotobridge_import as rbi
from rotobridge_nuke import point_members

GOLDEN = os.path.join(REPO, "test", "golden", "ae_scene.rbj")
SHAPE = "mixed"
HELD = range(19, 24)

out = sys.argv[1] if len(sys.argv) > 1 else HERE
lines = []


def say(text=""):
    lines.append(text)
    sys.stdout.write(text + "\n")


def spec_of(doc):
    return [s for s in doc["shapes"] if s["name"] == SHAPE][0]


def build():
    """A fresh import of the golden, keys exactly as the file wrote them."""
    doc = rbj.loads(open(GOLDEN).read())
    node, _, _ = rbi.import_document(doc, tolerance=float("inf"),
                                     subset=[SHAPE])
    shape = [el for el in node["curves"].rootLayer if el.name == SHAPE][0]
    return spec_of(doc), shape


def deviation(spec, shape):
    """Per frame, the worst any part of any point sits from the dense layer."""
    out = {}
    for frame in sorted(int(f) for f in spec["frames"]):
        record = spec["frames"][str(frame)]
        worst = 0.0
        for i, point in enumerate(record["points"]):
            cp = shape[i]
            for member, target in ((cp.center, point["c"]),
                                   (cp.leftTangent, point["in"]),
                                   (cp.rightTangent, point["out"])):
                worst = max(worst, rbi._deviation(
                    member.getPosition(float(frame)), target))
        out[frame] = worst
    return out


def report(label, per):
    past = [f for f in sorted(per) if per[f] > 0.5]
    say("  %s" % label)
    say("    arriving  16: %.4f px   17: %.4f px" % (per[16], per[17]))
    say("    frozen    %s" % "  ".join("%d: %.4f" % (f, per[f]) for f in HELD))
    say("    worst %.4f px, past 0.5 px on %s" % (max(per.values()), past))
    say()


def main():
    say("Nuke's step key and the segment arriving at it")
    say("Nuke %s, %s of %s" % (nuke.NUKE_VERSION_STRING, SHAPE,
                               os.path.basename(GOLDEN)))
    say()

    spec, shape = build()
    keys = [(k["frame"], k["interp"]["in"], k["interp"]["out"])
            for k in spec["keys"]]
    say("--- what the file asks for ---")
    say("  keys: %s" % keys)
    say("  the hold is frame 18's outgoing side; frames 19-23 are")
    say("  byte-identical in the bake and frame 24 jumps 360 px.")
    say()

    say("--- A: as shipped, a step key ---")
    report("step, lslope 0.0 (what the importer writes)",
           deviation(spec, shape))
    say("  The arrival is not held flat - that would read as the frame 15")
    say("  value. It overshoots and decelerates in, which is a cubic with a")
    say("  flat handle: case 63's eval(25) in pixels.")
    say()

    say("--- B: the same key made to honour an incoming slope ---")
    spec, shape = build()
    for i in range(len(shape)):
        for member in point_members(shape[i]):
            for d in range(member.dim):
                curve = member.getPositionAnimCurve(d)
                chord = (curve.evaluate(18.0) - curve.evaluate(15.0)) / 3.0
                for n in range(curve.getNumberOfKeys()):
                    key = curve.getKey(n)
                    if abs(key.time - 18.0) < 1e-6:
                        key.interpolationType = nuke.CONSTANT | nuke.BREAK
                        key.lslope = chord
    report("constant|break, incoming slope = the chord",
           deviation(spec, shape))
    say("  The arrival is now exact - 0.2 px is the export conform's own")
    say("  residual, not this key's. The freeze is gone instead: once the")
    say("  key is not constant its outgoing side travels to frame 24.")
    say()

    say("=== CONCLUSION ===")
    say("One type per key means the straight approach OR the freeze, not")
    say("both. The freeze is what the artist authored, so the arrival is")
    say("bought back by the drift pass - 2 corrective keys at the default")
    say("tolerance. What this measurement changed is the labelling:")
    say("`sides_from_nuke` writes `in: ease` for a step, and `to_nuke`")
    say("reports `in: linear` into a `hold` as NOT exact, so the import")
    say("warns instead of claiming a line Nuke does not draw.")

    path = os.path.join(out, "nuke_step_incoming.txt")
    handle = open(path, "w")
    try:
        handle.write("\n".join(lines) + "\n")
    finally:
        handle.close()
    sys.stdout.write("\nwrote %s\n" % path)


main()
