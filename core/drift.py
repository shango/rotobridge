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


def correct(frames, keys, apply_keys, measure, tolerance, max_passes=8):
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

    One frame is added per gap per pass, the worst in that gap, rather than
    every offending frame. A key placed at the worst point of a run splits it
    in two and usually fixes most of it, so bisecting converges in a few passes
    and lands far fewer keys than adding every frame over tolerance would. Every
    gap is worked in the same pass, so the pass count does not scale with the
    number of gaps - only with how deep the worst one has to subdivide.
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


def _survey(frames, keys, measure, tolerance):
    """Measure every non-key frame once.

    Returns `(additions, worst, at)`: the worst frame of each gap that exceeds
    `tolerance`, the worst deviation seen anywhere, and the frame carrying it.
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
            additions.append(at)
    return additions, worst, worst_at
