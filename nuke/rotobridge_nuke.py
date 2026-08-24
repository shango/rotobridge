"""Shared host-side helpers for the Nuke adapters.

Everything in here touches `nuke` or `nuke.rotopaint`. The geometry, timing and
schema live in `core/`, which imports neither, so they stay testable without a
licence (prd.md section 5.1).

API choices here are the ones Phase 0 and the Phase 2 probe measured. Where a
mapping is still unverified it says so at the point of use, and the export
records a warning in the file rather than pretending.
"""

import os
import sys

import nuke
import nuke.rotopaint as rp


def _bootstrap_core():
    """Put the repo root on sys.path so `core` imports inside Nuke."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    if root not in sys.path:
        sys.path.insert(0, root)


_bootstrap_core()

from core import (drift, geom, interp, messages, rbj, report, timing,  # noqa: E402
                  version)

VIEW = "main"

# Attribute names, from Phase 0 case 01.
ATTR_OPACITY = "opc"
ATTR_BLEND = "bm"
ATTR_INVERTED = "inv"
ATTR_FEATHER_X = "fx"
ATTR_FEATHER_Y = "fy"
ATTR_FEATHER_FALLOFF = "ff"


def about():
    """What build this is and where it was installed, for a bug report."""
    nuke.message("%s\n\ninstalled at %s\n\nwrites .rbj format version %d"
                 % (version.LABEL, os.path.dirname(os.path.abspath(__file__)),
                    rbj.MAX_VERSION))


# Phase 0 case 63 and Phase 2 case 74: AnimCurveKey.interpolationType wants the
# InterpolationType enum PLUS ONE. A fresh key reports 256, an unset sentinel.
# Case 74 confirmed this is the linear control on point position curves, and
# that CurveType has no linear member at all - it is the spline basis, so
# prd.md's "set curveType explicitly" was aimed at the wrong knob.
INTERP_LINEAR = rp.InterpolationType.eLinearInterpolationType + 1

# Q10, closed by the q10 probe. `bm` is an index into the RotoPaint node's
# `blending_mode` enumeration - fifteen PIXEL blend operations, not the thirty
# Merge operations case 73 guessed and case 75 swept. Case 94 read the names and
# their stored numbers straight off the knob.
#
# The operations are not boolean set operations. Case 98 measured what one
# actually does: a shape composites against the accumulated matte BELOW it, and
# only inside its own outline. So `over` gives union exactly, and nothing gives
# difference or intersection over the whole matte - `minus` cuts the overlap but
# drives alpha to -1 wherever the cutter reaches past what it is cutting, and
# `min` leaves the lower shape untouched outside the overlap. prd.md section 10
# assumed three set operations Nuke roto does not have.
#
# So the adapters still carry `union` only. That is now a measured limit rather
# than an open question, and the warning can name the mode it dropped.
BLEND_NAMES = {
    0: "over", 1: "max", 2: "multiply", 3: "color-burn", 4: "min",
    5: "screen", 6: "color-dodge", 7: "plus", 8: "overlay", 9: "soft-light",
    10: "hard-light", 11: "from", 12: "minus", 13: "difference",
    14: "exclusion",
}
BLEND_UNION = 0.0


def blend_name(bm):
    """The name Nuke's own `blending_mode` menu gives a `bm` value."""
    value = float(bm)
    if value != int(value):
        return "%g (not a whole number)" % value
    return BLEND_NAMES.get(int(value), "%g (outside the menu)" % value)


def blend_to_rbj(bm, warn, shape_name):
    """Nuke `bm` to an .rbj blend value. Anything unrecognised degrades."""
    if abs(float(bm) - BLEND_UNION) < 1e-9:
        return "union"
    warn(messages.render("nuke-blend-unmapped",
                         {"subject": "shape '%s'" % shape_name,
                          "mode": blend_name(bm)}))
    return "union"


def blend_from_rbj(blend, warn, shape_name):
    """An .rbj blend value to Nuke `bm`.

    `difference` and `intersection` have no faithful Nuke form. `minus` cuts
    the overlap but only when the cutter is ABOVE its target - the opposite of
    AE's list order - and goes negative outside it, so approximating either one
    would deform the matte in a way the warning could not describe.
    """
    if blend != "union":
        warn(messages.render("blend-unmapped",
                             {"subject": "shape '%s'" % shape_name,
                              "blend": blend}))
    return BLEND_UNION


