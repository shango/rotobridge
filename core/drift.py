"""The drift pass: tolerance-based corrective keys (prd.md sections 5.4, 8;
spec section 10.4).

Pure. The two calls that need a host are injected, so the algorithm is tested
without a licence and the same code runs behind both adapters.

Setting the authored keys is not enough. Tier 1 and tier 2 fit the destination's
interpolation as closely as it can be fitted; whatever is left over is measured
here against the dense layer and pinned with extra keys. That is what makes
tier 2 safe: the fit can be wrong, the positions cannot.
"""


def gaps(frames, keys):
    """Maximal runs of consecutive non-key frames, in order."""
    keyed = set(keys)
    runs = []
    current = []
    for frame in frames:
        if frame in keyed:
            if current:
                runs.append(current)
                current = []
        else:
            current.append(frame)
    if current:
        runs.append(current)
    return runs


def correct(frames, keys, apply_keys, measure, tolerance, max_passes=8,
            authored=None):
    """Add corrective keys until nothing drifts past `tolerance`.

    `apply_keys(key_frames)` writes exactly those keys into the destination.
    `measure(frame)` returns the worst deviation at that frame, in pixels,
    between what the destination now interpolates and the dense layer.

    Returns `(key_frames, worst, at)`. **On return the destination holds
    exactly `key_frames`** - the last thing this function does is apply and
    measure, so a caller never has to guess whether the host is a pass behind.
    `worst` is the largest deviation left on any non-key frame and `at` is the
    frame carrying it, or None when every frame is a key. `worst` is above
    `tolerance` only when `max_passes` ran out, which is what a caller warns
    about; `at` is what makes the warning actionable, since prd.md section 8
    requires the import report to name the frames of worst drift.

    One or two frames are added per gap per pass - the worst in that gap, and
    the gap's midpoint when the worst frame is an end of it - rather than every
    offending frame. A key placed inside a run splits it in two and usually
    fixes most of it, so bisecting converges in a few passes and lands far fewer
    keys than adding every frame over tolerance would. `_survey` carries why the
    midpoint is needed. Every gap is worked in the same pass, so the pass count
    does not scale with the number of gaps - only with how deep the worst one
    has to subdivide.

    Bisecting overshoots, so `_sweep` then takes back what it can. **Only
    invented keys are ever removed.** By default every frame the caller asked
    for counts as authored and survives; a caller that knows better - an
    importer reading a file that names the artist's own frames - passes
    `authored`, and then the keys the caller seeded but the artist never made
    (an exporter's pinned endpoints, a layer transform's frames) are the
    sweep's to give back too. The artist's keys are never this function's to
    optimise away, whatever the tolerance would allow.
    """
    frames = sorted(set(int(f) for f in frames))
    if not frames:
        raise ValueError("drift pass needs at least one frame")

    if tolerance <= 0.0:
        # Tolerance 0 is the dense mode of prd.md section 8: every frame is a
        # key by definition and there is nothing left to measure. Guarding here
        # rather than letting the loop discover it means Nuke's float32 storage
        # residual - about 3e-05 px, Phase 2 - can never be mistaken for drift
        # that more keys would fix.
        apply_keys(frames)
        return frames, 0.0, None

    current = sorted(set(int(f) for f in keys) & set(frames))
    if not current:
        raise ValueError("drift pass needs at least one key inside the frame "
                         "range; got %r against [%d, %d]"
                         % (list(keys), frames[0], frames[-1]))
    authored = set(current) if authored is None \
        else set(int(f) for f in authored)

    converged = False
    worst, at = 0.0, None
    for _ in range(max_passes):
        apply_keys(current)
        additions, worst, at = _survey(frames, current, measure, tolerance)
        if not additions:
            converged = True
            break
        current = sorted(set(current) | set(additions))

    if not converged:
        # The last pass chose frames it never got to apply. Apply and re-measure
        # so the host state and the returned `worst` both describe `current`.
        apply_keys(current)
        _, worst, at = _survey(frames, current, measure, tolerance)
        return current, worst, at

    swept = _sweep(frames, current, authored, apply_keys, measure, tolerance)
    if len(swept) != len(current):
        # The sweep left the host holding whichever trial it tried last, which
        # is not necessarily what it kept. Re-establish the contract.
        current = swept
        apply_keys(current)
        _, worst, at = _survey(frames, current, measure, tolerance)

    return current, worst, at


