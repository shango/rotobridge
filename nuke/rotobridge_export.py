"""RotoBridge export: Nuke to .rbj (prd.md section 9.2).

Phase 3 writes both layers: the dense per-frame bake that is ground truth, and
the sparse `keys` structure the artist actually authored (spec sections 7 and
9). `keys` is never omitted - an absent `keys` means "treat every frame as a
key", which is a claim about the artist's work, not about the geometry.

Unlike the After Effects export, the loop here is shape-major. Nuke takes the
frame as an argument to `getPosition`, so there is no per-frame host cost to
amortise; the frame-major requirement in prd.md section 9.1 is specific to
`comp.time` and does not apply on this side.
"""

import nuke

from rotobridge_nuke import (ATTR_BLEND, ATTR_FEATHER_FALLOFF, ATTR_FEATHER_X,
                             ATTR_FEATHER_Y, ATTR_INVERTED, ATTR_OPACITY, VIEW,
                             attr_value, blend_to_rbj, falloff_to_rbj, geom,
                             interp, is_closed, iter_shapes, messages,
                             point_members, rbj, roto_knob, script_range,
                             selected_roto_node, timing, vec2, version)


def _read_point(cp, frame, matrix):
    """One control point at one frame, with the shape transform baked in.

    `getPosition` reports pre-transform coordinates - Phase 2 case 70 measured a
    shape translated +200, +50 still reporting its authored (100, 100) - so the
    bake in prd.md section 9.2 step 5 is required, not optional.

    Tangents and the feather offset are vertex-relative, so they transform as
    directions: `apply_matrix_tangent` transforms the displaced point and
    subtracts the transformed vertex, which keeps translation out of them.
    """
    centre = vec2(cp.center.getPosition(frame))
    left = vec2(cp.leftTangent.getPosition(frame))
    right = vec2(cp.rightTangent.getPosition(frame))
    feather = vec2(cp.featherCenter.getPosition(frame))

    if matrix is not None:
        left = geom.apply_matrix_tangent(matrix, centre, left)
        right = geom.apply_matrix_tangent(matrix, centre, right)
        feather = geom.apply_matrix_tangent(matrix, centre, feather)
        centre = geom.apply_matrix_point(matrix, centre)

    return centre, left, right, feather


def _matrix_of(element, frame):
    """One element's transform at a frame as 16 flat floats, or None.

    `AnimCTransform` has no `getMatrixAt` despite prd.md section 9.2 naming it
    (Phase 0 case 30). The real path is `evaluate(frame)` to a `CTransform`,
    then `getMatrix()`.

    Identity is decided by looking at the numbers, not by `isDefault()`, which
    returns False on a transform that has never been touched (Phase 2 cases 30
    and 77) and so cannot be used to skip anything.
    """
    matrix = list(element.getTransform().evaluate(frame).getMatrix())
    return None if geom.is_identity_matrix(matrix) else matrix


def _chain_matrix(shape, ancestors, frame):
    """The full transform for a shape at a frame, layers composed in.

    A shape inside a layer is subject to both transforms and neither matrix
    knows about the other, so flattening the tree means multiplying the chain
    here. Ancestors arrive outermost first, and each layer's transform applies
    after the ones inside it.

    Returns `(matrix_or_None, stacked)`, where `stacked` is True when more than
    one link in the chain is non-identity - the only case where the composition
    order is observable, and the case Phase 2 could not measure (case 78:
    `Shape.evaluate` turned out to be pre-transform as well, so there was no
    oracle). With one transform in the chain the order cannot matter.
    """
    parts = []
    for layer in ancestors:
        matrix = _matrix_of(layer, frame)
        if matrix is not None:
            parts.append(matrix)
    own = _matrix_of(shape, frame)
    if own is not None:
        parts.append(own)

    if not parts:
        return None, False
    combined = parts[0]
    for matrix in parts[1:]:
        combined = geom.multiply_matrices(combined, matrix)
    return combined, len(parts) > 1


# A key this far off a whole frame is snapped with a warning; the same
# threshold the After Effects exporter applies (OFFGRID_FRAMES there).
OFFGRID_FRAMES = 1e-3


