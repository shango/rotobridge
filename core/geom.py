"""Canonical-space geometry conversion (prd.md section 5.5, spec section 3).

Canonical space is Nuke's: origin bottom-left, Y up, pixels, tangents stored
vertex-relative. Every adapter converts to and from it on its own side.

Pure functions, no host calls and no I/O. The part of the After Effects
conversion that needs the host - layer space to comp space via
`sourcePointToComp` - is deliberately not here; Phase 0 confirmed the host does
it exactly, including rotation and non-uniform scale, so reimplementing it would
add a second source of truth. These functions take points already in comp space.

Nuke's two directions are the identity. They exist so an adapter has the same
call surface on both sides and so the round-trip test covers all four paths
named in prd.md section 12, not because they do work.
"""

import math


def comp_to_canonical_point(p, comp_height):
    """After Effects comp space (top-left origin, Y down) to canonical."""
    return [float(p[0]), float(comp_height) - float(p[1])]


def canonical_to_comp_point(p, comp_height):
    """Canonical to After Effects comp space. Involution of the above."""
    return [float(p[0]), float(comp_height) - float(p[1])]


def comp_to_canonical_tangent(t):
    """Tangents are vertex-relative, so only the Y flip applies - no height."""
    return [float(t[0]), -float(t[1])]


def canonical_to_comp_tangent(t):
    return [float(t[0]), -float(t[1])]


def nuke_to_canonical_point(p):
    """Identity. Nuke is the canonical space."""
    return [float(p[0]), float(p[1])]


def canonical_to_nuke_point(p):
    return [float(p[0]), float(p[1])]


def nuke_to_canonical_tangent(t):
    return [float(t[0]), float(t[1])]


def canonical_to_nuke_tangent(t):
    return [float(t[0]), float(t[1])]


def ae_point_to_canonical(point, comp_height):
    """Convert one .rbj point object from comp space to canonical.

    Takes and returns the point shape of spec section 8: `c`, `in`, `out`, and
    optionally `feather` / `feather_offset`. Feather carries through untouched -
    `feather` is a signed scalar along the path normal and has no Y component to
    flip, and After Effects never writes `feather_offset`.
    """
    out = {
        "c": comp_to_canonical_point(point["c"], comp_height),
        "in": comp_to_canonical_tangent(point["in"]),
        "out": comp_to_canonical_tangent(point["out"]),
    }
    if "feather" in point:
        out["feather"] = float(point["feather"])
    return out


def canonical_point_to_ae(point, comp_height):
    """Convert one .rbj point object from canonical to comp space.

    Drops `feather_offset`: it is Nuke's tangential component and has no After
    Effects representation (spec section 11.1). The caller warns; this function
    does not, because it has no shape name to name.
    """
    out = {
        "c": canonical_to_comp_point(point["c"], comp_height),
        "in": canonical_to_comp_tangent(point["in"]),
        "out": canonical_to_comp_tangent(point["out"]),
    }
    if "feather" in point:
        out["feather"] = float(point["feather"])
    return out


# --- Shape transform bake (prd.md section 9.2 step 5) -----------------------
#
# Nuke keeps a shape's transform as a separate layer: `getPosition` reports
# pre-transform coordinates, measured in Phase 2 case 70 (a shape translated
# +200, +50 still reported its authored (100, 100)). So the export must bake.
#
# `CTransform.getMatrix()` returns a CMatrix4 whose `list()` is 16 floats in
# row-major order with translation in the last column, at indices 3 and 7. Case
# 70 read `{ { 1, 0, 0, 200 }, { 0, 1, 0, 50 }, ... }` for a +200, +50
# translation, and Nuke's own `matrix * vector` agreed with reading it that way.


def apply_matrix_point(matrix, p):
    """Apply a flat 16-float row-major matrix to a 2-D point."""
    x, y = float(p[0]), float(p[1])
    return [matrix[0] * x + matrix[1] * y + matrix[3],
            matrix[4] * x + matrix[5] * y + matrix[7]]


