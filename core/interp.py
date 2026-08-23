"""Key interpolation translation (spec section 10, prd.md section 7).

Pure functions, no host calls and no I/O.

Nuke's per-key interpolation field is the `InterpolationType` enum **plus one**
(Phase 0 case 63, Phase 2 case 74), so the constants here carry the offset and
no adapter ever writes a bare enum value. `256` is a separate unset sentinel
that a fresh key reports and that behaves as cubic.

After Effects' three key types map one-to-one onto the three `.rbj` values, so
that direction is exact and needs no tiers at all (spec section 10.1). Only its
`ease` parameters need converting, and only by a factor of 100. The tier
machinery below exists for Nuke, which has one type per key across every axis of
every control point.

The lossy step lives here rather than in an adapter because it is the same
step in both directions: `.rbj` carries **one** `interp` per key for the whole
shape, matching After Effects, where a mask path has one keyframe per time.
Nuke carries one per axis per control point. Going out reduces; coming in
expands. Positional truth is not this module's job - it belongs to the dense
layer and the drift pass (`core/drift.py`).
"""

# InterpolationType + 1. Never write the bare enum.
NUKE_STEP = 1
NUKE_LINEAR = 2
NUKE_CUBIC = 3
NUKE_UNSET = 256

HOLD = "hold"
LINEAR = "linear"
EASE = "ease"

# KeyframeInterpolationType, read off the host in Phase 0 (probe runs 2 and 4)
# rather than trusted from documentation. Note the ordering: LINEAR is the
# *lowest* of the three, which is easy to get wrong from memory because the
# menu presents them in the other order.
AE_LINEAR = 6612
AE_BEZIER = 6613
AE_HOLD = 6614

# After Effects reports ease influence as a percentage and .rbj stores a
# fraction (spec section 10.3). Its own default is 16.667%.
AE_INFLUENCE_SCALE = 100.0
AE_DEFAULT_INFLUENCE = 16.667


def sides_from_nuke(key_type):
    """One Nuke key type to the `{in, out}` pair spec section 10.1 wants.

    Step **freezes only the segment it leaves**, and the segment arriving at it
    is left **cubic** - case 63 measured a step key moving eval(75) to the key's
    value while eval(25) stayed at 0.6759, the cubic default, where an exact
    linear reads 0.4898. So the incoming side is `ease`: spec section 10.3's
    "smooth, parameters unknown, rely on the drift pass", which is what a
    flat-handled cubic is.

    **This used to report `linear` and that was a claim, not a reading.** The
    same measurement was there and the inference on top of it was that a side
    which does not freeze says nothing, so section 10.1's "writers put `linear`
    where a side is meaningless" applied. It does not: this side is meaningful
    and it is not straight. Measured in the host 2026-08-22, on the segment
    arriving at `mixed`'s hold, Nuke draws 507.561 where the straight line
    between the same two keys is 505.155 - 2.55 px, about 8% of that segment's
    travel. A file saying `linear` there was describing a line nobody drew.

    Everything that is not step or linear - cubic, the unset sentinel, and the
    two unidentified types case 63 swept - is `ease` on both sides, with no
    parameters. Spec section 10.3 defines that as "smooth, parameters unknown,
    rely on the drift pass", which is exactly what is true here.
    """
    if key_type == NUKE_STEP:
        return {"in": EASE, "out": HOLD}
    if key_type == NUKE_LINEAR:
        return {"in": LINEAR, "out": LINEAR}
    return {"in": EASE, "out": EASE}


def reduce_sides(votes):
    """Per-axis-per-point `{in, out}` pairs at one frame down to the one key.

    Returns `(sides, mixed)`. `mixed` is True only when the votes actually
    disagreed, which is the tier-2 case in prd.md section 7: "point 5 eases
    differently than point 12" has no After Effects representation, so the key
    degrades to `ease` with no parameters and the drift pass carries the
    geometry.

    **No votes is not a disagreement.** A key frame can come from the shape's
    transform, or from the range endpoints the export always pins, with no
    control point keyed there at all. Nothing was collapsed, so nothing is
    reported; the side is simply unknown, which is `ease`.

    Curves that abstain never reach here - see `rotobridge_export._votes_at`.
    A curve with fewer than two keys cannot describe an interval, and letting
    the constant z axis of every control point vote `linear` would mark every
    genuinely eased shape as mixed.
    """
    if not votes:
        return {"in": EASE, "out": EASE}, False

    sides = {}
    mixed = False
    for side in ("in", "out"):
        values = set(vote[side] for vote in votes)
        if len(values) == 1:
            sides[side] = values.pop()
        else:
            sides[side] = EASE
            mixed = True
    return sides, mixed


