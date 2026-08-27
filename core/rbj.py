"""The .rbj v1 schema, executable (spec/rbj-v1.md).

Validation and serialization only. No file access: adapters read and write the
bytes, this module decides whether they are legal. That split is what lets the
golden .rbj files test either adapter with neither application present
(prd.md section 5.1).

`validate` returns every problem it finds rather than raising on the first, so
one run tells an artist everything wrong with a file. `loads` and `dumps` raise,
because prd.md section 11 requires aborting rather than emitting partial output:
a file that is written but invalid looks correct until it is composited.
"""

import copy
import json
import math
import re

VERSION = 1

# spec/rbj-v2-draft.md section 2: a writer emits the lowest version that can
# express the file, not the highest it implements, so a file with no open spline
# is still a v1 file and still opens in a v1 reader.
VERSION_OPEN_SPLINES = 2
VERSION_ANCHORED_FEATHER = 2
# spec/rbj-v3-draft.md section 3: a dense frame may say {"same_as": N} instead
# of repeating an earlier frame it is identical to. Roto is full of held
# spans, and a shape held over 1000 frames used to write 1000 identical frame
# objects. A v1/v2 reader hard-fails on the reference record, so unlike the
# optional members, this one costs a version.
VERSION_FRAME_REFS = 3
MAX_VERSION = 3

BLENDS = ("union", "difference", "intersection")
ATTRIBUTE_NAMES = ("opacity", "feather_uniform")
# spec/rbj-v2-draft.md section 6.2: three exclusive models, not layers.
# `per_point` is Nuke's - one value per vertex - and is what v1 froze.
# `anchored` puts the feather layer in the frame's own `feather_points`, keyed
# by a position along the path, because After Effects anchors feather anywhere
# on a segment and can put two anchors on one segment. No point member can hold
# that, which is why this is a new list rather than a widened field.
FEATHER_MODELS = ("per_point", "anchored", "none")
FALLOFFS = ("linear", "smooth")
INTERPS = ("hold", "linear", "ease")

# spec section 7.1: plain decimal integers, no padding, no leading +, no "-0".
FRAME_KEY_RE = re.compile(r"^(0|-?[1-9][0-9]*)$")

# A malformed dense layer can produce one error per frame per point. Report
# enough to diagnose, then say how many were suppressed.
MAX_ERRORS_PER_SHAPE = 5


class RbjError(Exception):
    """An .rbj file is not readable as specified. Carries every reason."""

    def __init__(self, errors):
        self.errors = list(errors)
        Exception.__init__(self, "invalid .rbj:\n  " + "\n  ".join(self.errors))


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num(errs, where, obj, key, required=True):
    """Return obj[key] as a float, recording why not if it is not one."""
    if key not in obj:
        if required:
            errs.append("%s: missing %s" % (where, key))
        return None
    v = obj[key]
    if not _is_num(v):
        errs.append("%s: %s is %r, expected a number" % (where, key, v))
        return None
    if not math.isfinite(v):
        errs.append("%s: %s is %r, which is not finite" % (where, key, v))
        return None
    return float(v)


def _vec2(errs, where, obj, key, required=True):
    """Return obj[key] as a two-element float list, or None."""
    if key not in obj:
        if required:
            errs.append("%s: missing %s" % (where, key))
        return None
    v = obj[key]
    if not isinstance(v, list) or len(v) != 2:
        errs.append("%s: %s is %r, expected a two-element array" % (where, key, v))
        return None
    out = []
    for i, e in enumerate(v):
        if not _is_num(e):
            errs.append("%s: %s[%d] is %r, expected a number" % (where, key, i, e))
            return None
        if not math.isfinite(e):
            errs.append("%s: %s[%d] is %r, which is not finite" % (where, key, i, e))
            return None
        out.append(float(e))
    return out


def _enum(errs, where, obj, key, allowed):
    v = obj.get(key)
    if v not in allowed:
        errs.append("%s: %s is %r, expected one of %s"
                    % (where, key, v, " | ".join(allowed)))
        return None
    return v


