"""Every warning either implementation can write, rendered from one table.

A warning used to be a sentence composed at its emit site, and everything
downstream matched substrings of the prose: the tests, the import record's
file-versus-import split, any tool reading a .rbj. Rewording one was a
breaking change nobody was told about. Here each warning is a code plus
parameters, rendered as::

    [code] the sentence, with the parameters filled in

so tests and tools match the bracketed code and the prose can be rewritten
freely. The code also survives translation of the sentence, if that ever
matters.

This table is mirrored in ES3 (`ae/lib/rotobridge_core.jsx`, `RB.messages`) like
the rest of core, and the cross-check test renders every code in both
implementations and compares bytes - which is also what keeps the two hosts'
prose for the same loss from drifting apart, something the inline sentences
had already started doing (the inverted flag was announced two different ways).

Files written before this table exist and carry unprefixed prose; they stay
legal, because a warning is provenance of the writer that wrote it, and the
validator asks only that it be a string.

Parameters are strings or numbers. Numbers render as the import record renders
them (`core/report.py` `_num`): whole values lose the trailing zero on both
sides, because JavaScript has one number type. A float that needs fixed
decimals is pre-formatted by the caller with `px`, which rounds half away from
zero for the reason `report._pixels` gives.
"""

import math
import re

_PLACEHOLDER = re.compile(r"\{([a-z0-9_]+)\}")

# One entry per thing an adapter can lose or decide on the artist's behalf.
# {subject} is the emitting host's name for the shape: "mask 'X'" from After
# Effects, "shape 'X'" from Nuke - the artist's word for the thing they made.
TEMPLATES = {
    # -- both exporters ----------------------------------------------------
    "inverted-dropped":
        "{subject}: the inverted flag was dropped; .rbj v1 has no field"
        " for it",

    # -- After Effects export ----------------------------------------------
    "name-collision":
        "two masks are both named '{name}' (on layers '{first}' and"
        " '{second}'); importing a subset by name cannot tell them apart",
    "expansion-dropped":
        "{subject}: mask expansion of {px} px was dropped; .rbj v1 has no"
        " field for it",
    "mask-mode-unmapped":
        "{subject}: mask mode '{mode}' has no .rbj equivalent; wrote 'union'",
    "open-spline-stroke":
        "{subject} is an open spline, which produces no alpha as an After"
        " Effects mask; the geometry is carried but no stroke width or end"
        " caps are",
    "feather-shaping-dropped":
        "{subject}: feather point {members} value(s) were authored; .rbj has"
        " no member for them, so the feather's placement and radius travel"
        " but this shaping does not",
    "feather-anchored-v2":
        "{subject}: feather is anchored along the path rather than at"
        " vertices, which only .rbj version 2 can express, so this file is"
        " version 2 and a version 1 reader will refuse it. Nothing is lost;"
        " under version 1 this mask's feather was being moved to the nearest"
        " vertex",
    "feather-count-changes":
        "{subject}: the number of feather points changes between frames,"
        " which no .rbj version can carry - there is no correct interpolation"
        " between two counts - so the anchors were snapped to vertices as"
        " version 1 does",
    "feather-snapped":
        "{subject}: {count} feather point(s) sat mid-segment and were snapped"
        " to the nearer vertex; Nuke can only anchor feather at a vertex",
    "feather-duplicate-dropped":
        "{subject}: two feather points resolved to vertex {vertex}; kept"
        " radius {kept} and dropped {dropped}",
    "key-off-grid":
        "{subject}: a key sat {offset} of a frame off the grid and was"
        " snapped to frame {frame}; .rbj keys are whole frames",
    "ease-conformed":
        "{subject}: {count} key side(s) carried temporal ease, which Nuke's"
        " roto curves cannot hold. They were rewritten as linear and {added}"
        " key(s) added, so the path is within {tolerance} px of this comp on"
        " every frame. What is lost is editable timing, not the shape",
    "keys-added":
        "{subject}: {added} key(s) added so a straight line between keys"
        " stays within {tolerance} px of this comp on every frame. Nothing"
        " the artist authored changed; the sparse layer now needs no"
        " correction downstream",
    "hold-under-motion":
        "{subject}: {count} key(s) hold the mask path while the layer moves"
        " under it, so the shape is not flat there and the hold is not"
        " carried as one. Geometry is unaffected; what is lost is a held key"
        " the artist could edit",

    # -- both After Effects adapters -----------------------------------------
    "transform-not-affine":
        "layer '{layer}': its transform is not affine (off by {px} px); every"
        " point was converted through the host instead, which is slower but"
        " exact",

    # -- After Effects import ------------------------------------------------
    "comp-size-differs":
        "the file was exported from a {src} comp and this one is {dst};"
        " coordinates were used as-is, not rescaled",
    "fps-differs":
        "the file was exported at {src} fps and this comp is {dst} fps; frame"
        " numbers were used as-is, so the timing in seconds differs",
    "pixel-aspect-differs":
        "pixel aspect differs ({src} against {dst}); .rbj v1 treats pixels as"
        " square",
    "open-spline-renders-nothing":
        "{subject} is an open spline: After Effects produces no alpha from an"
        " open mask path, so the geometry arrives exactly but the mask"
        " renders nothing. Open paths matte in Nuke, not here",

    # -- both importers ------------------------------------------------------
    "subset-missing":
        "shape '{name}' was requested but is not in the file",
    "drift-residual":
        "{subject}: the drift pass ran out of passes with {residual} px still"
        " unaccounted for at frame {frame}; re-import this shape at a tighter"
        " tolerance if it shows",
    "record-unwritable":
        "the import record could not be written to {path} ({reason}); this"
        " import is not recorded anywhere but this dialog",

    # -- Nuke export ---------------------------------------------------------
    "interp-mixed":
        "{subject}: {count} key(s) interpolate differently from one control"
        " point to the next, which has no single-valued form; they were"
        " written as 'ease' with no parameters and the importer's drift pass"
        " carries the geometry (prd.md section 7, tier 2)",
    "open-spline-knobs":
        "{subject}: an open spline's render settings are node knobs"
        " (openspline_width and the end types), not shape attributes, so they"
        " are not carried in the file",
    "transform-order-unverified":
        "{subject}: a layer transform and a shape transform are both active,"
        " and their composition order is unverified (Q10). The geometry is"
        " baked assuming the shape's own transform applies first",
    "feather-tangential":
        "{subject}: feather offsets depart from the path normal; the"
        " tangential component survives in feather_offset but is lost to"
        " adapters other than Nuke",
    "nuke-blend-unmapped":
        "{subject}: Nuke blending mode '{mode}' is a pixel operation with no"
        " .rbj equivalent; wrote 'union'",
    "attr-animation-dropped":
        "{subject}: {attr} is keyed on more than one frame, but .rbj"
        " carries it as one value per shape; only its value at the"
        " first exported frame crossed",
    "layer-flattened":
        "layer '{name}' flattened to the root",
    "stroke-skipped":
        "paint stroke '{name}' skipped; .rbj v1 carries splines only",
    "element-skipped":
        "element '{name}' of unhandled type {type} skipped",

    # -- Nuke import -----------------------------------------------------------
    "blend-unmapped":
        "{subject}: .rbj blend '{blend}' has no Nuke roto equivalent - Nuke"
        " blends pixels, it has no boolean shape operations; used 'over'"
        " instead",
    "feather-degenerate-vertex":
        "{subject}: a feather point sits on a degenerate vertex with no"
        " defined normal; its feather was dropped",
    "feather-anchors-cross":
        "{subject}: feather anchors cross each other between frames ({detail}"
        " vertices would be needed), which would change the shape's topology"
        " partway through. They were snapped to vertices as .rbj version 1"
        " does, so this shape's feather is placed as it would have been"
        " before",
    "feather-vertices-inserted":
        "{subject}: {count} {noun} inserted to hold feather anchors that sat"
        " mid-segment. The subdivision is exact, so the shape has not moved -"
        " it has more points than the artist drew because Nuke can only"
        " anchor feather at a vertex",
    "feather-anchors-collide":
        "{subject}: {count} feather anchor(s) share a position with another"
        " and could not be given a vertex of their own; the larger radius was"
        " kept. Nuke carries one feather offset per control point",
    "key-sides-collapsed":
        "{subject}: {count} key(s) carry a different interpolation on each"
        " side, which a Nuke key cannot hold - one type governs the whole"
        " key. The closest type Nuke has was used and the drift pass"
        " corrected the positions",
    "ease-dropped":
        "{subject}: {count} key(s) carry authored ease. Nuke's roto curves"
        " cannot hold it, so the shape arrives as a dense bake and the"
        " keyframe timing is not editable downstream. Geometry is unaffected",
    "ease-restored":
        "{subject}: the file's keys were conformed to linear on the way out,"
        " for a destination that cannot hold temporal ease. This one can, so"
        " the {count} authored key(s) were rebuilt from the timing the file"
        " kept beside them. The conform warning the file carries does not"
        " apply here",
    "open-spline-unverified":
        "{subject} is an open spline from {app}; the geometry is exact but"
        " what it renders as across applications is unverified",
}