def _keyed_curves(shape, offgrid):
    """Every animation curve that can move this shape's geometry, keyed by frame.

    Yields `{frame: AnimCurveKey}` per curve. Four members per control point
    times `dim` axes each: a tangent can be keyed where the centre is not, and
    spec section 9 asks for the union across all of them.

    A single-key curve is yielded too: its one frame is a key the artist
    made, and skipping it exported a shape keyed exactly once as never keyed
    at all - `authored_frames` then said `[]` and the import deleted the
    artist's key. It must still abstain from the interpolation VOTE (the
    caller reads that off `len(keys)`): one key describes no interval, and
    letting the constant z axis that Phase 2's importer writes on every
    control point vote would outvote the axes that actually move and mark
    every eased shape as mixed.

    A key time off the frame grid is snapped, and its raw time goes into
    `offgrid` so the caller can warn once per distinct time; spec section 9
    requires whole frames, and a snap nobody hears about is a moved key.
    """
    for i in range(len(shape)):
        for member in point_members(shape[i]):
            for d in range(member.dim):
                curve = member.getPositionAnimCurve(d)
                count = curve.getNumberOfKeys()
                if not count:
                    continue
                keys = {}
                for k in range(count):
                    key = curve.getKey(k)
                    frame = timing.snap_frame(key.time)
                    if abs(key.time - frame) > OFFGRID_FRAMES:
                        offgrid.add(float(key.time))
                    keys[frame] = key
                yield keys


# Every family of key time an AnimCTransform exposes. Case 30 measured all of
# them on an UNTOUCHED transform, where each reported the same single time, so
# it never showed whether `getTransformKeyTimes` subsumes the others. Reading
# all six costs six calls per shape and removes the guess.
TRANSFORM_KEY_TIMES = ("getTransformKeyTimes", "getTranslationKeyTimes",
                       "getRotationKeyTimes", "getScaleKeyTimes",
                       "getSkewXKeyTimes", "getPivotPointKeyTimes")


def _transform_key_frames(shape, ancestors, offgrid):
    """Key frames on the shape's own transform and on every layer above it.

    The transform is baked into the exported points (case 70), so its keys are
    real shape animation even when no control point is keyed at all - prd.md
    section 9.2 step 5. The layer chain counts for the same reason its matrix
    does (case 77).

    A transform that has never been touched still reports one key time
    (case 30), so a family is animated when it has more than one. `isDefault`
    cannot decide this - it returns False on an untouched transform.
    """
    frames = set()
    for element in tuple(ancestors) + (shape,):
        transform = element.getTransform()
        for getter in TRANSFORM_KEY_TIMES:
            times = getattr(transform, getter)()
            if len(times) > 1:
                for t in times:
                    frame = timing.snap_frame(t)
                    if abs(t - frame) > OFFGRID_FRAMES:
                        offgrid.add(float(t))
                    frames.add(frame)
    return frames


def _sparse_keys(shape, ancestors, frames, warn, name):
    """The `keys` array for one shape: which frames, and how each interpolates.

    The frame range endpoints are always pinned. A key outside the exported
    range still drives the values inside it, and the dense layer covers exactly
    `[first, last]`, so without the endpoints a shape keyed at 60 and 200 and
    exported over 1 to 100 would claim to be static for its first 59 frames.
    Pinning both ends costs two keys and makes the sparse layer bracket the
    truth; the drift pass fills in whatever curves between them.

    A transform key is taken as a shape key whether or not the geometry needs
    one, which is not what the After Effects exporter does - there the
    transform's frames are candidates and `conformEase` keeps only the ones a
    line cannot skip. The asymmetry is deliberate. That fit is sound over there
    because the conform rewrites the interpolation to linear in the same pass,
    so the model and the claim agree. Here `keys` carries Nuke's own
    interpolation, which is often not linear, and fitting a line to decide what
    to drop would be asserting something about the curve that was never
    measured. Dropping the wrong one costs nothing in accuracy - the importer's
    drift pass bounds that at the far end whatever this says - so the price of
    leaving them in is a fuller curve, and the price of taking them out on a
    guess is a wrong one.

    Returns `(keys, authored_frames)`. The second is the control-point union
    clipped to the range and nothing else - the frames the artist keyed on the
    points themselves, before the endpoints are pinned and the transform union
    folded in (spec/rbj-v3-draft.md section 5.2). It is what lets an importer
    that measures tell an invented key from an authored one and give the
    invented ones back.
    """
    offgrid = set()
    curves = list(_keyed_curves(shape, offgrid))

    first, last = frames[0], frames[-1]
    union = set()
    for keys in curves:
        union.update(keys)
    authored = sorted(f for f in union if first <= f <= last)
    union.update(_transform_key_frames(shape, ancestors, offgrid))
    for time in sorted(offgrid):
        # Once per distinct time, not per curve: the same subframe key sits
        # on every axis of the member that carries it.
        warn(messages.render("key-off-grid",
                             {"subject": "shape '%s'" % name,
                              "offset": messages.px(
                                  time - timing.snap_frame(time), 3),
                              "frame": timing.snap_frame(time)}))
    union = set(f for f in union if first <= f <= last)
    union.add(first)
    union.add(last)

    out = []
    mixed = 0
    for frame in sorted(union):
        # `len(keys) > 1` is the vote filter _keyed_curves describes: a
        # single-key curve names an authored frame but no interval.
        votes = [interp.sides_from_nuke(keys[frame].interpolationType)
                 for keys in curves if frame in keys and len(keys) > 1]
        sides, is_mixed = interp.reduce_sides(votes)
        mixed += 1 if is_mixed else 0
        out.append({"frame": frame, "interp": sides})

    if mixed:
        warn(messages.render("interp-mixed",
                             {"subject": "shape '%s'" % name,
                              "count": mixed}))

    # No `ease` entries, ever, from a Nuke source. Case 63 made asymmetric
    # lslope/rslope stick but never measured what a slope value renders as, and
    # nothing on this side calibrates it against After Effects' influence and
    # speed. Spec section 10.3 defines a bare `ease` as "smooth, parameters
    # unknown, rely on the drift pass", which is exactly what is known here.
    return out, authored