def validate(doc):
    """Return a list of reasons `doc` is not a legal v1 .rbj. Empty means legal."""
    if not isinstance(doc, dict):
        return ["top level is %s, expected a JSON object" % type(doc).__name__]

    errs = []

    if doc.get("format") != "rotobridge":
        errs.append("format is %r, expected 'rotobridge'" % (doc.get("format"),))

    ver = doc.get("version")
    if not _is_int(ver):
        errs.append("version is %r, expected an integer" % (ver,))
        ver = None
    elif ver > MAX_VERSION:
        errs.append("version %d is newer than this reader implements (%d)"
                    % (ver, MAX_VERSION))
    elif ver < 1:
        errs.append("version %d is not a released version" % ver)

    _validate_source(errs, doc.get("source"))
    frames_expected = _validate_range(errs, doc.get("range"))

    warnings = doc.get("warnings")
    if not isinstance(warnings, list):
        errs.append("warnings is %r, expected an array (possibly empty)" % (warnings,))
    else:
        for i, w in enumerate(warnings):
            if not isinstance(w, str):
                errs.append("warnings[%d] is %r, expected a string" % (i, w))

    shapes = doc.get("shapes")
    if not isinstance(shapes, list):
        errs.append("shapes is %r, expected an array" % (shapes,))
    elif not shapes:
        errs.append("shapes is empty; a file with no shapes is a hard failure")
    else:
        for i, shape in enumerate(shapes):
            _validate_shape(errs, i, shape, frames_expected, ver)
        _validate_ids(errs, shapes)

    return errs


def _validate_ids(errs, shapes):
    # Uniqueness is the whole value of an id over a name (spec/rbj-v3-draft.md
    # section 5): names may collide - the exporter warns - but ids may not.
    seen = {}
    for i, shape in enumerate(shapes):
        if not isinstance(shape, dict) or "id" not in shape:
            continue
        got = shape["id"]
        if not isinstance(got, str) or not got:
            errs.append("shapes[%d]: id is %r, expected a non-empty string"
                        % (i, got))
        elif got in seen:
            errs.append("shapes[%d] and shapes[%d] share the id %r; an id "
                        "exists to tell shapes apart" % (seen[got], i, got))
        else:
            seen[got] = i


def _validate_source(errs, src):
    if not isinstance(src, dict):
        errs.append("source is %r, expected an object" % (src,))
        return
    for key in ("app", "app_version"):
        if not isinstance(src.get(key), str):
            errs.append("source: %s is %r, expected a string" % (key, src.get(key)))
    # Optional: which RotoBridge build wrote the file, as against `app_version`,
    # which is the host it ran in. Absent from every file written before the
    # member existed, and those stay legal - nothing renders from it, so
    # ignoring it cannot change what a reader draws (spec section 5). Present
    # and empty is a different thing from absent, though: it says the writer
    # tried to name itself and failed.
    if "tool_version" in src:
        got = src["tool_version"]
        if not isinstance(got, str) or not got:
            errs.append("source: tool_version is %r, expected a non-empty "
                        "string (omit the member instead)" % (got,))
    for key in ("width", "height"):
        v = src.get(key)
        if not _is_int(v):
            errs.append("source: %s is %r, expected an integer" % (key, v))
        elif v <= 0:
            errs.append("source: %s is %d, expected greater than zero" % (key, v))
    _num(errs, "source", src, "pixel_aspect")
    fps = _num(errs, "source", src, "fps")
    if fps is not None and fps <= 0:
        errs.append("source: fps is %r, expected greater than zero" % (fps,))


def _validate_range(errs, rng):
    """Return the set of frame-key strings the dense layer must cover, or None."""
    if not isinstance(rng, list) or len(rng) != 2:
        errs.append("range is %r, expected [first, last]" % (rng,))
        return None
    first, last = rng
    if not _is_int(first) or not _is_int(last):
        errs.append("range is %r, expected two integers" % (rng,))
        return None
    if first > last:
        errs.append("range is [%d, %d], which is not ascending" % (first, last))
        return None
    return set(str(f) for f in range(first, last + 1))


