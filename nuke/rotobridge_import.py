"""RotoBridge import: .rbj to Nuke (prd.md sections 8 and 9.2).

Phase 3 is the sparse path. The authored `keys` are set with the closest
interpolation Nuke can hold, then the drift pass measures what Nuke actually
interpolates against the dense layer and pins the difference with corrective
keys. That is the tier-3 backstop of prd.md section 7: the interpolation fit is
allowed to be approximate, the positions are not.

One control decides the mode, `tolerance` in pixels (prd.md section 8):
infinity leaves the authored keys alone, 0 keys every frame and is bit-exact to
the source, and the 0.5 default lands corrective keys only where the mismatch
would be visible. All three read the same file, so switching is a re-import and
never a round trip to the source application.

The shape transform is left at identity on purpose: the geometry in a .rbj is
already baked into the points (prd.md section 9.2 step 5), so adding a
transform on top would apply it twice.
"""

import nuke
import nuke.rotopaint as rp

from rotobridge_nuke import (ATTR_FEATHER_FALLOFF, ATTR_FEATHER_X,
                             ATTR_FEATHER_Y, ATTR_OPACITY, INTERP_LINEAR,
                             blend_from_rbj, drift, falloff_from_rbj, geom,
                             interp, point_members, rbj, roto_knob,
                             set_curve_linear, set_curve_types,
                             write_attr_curve)

DEFAULT_TOLERANCE = 0.5


def _feather_offsets(record, warn, shape_name, model, closed):
    """The per-point feather offset for one frame, in Nuke's vector form.

    spec section 11.1: `feather_offset` is Nuke's own representation and wins
    when present, which is what makes Nuke to Nuke lossless including the
    tangential component. Without it the signed scalar is rebuilt along the
    outward path normal, which is all any other adapter can express.
    """
    points = record["points"]
    if model == "none":
        return [[0.0, 0.0] for _ in points]

    if all("feather_offset" in p for p in points):
        return [list(p["feather_offset"]) for p in points]

    normals = geom.outward_normals([p["c"] for p in points], closed)
    offsets = []
    for point, normal in zip(points, normals):
        scalar = float(point.get("feather", 0.0))
        if scalar != 0.0 and normal == [0.0, 0.0]:
            warn("shape '%s': a feather point sits on a degenerate vertex with "
                 "no defined normal; its feather was dropped" % shape_name)
        offsets.append(geom.feather_vector(scalar, normal))
    return offsets


def _key_plan(spec, frames, offset, warn):
    """Which frames to key, and the Nuke key type each one wants.

    Returns `(key_frames, types)`, where `types` is keyed by **host** frame -
    source frame plus offset - because that is what the curves will report back.

    An absent `keys` is spec section 9's dense import: every frame is a key.
    That is a claim about the geometry, not a fallback, so it is not merged
    with the tolerance control - a dense document keys every frame whatever
    tolerance was asked for, and there is nothing left for the drift pass to
    correct.
    """
    keys = spec.get("keys")
    if keys is None:
        return list(frames), {}

    key_frames = []
    types = {}
    collapsed = 0
    shaped = 0
    for key in keys:
        frame = int(key["frame"])
        key_type, exact = interp.to_nuke(key["interp"])
        key_frames.append(frame)
        types[frame + offset] = key_type
        collapsed += 0 if exact else 1
        shaped += 1 if key.get("ease") else 0

    if collapsed:
        warn("shape '%s': %d key(s) carry a different interpolation on each "
             "side, which a Nuke key cannot hold - one type governs the whole "
             "key. They were set smooth and the drift pass corrected the "
             "positions" % (spec["name"], collapsed))

    if shaped:
        # `to_nuke` reports an ease/ease pair as exact, and for a Nuke-sourced
        # file it is: Nuke writes no parameters, so there are none to lose.
        # A key that carries an `ease` block came from an application that
        # shapes the curve itself, and none of that shaping survives. Nuke
        # honours an authored tangent only on an interior key - measured, 17.1v1
        # probe case 117 - so the outgoing side of a segment's first key is
        # dropped whatever is written, and even the half that lands is not
        # parameterised the way After Effects parameterises an ease. The
        # positions still arrive: the drift pass bakes them. What the artist
        # loses is the keyframes, and that is worth saying out loud, because
        # the alternative is a compositor opening a shape that looks keyed on
        # every frame with no idea why.
        warn("shape '%s': %d key(s) carry authored ease. Nuke's roto curves "
             "cannot hold it, so the shape arrives as a dense bake and the "
             "keyframe timing is not editable downstream. Geometry is "
             "unaffected" % (spec["name"], shaped))

    return key_frames, types


