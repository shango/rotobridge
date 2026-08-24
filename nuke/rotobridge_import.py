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

import time

import nuke
import nuke.rotopaint as rp

from rotobridge_nuke import (ATTR_FEATHER_FALLOFF, ATTR_FEATHER_X,
                             ATTR_FEATHER_Y, ATTR_OPACITY, INTERP_LINEAR,
                             blend_from_rbj, drift, falloff_from_rbj, geom,
                             interp, messages, point_members, rbj, report,
                             roto_knob, set_curve_linear, set_curve_types,
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
            warn(messages.render("feather-degenerate-vertex",
                                 {"subject": "shape '%s'" % shape_name}))
        offsets.append(geom.feather_vector(scalar, normal))
    return offsets


def _frame_offsets(dense, frames, warn, shape_name, model, closed):
    """`_feather_offsets` over the whole range, each warning said once.

    Once per frame, not once per drift pass: rebuilding the outward normals
    inside `measure` would recompute them on every pass, and it warns, which
    would repeat the warning once per pass as well. And once per SHAPE for
    the warning itself: the loop is per frame but a degenerate vertex is a
    per-shape fact, and 150 copies of one sentence bury every other warning
    in the record - the same rule colliding anchors already follow.
    """
    seen = []

    def once(message):
        if message not in seen:
            seen.append(message)
            warn(message)

    return dict((f, _feather_offsets(dense[str(f)], once, shape_name, model,
                                     closed))
                for f in frames)


def _snapped_dense(spec, frames):
    """The v1 reading of an anchored shape: every anchor moved to a vertex.

    The fallback `_anchored_dense` names, and the one section 6.8 keeps
    `geom.snap_feather_points` around for. It loses exactly what v1 lost, and
    the caller has already said so.
    """
    source = spec["frames"]
    out = {}
    for frame in frames:
        record = source[str(frame)]
        anchors = record["feather_points"]
        got = geom.snap_feather_points([int(a["t"]) for a in anchors],
                                       [float(a["t"]) - int(a["t"])
                                        for a in anchors],
                                       [a["feather"] for a in anchors],
                                       len(record["points"]))
        points = []
        for point, scalar in zip(record["points"], got["feather"]):
            carried = dict(point)
            carried["feather"] = scalar
            points.append(carried)
        out[str(frame)] = dict(record, points=points)
    return out


def _anchored_dense(spec, frames, warn):
    """The `anchored` feather layer as vertices Nuke can hold (spec 6.5).

    Returns a `frames` mapping whose points each carry a `feather` scalar, so
    everything downstream reads the shape as `per_point` - which is Nuke's own
    model and needs no further special case. Returns None when the shape cannot
    be carried this way and the caller should fall back to the v1 snap.

    Nuke anchors feather at a vertex and nowhere else, so an anchor that sits
    mid-segment gets one: the segment is split with de Casteljau, which
    reproduces the curve exactly, and the anchor rides the new vertex. The
    shape gains vertices and does not move. That is the trade section 6.5
    makes, and the compositor is told about it rather than left to wonder why
    there are more points than the artist drew.

    **The one case that does not work.** An anchor that slides past an
    original vertex changes its ordinal position around the ring, so the
    inserted vertex would have to change index partway through the shape -
    which is a topology change, forbidden for the reason v1 section 7.3
    forbids a changing vertex count. It shows up here as a vertex count that
    differs between frames, and the whole shape falls back to the snap. That
    is coarser than section 6.5's "snap that one anchor": the count says a
    crossing happened but not which pair crossed, and guessing would be worse
    than being plain about it.
    """
    name = spec["name"]
    source = spec["frames"]
    out = {}
    counts = {}
    inserted = 0
    collided = {}

    for frame in frames:
        record = source[str(frame)]
        got = geom.insert_anchor_vertices(record["points"],
                                          record["feather_points"],
                                          spec["closed"])
        counts.setdefault(len(got["points"]), frame)
        inserted = max(inserted, got["inserted"])
        for clash in got["collided"]:
            collided[clash["t"]] = clash
        points = []
        for point, scalar in zip(got["points"], got["feather"]):
            carried = dict(point)
            carried["feather"] = scalar
            points.append(carried)
        out[str(frame)] = dict(record, points=points)

    if len(counts) > 1:
        detail = ", ".join("%d at frame %s" % (n, counts[n])
                           for n in sorted(counts))
        warn(messages.render("feather-anchors-cross",
                             {"subject": "shape '%s'" % name,
                              "detail": detail}))
        return None

    if inserted:
        warn(messages.render(
            "feather-vertices-inserted",
            {"subject": "shape '%s'" % name, "count": inserted,
             "noun": "vertex was" if inserted == 1 else "vertices were"}))

    if collided:
        warn(messages.render("feather-anchors-collide",
                             {"subject": "shape '%s'" % name,
                              "count": len(collided)}))

    return out


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
        warn(messages.render("key-sides-collapsed",
                             {"subject": "shape '%s'" % spec["name"],
                              "count": collapsed}))

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
        warn(messages.render("ease-dropped",
                             {"subject": "shape '%s'" % spec["name"],
                              "count": shaped}))

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
    carried = model
    dense = spec["frames"]

    if model == "anchored":
        # Resolved to vertices before anything is built, because the split
        # changes the point count and the Shape is created from it.
        # `_anchored_dense` returns None only for the crossing case, and then
        # the v1 snap is the fallback - which is why `snap_feather_points`
        # does not go away (spec/rbj-v2-draft.md section 6.8).
        anchored = _anchored_dense(spec, frames, warn)
        if anchored is None:
            dense = _snapped_dense(spec, frames)
            # What the shape *became*, not what the file asked for: the record
            # is read to find out what arrived, and the warning above has
            # already said why it is not what was written.
            carried = "per_point (anchors snapped)"
        else:
            dense = anchored
        model = "per_point"

    shape = rp.Shape(knob)
    for point in dense[str(frames[0])]["points"]:
        shape.append(rp.ShapeControlPoint(float(point["c"][0]),
                                          float(point["c"][1])))
    shape.name = name
    shape.setFlag(rp.FlagType.eOpenFlag, not spec["closed"])
    knob.rootLayer.append(shape)

    offsets = _frame_offsets(dense, frames, warn, name, model, spec["closed"])

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
        warn(messages.render("drift-residual",
                             {"subject": "shape '%s'" % name,
                              "residual": messages.px(residual, 4),
                              "frame": at}))

    _write_attributes(shape, spec, frames, offset, warn)

    return {
        "name": name,
        "feather_model": carried,
        "points": len(dense[str(frames[0])]["points"]),
        "authored": len(key_frames),
        "corrective": len(final) - len(set(key_frames) & set(frames)),
        "residual": residual,
        # Host numbering, so it names the frame an artist would look at. The
        # drift pass works in source frames and has no offset to apply.
        "worst_frame": None if at is None else at + offset,
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


def _subset(shapes, subset, warn):
    """The shapes the artist asked for, by id first and name second.

    An id is unique when present (the validator enforces it); a name is a
    display label that may collide, which the exporters warn about. Accepting
    either lets the artist type what the file or the record shows them.
    """
    wanted = set(subset)
    out = [s for s in shapes
           if s["name"] in wanted or s.get("id") in wanted]
    known = set(s["name"] for s in shapes)
    known.update(s["id"] for s in shapes if "id" in s)
    for name in sorted(wanted - known):
        warn(messages.render("subset-missing", {"name": name}))
    if not out:
        raise ValueError("no shapes matched the requested subset")
    return out


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
        shapes = _subset(shapes, subset, warn)

    # An open spline round trips exactly within one application; what it
    # *renders* as across two is unmeasured on the After Effects side and lives
    # in node knobs on this one (spec/rbj-v2-draft.md section 5).
    if doc["source"]["app"] != "Nuke":
        for spec in shapes:
            if not spec["closed"]:
                warn(messages.render(
                    "open-spline-unverified",
                    {"subject": "shape '%s'" % spec["name"],
                     "app": doc["source"]["app"]}))

    node = nuke.createNode("Roto", inpanel=False)
    knob = roto_knob(node)
    reports = [build_shape(knob, spec, frames, offset, tolerance, warn)
               for spec in shapes]

    return node, warnings, reports


def build_record(doc, source_path, node, warnings, reports, offset, tolerance):
    """Everything this import knows, in the shape `core.report` renders.

    The two warning lists are split back apart here: `import_document` seeds its
    list with the file's own warnings, in order and first, so what the exporter
    already lost stays distinguishable from what this import lost. A record that
    ran them together would answer "which application dropped it?" with "one of
    them did".
    """
    file_warnings = list(doc.get("warnings", []))
    return {
        "written": time.strftime("%Y-%m-%d %H:%M:%S"),
        "host": "Nuke %s" % nuke.NUKE_VERSION_STRING,
        "target": node.name(),
        "source_file": source_path,
        "source": doc["source"],
        "version": doc["version"],
        "range": doc["range"],
        "offset": offset,
        "tolerance": tolerance,
        "shapes": reports,
        "file_warnings": file_warnings,
        "import_warnings": warnings[len(file_warnings):],
    }


def record_path(source_path):
    """Where the record goes: beside the script, or beside the .rbj.

    Beside the **script** is the point - the record belongs with the comp that
    holds the shapes, so someone opening it a month later finds it without
    knowing where the .rbj came from. An unsaved script has nowhere to sit
    next to, and then the source file is the next best anchor.
    """
    script = nuke.root().name()
    if script and script != "Root":
        return report.path_for(script)
    return report.path_for(source_path)


def write_record(record, path, warn):
    """Append one record to `path`. Returns the path, or None if it failed.

    Appended, never overwritten: a comp is imported into more than once, and
    the second import is not entitled to erase the evidence of the first.

    A record that cannot be written is a warning and not an exception. The
    shapes are already in the script by the time this runs, and losing an
    import over a read-only directory would be a worse failure than the one
    being reported.
    """
    try:
        handle = open(path, "a")
        try:
            handle.write(report.render(record))
        finally:
            handle.close()
    except (IOError, OSError) as exc:
        warn(messages.render("record-unwritable",
                             {"path": path, "reason": str(exc)}))
        return None
    return path


def import_from_file(path, offset=0, tolerance=DEFAULT_TOLERANCE, subset=None):
    """Import a .rbj and record what happened.

    Returns `(node, warnings, reports, record_path)`. Writing the record is
    part of importing rather than something a caller opts into: the whole
    argument for it is that it exists for every import, including the ones
    nobody thought would need defending.
    """
    handle = open(path, "r")
    try:
        text = handle.read()
    finally:
        handle.close()

    doc = rbj.loads(text)
    node, warnings, reports = import_document(doc, offset, tolerance, subset)
    record = build_record(doc, path, node, warnings, reports, offset, tolerance)
    written = write_record(record, record_path(path), warnings.append)
    return node, warnings, reports, written


def _parse_tolerance(raw):
    """The one import control (prd.md section 8). Blank or `inf` is unbounded."""
    raw = raw.strip().lower()
    if raw in ("", "inf", "infinity"):
        return float("inf")
    value = float(raw)
    if value != value or value < 0.0:
        # The self-comparison is the nan check: nan is not < 0, but accepting
        # it would run the drift pass as tolerance inf while the record says
        # "nan px". The AE importer already refuses it; so do we.
        raise ValueError("drift tolerance must be a number >= 0; got %s" % raw)
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

    node, warnings, reports, written = import_from_file(
        path, int(panel.value("frame offset")), tolerance, subset)

    lines = ["Imported %d shape(s) into %s" % (len(reports), node.name())]
    for entry in reports:
        line = "  %s: %d authored key(s)" % (entry["name"], entry["authored"])
        if entry["corrective"]:
            line += ", %d corrective" % entry["corrective"]
        if entry["worst_frame"] is not None:
            line += "; worst drift %.4g px at frame %d" % (entry["residual"],
                                                           entry["worst_frame"])
        lines.append(line)
    if written:
        lines.append("")
        lines.append("recorded in %s" % written)
    if warnings:
        lines.append("")
        lines.append("%d warning(s):" % len(warnings))
        lines.extend("  " + w for w in warnings)
    nuke.message("\n".join(lines))