def _validate_shape(errs, index, shape, frames_expected, version):
    where = "shapes[%d]" % index
    if not isinstance(shape, dict):
        errs.append("%s is %r, expected an object" % (where, shape))
        return

    name = shape.get("name")
    if isinstance(name, str):
        where = "%s '%s'" % (where, name)
    else:
        errs.append("%s: name is %r, expected a string" % (where, name))

    closed = shape.get("closed")
    if not isinstance(closed, bool):
        errs.append("%s: closed is %r, expected a boolean" % (where, closed))
    elif closed is False and version is not None \
            and version < VERSION_OPEN_SPLINES:
        errs.append("%s: closed is false, which needs version %d; this file "
                    "declares version %d (spec/rbj-v2-draft.md section 3)"
                    % (where, VERSION_OPEN_SPLINES, version))

    _enum(errs, where, shape, "blend", BLENDS)
    model = _enum(errs, where, shape, "feather_model", FEATHER_MODELS)
    _enum(errs, where, shape, "feather_falloff", FALLOFFS)
    if model == "anchored" and version is not None \
            and version < VERSION_ANCHORED_FEATHER:
        errs.append("%s: feather_model is 'anchored', which needs version %d; "
                    "this file declares version %d (spec/rbj-v2-draft.md "
                    "section 6.2)"
                    % (where, VERSION_ANCHORED_FEATHER, version))

    frame_keys = _validate_frames(errs, where, shape.get("frames"),
                                  frames_expected, model, closed, version)
    _validate_keys(errs, where, shape.get("keys"), frame_keys)
    if "pre_conform_keys" in shape:
        # Optional provenance (spec/rbj-v3-draft.md section 5): the authored
        # keys exactly as they were before the exporter conformed them, ease
        # blocks intact. Same schema as keys, so the same machinery.
        if shape["pre_conform_keys"] is None:
            errs.append("%s: pre_conform_keys is null; omit the member "
                        "instead" % where)
        else:
            _validate_keys(errs, "%s pre_conform_keys" % where,
                           shape["pre_conform_keys"], frame_keys)
    if "authored_frames" in shape:
        _validate_authored_frames(errs, where, shape["authored_frames"],
                                  frame_keys, shape.get("keys"))
    if "authored_attributes" in shape:
        _validate_authored_attributes(errs, where,
                                      shape["authored_attributes"], frame_keys)


def _validate_frames(errs, where, frames, frames_expected, model, closed,
                     version):
    """Validate the dense layer. Returns the frame keys present, or None.

    None means the dense layer was unusable, so callers should not go on to
    report every key as pointing at a missing frame - that buries the one error
    that matters under a hundred that follow from it.
    """
    if not isinstance(frames, dict):
        errs.append("%s: frames is %r, expected an object" % (where, frames))
        return None

    present = set(frames.keys())

    # The isinstance guard is for the dumps() direction: a hand-built dict
    # can carry int frame keys, and the regex would raise on them instead of
    # letting validate() keep its no-raise contract.
    malformed = sorted((k for k in present
                        if not isinstance(k, str) or not FRAME_KEY_RE.match(k)),
                       key=str)
    for k in malformed[:MAX_ERRORS_PER_SHAPE]:
        errs.append("%s: frames key %r is not a plain decimal integer" % (where, k))
    if len(malformed) > MAX_ERRORS_PER_SHAPE:
        errs.append("%s: and %d more malformed frames keys"
                    % (where, len(malformed) - MAX_ERRORS_PER_SHAPE))

    if frames_expected is not None:
        missing = sorted(frames_expected - present, key=int)
        extra = sorted((present - frames_expected) - set(malformed), key=int)
        if missing:
            errs.append("%s: frames is missing %d frame(s) in range, first %s"
                        % (where, len(missing), missing[0]))
        if extra:
            errs.append("%s: frames has %d frame(s) outside range, first %s"
                        % (where, len(extra), extra[0]))

    ordered = sorted((k for k in present if k not in malformed), key=int)
    shape_errs = []
    counts = {}
    anchor_counts = {}
    for key in ordered:
        if len(shape_errs) > MAX_ERRORS_PER_SHAPE:
            break
        if _is_ref(frames[key]):
            _validate_ref(shape_errs, "%s frame %s" % (where, key), key,
                          frames[key], frames, version)
            continue
        n, anchors = _validate_frame_record(shape_errs,
                                            "%s frame %s" % (where, key),
                                            frames[key], model, closed)
        if n is not None:
            counts.setdefault(n, key)
        if anchors is not None:
            anchor_counts.setdefault(anchors, key)

    errs.extend(shape_errs[:MAX_ERRORS_PER_SHAPE])
    if len(shape_errs) > MAX_ERRORS_PER_SHAPE:
        errs.append("%s: and further problems in later frames, suppressed" % where)

    if len(counts) > 1:
        detail = ", ".join("%d at frame %s" % (n, counts[n])
                           for n in sorted(counts))
        errs.append("%s: vertex count changes across frames (%s); Nuke cannot "
                    "represent this and there is no correct interpolation "
                    "between two counts" % (where, detail))

    # spec section 6.3 defers to section 7.3's reasoning about vertices: two
    # different counts have no correct interpolation between them, and that is
    # as true of feather anchors as of the points they hang off.
    if len(anchor_counts) > 1:
        detail = ", ".join("%d at frame %s" % (n, anchor_counts[n])
                           for n in sorted(anchor_counts))
        errs.append("%s: feather_points count changes across frames (%s); "
                    "there is no correct interpolation between two counts "
                    "(spec/rbj-v2-draft.md section 6.3)" % (where, detail))

    return present