def _warn_attr_animation(attrs, warn, name):
    """Warn for each per-shape attribute whose curve actually animates.

    `inv`, `bm` and `ff` cross as one value per shape, read at the first
    exported frame - the format has no per-frame field for them - so a curve
    keyed on more than one frame loses its animation in the crossing. The
    read stays what it is; this is the warning that loss was missing. One
    key is a value, not animation, and warns nothing.
    """
    for label, attr in (("the inverted flag", ATTR_INVERTED),
                        ("the blending mode", ATTR_BLEND),
                        ("the feather falloff", ATTR_FEATHER_FALLOFF)):
        if attrs.getCurve(attr, VIEW).getNumberOfKeys() > 1:
            warn(messages.render("attr-animation-dropped",
                                 {"subject": "shape '%s'" % name,
                                  "attr": label}))


def export_shape(shape, ancestors, frames, warn):
    """One Nuke Shape to an .rbj shape object."""
    name = shape.name
    closed = is_closed(shape)
    if not closed:
        # Nuke renders an open spline as a stroke, and its width and end caps
        # are NODE knobs - openspline_width and the two end types - not shape
        # attributes, so nothing per shape can carry them. See
        # spec/rbj-v2-draft.md section 5.
        warn(messages.render("open-spline-knobs",
                             {"subject": "shape '%s'" % name}))

    attrs = shape.getAttributes()
    _warn_attr_animation(attrs, warn, name)
    if abs(attr_value(attrs, ATTR_INVERTED, frames[0])) > 1e-9:
        warn(messages.render("inverted-dropped",
                             {"subject": "shape '%s'" % name}))

    dense = {}
    count = None
    any_feather = False
    off_normal = False

    stacked = False
    for frame in frames:
        matrix, frame_stacked = _chain_matrix(shape, ancestors, frame)
        stacked = stacked or frame_stacked
        centres, lefts, rights, feathers = [], [], [], []
        for i in range(len(shape)):
            centre, left, right, feather = _read_point(shape[i], frame, matrix)
            centres.append(centre)
            lefts.append(left)
            rights.append(right)
            feathers.append(feather)

        if count is None:
            count = len(centres)
        elif len(centres) != count:
            raise ValueError("shape '%s' has %d points at frame %d but %d "
                             "earlier; .rbj requires a constant vertex count"
                             % (name, len(centres), frame, count))

        normals = geom.outward_normals(centres, closed)
        points = []
        for i in range(len(centres)):
            point = {"c": centres[i], "in": lefts[i], "out": rights[i]}
            if feathers[i][0] != 0.0 or feathers[i][1] != 0.0:
                any_feather = True
                if geom.off_normal_angle(feathers[i], normals[i]) > 1.0:
                    off_normal = True
            point["_feather_offset"] = feathers[i]
            point["_normal"] = normals[i]
            points.append(point)

        dense[str(frame)] = {
            "opacity": attr_value(attrs, ATTR_OPACITY, frame),
            "feather_uniform": [attr_value(attrs, ATTR_FEATHER_X, frame),
                                attr_value(attrs, ATTR_FEATHER_Y, frame)],
            "points": points,
        }

    # feather_model describes the per-point layer only, and it is a property of
    # the whole shape, so it can only be decided once every frame is read. A
    # shape with zero offsets on every vertex of every frame is "none"; one with
    # some zeros and some not is "per_point", and the zeros are load-bearing
    # (prd.md section 9.3).
    model = "per_point" if any_feather else "none"
    for record in dense.values():
        for point in record["points"]:
            offset = point.pop("_feather_offset")
            normal = point.pop("_normal")
            if model == "per_point":
                point["feather"] = geom.feather_scalar(offset, normal)
                point["feather_offset"] = offset

    if stacked:
        warn(messages.render("transform-order-unverified",
                             {"subject": "shape '%s'" % name}))

    if off_normal:
        warn(messages.render("feather-tangential",
                             {"subject": "shape '%s'" % name}))

    keys, authored = _sparse_keys(shape, ancestors, frames, warn, name)
    return {
        "name": name,
        # Stable identity where the name is a display label an artist can
        # edit; export_node prefixes the node and settles collisions.
        "id": name,
        "closed": closed,
        "blend": blend_to_rbj(attr_value(attrs, ATTR_BLEND, frames[0]),
                              warn, name),
        "feather_model": model,
        "feather_falloff": falloff_to_rbj(
            attr_value(attrs, ATTR_FEATHER_FALLOFF, frames[0])),
        "frames": dense,
        "keys": keys,
        "authored_frames": authored,
    }


