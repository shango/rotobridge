"""Does the Nuke importer put the file's tangents on the control points?"""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "nuke"))
sys.path.insert(0, REPO)
import nuke
from core import rbj
import rotobridge_import as rbi

src = sys.argv[1]
doc = rbj.loads(open(src).read()) if hasattr(rbj, "loads") else json.load(open(src))
print("file: %s" % src)

for tol in (0.5, 0.0):
    nuke.scriptClear()
    node, warnings, reports = rbi.import_document(doc, tolerance=tol)
    curve = node["curves"]
    at = float(doc["range"][0])
    print("\n--- tolerance %s ---" % tol)
    for shape in curve.rootLayer:
        name = shape.name if hasattr(shape, "name") else "?"
        worst_in = worst_out = 0.0
        for cp in shape:
            li = cp.leftTangent.getPosition(at)
            ri = cp.rightTangent.getPosition(at)
            worst_in = max(worst_in, abs(li.x), abs(li.y))
            worst_out = max(worst_out, abs(ri.x), abs(ri.y))
        # what the file says for the same shape
        spec = [s for s in doc["shapes"] if s["name"] == name]
        f_in = 0.0
        if spec:
            pts = spec[0]["frames"][str(int(at))]["points"]
            f_in = max(max(abs(p["in"][0]), abs(p["in"][1]),
                           abs(p["out"][0]), abs(p["out"][1])) for p in pts)
        print("  %-12s node |t| max in=%.4f out=%.4f   file |t| max=%.4f"
              % (name, worst_in, worst_out, f_in))
