# `.rbj` version 1 - format specification

**Status:** FROZEN, 2026-08-20. Frozen from `prd.md` §6 at PRD v4.3, against Phase 0
evidence from Nuke 17.1v1 and After Effects 25.6x101.

**Changing this document** means bumping `version` to 2 and teaching every importer
to reject what it cannot read. Additive, ignorable members are the only change a v1
reader must tolerate (§2.5). §14 lists the four places this spec deliberately departs
from `prd.md` §6 and why.

RotoBridge is a hub format. `.rbj` stores the **union** of what its target
applications can express, not the intersection (`prd.md` §5.1). A field no v1 adapter
writes is still normative.

---

## 1. Scope

One `.rbj` file carries one or more animated closed bezier shapes over a contiguous
frame range, in a single coordinate space, with both a dense per-frame bake and the
sparse authored keyframe structure that produced it.

It does not carry: layer hierarchy, tracking data, transforms (they are baked),
strokes, open splines, or anything about the plate beyond its dimensions.

---

## 2. File conventions

### 2.1 Encoding

UTF-8, no byte-order mark. The file is a single JSON object. Line endings are
insignificant. Pretty-printing is recommended (the format is meant to diff) but not
required.

### 2.2 Numbers

All numeric values are JSON numbers and **must be finite**. `NaN`, `Infinity` and
`-Infinity` are invalid, including the bare literals that some JSON encoders emit by
default. A writer must configure its encoder to fail rather than emit them; Python's
`json.dumps` needs `allow_nan=False`, which is not the default.

Coordinates, tangents, feather and opacity are floating point. Frame numbers are
integers, written as JSON integers in `range` and `keys[].frame`, and as decimal
integer **strings** where they appear as object keys in `frames` (§7.1).

Writers should preserve the full double precision the host gives them. Readers must
not assume any particular formatting, digit count, or presence of a decimal point.

### 2.3 Member order

Insignificant everywhere. Readers must not depend on it.

### 2.4 Required means required

A member marked required must be present, of the stated type, even when its value is
a default. Absent-means-default is used in exactly two places, both marked.

### 2.5 Unknown members

A reader must **ignore** object members it does not recognise rather than fail on
them. This is what lets v1 tolerate additive extensions. A writer must not rely on
the other side preserving them: unknown members are not guaranteed to survive a
round trip through any adapter.

---

## 3. Coordinate space

Canonical space is Nuke's (`prd.md` §5.5):

- Origin **bottom-left** of the source image.
- **Y increases upward.**
- **Pixels**, not normalized. Pixel aspect is recorded but not applied; v1 treats
  pixels as square (`prd.md` §11).
- Tangents are **vertex-relative** offsets, not absolute positions. A point's
  outgoing bezier control handle is at `c + out`; its incoming handle is at `c + in`.

Every adapter converts to and from this on its own side. Nuke needs no conversion.
After Effects converts layer space to comp space through the host, then flips
`y_canonical = comp_height - y_comp` and negates tangent Y (`prd.md` §9.1 step 4).

Coordinates outside the image are legal. Shapes routinely extend past frame.

---

## 4. Frame numbering and time

`.rbj` is frame-based, never time-based. Frame numbers are integers in the **source
application's own numbering** - a Nuke script starting at 1001 writes 1001. An
importer applies its own offset to place them in the destination.

`fps` exists so an adapter whose host works in seconds (After Effects) can convert.
It is not used to reconcile differing rates: importing a 23.976 file into a 24 fps
comp maps frame to frame, not time to time, and the importer should warn.

Conversion between a frame number and a host time in seconds must round rather than
truncate. Host-reported key times are floating point and land just under the exact
value (After Effects reported 8.333333 s for frame 200 at 24 fps), so truncation
silently shifts a key one frame early.

---

## 5. Top-level object

| Member | Type | Required | Notes |
|---|---|---|---|
| `format` | string | yes | Exactly `"rotobridge"`. Any other value is a hard failure. |
| `version` | integer | yes | `1`. A reader must reject a version it does not implement. |
| `source` | object | yes | §5.1 |
| `range` | `[int, int]` | yes | `[first, last]`, **inclusive**, `first <= last`. |
| `shapes` | array | yes | One or more shape objects (§6). An empty array is a hard failure. |
| `warnings` | array of string | yes | May be empty. §13. |