def to_nuke(sides):
    """An `.rbj` `interp` pair to the one Nuke key type that fits it.

    Returns `(key_type, exact)`. Nuke has one type per key, so an asymmetric
    pair cannot survive and `exact` is False - the import warns once per shape
    and the drift pass restores the positions.

    `out: hold` becomes a step, and whether that is exact depends on what
    arrives. Nuke's step freezes the interval it leaves and draws the interval
    it arrives on as a cubic with a flat handle - `lslope` reads 0.0, and case
    63's eval(25) is the cubic value, not the linear one. So `ease` or `hold`
    arriving is held exactly, and **`linear` arriving is not**: Nuke has no way
    to run a straight segment into a step. Measured 2026-08-22, `mixed` frames
    16-17 of `test/golden/ae_scene.rbj`, imported with nothing correcting
    anything: 2.55 px and 2.05 px off the bake, roughly 8% of the travel of the
    segment that ends at the hold.

    That is not a reason to rewrite the hold. Straightening the arrival costs
    the freeze - probed: a key set to honour an incoming slope draws frames
    16-17 exactly and then lets 19-23 drift up to 280 px, because the outgoing
    side stops being constant. The freeze is what the artist authored, the
    drift pass buys back the arrival for two keys, and the only thing that was
    ever wrong is that this reported `exact` and nobody was told.

    prd.md section 9.2 step 3 also calls for writing `lslope` / `rslope` per
    side on an asymmetric key. This does not, and the reason is no longer that
    the question is open. Measured in 17.1v1, `test/probe/probe_nuke_ease.py`:

    - Under the cubic types Nuke recomputes a written slope rather than using
      it. Write 5.0, evaluate, read back 1.0101 (case 115).
    - interpolationType 5 is a genuine user-tangent mode, where slope and accel
      do drive the curve (case 115).
    - But only an INTERIOR key honours an authored tangent. Every value of the
      first key's outgoing slope and accel changes nothing (case 117).

    An ease describes a segment from both of its ends, so under any of those
    the outgoing half is unreachable. The best fit to a real After Effects
    curve is about 77 px off on a 700 px travel, against a 0.5 px tolerance.

    So dropping the parameters is not a deferral - it is the whole available
    vocabulary, and the dense layer is what carries the shape instead. Nuke is
    the hub for this pipeline, so that trade is worth stating plainly rather
    than leaving as a TODO. The Nuke importer warns when a key arrives carrying
    ease, because the geometry survives and the editable timing does not.
    """
    if sides["out"] == HOLD:
        return NUKE_STEP, sides["in"] != LINEAR
    if sides["in"] == LINEAR and sides["out"] == LINEAR:
        return NUKE_LINEAR, True
    if sides["in"] == EASE and sides["out"] == EASE:
        return NUKE_CUBIC, True
    return NUKE_CUBIC, False


# --- After Effects ---------------------------------------------------------
#
# One type per side per key on both sides of this mapping, so unlike the Nuke
# direction there is nothing to reduce and nothing to expand. What survives a
# round trip here is exactly what was authored.


def side_from_ae(ae_type):
    """One `keyInInterpolationType` / `keyOutInterpolationType` to an .rbj side.

    Anything unrecognised is `ease`, not an error: spec section 10.3 defines a
    bare `ease` as "smooth, parameters unknown, rely on the drift pass", which
    is a truthful description of an unknown type and keeps the geometry correct
    whatever it was.
    """
    if ae_type == AE_HOLD:
        return HOLD
    if ae_type == AE_LINEAR:
        return LINEAR
    return EASE


def side_to_ae(side):
    """An .rbj side to the `KeyframeInterpolationType` that renders it."""
    if side == HOLD:
        return AE_HOLD
    if side == LINEAR:
        return AE_LINEAR
    return AE_BEZIER


def ease_from_ae(influence, speed):
    """One `KeyframeEase` to the `[influence, speed]` pair of spec section 10.3.

    Influence is scaled, speed is not: influence is a percentage of the interval
    and normalises across control points, while speed is in value-units per
    second and does not, which is why the freeze made `ease` shape-wide.
    """
    return [float(influence) / AE_INFLUENCE_SCALE, float(speed)]


def ease_to_ae(pair):
    """An `[influence, speed]` pair back to After Effects' own units.

    Returns `(influence_percent, speed)`. Influence is clamped to the 0.1-100
    range After Effects accepts: spec section 10.3 bounds the stored fraction to
    0.0-1.0, and a file claiming 0.0 would otherwise raise inside the host
    rather than degrade.
    """
    influence = float(pair[0]) * AE_INFLUENCE_SCALE
    influence = max(0.1, min(100.0, influence))
    return influence, float(pair[1])