def apply_matrix_tangent(matrix, c, t):
    """Apply a matrix to a vertex-relative tangent.

    Transform `c + t` and subtract the transformed `c`, rather than zeroing the
    homogeneous component and transforming the tangent directly. Both are
    correct for an affine matrix, but this one does not depend on how Nuke maps
    a CVec3's third component onto the 4-vector, which case 70 could not
    distinguish: for a point with third component 1 the two readings give the
    same answer, and the case that separates them is exactly a tangent.
    """
    moved = apply_matrix_point(matrix, [float(c[0]) + float(t[0]),
                                        float(c[1]) + float(t[1])])
    base = apply_matrix_point(matrix, c)
    return [moved[0] - base[0], moved[1] - base[1]]


# --- Feather normals (prd.md section 9.3) ----------------------------------


def signed_area(points):
    """Twice the signed area of the polygon through `points`.

    Positive is counterclockwise in a Y-up space. Only the sign is used, to
    decide which side of the path is outside.
    """
    total = 0.0
    n = len(points)
    for i in range(n):
        x0, y0 = points[i][0], points[i][1]
        x1, y1 = points[(i + 1) % n][0], points[(i + 1) % n][1]
        total += x0 * y1 - x1 * y0
    return total


def outward_normals(points, closed=True):
    """One unit outward normal per vertex of a polygon or polyline.

    The path direction at a vertex is taken from the chord between its
    neighbours, which is stable at corners where one tangent is zero. The
    normal is that direction rotated a quarter turn towards the outside, which
    depends on winding, so the polygon's signed area picks the sign.

    An **open** path has no inside, so two things need saying, and both are
    spec/rbj-v2-draft.md section 4. An endpoint has no chord between neighbours,
    so it uses the chord to its single neighbour - the limit of the interior
    rule, not a new one. And the sign is fixed at +1, a consistent quarter turn
    from the direction of travel, rather than taken from an area. The area of a
    path closed implicitly is near zero for a near-straight polyline and its
    sign flips on a perturbation, which would flip the feather direction from
    one frame to the next; a fixed sign cannot. The cost is that the side
    follows point order rather than any notion of outside, which is
    unverifiable on an open path anyway.

    A degenerate vertex - one whose neighbours coincide with it - has no
    defined normal and gets `[0.0, 0.0]`. Callers must treat a zero normal as
    "no feather direction here" rather than dividing by it.
    """
    n = len(points)
    if n < 3:
        return [[0.0, 0.0] for _ in range(n)]

    if closed:
        sign = 1.0 if signed_area(points) >= 0.0 else -1.0
    else:
        sign = 1.0
    normals = []
    for i in range(n):
        if closed:
            prev, nxt = points[(i - 1) % n], points[(i + 1) % n]
        else:
            prev, nxt = points[max(i - 1, 0)], points[min(i + 1, n - 1)]
        dx = float(nxt[0]) - float(prev[0])
        dy = float(nxt[1]) - float(prev[1])
        length = math.hypot(dx, dy)
        if length == 0.0:
            normals.append([0.0, 0.0])
            continue
        normals.append([sign * dy / length, -sign * dx / length])
    return normals


def feather_scalar(offset, normal):
    """Signed distance along the outward normal (prd.md section 9.3).

    The signed projection, never the magnitude: `|featherCenter|` would discard
    whether the feather goes outward or inward. A zero normal yields 0.0.
    """
    return float(offset[0]) * float(normal[0]) + float(offset[1]) * float(normal[1])


def feather_vector(scalar, normal):
    """Rebuild a feather offset from a signed distance along the normal."""
    return [float(scalar) * float(normal[0]), float(scalar) * float(normal[1])]


def off_normal_angle(offset, normal):
    """Angle in degrees between a feather offset and the path normal.

    prd.md section 9.3 warns per shape when any offset departs from the normal
    by more than a degree, because the tangential component is what the scalar
    `feather` cannot carry. Returns 0.0 when either vector is degenerate, so a
    zero-length offset never triggers a warning.
    """
    ox, oy = float(offset[0]), float(offset[1])
    nx, ny = float(normal[0]), float(normal[1])
    olen = math.hypot(ox, oy)
    nlen = math.hypot(nx, ny)
    if olen == 0.0 or nlen == 0.0:
        return 0.0
    cosine = (ox * nx + oy * ny) / (olen * nlen)
    cosine = max(-1.0, min(1.0, cosine))
    return math.degrees(math.acos(abs(cosine)))