### 5.1 `source`

| Member | Type | Required | Notes |
|---|---|---|---|
| `app` | string | yes | Free text, e.g. `"Nuke"`, `"After Effects"`. |
| `app_version` | string | yes | Free text, e.g. `"17.1v1"`. |
| `width` | integer | yes | Source image width in pixels, `> 0`. |
| `height` | integer | yes | Source image height in pixels, `> 0`. Used by the AE flip. |
| `pixel_aspect` | number | yes | Recorded, not applied in v1. |
| `fps` | number | yes | `> 0`. See §4. |

`source` is provenance. An importer may warn on a resolution mismatch with its
destination (`prd.md` §11) but must not refuse to import or rescale.

---

## 6. Shape object

| Member | Type | Required | Notes |
|---|---|---|---|
| `name` | string | yes | Need not be unique; importers disambiguate. |
| `closed` | boolean | yes | v1 requires `true`. `false` is a hard failure (§12). |
| `blend` | string | yes | `union` \| `difference` \| `intersection`. |
| `feather_model` | string | yes | `per_point` \| `none`. Describes the **per-point layer only**. §11. |
| `feather_falloff` | string | yes | `linear` \| `smooth`. Static; neither host can keyframe it. |
| `frames` | object | yes | The dense layer. §7. |
| `keys` | array | no | The sparse layer. Absent means dense import. §9. |

Everything that animates lives in `frames`. The shape object holds only what both
hosts model as static.

**Opacity is not here.** It is per frame, in `frames` (§7.2). Both hosts animate it -
After Effects `maskOpacity` is a `Property`, Nuke `opc` is an `AnimAttributes` curve -
and reading it once per shape freezes it at the first frame. This is the same defect
Phase 0 case 62 found in uniform feather; it applies unchanged to opacity.

---

## 7. `frames` - the dense layer

`frames` is ground truth (`prd.md` §5.4). It is the shape evaluated through the
source application's own interpolation, so it is correct no matter how exotic the
source curves are. Every fidelity guarantee in the project rests on it, and mode
switching (`prd.md` §8) works only because it is always present.

### 7.1 Keys of `frames`

Object keys are decimal integer strings: no zero padding, no leading `+`, no
decimal point, `-` only for negative frames. Frame 1001 is `"1001"`.

`frames` must contain **exactly** one entry per frame in `range`, inclusive, with no
gaps and no extras. A missing or extra frame is a hard failure.

### 7.2 Frame record

| Member | Type | Required | Notes |
|---|---|---|---|
| `points` | array | yes | Ordered point objects (§8). Order defines the spline. |
| `opacity` | number | yes | `0.0` to `1.0`. |
| `feather_uniform` | `[x, y]` | yes | Pixels, 2-D, independent axes. §11.2. |

All three are required on every frame. The dense layer is deliberately complete and
verbose; that is what it is for. Compression is the answer to its size, not
omission (`prd.md` §15 Q4).

### 7.3 Vertex count

`len(points)` must be **identical on every frame** of a shape. Differing counts are a
hard failure naming the shape and the frames where the count changes (`prd.md` §11).
After Effects permits variable vertex counts; Nuke does not, and there is no
correct interpolation between two different counts.

Different shapes in one file may have different counts.

---

## 8. Point object

| Member | Type | Required | Notes |
|---|---|---|---|
| `c` | `[x, y]` | yes | Vertex position, canonical space. |
| `in` | `[x, y]` | yes | Incoming tangent, **vertex-relative**. `[0, 0]` for a corner. |
| `out` | `[x, y]` | yes | Outgoing tangent, vertex-relative. |
| `feather` | number | conditional | Required iff `feather_model` is `per_point`; absent otherwise. §11.1. |
| `feather_offset` | `[x, y]` | no | Nuke only. Never present without `feather`. §11.1. |

`in` and `out` are independent: a broken tangent is `in != -out`, which both hosts
support and v1 preserves.

---

## 9. `keys` - the sparse layer

`keys` is the artist's authored keyframe structure - the work product (`prd.md`
§5.4). It is optional. **Absent `keys` means dense import**: the importer treats
every frame in `range` as a key.

