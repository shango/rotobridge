"""How many keys the drift pass buys, against how few would do.

Read-only. Takes .rbj files and, for each shape, compares three counts over
the same dense layer and the same tolerance:

  authored  the keys the file carries
  greedy    what `drift.linear_fit` chooses starting from them
  minimum   the fewest keys any piecewise-linear fit could use, by exact
            dynamic programming over the frame range

Every authored key is pinned in both the sweep and the DP, because an
authored key is the artist's and not the tool's to optimise away. So the
floor is never below `authored`, and `greedy` above `minimum` is drift's
bisection buying corrective keys it did not need.

Pass `--free` to unpin them instead. That answers a different question - how
much of the count is the artist's and how much is ours - and its floor is not
a target.

    python3 test/probe/probe_key_minimality.py [tolerance] [file.rbj ...]
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE) if False else REPO)

from core import drift, rbj   # noqa: E402


def dense_vectors(shape, frames):
    """The bake as one flat list per frame, in `denseVectors`' order."""
    out = {}
    for frame in frames:
        flat = []
        for point in shape["frames"][str(frame)]["points"]:
            flat.extend(point["c"])
            flat.extend(point["in"])
            flat.extend(point["out"])
            if "feather" in point:
                flat.append(point["feather"])
        out[frame] = flat
    return out


def segment_fits(dense, frames, i, j, tolerance, held):
    """Does the segment from frames[i] to frames[j] hold every frame between?

    A straight line, except where frames[i] holds: spec section 10.2 makes a
    held segment flat, so pricing it as a line would let the DP claim a fit
    that the destination will not draw.
    """
    a, b = frames[i], frames[j]
    low, high = dense[a], dense[b]
    span = float(b - a)
    flat = a in held
    for k in range(i + 1, j):
        frame = frames[k]
        target = dense[frame]
        ratio = 0.0 if flat else (frame - a) / span
        for n in range(len(target)):
            value = low[n] if flat else low[n] + (high[n] - low[n]) * ratio
            if abs(value - target[n]) > tolerance:
                return False
    return True


def prune(dense, frames, keys, tolerance, pinned, held):
    """Drop every key whose removal still holds the fit - the cheap remedy.

    One backwards sweep. Backwards because drift adds a gap's worst frame and
    its midpoint together, and the midpoint is the one made redundant by the
    worst frame landing next to it; sweeping from the end reaches it while its
    neighbours are still in place.
    """
    keep = list(keys)
    index = dict((frame, i) for i, frame in enumerate(frames))
    for frame in reversed(list(keys)):
        if frame in pinned or frame == frames[0] or frame == frames[-1]:
            continue
        trial = [f for f in keep if f != frame]
        at = trial.index(next(f for f in trial if f > frame))
        if segment_fits(dense, frames, index[trial[at - 1]], index[trial[at]],
                        tolerance, held):
            keep = trial
    return keep


def minimum_keys(dense, frames, tolerance, pinned, held):
    """Fewest keys a piecewise-linear fit needs, by DP. Endpoints always keyed.

    `pinned` frames are forced in - a hold or an authored key is not the drift
    pass's to remove, so counting them out would flatter the comparison.
    """
    n = len(frames)
    forced = set([0, n - 1])
    for index, frame in enumerate(frames):
        if frame in pinned:
            forced.add(index)
    best = [None] * n
    best[0] = (1, None)
    for j in range(1, n):
        for i in range(j):
            if best[i] is None:
                continue
            # A forced frame between i and j would be skipped by this segment.
            if any(i < f < j for f in forced):
                continue
            if not segment_fits(dense, frames, i, j, tolerance, held):
                continue
            if best[j] is None or best[i][0] + 1 < best[j][0]:
                best[j] = (best[i][0] + 1, i)
    if best[n - 1] is None:
        return None
    chain, at = [], n - 1
    while at is not None:
        chain.append(frames[at])
        at = best[at][1]
    return list(reversed(chain))


def report(path, tolerance, free):
    doc = rbj.load(open(path).read()) if hasattr(rbj, "load") else None
    if doc is None:
        import json
        doc = json.load(open(path))
    print("== %s   tolerance %s px" % (os.path.basename(path), tolerance))
    for shape in doc["shapes"]:
        frames = sorted(int(f) for f in shape["frames"])
        dense = dense_vectors(shape, frames)
        keys = shape.get("keys")
        authored = ([int(k["frame"]) for k in keys] if keys is not None
                    else list(frames))
        holds = [int(k["frame"]) for k in (keys or [])
                 if k["interp"]["out"] == "hold"]
        greedy = drift.linear_fit(frames, dense, authored, tolerance, holds)[0]
        pinned = set(holds) if free else set(holds) | set(authored)
        swept = prune(dense, frames, greedy, tolerance, pinned, set(holds))
        floor = minimum_keys(dense, frames, tolerance, pinned, set(holds))
        print("   %-16s frames %3d   authored %3d   greedy %3d   pruned %3d"
              "   minimum %3s%s"
              % (shape["name"], len(frames), len(authored), len(greedy),
                 len(swept), len(floor) if floor else "-",
                 "   <- %d spare" % (len(greedy) - len(floor))
                 if floor and len(greedy) > len(floor) else ""))


def main():
    args = sys.argv[1:]
    tolerance = 0.5
    free = "--free" in args
    args = [a for a in args if a != "--free"]
    if args and not args[0].endswith(".rbj"):
        tolerance = float(args.pop(0))
    paths = args or sorted(
        os.path.join(REPO, "test", "golden", name)
        for name in os.listdir(os.path.join(REPO, "test", "golden"))
        if name.endswith(".rbj"))
    for path in paths:
        report(path, tolerance, free)


if __name__ == "__main__":
    main()
