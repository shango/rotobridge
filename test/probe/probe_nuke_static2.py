"""Second half of probe_nuke_static: the setPosition signature, and whether
tangents and featherCenter hold a static set the same way. Same invocation."""
import nuke
import nuke.rotopaint as rp


def vec(v):
    return (round(v.x, 4), round(v.y, 4))


def main():
    node = nuke.createNode("Roto", inpanel=False)
    knob = node["curves"]
    shape = rp.Shape(knob)
    shape.append(rp.ShapeControlPoint(120.0, 45.0))
    knob.rootLayer.append(shape)
    cp = shape[0]

    try:
        cp.leftTangent.setPosition(rp.CVec3(-10.0, 2.0, 0.0))
        print("setPosition(CVec3) accepted")
    except TypeError as e:
        print("setPosition(CVec3) refused: %s" % e)
        try:
            cp.leftTangent.setPosition(1.0, rp.CVec3(-10.0, 2.0, 0.0))
            print("setPosition(at, CVec3) accepted")
        except TypeError as e2:
            print("setPosition(at, CVec3) refused: %s" % e2)

    for at in (1.0, 60.0):
        print("   leftTangent at %5.1f: %s" % (at, vec(cp.leftTangent.getPosition(at))))
    print("   leftTangent keys: %d" % len(cp.leftTangent.getPositionKeyTime()
                                          if hasattr(cp.leftTangent, "getPositionKeyTime") else []))

    cp.featherCenter.setPosition(rp.CVec3(3.0, 4.0, 0.0)) if True else None
    for at in (1.0, 60.0):
        print("   featherCenter at %5.1f: %s" % (at, vec(cp.featherCenter.getPosition(at))))
    print("PROBE DONE")


main()