def _is_ref(rec):
    """A frame that says it is the same as an earlier one - exactly
    {"same_as": N} and nothing else (spec/rbj-v3-draft.md section 3)."""
    return isinstance(rec, dict) and set(rec.keys()) == {"same_as"}


def _validate_ref(errs, where, key, rec, frames, version):
    if version is not None and version < VERSION_FRAME_REFS:
        errs.append("%s: same_as needs version %d; this file declares "
                    "version %d (spec/rbj-v3-draft.md section 3)"
                    % (where, VERSION_FRAME_REFS, version))
    target = rec["same_as"]
    if not _is_int(target):
        errs.append("%s: same_as is %r, expected an integer frame"
                    % (where, target))
        return
    if target >= int(key):
        # Earlier only. Backward references keep a reader single-pass and
        # make a cycle impossible to write.
        errs.append("%s: same_as %d does not point at an earlier frame"
                    % (where, target))
        return
    got = frames.get(str(target))
    if got is None:
        errs.append("%s: same_as %d, which is not in the dense layer"
                    % (where, target))
    elif _is_ref(got):
        errs.append("%s: same_as %d, which is itself a reference; references "
                    "do not chain, so every reference resolves in one step"
                    % (where, target))


def fold_frames(doc):
    """Fold runs of identical consecutive frames into references.

    Returns a new document; `doc` is untouched. Bumps the version to
    VERSION_FRAME_REFS only when something actually folded, which is the
    section 6.7 policy again: only the files that benefit pay the
    compatibility cost, and a shape that moves every frame stays a v1 file.

    Explicit rather than built into `dumps`, so `loads(dumps(doc))` stays the
    identity and the exporters own the decision - they call this right before
    serializing. Equality is data equality, which both implementations agree
    on: Python's == treats 1 and 1.0 as the same value and JavaScript has one
    number type, so the two writers make the same folding decisions.
    """
    folded_any = False
    shapes_out = []
    for shape in doc["shapes"]:
        frames = shape["frames"]
        out = {}
        head = None
        for key in sorted(frames, key=int):
            rec = frames[key]
            if head is not None and rec == frames[head]:
                out[key] = {"same_as": int(head)}
                folded_any = True
            else:
                out[key] = rec
                head = key
        folded = dict(shape)
        folded["frames"] = out
        shapes_out.append(folded)
    out_doc = dict(doc)
    out_doc["shapes"] = shapes_out
    if folded_any and out_doc.get("version", 0) < VERSION_FRAME_REFS:
        out_doc["version"] = VERSION_FRAME_REFS
    return out_doc


def expand_frames(doc):
    """Resolve every reference to a deep copy of its frame.

    The inverse of `fold_frames`, applied by `loads` after validation so
    everything downstream of a reader - the drift pass, the importers, the
    tests - still sees a dense layer on every frame. Deep copies, because two
    keys sharing one record would let a mutation of "frame 11" silently edit
    frame 10 as well.
    """
    shapes_out = []
    for shape in doc["shapes"]:
        frames = shape["frames"]
        out = {}
        for key in frames:
            rec = frames[key]
            if _is_ref(rec):
                out[key] = copy.deepcopy(frames[str(rec["same_as"])])
            else:
                out[key] = rec
        expanded = dict(shape)
        expanded["frames"] = out
        shapes_out.append(expanded)
    out_doc = dict(doc)
    out_doc["shapes"] = shapes_out
    return out_doc