def export_node(node, first, last, width, height, pixel_aspect, fps):
    """Build the .rbj document for one Roto/RotoPaint node."""
    warnings = []

    def warn(message):
        warnings.append(message)

    frames = list(range(int(first), int(last) + 1))
    if not frames:
        raise ValueError("frame range [%s, %s] is empty" % (first, last))

    shapes = [export_shape(shape, ancestors, frames, warn)
              for shape, ancestors in iter_shapes(roto_knob(node).rootLayer,
                                                  warn)]
    if not shapes:
        raise ValueError("node '%s' has no shapes to export" % node.name())

    # "Roto1/Bezier3", and "#2" on a repeated name, because the validator
    # rejects duplicate ids - uniqueness is the whole value of an id over a
    # name (spec/rbj-v3-draft.md section 5).
    counts = {}
    for shape in shapes:
        counts[shape["id"]] = counts.get(shape["id"], 0) + 1
        suffix = "#%d" % counts[shape["id"]] if counts[shape["id"]] > 1 else ""
        shape["id"] = "%s/%s%s" % (node.name(), shape["id"], suffix)

    return {
        "format": "rotobridge",
        "version": rbj.version_for(shapes),
        "source": {
            "app": "Nuke",
            "app_version": nuke.NUKE_VERSION_STRING,
            # The host above, this build below. A bug report that arrives as
            # an .rbj alone still names what wrote it.
            "tool_version": version.VERSION,
            "width": int(width),
            "height": int(height),
            "pixel_aspect": float(pixel_aspect),
            "fps": float(fps),
        },
        "range": [int(first), int(last)],
        "shapes": shapes,
        "warnings": warnings,
    }


def export_to_file(node, path, first, last):
    """Validate, then write. An invalid document raises and writes nothing."""
    fmt = node.format()
    doc = export_node(node, first, last, fmt.width(), fmt.height(),
                      fmt.pixelAspect(), nuke.root()["fps"].value())
    # Folding is the writer's decision, made at the last moment so the
    # returned document - which main() reports from - stays dense.
    text = rbj.dumps(rbj.fold_frames(doc))
    handle = open(path, "w")
    try:
        handle.write(text + "\n")
    finally:
        handle.close()
    return doc


def main():
    node = selected_roto_node()
    first, last = script_range()

    panel = nuke.Panel("%s export" % version.LABEL)
    panel.addFilenameSearch("output .rbj", "")
    panel.addSingleLineInput("first frame", str(first))
    panel.addSingleLineInput("last frame", str(last))
    if not panel.show():
        return

    path = panel.value("output .rbj")
    if not path:
        raise ValueError("no output path given")

    doc = export_to_file(node, path, int(panel.value("first frame")),
                         int(panel.value("last frame")))

    frames = len(doc["shapes"][0]["frames"]) if doc["shapes"] else 0
    message = "%s\n\nWrote %d shape(s), %d frames to %s" % (
        version.LABEL, len(doc["shapes"]), frames, path)
    if doc["warnings"]:
        message += "\n\n%d warning(s):\n  %s" % (
            len(doc["warnings"]), "\n  ".join(doc["warnings"]))
    nuke.message(message)