A key object:

| Member | Type | Required | Notes |
|---|---|---|---|
| `frame` | integer | yes | Must exist in `frames`. Otherwise a hard failure. |
| `interp` | object | yes | `{"in": ..., "out": ...}`. §10. |
| `ease` | object | no | `{"in": [...], "out": [...]}`, sides present only as §10.3 allows. |

`keys` must be sorted ascending by `frame`, with no duplicates.

For a Nuke source, `keys` is the **union** of key times across every control point of
the shape, plus the shape transform's key times when the transform is animated - a
static shape under an animated transform is keyed animation (`prd.md` §9.2 step 5).

---

## 10. Interpolation semantics

Both applications model a keyframe as a **two-sided bezier handle that can be
broken** (`prd.md` §15 Q9). `.rbj` matches that: every key carries an independent
value for each side.

### 10.1 `interp`

An object with both `in` and `out` **always present**, each one of:

- `hold` - constant, no interpolation
- `linear` - straight
- `ease` - smooth, parameters in `ease` if known

There is no string shorthand. A single form means no reader ever branches on the
type of `interp`.

`out` describes the handle **leaving** this key. `in` describes the handle
**arriving** at it. On the first key `in` is meaningless and on the last key `out`
is meaningless; writers put `linear` there and readers ignore it.

### 10.2 Interval rule

The segment between consecutive keys A and B is governed **jointly** by `A.interp.out`
and `B.interp.in`, since each is one side of a breakable handle.

One exception: **`hold` on the outgoing side dominates.** When `A.interp.out` is
`hold` the segment is flat and `B.interp.in` is ignored for that segment. This
matches both hosts. An After Effects hold keyframe freezes the segment leaving it,
and Nuke's step interpolation was measured as outgoing-only (case 63: setting step
moved eval(75) to 1.0 while leaving eval(25) at the cubic default).

`hold` on the incoming side is legal and means the arriving handle is flat. It does
not freeze the preceding segment; only `A.interp.out` can do that.

### 10.3 `ease`

Optional, keyed by side: `{"in": [influence, speed], "out": [influence, speed]}`.

A side has an entry **only** if its `interp` is `ease`. Sides that are `hold` or
`linear` have no entry, and `ease` is omitted entirely when neither side is `ease`.

- `influence` - handle length as a fraction, `0.0` to `1.0`. After Effects reports
  this as a percentage; divide by 100. Its default is 16.667%, so `0.16667`.
- `speed` - handle direction, as rate of change of shape progress per second. After
  Effects reports it directly as the ease `.speed`; measured values on mask paths
  were `0` and `1`.

Both are **shape-wide**, matching After Effects, which carries one ease per key for
the whole `maskPath` rather than per point.

**A side may be `ease` with no matching `ease` entry.** This means "smooth,
parameters unknown, rely on the drift pass". It is how tier 2 (`prd.md` §7) reports
a Nuke shape whose points ease differently from each other, which has no After
Effects representation. Readers must handle it; applying the host's default smooth
ease is correct, because positional truth comes from `frames`, not from the fit.

### 10.4 What an importer owes the sparse layer

Setting keys is not enough. After they are set, the importer evaluates the
destination's actual interpolation at every intermediate frame against `frames` and
inserts corrective keys wherever any point drifts beyond tolerance (`prd.md` §5.4,
§8). Authored keys always survive verbatim; corrective keys appear only where the
mismatch is real.

---

## 11. Feather

The two feather mechanisms are **independent layers that compose**, not alternatives.
Phase 0 measured both on one shape simultaneously on both sides (Nuke case 62: a
`featherCenter` of `(12, 7)` alongside `fx`/`fy` of 20/5; AE run 6: two feather
points alongside `maskFeather [10, 10]`). A file carries whichever are present, and
`feather_model` governs only the per-point layer.

### 11.1 Per-point feather

`feather_model`:

- `per_point` - the shape has authored per-point feather. **Every** point on **every**
  frame carries `feather`, including points whose value is `0.0`. A zero is an
  authored point that pins feather to zero width; dropping it changes the shape
  (measured, probe run 3).
