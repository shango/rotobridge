# `.rbj` version 2 - open splines (DRAFT)

**Status:** DRAFT, 2026-08-21. Not frozen. `spec/rbj-v1.md` is unchanged and stays
FROZEN; this document is a delta against it and nothing here weakens a v1 file.

**Scope:** one change - open splines, `prd.md` §12 Phase 6. The other three Phase 6
extras (inverted flag, mask expansion, richer ease fitting) are **not** in this draft.
They are named here only so their absence is a decision: the inverted flag is an
additive member that a v1 reader would silently ignore, which is the exact failure
mode `prd.md` §11 exists to prevent, and richer ease fitting is blocked on a
measurement nobody has taken (`HANDOFF.md`, Phase 5).

Read §1-§16 of `spec/rbj-v1.md` first. Everything not named below is unchanged.

---

## 1. Why a whole version number for one boolean

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
> file it is writing: `2` when any shape has `closed: false`, `1` otherwise. A
> reader must reject a version it does not implement.

An exporter does not stamp `2` on its output because it is a v2 exporter. It stamps
`2` because the file needs it. Every file that would have been written before this
draft is still written byte-identically, still says `version: 1`, and still opens in
a v1 reader - which is what makes this draft cheap to abandon.

`core.rbj.version_for(shapes)` is the one implementation of that rule, mirrored in
`RB.rbj.versionFor`. Two writers deciding it independently is how they drift apart.

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
- **After Effects** has no equivalent knob at all. What an open mask path renders as
  is **unmeasured**; nothing in probe runs 1-6 authored one.

So a v2 exporter warns that the render settings were not carried, and a v2 importer
warns when it takes an open spline from a **different** application than its own. Both
are soft failures (v1 §12.2, extended):

> - An open spline's host render settings, not carried. Warned once per shape.
> - An open spline whose `source.app` is not the importing application: what it
>   renders as is unverified across hosts. Warned once per shape.

The document-level round trip is exact in both hosts. The **rendered** one is exact
only within a host, and says so.

## 6. Validation summary, as a delta

| Rule | v1 | v2 |
|---|---|---|
| `version` accepted | `1` | `1` or `2` |
| `version` written | `1` | lowest that expresses the file (§2) |
| `closed` type | boolean, must be `true` | boolean |
| `closed: false` | hard failure | needs `version: 2` |
| open spline render settings | n/a | soft failure, warned |
| open spline crossing hosts | n/a | soft failure, warned |

Nothing else in §12.1 or §12.2 moves.

## 7. What would have to be true to freeze this

1. An open spline authored in Nuke exports, re-imports, and renders the same matte -
   including the stroke width the file does not carry, which means confirming the
   node knobs are untouched by the importer rather than assuming it.
2. An open mask authored in After Effects does the same, which first needs somebody
   to author one and find out what AE renders it as (§5).
3. §4 point 2 measured rather than assumed, in the same run that settles `ff`.

Until all three, this stays a draft and `spec/rbj-v1.md` stays the frozen format.