def _survey(frames, keys, measure, tolerance):
    """Measure every non-key frame once.

    Returns `(additions, worst, at)`: the frames to key next, the worst
    deviation seen anywhere, and the frame carrying it.

    A gap over `tolerance` contributes its worst frame. It contributes the
    gap's **midpoint as well** when that worst frame is one of the gap's two
    ends, because a key on the end of a run does not split it - it shortens it
    by one frame, and `correct`'s whole convergence argument is that a run gets
    split. Error that grows steadily across a run puts its maximum on the run's
    last frame every time, so the pass would walk backwards one frame per pass
    instead of halving, and run out of passes on a gap it could have closed.
    That is not hypothetical: it is what an outgoing `hold` does whenever an
    ancestor transform moves the geometry through the held interval, since the
    destination freezes while the dense layer keeps going (`HANDOFF.md`).

    The worst frame is still always added, so this can only reduce the passes a
    gap needs, never increase them - at a cost of at most one extra key per
    degenerate gap per pass.

    Adding the midpoint *instead of* the worst frame was measured and is worse.
    It looks leaner on a synthetic hold (4 corrective keys against 6) but on the
    real crossing of `test/golden/ae_scene.rbj` it lands the same key count on
    five of six shapes and leaves the sixth - `mixed`, the one carrying the
    `hold` - at 0.4503 px where adding both reaches 0.1000 px. Once the error is
    not perfectly monotone, pinning the measured worst frame is what closes the
    gap; the midpoint only guarantees the run gets split.
    """
    additions = []
    worst, worst_at = 0.0, None
    for run in gaps(frames, keys):
        at, deviation = None, -1.0
        for frame in run:
            here = float(measure(frame))
            if here > deviation:
                at, deviation = frame, here
        if deviation > worst:
            worst, worst_at = deviation, at
        if deviation > tolerance:
            if at == run[0] or at == run[-1]:
                additions.append(run[len(run) // 2])
            additions.append(at)
    return additions, worst, worst_at


def _sweep(frames, keys, authored, apply_keys, measure, tolerance):
    """Give back every added key the fit turns out not to need.

    `correct` bisects, and bisection overshoots: it pins a gap's worst frame
    and the gap's midpoint together, and the midpoint is usually made redundant
    the moment the worst frame lands beside it. Nothing in the loop revisits
    that, so without this pass the result converges above the floor - measured
    against an exact dynamic-programming minimum in
    `test/probe/probe_key_minimality.py`, 9 keys where 4 held the shape on
    `test/golden/held_over_moving_layer.rbj`.

    `authored` names the caller's own keys, which are never candidates. Only
    the frames this pass invented are, so a shape cannot come back with fewer
    keys than the artist put on it.

    Backwards, because the redundant midpoint is the one whose neighbour landed
    after it; reaching it while that neighbour is still in place is what lets a
    single sweep do the work of several.

    Removing a key only changes what the destination draws **between its two
    neighbours** - every other segment still runs between the same pair - so
    only that window is re-measured. An endpoint is a candidate like any other
    unauthored key: dropping one does not merge two segments, it truncates the
    keyed span, and both hosts hold the nearest key's value beyond it - so the
    window it re-measures is everything past its surviving neighbour, and a
    span that really is flat out to the edge gives its endpoint back. That is
    what lets a mask the artist never keyed come home with one key instead of
    the two the exporter pinned around it. One key always survives, because a
    destination cannot hold a shape with none.

    **On return the destination holds exactly what is returned**, which is what
    lets `correct` keep its own promise. A trial has to be applied to be
    measured, so a rejected one leaves the host a key short of the answer -
    and the last trial is rejected as often as not.
    """
    keep = list(keys)
    stale = False
    for frame in reversed(list(keys)):
        if frame in authored or len(keep) == 1:
            continue
        at = keep.index(frame)
        low = keep[at - 1] if at > 0 else None
        high = keep[at + 1] if at + 1 < len(keep) else None
        trial = keep[:at] + keep[at + 1:]
        apply_keys(trial)
        stale = True
        worst = 0.0
        for candidate in frames:
            if (low is None or candidate > low) \
                    and (high is None or candidate < high):
                worst = max(worst, float(measure(candidate)))
                if worst > tolerance:
                    break
        if worst <= tolerance:
            keep = trial
            stale = False
    if stale:
        apply_keys(keep)
    return keep


def linear_fit(frames, dense, keys, tolerance, holds=None, authored=None):
    """The key frames a LINEAR sparse layer needs to reproduce the dense one.

    The export side of the question `correct` answers at import, and the same
    search: only the `measure` differs, and it needs no host, because what a
    straight line between two keys leaves on the frames between them is
    arithmetic on numbers the exporter already has.

    `dense` maps a frame to a flat list of every scalar the destination will
    interpolate - each point's centre, both tangents and its feather, laid end
    to end. Flat because the comparison is component-wise and the container is
    the caller's business; a fixed order because a shape's point count cannot
    change inside a range (spec section 7.3). Tangents and feather are measured
    on the same scale as vertices against the same tolerance, which is the rule
    `nuke/rotobridge_import.py:_deviation` already applies: a tangent that
    drifts bends the rendered edge exactly as far as a vertex that drifts.

    Returns `(key_frames, worst, at)`, as `correct` does, and `authored`
    passes straight through to it: a caller whose seed keys are all its own
    invention - an attribute collapse seeding the range endpoints - passes an
    empty set, and the fit may then land fewer keys than it was given.

    **What this is for.** An adapter whose host has an interpolation the
    destination cannot hold can spend the keys here instead of leaving them to
    be spent at the other end. After Effects' temporal ease is that case and
    the only one measured: Nuke's roto curves have no vocabulary for it at all
    (`core/interp.to_nuke`), so an eased key crosses as a dense bake and the
    compositor meets a shape keyed on every frame with no explanation. Rewriting
    it to linear before the file is written moves the cost to the application
    that created it, and the file that arrives needs no correction.
    """
    held = set(int(f) for f in (holds or ()))
    chosen = {"keys": sorted(set(int(f) for f in keys))}

    def apply_keys(key_frames):
        chosen["keys"] = sorted(int(f) for f in key_frames)

    def measure(frame):
        return _linear_error(dense, chosen["keys"], int(frame), held)

    return correct(frames, keys, apply_keys, measure, tolerance,
                   authored=authored)


def _linear_error(dense, keys, frame, held=()):
    """The worst component of what the destination will draw against the bake.

    A straight line between the bracketing keys, except where the key before
    holds: `holds` names the key frames whose outgoing side is `hold`, and a
    held segment is flat by definition (spec section 10.2). Measuring one as a
    line would report the whole travel of the next key as drift and buy keys to
    flatten something already flat - which is how a conform that meant to
    preserve holds would quietly destroy them.
    """
    target = dense[frame]
    before, after = None, None
    for key in keys:
        if key <= frame:
            before = key
        elif after is None:
            after = key
    if before is not None and before in held:
        low = dense[before]
        return max([abs(low[i] - target[i]) for i in range(len(target))] or [0.0])
    if before is None or after is None:
        # Outside the keyed span there is no line to draw: the destination
        # holds the nearest key's value, which is what both hosts do beyond
        # their first and last key.
        edge = dense[after if before is None else before]
        return max([abs(h - t) for h, t in zip(edge, target)] or [0.0])

    ratio = (frame - before) / float(after - before)
    low, high = dense[before], dense[after]
    worst = 0.0
    for i in range(len(target)):
        value = low[i] + (high[i] - low[i]) * ratio
        worst = max(worst, abs(value - target[i]))
    return worst
