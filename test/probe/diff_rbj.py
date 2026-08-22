"""Compare two `.rbj` files field by field. Host-free, stdlib only.

Written for one job: deciding whether a re-export of `test/golden/ae_scene.rbj`
changed only what the exporter change predicted. A plain `diff` cannot answer
that - the file is 1200 lines of pretty-printed floats, so a one-ulp wobble in
the bake and a flipped `interp` label look the same in it.

So geometry and labels are reported separately. Geometry is summarised as a
worst-case distance in pixels, which is a number you can hold against a
tolerance; labels are listed individually, because every one of them is a claim
someone made on purpose.

    python3 test/probe/diff_rbj.py OLD.rbj NEW.rbj
"""

import json
import sys

HEADER = ("format", "version", "range")
SHAPE_FIELDS = ("closed", "blend", "feather_model", "feather_falloff")


def load(path):
    with open(path) as handle:
        return json.load(handle)


def by_name(doc):
    return dict((s["name"], s) for s in doc["shapes"])


def diff_keys(old, new, name, out):
    """Key lists as `{frame: key}`, so a key added or dropped reads as one."""
    a = dict((k["frame"], k) for k in old["keys"])
    b = dict((k["frame"], k) for k in new["keys"])
    for frame in sorted(set(a) | set(b)):
        if frame not in a:
            out.append("%s key %s: added" % (name, frame))
            continue
        if frame not in b:
            out.append("%s key %s: dropped" % (name, frame))
            continue
        for side in ("in", "out"):
            was, now = a[frame]["interp"][side], b[frame]["interp"][side]
            if was != now:
                out.append("%s key %s %s: %s -> %s"
                           % (name, frame, side, was, now))
        if a[frame].get("ease") != b[frame].get("ease"):
            out.append("%s key %s: ease %s -> %s"
                       % (name, frame, a[frame].get("ease"),
                          b[frame].get("ease")))


def diff_anchors(old, new, note):
    """The `anchored` feather layer, spec/rbj-v2-draft.md section 6.3.

    Compared by position rather than by index: `t` is what identifies an
    anchor, and the list is sorted by it, so an anchor added at the front
    would otherwise report as every entry having changed.

    This is geometry, not a label. `t` is a position along the path and
    `feather` is a distance in pixels, and both move by float epsilon for the
    same reasons a vertex does.
    """
    a = dict((round(e["t"], 9), e) for e in old.get("feather_points", ()))
    b = dict((round(e["t"], 9), e) for e in new.get("feather_points", ()))
    for t in sorted(set(a) | set(b)):
        if t not in a:
            note("anchor added at t %g, feather %g" % (t, b[t]["feather"]))
        elif t not in b:
            note("anchor dropped at t %g, feather %g" % (t, a[t]["feather"]))
        elif a[t]["feather"] != b[t]["feather"]:
            note("anchor at t %g feather %g -> %g"
                 % (t, a[t]["feather"], b[t]["feather"]))


def summarise(frames, total):
    """Which frames a per-frame difference happened on, said briefly.

    A feather layer that changed model changed on all 25 frames, and printing
    that 25 times buries the one line that says which model. The tool exists
    to make a diff readable, so it says the count instead.
    """
    if len(frames) == total:
        return "on every frame"
    if len(frames) <= 3:
        return "at frame " + ", ".join(str(f) for f in frames)
    return "at %d frames, first %s" % (len(frames), frames[0])


def worst_geometry(old, new, name, out):
    """Worst per-point distance over every frame, or None if incomparable.

    A frame or point count that differs is not a distance - it is a different
    shape, and averaging it into a millimetre figure would hide that. Those
    report and return None rather than contributing a number.
    """
    if set(old["frames"]) != set(new["frames"]):
        out.append("%s: frame set differs" % name)
        return None
    worst, where = 0.0, None
    ordered = sorted(old["frames"], key=int)
    # Per-frame differences are gathered rather than printed, because the ones
    # that matter here are the ones that repeat: a shape whose feather model
    # changed says the same thing on every frame it has.
    seen = {}

    def note(message, frame):
        seen.setdefault(message, []).append(frame)

    for frame in ordered:
        pa = old["frames"][frame]["points"]
        pb = new["frames"][frame]["points"]
        if len(pa) != len(pb):
            out.append("%s frame %s: %d points -> %d"
                       % (name, frame, len(pa), len(pb)))
            return None
        for i in range(len(pa)):
            for vec in ("c", "in", "out"):
                for axis in (0, 1):
                    d = abs(pa[i][vec][axis] - pb[i][vec][axis])
                    if d > worst:
                        worst, where = d, "%s point %d %s" % (frame, i, vec)
            if pa[i].get("feather") != pb[i].get("feather"):
                note("point %d: feather %s -> %s"
                     % (i, pa[i].get("feather"), pb[i].get("feather")), frame)
        diff_anchors(old["frames"][frame], new["frames"][frame],
                     lambda m, f=frame: note(m, f))

    for message in sorted(seen):
        out.append("%s: %s %s"
                   % (name, message, summarise(seen[message], len(ordered))))
    if where:
        out.append("%s: geometry worst %.4e px at frame %s"
                   % (name, worst, where))
    return worst


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    old, new = load(argv[1]), load(argv[2])
    labels, geometry = [], []

    for field in HEADER:
        if old[field] != new[field]:
            labels.append("header %s: %r -> %r"
                          % (field, old[field], new[field]))
    if old["source"] != new["source"]:
        labels.append("source: %r -> %r" % (old["source"], new["source"]))
    for line in set(old.get("warnings", [])) ^ set(new.get("warnings", [])):
        labels.append("warning changed: %s" % line)

    a, b = by_name(old), by_name(new)
    for name in sorted(set(a) | set(b)):
        if name not in a or name not in b:
            labels.append("shape %s: %s"
                          % (name, "added" if name in b else "dropped"))
            continue
        for field in SHAPE_FIELDS:
            if a[name][field] != b[name][field]:
                labels.append("%s %s: %r -> %r"
                              % (name, field, a[name][field], b[name][field]))
        diff_keys(a[name], b[name], name, labels)
        worst_geometry(a[name], b[name], name, geometry)

    print("--- labels: what someone claimed on purpose ---")
    print("\n".join("  " + l for l in labels) if labels else "  identical")
    print("")
    print("--- geometry: what the bake evaluated to ---")
    print("\n".join("  " + l for l in geometry) if geometry else "  identical")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
