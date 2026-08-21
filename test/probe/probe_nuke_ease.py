"""RotoBridge ease probe - what Nuke's lslope/rslope and la/ra render as.

Run:  nuke --nc -t probe_nuke_ease.py [output_dir]

`core/interp.to_nuke` deliberately does not write per-side slopes. Its docstring
says why: "case 63 made asymmetric slopes stick but never measured what a slope
value renders as", and it defers the question to After Effects because AE "is
the only place both sides of the mapping are observable at once".

That second reason is no longer true. `test/golden/ae_static_ease.rbj` is a real
After Effects export whose dense layer records, frame by frame, the curve AE
actually rendered from `ease` `in [0.91176, 0]` / `out [0.33333, 0]`. Reading
the normalised progress of one vertex out of that dense layer gives the target
curve as measured in the host, and it reproduces host-free from the stored
parameters alone to 0.00004 in unit terms - about 0.018 px over that shape's
400 px span, which is the 5-decimal rounding of the stored influence and
nothing else.

So one side of the mapping is already pinned, in a file, on disk. What is left
is entirely a Nuke question, and Nuke answers it headless:

  110  What are lslope / rslope in? A slope is either value-units per frame or
       per second, and the two differ by fps - a factor of 24 or 25 that would
       be invisible in a Nuke-to-Nuke round trip and wrong in every crossing.
  111  What do la / ra do? Case 63 read them as 0.0 on every key and never set
       one. If they are the bezier handle length as a fraction of the interval
       they are AE's influence directly; if they are anything else this is
       where the conversion shows up.
  112  Can a Nuke key reproduce the curve After Effects actually rendered? Fit
       (ra, la) against the measured target and report the residual. A close
       fit whose parameters equal the stored influence means the mapping is an
       identity. A close fit at different parameters gives the conversion. A
       poor fit at every parameter means Nuke's cubic is not this cubic, which
       is the answer that matters most and the one `to_nuke` must not guess.
  113  Control. A linear segment must read back exactly linear. `linear_static`
       does in After Effects, to 0.0000, which is what makes case 112's target
       trustworthy; if the same check fails here the sampling is at fault and
       nothing else in this file means anything.

Nothing here changes `core/interp.py`. This measures; the mapping is Phase 5's
to write, against a rendered crossing.
"""

import json
import os
import sys
import traceback

import nuke
import nuke.rotopaint as rp

CUBIC = 3          # case 63: the interpolationType field is the enum plus one
LINEAR = 2
A, B = 0.0, 12.0   # the segment ae_static_ease.rbj keys, in frames

CASES = []


def case(name):
    def register(fn):
        CASES.append((name, fn))
        return fn
    return register


def out_dir():
    if len(sys.argv) > 1:
        d = sys.argv[1]
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        d = os.path.join(here, "..", "golden", "nuke_probe",
                         nuke.NUKE_VERSION_STRING, "ease")
    d = os.path.abspath(d)
    if not os.path.isdir(d):
        os.makedirs(d)
    return d


def write(name, text):
    f = open(os.path.join(OUT, name), "w")
    f.write(text)
    f.close()