def _write_frame(shape, record, at, offsets):
    """Key every control point of one frame at host time `at`."""
    for i, point in enumerate(record["points"]):
        cp = shape[i]
        # The third component is the homogeneous term: 1 for a position, 0 for
        # a vertex-relative direction (Phase 2 cases 70 and 71).
        cp.center.addPositionKey(at, rp.CVec3(float(point["c"][0]),
                                              float(point["c"][1]), 1.0))
        cp.leftTangent.addPositionKey(at, rp.CVec3(float(point["in"][0]),
                                                   float(point["in"][1]), 0.0))
        cp.rightTangent.addPositionKey(at, rp.CVec3(float(point["out"][0]),
                                                    float(point["out"][1]), 0.0))
        cp.featherCenter.addPositionKey(at, rp.CVec3(offsets[i][0],
                                                     offsets[i][1], 0.0))


def _deviation(position, target):
    """How far a curve's evaluated point sits from the dense layer, in pixels.

    Tangents and feather offsets are measured on the same scale as vertices and
    against the same tolerance. They are vertex-relative pixel offsets, and a
    tangent that drifts bends the rendered edge exactly as far as a vertex that
    drifts does.
    """
    return max(abs(float(position.x) - float(target[0])),
               abs(float(position.y) - float(target[1])))


def _apply_key_types(shape, types, default):
    """Push the authored interpolation onto every point curve.

    Re-run after every drift pass rather than once: the pass inserts keys, and
    a fresh key reports 256 - the unset sentinel that behaves as cubic. Anything
    `types` does not name is a corrective key, and those are **linear**. A
    corrective key exists precisely because the host's own interpolation left
    the dense layer, so a cubic one could overshoot between corrective keys and
    create fresh drift; straight segments between measured frames cannot, which
    is what makes each pass reduce the error rather than move it.
    """
    for i in range(len(shape)):
        for member in point_members(shape[i]):
            for d in range(member.dim):
                set_curve_types(member.getPositionAnimCurve(d), types, default)


def build_shape(knob, spec, frames, offset, tolerance, warn):
    """Create one Nuke Shape from an .rbj shape object.

    Returns a report: which frames were authored, how many corrective keys the
    drift pass added, and the worst residual. prd.md section 8 requires this -
    it is what tells an artist which shape to re-import at a tighter tolerance.
    """
    name = spec["name"]
    model = spec["feather_model"]
    dense = spec["frames"]

    shape = rp.Shape(knob)
    for point in dense[str(frames[0])]["points"]:
        shape.append(rp.ShapeControlPoint(float(point["c"][0]),
                                          float(point["c"][1])))
    shape.name = name
    shape.setFlag(rp.FlagType.eOpenFlag, not spec["closed"])
    knob.rootLayer.append(shape)

    # Once per frame, not once per drift pass: rebuilding the outward normals
    # inside `measure` would recompute them on every pass, and `_feather_offsets`
    # warns, which would repeat the warning once per pass as well.
    offsets = dict((f, _feather_offsets(dense[str(f)], warn, name, model,
                                        spec["closed"]))
                   for f in frames)

    key_frames, types = _key_plan(spec, frames, offset, warn)
    written = set()

    def apply_keys(wanted):
        # The drift pass only ever grows its key list, so a frame already
        # written is already correct and re-issuing it would be wasted host
        # calls. The types are re-pushed every time, because the new keys are
        # not the only ones whose indices moved.
        for frame in wanted:
            if frame not in written:
                _write_frame(shape, dense[str(frame)], float(frame + offset),
                             offsets[frame])
                written.add(frame)
        _apply_key_types(shape, types, INTERP_LINEAR)

    def measure(frame):
        record = dense[str(frame)]
        at = float(frame + offset)
        worst = 0.0
        for i, point in enumerate(record["points"]):
            cp = shape[i]
            for member, target in ((cp.center, point["c"]),
                                   (cp.leftTangent, point["in"]),
                                   (cp.rightTangent, point["out"]),
                                   (cp.featherCenter, offsets[frame][i])):
                here = _deviation(member.getPosition(at), target)
                if here > worst:
                    worst = here
        return worst

    final, residual, at = drift.correct(frames, key_frames, apply_keys, measure,
                                        tolerance)

    if residual > tolerance:
        warn("shape '%s': the drift pass ran out of passes with %.4g px still "
             "unaccounted for at frame %d; re-import this shape at a tighter "
             "tolerance if it shows" % (name, residual, at))

    _write_attributes(shape, spec, frames, offset, warn)

    return {
        "name": name,
        "authored": len(key_frames),
        "corrective": len(final) - len(set(key_frames) & set(frames)),
        "residual": residual,
        "worst_frame": at,
    }


def _collapse(samples):
    """One key instead of one per frame when the value never changes.

    An artist opening a shape whose opacity was never animated should find one
    key on it, not a hundred and fifty. This changes nothing about the values -
    the dense layer is still where they came from - only how much of the curve
    editor an unanimated attribute takes up.
    """
    first = samples[0][1]
    for _, value in samples:
        if abs(value - first) > 1e-9:
            return samples
    return samples[:1]


