"""Can a Roto shape or attribute hold a value with no keys at all?

The provenance work (spec/rbj-v3-draft.md sections 5.2-5.3) lets an importer
know a property was never keyed. After Effects can then hand back a plain
value; this asks what the Nuke side could do with the same knowledge.

Three questions, each measured rather than assumed:

1. Does an `AnimControlPoint` evaluate to a stable position when nothing ever
   calls `addPositionKey` - and is there any call that sets that static value?
2. Does adding one key and then removing it leave the value, or reset it?
3. Does `AnimAttributes.add` set a static attribute value on a shape whose
   curve was never keyed - and does a curve with a single key read back the
   same everywhere?

    "/mnt/c/Program Files/Nuke17.1v1/Nuke17.1.exe" --nc -t test/probe/probe_nuke_static.py

Reads and writes nothing outside the node it builds in memory.
"""

import nuke
import nuke.rotopaint as rp

VIEW = "main"


def vec(v):
    return (round(v.x, 4), round(v.y, 4))


def main():
    node = nuke.createNode("Roto", inpanel=False)
    knob = node["curves"]
    shape = rp.Shape(knob)
    shape.append(rp.ShapeControlPoint(120.0, 45.0))
    knob.rootLayer.append(shape)
    cp = shape[0]

    print("-- 1. constructed position, no keys ever")
    for at in (1.0, 25.0, 100.0):
        print("   centre at %5.1f: %s" % (at, vec(cp.center.getPosition(at))))
    names = [n for n in dir(cp.center)
             if not n.startswith("__") and "Position" in n]
    print("   position-ish members: %s" % ", ".join(sorted(names)))

    print("-- 2. one key added then removed")
    cp.center.addPositionKey(10.0, rp.CVec3(300.0, 200.0, 1.0))
    print("   after add, at 10: %s, at 50: %s"
          % (vec(cp.center.getPosition(10.0)),
             vec(cp.center.getPosition(50.0))))
    cp.center.removePositionKey(10.0)
    print("   after remove, at 10: %s, at 50: %s"
          % (vec(cp.center.getPosition(10.0)),
             vec(cp.center.getPosition(50.0))))

    print("-- 3. attributes")
    attrs = shape.getAttributes()
    curve = attrs.getCurve("opc", VIEW)
    print("   fresh opc keys: %d, value at 1: %.4f, at 50: %.4f"
          % (curve.getNumberOfKeys(),
             attrs.getValue(1, "opc", VIEW), attrs.getValue(50, "opc", VIEW)))
    attrs.add("opc", 0.25)
    curve = attrs.getCurve("opc", VIEW)
    print("   after add(0.25): keys %d, value at 1: %.4f, at 50: %.4f"
          % (curve.getNumberOfKeys(),
             attrs.getValue(1, "opc", VIEW), attrs.getValue(50, "opc", VIEW)))

    curve = attrs.getCurve("fx", VIEW)
    curve.removeAllKeys()
    curve.addKey(1.0, 7.5)
    print("   fx single key: keys %d, value at 1: %.4f, at 50: %.4f"
          % (curve.getNumberOfKeys(),
             attrs.getValue(1, "fx", VIEW), attrs.getValue(50, "fx", VIEW)))

    print("PROBE DONE")


main()