def target_curve():
    """The eased unit curve After Effects rendered, out of the golden file.

    One vertex, the axis it travels furthest on, normalised to 0..1 across the
    first keyed segment. Returns `(us, ease_out, ease_in)`.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "golden", "ae_static_ease.rbj")
    doc = json.load(open(path))
    shape = [s for s in doc["shapes"] if s["name"] == "eased_static"][0]
    frames, keys = shape["frames"], shape["keys"]
    a, b = keys[0]["frame"], keys[1]["frame"]
    pa = frames[str(a)]["points"][0]["c"]
    pb = frames[str(b)]["points"][0]["c"]
    axis = 0 if abs(pb[0] - pa[0]) >= abs(pb[1] - pa[1]) else 1
    span = pb[axis] - pa[axis]
    us = [(frames[str(t)]["points"][0]["c"][axis] - pa[axis]) / span
          for t in range(a, b + 1)]
    return us, keys[0]["ease"]["out"][0], keys[1]["ease"]["in"][0]


_CURVE = []


def curve():
    """The one AnimCurve this probe reuses.

    Non-commercial Nuke caps Python-visible nodes at 10, so a probe that
    searches a parameter grid cannot make a node per sample. `opc` is a scalar
    attribute with no geometry attached, so nothing here depends on how a
    control point is stored, and `removeAllKeys` returns it to a clean slate.
    Case 114 is the guard on that reuse.
    """
    if not _CURVE:
        node = nuke.createNode("RotoPaint")
        knob = node["curves"]
        knob.rootLayer.append(rp.Shape(knob))
        # append() copies into the tree; the local Shape is stale from here on.
        _CURVE.append(knob.rootLayer[0].getAttributes().getCurve("opc"))
    return _CURVE[0]


def keyed(va, vb, interp=CUBIC, rslope_a=0.0, lslope_b=0.0, ra_a=0.0, la_b=0.0):
    """The shared curve, re-keyed with every per-side parameter set."""
    c = curve()
    c.removeAllKeys()
    c.addKey(A, va)
    c.addKey(B, vb)
    k0 = c.getKey(0)
    k0.interpolationType = interp
    k0.rslope = rslope_a
    k0.ra = ra_a
    k1 = c.getKey(1)
    k1.interpolationType = interp
    k1.lslope = lslope_b
    k1.la = la_b
    return c


def sample(curve, n=12):
    """The curve at each of n+1 evenly spaced frames across the segment."""
    return [curve.evaluate(A + (B - A) * i / float(n)) for i in range(n + 1)]


def row(label, values):
    return "  %-22s %s" % (label, " ".join("%7.4f" % v for v in values))


@case("108_does_a_curve_bend_at_all")
def _():
    """The control every other case in this directory depends on.

    A two-key curve came back exactly linear for every interpolation type,
    slope and accel this probe could set. That reading is only worth something
    if a curve that is *supposed* to bend actually does, so this rebuilds case
    21's three-key curve - keys 0@f1, 20@f50, 100@f100, deliberately
    non-collinear - which Phase 0 measured as bending well off the chord.

    If the three-key curve bends and the two-key one cannot, the two-key result
    is about key count, not about slopes, and says nothing at all about whether
    Nuke honours an authored tangent.
    """
    c = curve()
    c.removeAllKeys()
    for t, v in ((1.0, 0.0), (50.0, 20.0), (100.0, 100.0)):
        c.addKey(t, v)
    lines = ["Case 21's three-key curve, rebuilt:", ""]
    frames = (1, 12, 25, 37, 50, 62, 75, 87, 100)
    got = [c.evaluate(float(f)) for f in frames]
    lines.append("  frame    " + " ".join("%8d" % f for f in frames))
    lines.append("  evaluate " + " ".join("%8.4f" % v for v in got))
    lines.append("  phase 0  " + " ".join("%8.4f" % v for v in
                 (0.0, 1.3460, 4.3055, 9.7074, 20.0, 34.4657, 54.4697,
                  75.6249, 100.0)))
    lines.append("")
    lines.append("  matches Phase 0: %s"
                 % ("yes" if max(abs(a - b) for a, b in zip(got, (
                    0.0, 1.3460, 4.3055, 9.7074, 20.0, 34.4657, 54.4697,
                    75.6249, 100.0))) < 1e-3 else "NO"))
    lines.append("")
    lines.append("Now move the middle key's tangents and see if the shape")
    lines.append("follows. Sampled either side of that key, at frames 25 and")
    lines.append("75, where case 21 read 4.3055 and 54.4697.")
    lines.append("")
    for name, value in (("lslope", 5.0), ("rslope", 5.0), ("la", 1.0),
                        ("ra", 1.0), ("interpolationType", LINEAR)):
        c.removeAllKeys()
        for t, v in ((1.0, 0.0), (50.0, 20.0), (100.0, 100.0)):
            c.addKey(t, v)
        k = c.getKey(1)
        setattr(k, name, value)
        lines.append("  %-18s = %-6r -> f25 %8.4f  f75 %8.4f  %s"
                     % (name, value, c.evaluate(25.0), c.evaluate(75.0),
                        "MOVES" if abs(c.evaluate(25.0) - 4.3055) > 1e-3
                        or abs(c.evaluate(75.0) - 54.4697) > 1e-3
                        else "no effect"))
    lines.append("")
    lines.append("Anything reading 'no effect' here is stored by the API and")
    lines.append("ignored by the evaluator, which would mean `to_nuke` cannot")
    lines.append("place a tangent from Python however it spells it.")
    return "\n".join(lines)


@case("109_the_api_surface_and_a_degenerate_case")
def _():
    """What a roto AnimCurve and its keys expose, and one finding that is easy
    to trip over: a TWO-key curve is exactly the chord whatever is set on it.

    Every interpolation type, slope and accel this probe can write leaves a
    two-key curve straight. That is not a statement about tangents - case 108
    shows a three-key curve does honour some of them - it is a statement about
    key count, and it is why every measurement in this directory uses three
    keys. Reading a two-key result as "Nuke ignores tangents" is the wrong
    conclusion from the right data.
    """
    c = keyed(0.0, 12.0)
    k = c.getKey(0)
    lines = ["AnimCurveKey surface:", "  " + ", ".join(
        n for n in sorted(dir(k)) if not n.startswith("__"))]
    lines.append("")
    lines.append("AnimCurve surface:")
    lines.append("  " + ", ".join(
        n for n in sorted(dir(c)) if not n.startswith("__")))
    lines.append("")
    lines.append("curveType=%r curveTension=%r" % (c.curveType,
                                                   c.curveTension))
    flags = []
    for i in range(8):
        try:
            flags.append("%d=%r" % (i, c.getFlag(i)))
        except Exception as exc:
            flags.append("%d=<%s>" % (i, type(exc).__name__))
    lines.append("getFlag(i): " + " ".join(flags))
    lines.append("")
    lines.append("Two keys, 0@f%g and 12@f%g. The straight line reads 6.0 at"
                 % (A, B))
    lines.append("the midpoint; anything else is a bend.")
    lines.append("")
    for interp in (-1, 0, 1, 2, 3, 4, 5, 256):
        c = keyed(0.0, 12.0, interp=interp, rslope_a=5.0, lslope_b=5.0,
                  ra_a=1.0, la_b=1.0)
        lines.append("  type %-4d slope 5 accel 1 -> midpoint %.4f"
                     % (interp, c.evaluate((A + B) / 2.0)))
    lines.append("")
    lines.append("Every one straight except the step type, which holds its")
    lines.append("value here as it does on a three-key curve. So the")
    lines.append("degeneracy is specific to the types that SHAPE a segment:")
    lines.append("with no third key to derive a tangent from, and endpoint")
    lines.append("tangents ignored (case 117), there is nothing left for a")
    lines.append("cubic to be but the chord. Use three keys.")
    return "\n".join(lines)


@case("115_is_there_a_tangent_mode")
def _():
    """Case 108 found lslope/rslope/la/ra stored and ignored under the cubic
    and linear types. Before concluding the evaluator never honours an authored
    tangent, sweep the types it has not been asked under.

    Case 63 swept interpolationType and labelled 4, 5 and -1 as "other" -
    shapes that are neither cubic, linear nor step - and never identified them.
    If any mode exists where a slope takes effect, it is one of those.

    Each type is measured twice on case 21's three-key curve: once with the
    middle key's tangents left alone, once with them driven hard. A type where
    the two differ is a type that honours the authored tangent.
    """
    def build(interp, slope, accel):
        c = curve()
        c.removeAllKeys()
        for t, v in ((1.0, 0.0), (50.0, 20.0), (100.0, 100.0)):
            c.addKey(t, v)
        for i in range(3):
            k = c.getKey(i)
            k.interpolationType = interp
            k.lslope, k.rslope = slope, slope
            k.la, k.ra = accel, accel
        return c

    lines = ["Every interpolationType, with tangents left alone and driven"
             " hard.", ""]
    lines.append("  %-6s %-19s %-19s %s"
                 % ("type", "tangents at 0", "slope 5 accel 1", "verdict"))
    for interp in (-1, 0, 1, 2, 3, 4, 5, 256):
        try:
            flat = build(interp, 0.0, 0.0)
            a = (flat.evaluate(25.0), flat.evaluate(75.0))
            driven = build(interp, 5.0, 1.0)
            b = (driven.evaluate(25.0), driven.evaluate(75.0))
            moved = max(abs(x - y) for x, y in zip(a, b)) > 1e-6
            lines.append("  %-6d f25 %7.4f f75 %7.4f  f25 %7.4f f75 %7.4f  %s"
                         % (interp, a[0], a[1], b[0], b[1],
                            "HONOURS TANGENTS" if moved else "ignores them"))
        except Exception as exc:
            lines.append("  %-6d FAILED: %s: %s" % (interp,
                                                    type(exc).__name__, exc))
    lines.append("")

    lines.append("Are the values clobbered, or merely ignored? Set, evaluate,")
    lines.append("then read back:")
    c = build(3, 5.0, 1.0)
    c.evaluate(25.0)
    k = c.getKey(1)
    lines.append("  wrote slope 5.0 accel 1.0 -> after evaluate reads"
                 " lslope=%r rslope=%r la=%r ra=%r" % (k.lslope, k.rslope,
                                                       k.la, k.ra))
    lines.append("  Values that survive are ignored by the evaluator, not")
    lines.append("  recomputed by it. Those are different bugs to work around")
    lines.append("  and only the second could be beaten by writing later.")
    lines.append("")

    return "\n".join(lines)


@case("116_can_type_5_hold_an_ae_ease")
def _():
    """Case 115 found interpolationType 5 is a user-tangent mode: lslope,
    rslope, la and ra all drive the curve under it, where the cubic types
    recompute the slope out from under whatever was written.

    That reopens the question this whole probe started on. If type 5 is
    parameterised the way After Effects parameterises an ease, then an AE ease
    crosses into Nuke as three keys instead of as a bake on every frame.

    The target is measured, not modelled: it is the normalised progress one
    vertex of `eased_static` actually travelled, out of a real AE export whose
    layer does not move. The stored parameters are influence 0.33333 out of the
    first key and 0.91176 into the second, both speeds 0.
    """
    us, ease_out, ease_in = target_curve()

    def build(rslope, ra, lslope, la):
        c = curve()
        c.removeAllKeys()
        c.addKey(A, 0.0)
        c.addKey(B, 1.0)
        k0, k1 = c.getKey(0), c.getKey(1)
        k0.interpolationType = k1.interpolationType = 5
        k0.rslope, k0.ra = rslope, ra
        k1.lslope, k1.la = lslope, la
        return c

    def worst(*args):
        got = sample(build(*args), 12)
        return max(abs(g - u) for g, u in zip(got, us))

    lines = ["Target, from test/golden/ae_static_ease.rbj:", ""]
    lines.append(row("AE rendered", us))
    lines.append("")
    lines.append("The obvious reading: accel IS influence, slope IS speed, and")
    lines.append("both speeds here are 0.")
    lines.append(row("ra=%.5f la=%.5f" % (ease_out, ease_in),
                     sample(build(0.0, ease_out, 0.0, ease_in), 12)))
    lines.append("  worst |Nuke - AE| = %.5f" % worst(0.0, ease_out, 0.0,
                                                      ease_in))
    lines.append("")
    lines.append("Swapped, in case la/ra are the other way round:")
    lines.append(row("ra=%.5f la=%.5f" % (ease_in, ease_out),
                     sample(build(0.0, ease_in, 0.0, ease_out), 12)))
    lines.append("  worst |Nuke - AE| = %.5f" % worst(0.0, ease_in, 0.0,
                                                      ease_out))
    lines.append("")
    lines.append("And the same influences read as a fraction of the interval")
    lines.append("in frames rather than as a unit fraction:")
    n = B - A
    lines.append("  ra=%.4f la=%.4f -> worst %.5f"
                 % (ease_out * n, ease_in * n,
                    worst(0.0, ease_out * n, 0.0, ease_in * n)))
    lines.append("")

    best = None
    lo, hi = 0.0, 2.0
    for _pass in range(7):
        step = (hi - lo) / 10.0
        grid = [lo + step * i for i in range(11)]
        for ra in grid:
            for la in grid:
                w = worst(0.0, ra, 0.0, la)
                if best is None or w < best[0]:
                    best = (w, ra, la)
        lo = max(0.0, min(best[1], best[2]) - step)
        hi = max(best[1], best[2]) + step
    lines.append("Best fit with both slopes held at 0, searching ra and la:")
    lines.append("  ra=%.5f la=%.5f  worst %.5f" % (best[1], best[2], best[0]))
    lines.append(row("best fit", sample(build(0.0, best[1], 0.0, best[2]), 12)))
    lines.append("  ratios against the stored influences: %.4f and %.4f"
                 % (best[1] / ease_out, best[2] / ease_in))
    lines.append("")
    lines.append("A worst near 0 means an AE ease crosses into Nuke as three")
    lines.append("keys rather than as the 22 corrective keys the drift pass")
    lines.append("currently needs, and `to_nuke` should write type 5.")
    return "\n".join(lines)


@case("117_are_endpoint_tangents_honoured")
def _():
    """Case 116 found a two-key curve collapses to the chord under type 5 too,
    but case 115 measured type 5's effect on the *middle* key of a three-key
    curve. A two-key curve has no interior key, so the two results are not in
    conflict: Nuke may honour an authored tangent only where it has no
    neighbouring segment to derive one from.

    That distinction decides the crossing. An After Effects ease lives on the
    two endpoints of a segment, so if only interior keys are honoured, the
    first and last segment of every shape lose their ease whatever `to_nuke`
    writes.

    Three keys at frames 0, 12 and 24. Everything is measured on the FIRST
    segment, whose start is an endpoint and whose end is interior.
    """
    def build(rslope0, ra0, lslope1, la1, interp=5):
        c = curve()
        c.removeAllKeys()
        for t, v in ((A, 0.0), (B, 1.0), (24.0, 2.0)):
            c.addKey(t, v)
        for i in range(3):
            c.getKey(i).interpolationType = interp
        k0, k1 = c.getKey(0), c.getKey(1)
        k0.rslope, k0.ra = rslope0, ra0
        k1.lslope, k1.la = lslope1, la1
        return c

    lines = ["Three keys, 0@f0 1@f12 2@f24. The first segment only.", ""]
    base = sample(build(0.0, 0.0, 0.0, 0.0), 12)
    lines.append(row("all tangents 0", base))
    lines.append("")
    lines.append("Move the ENDPOINT (key 0, outgoing) alone:")
    for rs, ra in ((5.0, 0.0), (0.0, 1.0), (5.0, 1.0), (-5.0, 1.0)):
        got = sample(build(rs, ra, 0.0, 0.0), 12)
        lines.append(row("rslope=%.1f ra=%.1f" % (rs, ra), got))
        lines.append("      %s" % ("MOVES" if max(abs(a - b) for a, b in
                                                  zip(got, base)) > 1e-6
                                   else "no effect"))
    lines.append("")
    lines.append("Move the INTERIOR key (key 1, incoming) alone:")
    for ls, la in ((5.0, 0.0), (0.0, 1.0), (5.0, 1.0), (-5.0, 1.0)):
        got = sample(build(0.0, 0.0, ls, la), 12)
        lines.append(row("lslope=%.1f la=%.1f" % (ls, la), got))
        lines.append("      %s" % ("MOVES" if max(abs(a - b) for a, b in
                                                  zip(got, base)) > 1e-6
                                   else "no effect"))
    lines.append("")

    us, ease_out, ease_in = target_curve()
    lines.append("Against the real AE curve. Only the first segment is fitted,")
    lines.append("so key 2 is out of the way at a constant slope.")
    lines.append(row("AE rendered", us))

    def worst(rs, ra, ls, la):
        got = sample(build(rs, ra, ls, la), 12)
        return max(abs(g - u) for g, u in zip(got, us))

    lines.append("  stored influences read straight in: worst %.5f"
                 % worst(0.0, ease_out, 0.0, ease_in))
    best = None
    lo, hi = -2.0, 2.0
    for _pass in range(6):
        step = (hi - lo) / 8.0
        grid = [lo + step * i for i in range(9)]
        for ra in grid:
            for la in grid:
                for sl in (0.0,):
                    w = worst(sl, ra, sl, la)
                    if best is None or w < best[0]:
                        best = (w, ra, la)
        lo, hi = min(best[1], best[2]) - step, max(best[1], best[2]) + step
    lines.append("  best fit over ra, la with slopes 0: ra=%.5f la=%.5f"
                 " worst %.5f" % (best[1], best[2], best[0]))
    lines.append(row("best fit", sample(build(0.0, best[1], 0.0, best[2]), 12)))
    return "\n".join(lines)


OUT = out_dir()

print("RotoBridge ease probe -> %s" % OUT)
for name, fn in CASES:
    print("running %s" % name)
    try:
        write("%s.txt" % name, fn())
    except Exception:
        write("%s.FAILED.txt" % name, traceback.format_exc())
        print("  FAILED, traceback written")
print("done")