- `none` - no per-point feather anywhere in the shape. No point carries `feather`.

`feather` is a **signed** float: distance along the outward path normal, positive
outward, negative inward. The sign is load-bearing everywhere. Taking a magnitude at
any point in a pipeline silently flips inward feather to outward.

This is After Effects' `featherRadii` **verbatim**, with no conversion at the AE
adapter. Run 3 read `[89.5565, 0, -46.6171, -1e-8]` against `featherTypes [0, 0, 1, 1]`:
type 0 came back non-negative, type 1 non-positive, so the signed radius already
carries the direction and `featherTypes` is redundant on read. It is also the shape
of Mocha Pro's `edge_width`.

`feather_offset` is an optional 2-D vector in canonical space, carrying the full
feather offset including any **tangential** component that the signed scalar cannot
express. Only Nuke has a genuine vector feather (a second bezier curve with its own
tangents), so only Nuke writes it, and a Nuke importer that finds it uses it in place
of `feather`, making Nuke to Nuke lossless. Every other adapter ignores it. It is
never present without `feather`, so an adapter that ignores it is never left with
nothing.

### 11.2 Uniform feather

`feather_uniform` is `[x, y]` in pixels, per shape **per frame**, in the dense layer.

It is 2-D with genuinely independent axes on both sides, so the mapping is 1:1 and
lossless in both directions: After Effects `maskFeather` maps to Nuke `fx`/`fy`
directly. There is no collapse to a mean and no anisotropy warning.

It is per frame because it **animates** on both sides. Nuke case 62 keyed `fx` 5 to
40 and read 22.14 at the midpoint; AE run 6 keyed `maskFeather` `[10,10]` to
`[80,80]` and read `[45,45]`. Reading it once per shape freezes it at the first
frame.

`[0.0, 0.0]` means no uniform feather. It is written on every frame regardless of
`feather_model`, because the two layers are independent.

`feather_falloff` is `linear` or `smooth`, static per shape: After Effects
`maskFeatherFalloff` (an *attribute*, not a `Property`, so it genuinely cannot be
keyframed) and Nuke `ff`.

---

## 12. Validation

### 12.1 Hard failures

Abort, name the offending shape, write or import nothing. Partial output is worse
than no output, because it looks correct until it is composited (`prd.md` §11).

- `format` is not `"rotobridge"`.
- `version` is absent, not an integer, or newer than the reader implements.
- Any required member absent or of the wrong type.
- A non-finite number anywhere.
- `range` is not two integers with `first <= last`.
- `shapes` is empty.
- `frames` does not cover `range` exactly: a gap, an extra frame, or a key that is
  not a plain decimal integer string.
- Vertex count differs across frames within one shape. Report the frames where it
  changes.
- `closed` is `false` (open splines are out of scope for v1).
- `blend`, `feather_model` or `feather_falloff` outside its enum.
- A `keys` entry whose `frame` is not in `frames`.
- `keys` not sorted ascending, or containing duplicate frames.
- `interp` missing `in` or `out`, or either outside the enum.
- An `ease` entry on a side whose `interp` is not `ease`.
- `feather` present on a point when `feather_model` is `none`, or absent when it is
  `per_point`.
- `feather_offset` present on a point without `feather`.

### 12.2 Soft failures

Warn, continue, append to `warnings`. These are the conversions the format cannot
make losslessly (`prd.md` §11):

- Unmappable blend mode, degraded to `union`.
- A Nuke feather offset with a tangential component, when the destination is not
  Nuke: the normal component only survives.
- An After Effects feather point placed mid-segment, snapped to the nearer vertex.
- Two After Effects feather points snapping to the same vertex: the one with the
  larger `|feather|` is kept, the other dropped. A `feather` of exactly `0.0`
  competes on equal terms; it is not treated as absent.
- Divergent per-point interpolation, reported as `ease` without parameters.
- Inverted flag, dropped.
- Paint strokes and nested layers, skipped.
- Non-square pixel aspect, treated as square.
- Resolution or frame-rate mismatch between `source` and the destination.

---

## 13. `warnings`

An array of human-readable strings, always present, possibly empty. An exporter
records every lossy conversion it made; an importer appends its own to the report it
shows the artist. This makes a `.rbj` carry its own provenance: a shape that looks
wrong can be diagnosed from the file alone, without either application
(`prd.md` §5.1).

