# `.rbj` version 2 - open splines and feather anchors (DRAFT)

**Status: DRAFT, and the reason it is one changed on 2026-08-21.** It now holds
two deltas against `spec/rbj-v1.md` with opposite justifications:

- **Open splines** (§3-§5) are implemented, tested, and have **no demonstrated
  use**. They carry geometry correctly and cannot render anywhere the format
  reaches. Decided a permanent draft by the user, 2026-08-21.
- **Feather anchors** (§6) are the reverse: a **measured defect with no other
  available fix**, and **nothing is implemented**. An After Effects mask with
  feather points mid-segment has them destroyed at the source adapter today, in
  the direction that matters most.

So v2 is no longer a document with nothing to be for. The second half is a
reason to finish it and the first half is not, and neither cancels the other.
`spec/rbj-v1.md` is unchanged and stays **FROZEN**, and it is the format. This
is a delta against it and nothing here weakens a v1 file.

**Why the open-spline half stays a draft rather than being deleted or
finished.** Open splines do
not produce a matte anywhere `.rbj` can reach: After Effects renders no alpha
from an open mask path at all, and Nuke renders a stroke whose width and end
caps are node knobs this format has no member for, so even a Nuke-to-Nuke
crossing arrives at the defaults (width 10.0, `rounded` caps). In roto practice,
across applications, open splines are not used for matting - they are strokes,
guides and paths-as-data. So the feature carries **geometry** correctly and
cannot make it render correctly, which is not enough to justify a version number.

Deleting it would be equally wrong: the code exists, is tested, is honest about
what it drops, and costs the v1 paths nothing (a writer emits `version: 1`
unless a shape is actually open, §2). If a Silhouette or Mocha adapter ever
turns up a real use, this is ready. Until then no file should be written with
`version: 2` on purpose.

**Scope:** two changes - open splines (`prd.md` §12 Phase 6) and feather anchors
(§6). The other three Phase 6 extras (inverted flag, mask expansion, richer ease
fitting) are **not** in this draft. They are named here only so their absence is
a decision: the inverted flag is an additive member that a v1 reader would
silently ignore, which is the exact failure mode `prd.md` §11 exists to prevent,
and richer ease fitting is blocked on a measurement nobody has taken
(`HANDOFF.md`, Phase 5).

Read §1-§16 of `spec/rbj-v1.md` first. Everything not named below is unchanged.

---

## 1. Why a whole version number for one boolean

*(Written when `closed` was the only delta. §6 has since added a second, which
makes the bump easier to justify rather than changing the argument.)*

v1 §5 types `version` as an **integer**, so `1.1` is not a value this format has. A
reader that meets `1.1` rejects it as "not an integer", which is loud but misleading.
So the bump is to `2`.

The bump buys honesty, not safety. Both are already loud: a v1 reader that meets
`closed: false` at `version: 1` rejects it by v1 §12.1 with the right message, and one
that meets `version: 2` rejects it by v1 §12.1 with a different right message. What
`2` adds is that the file describes itself - a v2 reader can know it may see an open
shape without inspecting every shape to find out.

## 2. `version` is per file, not per adapter

> **v1 §5, `version`:** `1`. A reader must reject a version it does not implement.
>
> **v2:** `1` or `2`. A writer emits the **lowest** version that can express the
> file it is writing: `2` when any shape has `closed: false` or
> `feather_model: anchored` (§6.2), `1` otherwise. A reader must reject a
> version it does not implement.

An exporter does not stamp `2` on its output because it is a v2 exporter. It stamps
`2` because the file needs it. Every file that would have been written before this
draft is still written byte-identically, still says `version: 1`, and still opens in
a v1 reader - which is what makes this draft cheap to abandon.

`core.rbj.version_for(shapes)` is the one implementation of that rule, mirrored in
`RB.rbj.versionFor`. Two writers deciding it independently is how they drift apart.
Both currently know only the `closed` clause; the `anchored` clause goes in the
same two functions and nowhere else.

## 3. `closed` is a boolean again

> **v1 §6, `closed`:** boolean, required. v1 requires `true`. `false` is a hard
> failure (§12).
>
> **v2:** boolean, required. `false` means the path is an open polyline: it runs
> from point 0 to point *n*-1 and there is no segment from *n*-1 back to 0.
> `false` requires `version: 2`.

