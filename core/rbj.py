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

import json
import math
import re

VERSION = 1

# spec/rbj-v2-draft.md section 2: a writer emits the lowest version that can
# express the file, not the highest it implements, so a file with no open spline
# is still a v1 file and still opens in a v1 reader.
VERSION_OPEN_SPLINES = 2
MAX_VERSION = 2

BLENDS = ("union", "difference", "intersection")
FEATHER_MODELS = ("per_point", "none")
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

    return errs


def _validate_source(errs, src):
    if not isinstance(src, dict):
        errs.append("source is %r, expected an object" % (src,))
        return
    for key in ("app", "app_version"):
        if not isinstance(src.get(key), str):
            errs.append("source: %s is %r, expected a string" % (key, src.get(key)))
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

    frame_keys = _validate_frames(errs, where, shape.get("frames"),
                                  frames_expected, model)
    _validate_keys(errs, where, shape.get("keys"), frame_keys)


def _validate_frames(errs, where, frames, frames_expected, model):
    """Validate the dense layer. Returns the frame keys present, or None.

    None means the dense layer was unusable, so callers should not go on to
    report every key as pointing at a missing frame - that buries the one error
    that matters under a hundred that follow from it.
    """
    if not isinstance(frames, dict):
        errs.append("%s: frames is %r, expected an object" % (where, frames))
        return None

    present = set(frames.keys())

    malformed = sorted(k for k in present if not FRAME_KEY_RE.match(k))
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
    for key in ordered:
        if len(shape_errs) > MAX_ERRORS_PER_SHAPE:
            break
        n = _validate_frame_record(shape_errs, "%s frame %s" % (where, key),
                                   frames[key], model)
        if n is not None:
            counts.setdefault(n, key)

    errs.extend(shape_errs[:MAX_ERRORS_PER_SHAPE])
    if len(shape_errs) > MAX_ERRORS_PER_SHAPE:
        errs.append("%s: and further problems in later frames, suppressed" % where)

    if len(counts) > 1:
        detail = ", ".join("%d at frame %s" % (n, counts[n])
                           for n in sorted(counts))
        errs.append("%s: vertex count changes across frames (%s); Nuke cannot "
                    "represent this and there is no correct interpolation "
                    "between two counts" % (where, detail))

    return present


def _validate_frame_record(errs, where, rec, model):
    """Validate one frame. Returns its vertex count, or None if unusable."""
    if not isinstance(rec, dict):
        errs.append("%s is %r, expected an object" % (where, rec))
        return None

    opacity = _num(errs, where, rec, "opacity")
    if opacity is not None and not (0.0 <= opacity <= 1.0):
        errs.append("%s: opacity is %r, expected 0.0 to 1.0" % (where, opacity))
    _vec2(errs, where, rec, "feather_uniform")

    points = rec.get("points")
    if not isinstance(points, list):
        errs.append("%s: points is %r, expected an array" % (where, points))
        return None
    if not points:
        errs.append("%s: points is empty" % where)
        return None

    for i, pt in enumerate(points):
        _validate_point(errs, "%s point %d" % (where, i), pt, model)
    return len(points)


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

    if "feather_offset" in pt:
        if not has_feather:
            errs.append("%s: feather_offset without feather" % where)
        _vec2(errs, where, pt, "feather_offset")


def _validate_keys(errs, where, keys, frame_keys):
    if keys is None:
        return
    if not isinstance(keys, list):
        errs.append("%s: keys is %r, expected an array" % (where, keys))
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

        _validate_interp(errs, kwhere, key)

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
        _vec2(errs, where, ease, side)
    for side in ease:
        if side not in ("in", "out"):
            errs.append("%s: ease has an unexpected side %r" % (where, side))


def version_for(shapes):
    """The lowest `version` that can express `shapes`.

    Open splines need version 2 (spec/rbj-v2-draft.md section 3); everything
    else is still a v1 file and must still say so, or every existing reader
    rejects a file it could have read. One implementation, shared by both
    exporters, because two writers deciding this independently is how they
    drift apart.
    """
    for shape in shapes:
        if shape.get("closed") is False:
            return VERSION_OPEN_SPLINES
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
    return doc


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