def _validate_frame_record(errs, where, rec, model, closed):
    """Validate one frame.

    Returns `(vertex count, feather anchor count)`, either of which is None
    when that layer was unusable and the caller should not compare it across
    frames.
    """
    if not isinstance(rec, dict):
        errs.append("%s is %r, expected an object" % (where, rec))
        return None, None

    opacity = _num(errs, where, rec, "opacity")
    if opacity is not None and not (0.0 <= opacity <= 1.0):
        errs.append("%s: opacity is %r, expected 0.0 to 1.0" % (where, opacity))
    _vec2(errs, where, rec, "feather_uniform")

    points = rec.get("points")
    if not isinstance(points, list):
        errs.append("%s: points is %r, expected an array" % (where, points))
        return None, None
    if not points:
        errs.append("%s: points is empty" % where)
        return None, None

    for i, pt in enumerate(points):
        _validate_point(errs, "%s point %d" % (where, i), pt, model)
    return len(points), _validate_feather_points(errs, where, rec, model,
                                                 closed, len(points))


def _validate_feather_points(errs, where, rec, model, closed, n_points):
    """The `anchored` feather layer (spec section 6.3). Returns its count.

    Required exactly when the model is `anchored` and forbidden otherwise,
    which is section 2's rule that a file says what it means: an empty list
    under `per_point` and an absent one would be two spellings of nothing.
    """
    present = "feather_points" in rec
    if model != "anchored":
        if present and model is not None:
            errs.append("%s: feather_points is present but feather_model is "
                        "%r, not 'anchored'" % (where, model))
        return None
    if not present:
        errs.append("%s: missing feather_points, which feather_model "
                    "'anchored' requires" % where)
        return None

    anchors = rec["feather_points"]
    if not isinstance(anchors, list):
        errs.append("%s: feather_points is %r, expected an array"
                    % (where, anchors))
        return None

    # Section 6.4. A closed shape has one segment per vertex, and t = n names
    # the same anchor as t = 0, so the upper bound is exclusive and must be
    # written as 0. An open shape has one segment fewer and genuinely ends on
    # its last vertex, so there the bound is inclusive.
    #
    # A `closed` that is neither true nor false has already been reported by
    # the caller. Reading it as closed here takes the wider of the two bounds,
    # so the one real error does not drag a range error along behind it.
    is_open = closed is False
    limit = float(n_points - 1) if is_open else float(n_points)
    prev = None
    for i, anchor in enumerate(anchors):
        awhere = "%s feather_points[%d]" % (where, i)
        if not isinstance(anchor, dict):
            errs.append("%s is %r, expected an object" % (awhere, anchor))
            continue
        t = _num(errs, awhere, anchor, "t")
        if t is not None:
            over = t > limit if is_open else t >= limit
            if t < 0.0 or over:
                errs.append("%s: t is %r, expected 0 to %g on %s shape of "
                            "%d point(s)"
                            % (awhere, t, limit,
                               "an open" if is_open else "a closed", n_points))
            elif prev is not None and t < prev:
                errs.append("%s: t is %r, which is below the previous anchor's "
                            "%r; feather_points is ordered by t ascending "
                            "(spec/rbj-v2-draft.md section 6.3)"
                            % (awhere, t, prev))
            prev = t
        _num(errs, awhere, anchor, "feather")
        if "feather_offset" in anchor:
            _vec2(errs, awhere, anchor, "feather_offset")
    return len(anchors)


def _validate_point(errs, where, pt, model):
    if not isinstance(pt, dict):
        errs.append("%s is %r, expected an object" % (where, pt))
        return
    _vec2(errs, where, pt, "c")
    _vec2(errs, where, pt, "in")
    _vec2(errs, where, pt, "out")

    has_feather = "feather" in pt
    if model == "per_point":
        _num(errs, where, pt, "feather")
    elif model == "none" and has_feather:
        errs.append("%s: feather is present but feather_model is 'none'; a zero "
                    "under 'none' is indistinguishable from an authored "
                    "zero-width point" % where)
    elif model == "anchored" and has_feather:
        errs.append("%s: feather is present but feather_model is 'anchored', "
                    "which carries the whole feather layer in the frame's "
                    "feather_points; two places to look is one too many "
                    "(spec/rbj-v2-draft.md section 6.2)" % where)

    if "feather_offset" in pt:
        if not has_feather:
            errs.append("%s: feather_offset without feather" % where)
        _vec2(errs, where, pt, "feather_offset")