> **v1 §12.1, hard failures:** `closed` is `false` (open splines are out of scope
> for v1).
>
> **v2:** `closed` is not a boolean. Or `closed` is `false` in a file declaring
> `version: 1`.

The second clause is what keeps the freeze meaningful: v1 forbids open splines, and a
file claiming to be v1 is held to that whatever wrote it.

A shape with fewer than two points cannot be open in any useful sense, but v1 already
has no minimum vertex count and this draft does not add one.

## 4. Feather on an open spline

*This section is about the feather **sign** on a path with no inside. §6 is
about where a feather value is **anchored**. They are independent: an `anchored`
open spline takes its normal direction from here and its anchor from there.*

v1 §11.1 defines `feather` as the signed distance along the **outward** path normal.
An open polyline has no inside, so "outward" needs saying:

1. The path direction at an interior vertex is the chord between its neighbours, as
   in v1. At an **endpoint** there is no such chord, so the direction is the chord to
   its single neighbour. That is the limit of the interior rule, not a new one.
2. The global sign is **fixed**: a consistent quarter turn from the direction of
   travel, not taken from an area. A closed shape uses its signed area so that
   "outward" comes out the same whichever way the artist drew it. An open path has
   no inside for that to be about, and the area of a path closed implicitly is near
   zero for a near-straight polyline, where the sign flips on a perturbation - which
   on a moving shape would flip the feather direction from one frame to the next.
   That is a wrong matte rather than a wrong convention, so the rule that cannot do
   it wins. The cost is that the side follows point order.

Point 2 is **unverified against After Effects**, and is the same class of open
question as `ff` (`HANDOFF.md`): a consistent rule run in both directions round-trips
exactly within one host and is only exposed by a file that crosses between two. It
should be measured in Phase 5 rather than guessed at again here.

Nuke's `feather_offset` (v1 §11.1) is a vector in canonical space and needs no normal
at all, so a Nuke-to-Nuke open spline with per-point feather is lossless regardless of
how point 2 settles.

## 5. What an open spline still does not carry

Both hosts render an open path through settings this format has no member for, and
none of them are per shape:

- **Nuke** renders an open spline as a stroke. Its width and end caps are **node**
  knobs - `openspline_width`, `openspline_start_end_type`, `openspline_last_end_type`,
  `toolbar_openspline_falloff`, `toolbar_openspline_render_hull` (probe
  `q10/93_node_knobs.txt`). Probe `phase2/72_shape_attributes.txt` enumerates the
  per-shape attributes and none of them is any of these.
- **After Effects** cannot matte an open path **at all**. A mask whose path is
  open produces **no alpha**. Open paths exist in AE - on shape layers, for
  strokes, trim paths and paths-as-data - but masking is not one of their uses.
  Reported by the user 2026-08-21, after `setup_ae_scene.jsx` authored one.

  This is not the "unmeasured" earlier drafts of this section recorded. It is
  measured, and the answer is that the After Effects side of an open spline is a
  **data** round trip and never a rendered one. Note the API does not object:
  `maskPath.closed = false` is stored, read back as `false` and exported as
  `closed: false`, which is why `test/golden/ae_scene.rbj` says so and stamps
  `version: 2` honestly. The document is right; the matte is empty.

So a v2 exporter warns that the render settings were not carried, and a v2
importer into After Effects warns that the mask will produce nothing. Both are
soft failures (v1 §12.2, extended):

> - An open spline's host render settings, not carried. Warned once per shape.
> - An open spline imported into an application that cannot matte one. Warned
>   once per shape, **regardless of `source.app`**: After Effects produces no
>   alpha from an open mask path whoever wrote the file, itself included.

The document-level round trip is exact in both hosts. The **rendered** one is
exact in Nuke and does not exist in After Effects.

**This is deliberately not a hard failure.** The geometry is real, it mattes in
Nuke, and an artist may want it in an AE comp to move onto a shape layer or to
drive a stroke. Refusing it would destroy data to prevent a surprise a warning
covers, and closing it would invent a segment the artist never drew.