def codes():
    """Every code in the table, sorted. The cross-check walks this."""
    return sorted(TEMPLATES)


def _param(value):
    """One parameter as text, spelled the same way by both implementations."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("warning parameters are strings or numbers; got %r"
                         % (value,))
    value = float(value)
    if value == int(value) and abs(value) < 1e16:
        return "%d" % int(value)
    return repr(value)


def px(value, places):
    """A pixel measurement at fixed decimals, rounded half away from zero.

    Python's %.Nf rounds half to even and JavaScript's toFixed rounds half
    away from zero, so a value landing exactly on a tie would be spelled
    differently by the two hosts. Same rule as `report._pixels`, generalised.
    """
    scale = 10 ** places
    scaled = int(math.floor(abs(float(value)) * scale + 0.5))
    sign = "-" if float(value) < 0.0 and scaled else ""
    return "%s%d.%0*d" % (sign, scaled // scale, places, scaled % scale)


def render(code, params=None):
    """The warning string for `code`: "[code] " and the filled-in template.

    Raises on an unknown code or a placeholder with no parameter, because a
    malformed warning is a bug in the adapter, not a loss to record.
    """
    if code not in TEMPLATES:
        raise ValueError("unknown warning code: %s" % code)
    params = params or {}
    missing = []

    def fill(match):
        key = match.group(1)
        if key not in params:
            missing.append(key)
            return match.group(0)
        return _param(params[key])

    text = _PLACEHOLDER.sub(fill, TEMPLATES[code])
    if missing:
        raise ValueError("warning '%s' is missing parameter(s): %s"
                         % (code, ", ".join(missing)))
    return "[%s] %s" % (code, text)