# `ff` defaults to 1.0 on a fresh shape and the API never names its values.
# UNVERIFIED: treating non-zero as smooth is a guess, recorded in Q10. It round
# trips Nuke to Nuke either way, because the same rule runs in both directions.
def falloff_to_rbj(ff):
    return "smooth" if abs(float(ff)) > 1e-9 else "linear"


def falloff_from_rbj(falloff):
    return 1.0 if falloff == "smooth" else 0.0


def vec2(v):
    """A CVec2/CVec3 as a plain [x, y].

    Phase 2 case 70: CVec exposes `.x` / `.y` and is iterable. The Phase 0
    probe parsed the repr with a regex, which an adapter should not do.
    """
    return [float(v.x), float(v.y)]


def is_closed(shape):
    """Shapes carry an open flag; closed is its inverse (Phase 2 case 72)."""
    return not shape.getFlag(rp.FlagType.eOpenFlag)


def roto_knob(node):
    return node["curves"]


def iter_shapes(element, warn, path="", ancestors=()):
    """Yield `(shape, ancestor_layers)` for every Shape under `element`.

    prd.md section 9.2 requires flattening nested layers with a warning, and
    skipping paint strokes with a warning. `isinstance` against the rotopaint
    classes is the documented dispatch and Phase 0 case 50 confirmed it works.

    The ancestor layers come back with the shape because **a layer carries its
    own transform, independent of the shape's** (Phase 2 case 77: a layer
    translated +500, +25 left the shape's own matrix at +7, +9 and left
    `getPosition` reporting the authored coordinates). Flattening without
    composing that chain moves the geometry silently, which is worse than any
    mapping loss.
    """
    for child in element:
        name = getattr(child, "name", "?")
        if isinstance(child, rp.Shape):
            yield child, tuple(ancestors)
        elif isinstance(child, rp.Layer):
            here = "%s/%s" % (path, name) if path else name
            warn(messages.render("layer-flattened", {"name": here}))
            for item in iter_shapes(child, warn, here,
                                    tuple(ancestors) + (child,)):
                yield item
        elif isinstance(child, rp.Stroke):
            warn(messages.render("stroke-skipped", {"name": name}))
        else:
            warn(messages.render("element-skipped",
                                 {"name": name,
                                  "type": type(child).__name__}))


def attr_value(attrs, name, frame):
    """Read one shape attribute at a frame.

    `getValue`'s third argument is a view NAME, not an index (Phase 0 case 62).
    """
    return float(attrs.getValue(frame, name, VIEW))


def write_attr_curve(attrs, name, samples):
    """Key one shape attribute from [(frame, value), ...].

    Via `getCurve` then `AnimCurve.addKey`, the only route that works:
    `AnimAttributes.addKey` introspects as four parameters but accepts two, and
    `attrs.add(name, value)` silently SHADOWS the curve, so a shape that gets
    both reads back the constant at every frame while the curve animates
    underneath (Phase 0 case 62). Never call `add` on an attribute you key.
    """
    curve = attrs.getCurve(name, VIEW)
    curve.removeAllKeys()
    for frame, value in samples:
        curve.addKey(float(frame), float(value))
    return curve


def set_curve_linear(curve):
    """Make every key on one AnimCurve interpolate linearly."""
    set_curve_types(curve, {}, INTERP_LINEAR)


def set_curve_types(curve, types, default):
    """Set each key's interpolation from `types`, keyed by host frame.

    Keys are addressed by time rather than by index because the drift pass
    inserts keys between passes, which renumbers every index after the
    insertion point. `default` covers keys `types` says nothing about - the
    corrective keys the drift pass adds, which no authored `interp` describes.
    """
    for i in range(curve.getNumberOfKeys()):
        key = curve.getKey(i)
        key.interpolationType = types.get(timing.snap_frame(key.time), default)


def point_members(cp):
    """The four animatable parts of a control point, in .rbj field order."""
    return (cp.center, cp.leftTangent, cp.rightTangent, cp.featherCenter)


def selected_roto_node():
    """The one selected Roto or RotoPaint node, or raise with why not."""
    try:
        node = nuke.selectedNode()
    except Exception:
        raise ValueError("select a Roto or RotoPaint node first")
    if node.Class() not in ("Roto", "RotoPaint"):
        raise ValueError("selected node '%s' is a %s; select a Roto or "
                         "RotoPaint node" % (node.name(), node.Class()))
    return node


def script_range():
    root = nuke.root()
    return int(root.firstFrame()), int(root.lastFrame())