IDENTITY_MATRIX = [1.0, 0.0, 0.0, 0.0,
                   0.0, 1.0, 0.0, 0.0,
                   0.0, 0.0, 1.0, 0.0,
                   0.0, 0.0, 0.0, 1.0]


def multiply_matrices(a, b):
    """Row-major 4x4 product `a * b`, applied to a column vector on the right.

    So `multiply_matrices(outer, inner)` applies `inner` first. Nuke keeps a
    transform per shape AND per layer, neither aware of the other (Phase 2 case
    77), so an exporter that flattens layers has to compose the chain itself.
    """
    out = [0.0] * 16
    for row in range(4):
        for col in range(4):
            out[row * 4 + col] = sum(a[row * 4 + k] * b[k * 4 + col]
                                     for k in range(4))
    return out


def is_identity_matrix(matrix, tolerance=1e-9):
    """Whether a matrix does nothing.

    Compared numerically rather than asking Nuke, because `isDefault()` returns
    False on a freshly created transform that has never been touched (Phase 2
    cases 30 and 77), so it cannot be used to skip work.
    """
    for got, want in zip(matrix, IDENTITY_MATRIX):
        if abs(got - want) > tolerance:
            return False
    return True


# --- After Effects feather points (prd.md section 9.3) ---------------------
#
# The two applications anchor feather differently and neither is a superset.
# After Effects places a point anywhere along a segment and gives it a signed
# distance along the normal; Nuke anchors at a vertex and gives it a free 2-D
# offset. `.rbj` carries one signed scalar per vertex, so the AE side has to
# resolve a segment location to a vertex on the way out and invent one on the
# way back.
#
# Probe run 3 read four points off a seven-vertex mask - three mid-segment, two
# on the same segment, one with a radius of exactly zero. Every branch below
# comes from that data, so none of them are hypothetical.


def snap_feather_points(seg_locs, rel_locs, radii, vertex_count):
    """After Effects feather points to one signed scalar per vertex.

    Returns `{"feather": [...], "snapped": [...], "dropped": [...]}`.
    `feather` is `vertex_count` long, zero where no point resolved there.
    `snapped` lists the indices of points that were not already sitting on a
    vertex, and `dropped` the ones a collision discarded, each as
    `{"index", "vertex", "radius", "kept"}`. Both are for the caller's
    warnings; this function has no shape name to put in one.

    A point at `rel` 0.0 belongs to the segment's start vertex and one at 1.0
    to its end, both exactly. Anything between is snapped to the nearer, which
    is what spec section 12.2 calls a soft failure. **A radius of exactly zero
    is an authored point**, not an absent one: it pins the feather back to zero
    width and is load-bearing, so it competes for its vertex on equal terms.
    """
    feather = [0.0] * vertex_count
    claimed = {}
    snapped = []
    dropped = []

    for i in range(len(radii)):
        rel = float(rel_locs[i])
        seg = int(seg_locs[i])
        radius = float(radii[i])

        if rel >= 0.5:
            vertex = (seg + 1) % vertex_count
        else:
            vertex = seg % vertex_count
        if rel != 0.0 and rel != 1.0:
            snapped.append(i)

        if vertex in claimed:
            other, other_radius = claimed[vertex]
            # Larger magnitude wins. On a tie the earlier point holds the
            # vertex, so the result does not depend on read order.
            if abs(radius) > abs(other_radius):
                dropped.append({"index": other, "vertex": vertex,
                                "radius": other_radius, "kept": radius})
                claimed[vertex] = (i, radius)
                feather[vertex] = radius
            else:
                dropped.append({"index": i, "vertex": vertex,
                                "radius": radius, "kept": other_radius})
        else:
            claimed[vertex] = (i, radius)
            feather[vertex] = radius

    return {"feather": feather, "snapped": snapped, "dropped": dropped}