def _write_attributes(shape, spec, frames, offset, warn):
    """Opacity and uniform feather per frame; falloff and blend once."""
    attrs = shape.getAttributes()
    dense = spec["frames"]

    opacity, feather_x, feather_y = [], [], []
    for frame in frames:
        record = dense[str(frame)]
        at = float(frame + offset)
        opacity.append((at, record["opacity"]))
        feather_x.append((at, record["feather_uniform"][0]))
        feather_y.append((at, record["feather_uniform"][1]))

    for name, samples in ((ATTR_OPACITY, opacity),
                          (ATTR_FEATHER_X, feather_x),
                          (ATTR_FEATHER_Y, feather_y)):
        set_curve_linear(write_attr_curve(attrs, name, _collapse(samples)))

    # Static per shape, so one key each. Attribute curves default to curved too
    # (Phase 0 case 62), but a single-key curve has nothing to interpolate.
    write_attr_curve(attrs, ATTR_FEATHER_FALLOFF,
                     [(float(frames[0] + offset),
                       falloff_from_rbj(spec["feather_falloff"]))])
    blend_from_rbj(spec["blend"], warn, spec["name"])


def import_document(doc, offset=0, tolerance=DEFAULT_TOLERANCE, subset=None):
    """Build a Roto node from a validated .rbj document.

    Returns `(node, warnings, reports)`. The file's own warnings come first: a
    .rbj carries its own provenance, so an importer shows what the exporter
    already lost before adding anything of its own (prd.md section 5.1).
    """
    warnings = list(doc.get("warnings", []))

    def warn(message):
        warnings.append(message)

    first, last = doc["range"]
    frames = list(range(int(first), int(last) + 1))

    shapes = doc["shapes"]
    if subset:
        wanted = set(subset)
        shapes = [s for s in shapes if s["name"] in wanted]
        missing = wanted - set(s["name"] for s in doc["shapes"])
        for name in sorted(missing):
            warn("shape '%s' was requested but is not in the file" % name)
        if not shapes:
            raise ValueError("no shapes matched the requested subset")

    # An open spline round trips exactly within one application; what it
    # *renders* as across two is unmeasured on the After Effects side and lives
    # in node knobs on this one (spec/rbj-v2-draft.md section 5).
    if doc["source"]["app"] != "Nuke":
        for spec in shapes:
            if not spec["closed"]:
                warn("shape '%s' is an open spline from %s; the geometry is "
                     "exact but what it renders as across applications is "
                     "unverified" % (spec["name"], doc["source"]["app"]))

    node = nuke.createNode("Roto", inpanel=False)
    knob = roto_knob(node)
    reports = [build_shape(knob, spec, frames, offset, tolerance, warn)
               for spec in shapes]

    return node, warnings, reports


def import_from_file(path, offset=0, tolerance=DEFAULT_TOLERANCE, subset=None):
    handle = open(path, "r")
    try:
        text = handle.read()
    finally:
        handle.close()
    return import_document(rbj.loads(text), offset, tolerance, subset)


def _parse_tolerance(raw):
    """The one import control (prd.md section 8). Blank or `inf` is unbounded."""
    raw = raw.strip().lower()
    if raw in ("", "inf", "infinity"):
        return float("inf")
    value = float(raw)
    if value < 0.0:
        raise ValueError("drift tolerance must not be negative; got %g" % value)
    return value


def main():
    panel = nuke.Panel("RotoBridge import")
    panel.addFilenameSearch("input .rbj", "")
    panel.addSingleLineInput("frame offset", "0")
    panel.addSingleLineInput("drift tolerance px (0 = every frame, inf = none)",
                             str(DEFAULT_TOLERANCE))
    panel.addSingleLineInput("shapes (blank for all)", "")
    if not panel.show():
        return

    path = panel.value("input .rbj")
    if not path:
        raise ValueError("no input path given")

    raw = panel.value("shapes (blank for all)").strip()
    subset = [s.strip() for s in raw.split(",") if s.strip()] or None
    tolerance = _parse_tolerance(
        panel.value("drift tolerance px (0 = every frame, inf = none)"))

    node, warnings, reports = import_from_file(
        path, int(panel.value("frame offset")), tolerance, subset)

    lines = ["Imported %d shape(s) into %s" % (len(reports), node.name())]
    for report in reports:
        line = "  %s: %d authored key(s)" % (report["name"], report["authored"])
        if report["corrective"]:
            line += ", %d corrective" % report["corrective"]
        if report["worst_frame"] is not None:
            line += "; worst drift %.4g px at frame %d" % (report["residual"],
                                                           report["worst_frame"])
        lines.append(line)
    if warnings:
        lines.append("")
        lines.append("%d warning(s):" % len(warnings))
        lines.extend("  " + w for w in warnings)
    nuke.message("\n".join(lines))