def _validate_authored_frames(errs, where, frames, frame_keys, keys):
    """Optional provenance (spec/rbj-v3-draft.md section 5.2): the frames the
    artist keyed on the spline itself. May be empty - that is the member's
    point - but what it names must exist, both in the dense layer and among
    the shape's `keys`, or an importer honouring it would pin a frame the
    file cannot deliver."""
    awhere = "%s authored_frames" % where
    if not isinstance(frames, list):
        errs.append("%s is %r, expected an array" % (awhere, frames))
        return
    keyed = None
    if isinstance(keys, list):
        keyed = set(k["frame"] for k in keys
                    if isinstance(k, dict) and _is_int(k.get("frame")))
    prev = None
    for i, frame in enumerate(frames):
        if not _is_int(frame):
            errs.append("%s[%d] is %r, expected an integer"
                        % (awhere, i, frame))
            continue
        fwhere = "%s[%d] frame %d" % (awhere, i, frame)
        if frame_keys is not None and str(frame) not in frame_keys:
            errs.append("%s: no such frame in the dense layer" % fwhere)
        if keyed is not None and frame not in keyed:
            errs.append("%s: not present in keys" % fwhere)
        if prev is not None:
            if frame == prev:
                errs.append("%s: duplicate frame" % fwhere)
            elif frame < prev:
                errs.append("%s: frames are not sorted ascending (follows %d)"
                            % (fwhere, prev))
        prev = frame


def _validate_authored_attributes(errs, where, attrs, frame_keys):
    """Optional provenance (spec/rbj-v3-draft.md section 5.3): the artist's
    own keyframes on the attributes the dense layer carries per frame. Each
    entry has exactly the schema of `keys` - values are deliberately absent,
    since the dense layer already holds the value on every frame - so the
    same machinery validates it."""
    awhere = "%s authored_attributes" % where
    if not isinstance(attrs, dict):
        errs.append("%s is %r, expected an object" % (awhere, attrs))
        return
    for name in attrs:
        if name not in ATTRIBUTE_NAMES:
            errs.append("%s has an unexpected attribute %r" % (awhere, name))
    for name in ATTRIBUTE_NAMES:
        if name not in attrs:
            continue
        entry = attrs[name]
        if entry is None:
            # `_validate_keys` reads None as an absent `keys` member, which
            # would let the null spelling through; spec section 5.3 requires
            # a non-empty array.
            errs.append("%s %s is null; omit the entry instead"
                        % (awhere, name))
            continue
        if entry == []:
            errs.append("%s %s is empty; omit the entry instead"
                        % (awhere, name))
            continue
        _validate_keys(errs, "%s %s" % (awhere, name), entry, frame_keys)


def _validate_keys(errs, where, keys, frame_keys):
    if keys is None:
        return
    if not isinstance(keys, list):
        errs.append("%s: keys is %r, expected an array" % (where, keys))
        return
    if not keys:
        # An empty array is a second spelling of "no sparse layer", and the
        # drift pass downstream needs at least one key; dense is spelled by
        # omitting the member (spec section 9).
        errs.append("%s: keys is empty; omit the member instead" % where)
        return

    key_errs = []
    prev = None
    for i, key in enumerate(keys):
        if len(key_errs) > MAX_ERRORS_PER_SHAPE:
            break
        kwhere = "%s keys[%d]" % (where, i)
        if not isinstance(key, dict):
            key_errs.append("%s is %r, expected an object" % (kwhere, key))
            continue

        frame = key.get("frame")
        if not _is_int(frame):
            key_errs.append("%s: frame is %r, expected an integer" % (kwhere, frame))
        else:
            kwhere = "%s keys[%d] frame %d" % (where, i, frame)
            if frame_keys is not None and str(frame) not in frame_keys:
                key_errs.append("%s: no such frame in the dense layer" % kwhere)
            if prev is not None:
                if frame == prev:
                    key_errs.append("%s: duplicate key frame" % kwhere)
                elif frame < prev:
                    key_errs.append("%s: keys are not sorted ascending (follows %d)"
                                    % (kwhere, prev))
            prev = frame

        _validate_interp(key_errs, kwhere, key)

    errs.extend(key_errs[:MAX_ERRORS_PER_SHAPE])
    if len(key_errs) > MAX_ERRORS_PER_SHAPE:
        errs.append("%s: and further problems in later keys, suppressed" % where)