## 6. Feather anchors

**Why this one is not like open splines.** Open splines are in this draft
because the code existed and had nowhere else to live. Feather anchors are here
because a measured defect has no other available fix, and because the loss
happens in the After Effects to Nuke direction, which is the one the product
exists to serve.

### 6.1 What v1 cannot say

v1 §8 hangs `feather` on a **point**, and v1 §11.1 defines it as a signed
distance along the normal at that vertex. That is Nuke's model exactly, and it
is wrong for every other application measured so far:

- After Effects anchors a feather point **anywhere along a segment**, at
  `(featherSegLocs, featherRelSegLocs)`, with a signed `featherRadii`
  (`prd.md` §15, run 3).
- The count is not one per vertex. Run 3 read **four** feather points on a
  **seven**-vertex shape, three of them mid-segment, and **two of them on the
  same segment**. That last one is decisive: no per-point member can hold two
  values for one point, so this is not a field that can be widened.

The v1 After Effects exporter therefore calls `geom.snapFeatherPoints` per
frame and moves each anchor to the nearer vertex before writing anything. The
anchor is destroyed at the **source** adapter, so no importer change can
recover it and no v1 file can be inspected for it.

Measured cost on the golden scene's `feathered`, a 300 px square with anchors
at `seg + rel` of `[0.25, 0.75, 2.5, 3.0]` and radii `[30, -15, 12, 0]`: the
radius-12 anchor travels **150 px** along the path to reach vertex 3, and lands
on the artist's authored radius-**0** point, which is discarded. A corner
deliberately pinned to zero feather width arrives 12 px soft. Geometry
bit-perfect, softness visibly wrong.

### 6.2 `feather_model` gains a third value

> **v1 §11.1, `feather_model`:** `per_point` | `none`.
>
> **v2:** `per_point` | `anchored` | `none`. `anchored` means the per-point
> feather layer is carried in the shape's own per-frame `feather_points` list
> (§6.3), and **no point carries `feather`**. `anchored` requires `version: 2`.

The three are exclusive, not layered. `per_point` stays exactly what v1 froze -
one value per vertex, optional `feather_offset`, which is Nuke's model - and a
v1 file is read and written unchanged.

Uniform feather (v1 §11.2) is an independent layer and this section does not
touch it. `feather_falloff` likewise stays per shape and static.

### 6.3 The `feather_points` list

A member of the **frame** object (v1 §7), required iff `feather_model` is
`anchored` and forbidden otherwise. Each entry:

| Member | Type | Required | Notes |
|---|---|---|---|
| `t` | number | yes | Anchor position in **segment units** along the path. §6.4. |
| `feather` | number | yes | Signed distance along the outward normal at `t`. v1 §11.1's sign convention, unchanged. |
| `feather_offset` | `[x, y]` | no | As v1 §8, and still Nuke-only. Never present without `feather`. |

`len(feather_points)` must be **identical on every frame** of a shape, for the
reason v1 §7.3 gives about vertices: there is no correct interpolation between
two different counts. Zero is a legal count, but a shape with no feather points
is `feather_model: none` and should say so, which is §2's rule applied to
feather.

Entries are ordered by `t` **ascending** on every frame. A radius of exactly
`0.0` is an authored anchor that pins feather to zero width, never an absent
one - v1 §11.1's rule, and the golden scene depends on it.

### 6.4 `t`, and what it inherits from a measurement

`t` is a single number rather than the `(segment, fraction)` pair the host
reports. `t = segment + fraction`: the integer part names the segment, the
fractional part is the position within it. So `2.5` is the midpoint of the
segment leaving vertex 2, and `3.0` is vertex 3 itself.

