"""Two linear keys, fifty frames apart, into Nuke. How many come out?

The plainest thing an artist can ask of the tool: nothing else is animated, the
segment between the two keys is straight, and a pass that adds a key here is
manufacturing work.

    "/mnt/c/Program Files/Nuke17.1v1/Nuke17.1.exe" --nc -t test/probe/probe_nuke_two_linear.py

Reads `test/golden/two_linear_keys.rbj`, which the After Effects exporter wrote
from exactly that comp. Imports at 0.5 px and at 0, and reports the key times
that end up on the node's first control point beside what the file asked for.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "nuke"))

import rotobridge_import as rbi   # noqa: E402

sys.path.insert(0, REPO)
from core import rbj   # noqa: E402


def main():
    path = os.path.join(REPO, "test", "golden", "two_linear_keys.rbj")
    with open(path) as handle:
        source = handle.read()

    # `rbj.loads` and not `json.loads`: a v3 file may fold a held span as
    # {"same_as": N}, and expanding that is part of reading the format.
    doc = rbj.loads(source)
    asked = [key["frame"] for key in doc["shapes"][0]["keys"]]
    print("the file asks for %d key(s): %s" % (len(asked), asked))
    print("over %d frames" % len(doc["shapes"][0]["frames"]))
    print("")

    for tolerance in (0.5, 0.0):
        node, warnings, reports = rbi.import_document(rbj.loads(source),
                                                      tolerance=tolerance)
        shape = node["curves"].rootLayer[0]
        times = [int(t) for t in shape[0].center.getControlPointKeyTimes()]
        report = reports[0]
        print("tolerance %.1f px" % tolerance)
        print("  key times on the node: %s" % times)
        print("  %d authored, %d corrective, worst %.4f px"
              % (report["authored"], report["corrective"], report["residual"]))
        for warning in warnings:
            print("  warning: %s" % warning)
        print("")


main()
