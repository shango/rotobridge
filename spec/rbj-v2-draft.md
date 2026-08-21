# `.rbj` version 2 - open splines (DRAFT)

**Status: PERMANENT DRAFT.** Decided 2026-08-21, after §5 and §7 turned out the
way they did. This is not a document waiting to be frozen; it is a record of a
feature that works and has no demonstrated use. `spec/rbj-v1.md` is unchanged and
stays **FROZEN**, and it is the format. This is a delta against it and nothing
here weakens a v1 file.

**Why it stays a draft rather than being deleted or finished.** Open splines do
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

**Read §5 before treating this as nearly frozen.** Two of the three conditions
turned out to be about rendering, and rendering is where open splines are
weakest: After Effects produces nothing, and Nuke produces a stroke whose width
and end caps `.rbj` does not carry. What v2 reliably does is move the
**geometry**. That may be the honest scope of the feature rather than a gap in
it, but it is a decision that has not been taken.

Until all three, this stays a draft and `spec/rbj-v1.md` stays the frozen format.