**One number rather than two, because the pair is not stable.** After Effects
renames anchors on **every** read - a point written at `(segment i, 0)` comes
back at `(segment i-1, 1)` - and **regroups the arrays by feather type** when
the value is read between keyframes rather than on one (`HANDOFF.md`, "Two
probes, and the answer needed both"). Both transformations preserve `seg + rel`.
The format stores that invariant and leaves each adapter to spell it however its
host does. `ae/rotobridge_import.jsx` already compares feather this way, so this
is a rule with a working implementation behind it rather than a new idea.

Range: `0 <= t < len(points)` on a closed shape, and `0 <= t <= len(points) - 1`
on an open one, which has one fewer segment. On a closed shape the upper bound
names the same anchor as `t = 0` and must be written as `0`.

**The fractional part is the bezier parameter, and that is a decision taken
without the measurement.** De Casteljau, which is what makes §6.5 exact, splits
at the parameter. Whether After Effects' `featherRelSegLocs` is that parameter
or an **arc-length fraction** has never been measured, and on a segment with
asymmetric tangents the two are far apart. The format picks the parameter
because that is the definition the rest of the geometry is written against; if
the host turns out to mean arc length, that is an **After Effects adapter
conversion** in both directions and not a change here. The conversion is a
numeric root-find with no closed form, so it is not free.

Reading the value back cannot settle it, because After Effects returns what was
written. It needs a rendered comparison, which puts it with Phase 5 and `ff`.
**Until it is measured, an anchored After Effects file is not known to be
exact** - only known to be better than the snap.

### 6.5 Into a host that can only anchor at a vertex

Nuke anchors feather at a vertex and nowhere else (`prd.md` §9.3). For each
anchor whose `t` is not an integer, a v2 importer into Nuke:

1. Splits the bezier segment at the fractional part of `t` with **de
   Casteljau**, and inserts the resulting vertex. Subdivision reproduces the
   original curve exactly, so the geometry does not move: the shape gains a
   vertex and changes nothing about where it is.
2. Anchors the feather on the new vertex, carrying `feather` and any
   `feather_offset` unchanged.
3. Warns once per shape, naming how many vertices were inserted. The compositor
   sees more vertices than the artist authored and should be told why rather
   than left to work it out.

That is the whole point of the section: the anchor arrives **exact** instead of
snapped, and the price is vertices rather than accuracy.

**An anchor that moves frame to frame costs keys, not accuracy.** The split is
exact at whatever parameter it is given, so the dense layer stays exact frame by
frame and the vertex count stays constant, which is what v1 §7.3 actually
requires. What degrades is the **sparse** layer: the destination interpolates
the inserted vertex as a vertex, in a straight line between authored keys, while
the truth is a point sliding along a curve. That is ordinary drift, and the
drift pass already measures and corrects it.

**The one case that breaks, and it is narrow.** An anchor that slides *past* an
original vertex changes its ordinal position around the ring, so the inserted
vertex would have to change index in `points` partway through the shape. That is
a topology change, forbidden for the reason v1 §7.3 forbids a changing vertex
count. It is visible in the file, because §6.3 orders entries by `t`: two
entries cross and their `feather` values jump between frames. A writer that can
see it warns; a reader that meets it warns and snaps that one anchor, which is
v1 behaviour and no worse than today.

### 6.6 Out of a host that can only anchor at a vertex

Unchanged from v1. A Nuke export writes `feather_model: per_point` and
`version: 1`, because vertex-anchored feather with a free 2-D offset is exactly
what v1 expresses and `anchored` would express it less well - `feather_offset`
is a vector in canonical space and needs no anchor parameter at all. Nothing in
this section makes a Nuke file a v2 file.

### 6.7 What an After Effects export writes

§2's rule decides it, and the answer is not "always v2":

- **Every anchor already sits on a vertex**, `t` integral with no two sharing
  one: the snap is a no-op, `per_point` says everything there is to say, and
  the file is written `version: 1` byte-identically to today.
- **Any anchor is mid-segment, or two share a vertex**: only `anchored` can
  express it, so `feather_model: anchored` and `version: 2`.

The compatibility cost is therefore paid **only by the files that were being
damaged**. A v1 reader rejects those on the version, loudly, by v1 §12.1. That
is the correct outcome and a large improvement on silently receiving feather
that has been moved 150 px.

### 6.8 Validation, as a delta

Hard failures (v1 §12.1, extended):

> - `feather_model` is `anchored` in a file declaring `version: 1`.
> - `feather_model` is `anchored` and a point carries `feather`, or a frame has
>   no `feather_points`.
> - `feather_points` is present on a frame whose shape is not `anchored`.
> - `len(feather_points)` differs between frames of one shape. Names the shape
>   and the frames where the count changes, as v1 §7.3 does for vertices.
> - A `t` outside its shape's range (§6.4), or entries not ordered by `t`
>   ascending.

Soft failures (v1 §12.2, extended):

> - Vertices inserted to hold anchors. Warned once per shape, with the count.
> - An anchor snapped to a vertex because §6.5's crossing case applies and it
>   could not be inserted. Warned per anchor.
> - Two anchors' `t` values crossing between frames. Warned once per shape.

`geom.snapFeatherPoints` does not go away. It stays as the fallback for the
crossing case, and as what a v2 reader does when the destination cannot take
extra vertices at all.

## 7. Validation summary, as a delta

| Rule | v1 | v2 |
|---|---|---|
| `version` accepted | `1` | `1` or `2` |
| `version` written | `1` | lowest that expresses the file (§2) |
| `closed` type | boolean, must be `true` | boolean |
| `closed: false` | hard failure | needs `version: 2` |
| open spline render settings | n/a | soft failure, warned |
| open spline crossing hosts | n/a | soft failure, warned |
| `feather_model` accepted | `per_point`, `none` | `per_point`, `anchored`, `none` |
| `feather_model: anchored` | n/a | needs `version: 2` |
| feather anchor position | not carried, snapped at the source | `feather_points[].t` (§6.3) |
| two anchors on one segment | not expressible, one is dropped | two entries |
| `len(feather_points)` per frame | n/a | constant, hard failure (§6.8) |
| mid-segment anchor into Nuke | snapped, warned | vertex inserted, warned |

Nothing else in §12.1 or §12.2 moves.

## 8. What would have to be true to freeze this

1. An open spline authored in Nuke exports, re-imports, and renders the same matte -
   including the stroke width the file does not carry, which means confirming the
   node knobs are untouched by the importer rather than assuming it.
2. ~~An open mask authored in After Effects does the same.~~ **Answered
   2026-08-21, and it cannot ever be satisfied: After Effects produces no alpha
   from an open mask path (§5).** Replaced by a condition that can be met - that
   an open spline survives After Effects as *data*: it imports, exports again
   with `closed: false`, and the geometry returns unchanged. Covered by
   `test/test_ae_import.js`, so this half is already done.
3. §4 point 2 measured rather than assumed, in the same run that settles `ff`.
   **This got cheaper and less urgent at once.** The open-path feather sign only
   ever mattered for what it renders, and After Effects does not render an open
   path at all, so the only application that could disagree with Nuke about it is
   one that does not exist yet. It stays a stated convention until a third
   adapter needs it.

Conditions 1-3 are about open splines. §6 adds its own, and they are the ones
worth working on:

4. **§6.4 measured**: is `featherRelSegLocs` a bezier parameter or an
   arc-length fraction? Everything in §6 is exact if it is the parameter and
   quietly wrong on curved segments if it is not. It needs a render, so it goes
   in the Phase 5 run with `ff`.
5. **§6 implemented at all.** Nothing of it exists yet: `FEATHER_MODELS` in
   `core/rbj.py` is still `("per_point", "none")`, `version_for` still knows
   only the `closed` clause, the After Effects exporter still snaps
   unconditionally, and the Nuke importer has no de Casteljau split.
6. An After Effects mask with mid-segment feather crosses into Nuke and back
   with every anchor's `t` and signed radius intact, and renders the same matte.
   That is `prd.md` §14 criterion 8b rewritten to expect a **pass** where it
   currently expects an accepted loss.

**Read §5 before treating the open-spline half as nearly frozen.** Two of its
three conditions turned out to be about rendering, and rendering is where open
splines are weakest: After Effects produces nothing, and Nuke produces a stroke
whose width and end caps `.rbj` does not carry. What that half reliably does is
move the **geometry**. That may be the honest scope of the feature rather than a
gap in it, but it is a decision that has not been taken.

**§6 is the opposite case and should not inherit that verdict.** It is about a
matte that is measurably wrong today, in the direction the product exists to
serve, and it has a fix. If v2 is ever frozen, this is what freezes it.

Until then this stays a draft and `spec/rbj-v1.md` stays the frozen format.
