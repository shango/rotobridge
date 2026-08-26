"""Can a key be taken off a Roto control point once it is on?

The drift pass' sweep gives back corrective keys it turns out not to need, and
`drift.correct` documents `apply_keys` as writing **exactly** the frames it is
given. Both importers were written when the pass only ever grew its key list,
so they only ever add. This asks what the Nuke half would have to call to
honour a removal.

    "/mnt/c/Program Files/Nuke17.1v1/Nuke17.1.exe" --nc -t test/probe/probe_nuke_key_removal.py

Reads and writes nothing outside the temporary script it builds in memory.
"""

import nuke
import nuke.rotopaint as rp


def main():
    node = nuke.createNode("Roto", inpanel=False)
    knob = node["curves"]
    shape = rp.Shape(knob)
    point = rp.ShapeControlPoint(0.0, 0.0)
    shape.append(point)
    knob.rootLayer.append(shape)

    centre = shape[0].center
    for at in (1.0, 2.0, 3.0):
        centre.addPositionKey(at, rp.CVec3(at * 10.0, 0.0, 1.0))

    print("centre type: %s" % type(centre).__name__)
    print("keys after three adds: %d" % len(centre.getControlPointKeyTimes()
                                            if hasattr(centre,
                                                       "getControlPointKeyTimes")
                                            else []))
    names = [n for n in dir(centre)
             if "ey" in n and not n.startswith("__")]
    print("key-ish members: %s" % ", ".join(sorted(names)))

    for call in ("removeKeyAt", "removeKey", "removeAllKeys", "clear"):
        print("  has %-16s %s" % (call, hasattr(centre, call)))

    print("key times: %s" % list(centre.getControlPointKeyTimes()))

    # The one that matters: does taking frame 2 off restore the straight line
    # between 1 and 3? 20.0 at frame 2 means the key is gone and the segment
    # interpolates; 20.0 is also what the key held, so frame 2 is read after
    # moving the key at 3 out of the way first.
    centre.addPositionKey(3.0, rp.CVec3(100.0, 0.0, 1.0))
    print("before removal, position at 2.0 = %.4f (keyed 20)"
          % centre.getPosition(2.0).x)

    for call in ("removePositionKey", "removeKey"):
        try:
            getattr(centre, call)(2.0)
            print("%s(2.0) -> times %s, position at 2.0 = %.4f"
                  % (call, list(centre.getControlPointKeyTimes()),
                     centre.getPosition(2.0).x))
            print("   55.0 is the midpoint of 10 at frame 1 and 100 at"
                  " frame 3, so the key really is gone")
            break
        except Exception as error:
            print("%s(2.0) raised: %s" % (call, error))
            try:
                getattr(centre, call)(1)
                print("%s(index 1) -> times %s"
                      % (call, list(centre.getControlPointKeyTimes())))
            except Exception as second:
                print("%s(index 1) raised: %s" % (call, second))


def through_the_importer():
    """And the same thing where it matters: the importer's own apply_keys.

    `held_over_moving_layer.rbj` is the file whose held gap the pass used to
    overshoot. Four key times means the sweep's removals reached the host; nine
    means `apply_keys` is still grow-only and the pass is reporting a shape
    nobody has.
    """
    import json
    import os
    import sys

    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(os.path.dirname(here))
    sys.path.insert(0, os.path.join(repo, "nuke"))
    import rotobridge_import as rbi

    with open(os.path.join(repo, "test", "golden",
                           "held_over_moving_layer.rbj")) as handle:
        doc = json.load(handle)

    node, warnings, reports = rbi.import_document(doc, tolerance=0.5)
    shape = node["curves"].rootLayer[0]
    print("")
    print("through the importer, held_over_moving_layer.rbj at 0.5 px:")
    print("  key times on the node: %s"
          % list(shape[0].center.getControlPointKeyTimes()))
    for report in reports:
        print("  report: %s authored, %s corrective"
              % (report["authored"], report["corrective"]))
    for warning in warnings:
        print("  warning: %s" % warning)


main()
through_the_importer()