def _validate_interp(errs, where, key):
    interp = key.get("interp")
    if not isinstance(interp, dict):
        errs.append("%s: interp is %r, expected an object with in and out"
                    % (where, interp))
        return

    sides = {}
    for side in ("in", "out"):
        sides[side] = _enum(errs, where, interp, side, INTERPS)

    ease = key.get("ease")
    if ease is None:
        return
    if not isinstance(ease, dict):
        errs.append("%s: ease is %r, expected an object" % (where, ease))
        return
    for side in ("in", "out"):
        if side not in ease:
            continue
        if sides[side] != "ease":
            errs.append("%s: ease has an entry for the %s side, whose interp is "
                        "%r, not 'ease'" % (where, side, sides[side]))
        pair = _vec2(errs, where, ease, side)
        if pair is not None and not (0.0 <= pair[0] <= 1.0):
            # Influence is a fraction of the segment (spec section 10.3), and
            # the likeliest way out of range is a writer forgetting to divide
            # After Effects' percentage down - worth refusing at write time.
            errs.append("%s: ease %s influence is %r, expected 0.0 to 1.0"
                        % (where, side, ease[side][0]))
    for side in ease:
        if side not in ("in", "out"):
            errs.append("%s: ease has an unexpected side %r" % (where, side))


def version_for(shapes):
    """The lowest `version` that can express `shapes`.

    Open splines need version 2 (spec/rbj-v2-draft.md section 3) and so does
    anchored feather (section 6.2); everything else is still a v1 file and must
    still say so, or every existing reader rejects a file it could have read.
    One implementation, shared by both exporters, because two writers deciding
    this independently is how they drift apart.

    Section 6.7 is what keeps the anchored clause from swallowing every file
    with feather in it: the exporter decides `per_point` against `anchored` by
    whether the snap would lose anything, and only the files that were being
    damaged pay the compatibility cost.
    """
    for shape in shapes:
        if shape.get("closed") is False:
            return VERSION_OPEN_SPLINES
        if shape.get("feather_model") == "anchored":
            return VERSION_ANCHORED_FEATHER
    return VERSION


def _reject_constant(name):
    raise RbjError(["%s is not a legal JSON number in .rbj" % name])


def loads(text):
    """Parse and validate. Raises RbjError listing every problem found."""
    try:
        doc = json.loads(text, parse_constant=_reject_constant)
    except ValueError as exc:
        raise RbjError(["not valid JSON: %s" % exc])
    errs = validate(doc)
    if errs:
        raise RbjError(errs)
    return expand_frames(doc)


def _pretty(obj, indent, level):
    """Pretty-print, but keep arrays of numbers on one line.

    `json.dumps(indent=2)` puts every element of every array on its own line,
    which turns each coordinate pair into three lines and a 150-frame shape into
    something no one can read a diff of. The format is meant to be diffable
    (spec section 2.1), and that is worth thirty lines of printer. Leaf values
    still go through `json.dumps`, so escaping and number formatting are not
    reimplemented here.
    """
    pad = " " * (indent * level)
    inner = " " * (indent * (level + 1))

    if isinstance(obj, dict):
        if not obj:
            return "{}"
        items = ["%s%s: %s" % (inner, json.dumps(k, ensure_ascii=False),
                               _pretty(v, indent, level + 1))
                 for k, v in obj.items()]
        return "{\n" + ",\n".join(items) + "\n" + pad + "}"

    if isinstance(obj, list):
        if not obj:
            return "[]"
        if all(_is_num(v) for v in obj):
            return "[" + ", ".join(json.dumps(v, allow_nan=False) for v in obj) + "]"
        items = [inner + _pretty(v, indent, level + 1) for v in obj]
        return "[\n" + ",\n".join(items) + "\n" + pad + "]"

    return json.dumps(obj, allow_nan=False, ensure_ascii=False)


def dumps(doc, indent=2):
    """Validate, then serialize. Raises rather than writing an invalid file.

    `allow_nan=False` is not the default anywhere in Python's json module:
    without it the encoder emits the bare literals NaN and Infinity, which no
    JSON parser is required to accept and which spec section 2.2 forbids.
    """
    errs = validate(doc)
    if errs:
        raise RbjError(errs)
    return _pretty(doc, indent, 0)