def feather_anchors(seg_locs, rel_locs, radii, vertex_count, closed=True):
    """After Effects feather points as the `feather_points` of spec 6.3.

    Returns a list of `{"t", "feather"}` sorted by `t` ascending. This is the
    lossless reading: `snap_feather_points` above resolves the same input onto
    vertices and is what v1 files carry, at the cost the draft's section 6.1
    measures. Both are kept, because a file whose anchors already sit on
    vertices is still a v1 file (section 6.7) and the snap is still the
    fallback for a destination that cannot take extra vertices.

    `t = segment + fraction` (section 6.4). One number rather than the pair the
    host reports, because the pair is not stable: After Effects renames a point
    written at `(i, 0)` to `(i-1, 1)` and regroups the arrays by feather type
    when the shape is read between keyframes. Both transformations preserve the
    sum, which is why the sum is what the format stores.

    On a closed shape `t = vertex_count` names the same anchor as `t = 0` and
    section 6.4 requires the latter, so it wraps.

    **Sorted per frame, independently.** The host's array order is not stable
    across frames - that same regrouping - so there is no index to carry an
    anchor's identity from one frame to the next, and sorting is the only thing
    that produces the ascending order section 6.3 requires. It also means this
    function cannot see two anchors crossing: the sorted sequence is monotone
    by construction. Section 6.5 puts the detection on the reader, which has
    the whole file at once and can watch the feather values jump.

    The tie-break on `feather` is for determinism rather than meaning. Two
    anchors at one `t` are interchangeable in the format, and re-exporting the
    same scene should not produce a different file because the host grouped
    its arrays differently.
    """
    anchors = []
    for i in range(len(radii)):
        t = int(seg_locs[i]) + float(rel_locs[i])
        if closed:
            t = math.fmod(t, float(vertex_count))
            if t < 0.0:
                t += float(vertex_count)
        anchors.append({"t": t, "feather": float(radii[i])})
    anchors.sort(key=lambda a: (a["t"], a["feather"]))
    return anchors


def feather_points_from_anchors(anchors):
    """`feather_points` (spec 6.3) back to the arrays After Effects wants.

    Returns `(seg_locs, rel_locs, radii, types)`. The inverse of
    `feather_anchors`, and the easy direction: After Effects anchors feather
    anywhere along a segment, so every entry lands exactly where the file says
    and nothing is snapped, split or dropped.

    `t = segment + fraction`, so the split is the floor and the remainder. A
    `t` that is exactly integral is written as `(t, 0.0)`, the start of its own
    segment - the host renames that to `(t-1, 1.0)` on the way back out and
    `feather_anchors` reads either spelling as the same number.

    `types` follows the sign for the reason `feather_points_from_vertices`
    gives: a point's direction cannot be changed after creation, so the host
    has to be handed the right one up front.
    """
    seg_locs, rel_locs, radii, types = [], [], [], []
    for anchor in anchors:
        t = float(anchor["t"])
        segment = math.floor(t)
        d = float(anchor["feather"])
        seg_locs.append(int(segment))
        rel_locs.append(t - segment)
        radii.append(d)
        types.append(0 if d >= 0.0 else 1)
    return seg_locs, rel_locs, radii, types


def feather_points_from_vertices(feather):
    """One signed scalar per vertex to the arrays After Effects wants.

    Returns `(seg_locs, rel_locs, radii, types)`, one entry per vertex, each
    point pinned to the start of its own vertex's segment (prd.md section 9.3).

    `featherRadii` is signed and its sign agrees with `featherTypes` - run 3
    read type 0 back non-negative and type 1 non-positive - so the radius alone
    carries the direction and the type is redundant. It is still written
    consistently, because a point's direction cannot be changed after creation
    and the host has to be given the right one up front.

    Zeros are emitted rather than skipped: a shape with some zero and some
    non-zero offsets is `per_point`, and dropping the zeros would widen the
    feather at exactly the vertices that were pinned to nothing.
    """
    seg_locs, rel_locs, radii, types = [], [], [], []
    for i, value in enumerate(feather):
        d = float(value)
        seg_locs.append(i)
        rel_locs.append(0.0)
        radii.append(d)
        types.append(0 if d >= 0.0 else 1)
    return seg_locs, rel_locs, radii, types