Strings are for humans. Nothing parses them.

---

## 14. Departures from `prd.md` §6

Four, all resolved during this freeze because §6 left them ambiguous or
self-contradictory. `prd.md` v4.4 carries the same resolutions.

1. **`opacity` moved into the dense layer.** §6 showed it as a static shape member.
   Both hosts animate opacity, so a static field freezes it at the first frame -
   exactly the defect case 62 found in uniform feather and Q8 corrected there. There
   is no static shape-level `opacity`: one location, no shadowing.

2. **`feather_model` lost its `uniform` value.** §6 listed
   `per_point | uniform | none`, from the era when the two feather layers were
   thought exclusive. Case 62 proved them independent and §11 already says the models
   "are not exclusive", which leaves `uniform` meaning nothing that
   `feather_uniform != [0,0]` does not already say. Two members encoding one fact can
   disagree, and this format has no tiebreak rule. Removed.

3. **`ease`'s second element is named `speed`, not `value_offset`.** Same position,
   same meaning, and it is what both the After Effects API and the Phase 0 probe
   output call the value. `value_offset` described nothing measurable.

4. **`feather` is conditional rather than universal.** §6 said every adapter reads
   and writes it. Under `feather_model: "none"` there is nothing to write, and
   writing `0.0` on every point of every frame would be indistinguishable from an
   authored all-zero shape, which §11.1 says is a real distinction.

---

## 15. Not in v1

Named so that their absence is a decision rather than an oversight:

- **Open splines.** Hard failure today (`prd.md` §12 Phase 6).
- **Mask expansion.** After Effects `maskExpansion` is present and animatable, and
  Phase 0 flagged it as the same class of silent per-mask drop as uniform feather.
  v1 drops it and warns.
- **Inverted flag.** Dropped with a warning; Nuke has no direct equivalent.
- **Layer hierarchy.** Flattened to a single shape list, with a warning.
- **Tracking and transform data.** Transforms are baked into the points.
- **Pixel aspect.** Recorded in `source`, never applied.
- **Compression.** v1 is uncompressed. Gzip is the likely v2 answer to dense-layer
  size (`prd.md` §15 Q4), and it changes the container, not this schema.

---

## 16. Complete example

Two frames of a one-point shape, elided for length. A real file has every frame in
`range` and every point of each.

```json
{
  "format": "rotobridge",
  "version": 1,
  "source": {
    "app": "Nuke",
    "app_version": "17.1v1",
    "width": 2048,
    "height": 858,
    "pixel_aspect": 1.0,
    "fps": 23.976
  },
  "range": [1001, 1002],
  "shapes": [
    {
      "name": "arm_L",
      "closed": true,
      "blend": "union",
      "feather_model": "per_point",
      "feather_falloff": "smooth",
      "keys": [
        {"frame": 1001, "interp": {"in": "linear", "out": "ease"},
         "ease": {"out": [0.33, 0.0]}},
        {"frame": 1002, "interp": {"in": "ease", "out": "linear"},
         "ease": {"in": [0.91176, 0.0]}}
      ],
      "frames": {
        "1001": {
          "opacity": 1.0,
          "feather_uniform": [20.0, 5.0],
          "points": [
            {
              "c": [1024.0, 429.0],
              "in": [-12.5, 3.0],
              "out": [12.5, -3.0],
              "feather": 2.5,
              "feather_offset": [2.4, 0.7]
            }
          ]
        },
        "1002": {
          "opacity": 1.0,
          "feather_uniform": [20.0, 5.0],
          "points": [
            {
              "c": [1026.75, 430.125],
              "in": [-12.5, 3.0],
              "out": [12.5, -3.0],
              "feather": 2.5,
              "feather_offset": [2.4, 0.7]
            }
          ]
        }
      }
    }
  ],
  "warnings": ["Shape 'hair' had inverted flag; dropped."]
}
```

The `keys` layer here says: leave frame 1001 on an eased handle, arrive at 1002 on an
eased handle. Both sides carry parameters because both are `ease`. The first key's
`in` and the last key's `out` are the ignored placeholders of §10.1.
