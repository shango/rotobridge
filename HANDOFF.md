# RotoBridge - working state

Scratch record of where things stand. Detail lives in `prd.md` and
`test/probe/README.md`; this file only holds what those two do not.

Last updated: 2026-08-21. **Phase 4 is complete and has met both hosts.**

Earlier this session: both After Effects import bugs found, fixed and confirmed
in the host (stale mask handles; feather compared by array index); the drift
pass now splits a monotone gap instead of walking back from its end, which
closed the `hold`-over-a-moving-ancestor question; bezier ease measured and
exact; and open splines settled as a **permanent draft** after After Effects
turned out to produce no alpha from an open mask path at all.

Then the project got a use case, and it reordered the work. **Nuke is the hub**
and **the format has to be falsifiable** - see the two sections under Status.
The AE ease question is closed as a "cannot", not a "not yet". **The frontier is
now feather anchoring, then Phase 5 rendered pixels.**

## Status

`prd.md` is at **4.10**. Phase 0 is complete on both sides and **every open
question is closed** (Q6-Q9). **`spec/rbj-v1.md` is FROZEN** (2026-08-20).
Raw probe output is committed under `test/golden/nuke_probe/17.1v1/` (12 files,
10/10 cases) and `test/golden/ae_probe/` (6 runs; run 3 is the only one with
feather points, run 6 the only one with mixed key interpolation - both are
load-bearing evidence).

**Phases 1, 2, 3 and 4 are complete**, and Phase 4 has now met both hosts: the
export and the six-shape import both pass in After Effects, and both Nuke
acceptance tests pass. `core/` holds the host-free geometry, timing, schema,
interpolation and drift code: stdlib only, no host imports, no file access, so
it runs unchanged under plain Python and under Nuke's embedded Python. `nuke/`
holds the Nuke adapter pair and `ae/` the After Effects one, over an ES3 mirror
of `core/`. `test/test_core.py` is **176 passing tests**, run with `python3
test/test_core.py` (not `unittest discover` - `test/` is deliberately not a
package). `./test/run.sh` runs all five host-free suites: **369 tests**.

`test/test_nuke_roundtrip.py` is the Phase 2 **and Phase 3** acceptance test and
needs Nuke; the invocation, including the sync step, is in
`test/probe/README.md`. Last run: **PASS**. Dense worst deviation 3.05e-05 px,
which is Nuke's float32 storage floor and not accumulated error; sparse 5-key
round trip 6.1e-05 px with **0 corrective keys**; drift bound 30.9 px unbounded
against 0.465 px at tolerance 0.5. Report committed at
`test/golden/nuke_probe/17.1v1/phase3/roundtrip_report.txt`.

Golden files: `test/golden/square.rbj` (hand-built), `test/golden/roundtrip.rbj`
(a real Nuke export carrying every v1 field), `test/golden/sparse.rbj` (a real
export of a shape keyed on 5 frames of 41), **`test/golden/ae_scene.rbj`** (the
first real After Effects export, 6 shapes, `version: 2`, 2026-08-21),
**`test/golden/ae_static_ease.rbj`** (2 shapes on a layer that does not move,
the file that answered the ease question) and
**`test/golden/held_over_moving_layer.rbj`** (hand-built: a `hold` the dense
layer contradicts - see below). All three are validated with no
Nuke present by `test/test_core.py`, and the latter two are **run through the
After Effects adapters** by `test/test_ae_crossapp.js` - see below.

**The crossing is tested in one direction with neither application present**
(`test/test_ae_crossapp.js`, 14 tests, added 2026-08-20). It imports a real Nuke
`.rbj` into the mock and exports it straight back out. That is the one thing a
same-app round trip cannot do: a pipeline that flipped Y the wrong way, inverted
feather's sign or stored ease a factor of 100 out would still hand back exactly
what it was given, for the same reason Nuke to Nuke does not drift. What it
found:

- `roundtrip.rbj` at tolerance 0 returns **bit-identical** - every vertex,
  tangent, opacity, uniform feather and signed per-point feather, all 20 frames.
- **`feather_offset` is the only field dropped.** The test compares the key set
  of every point both ways, so a *second* omission fails instead of passing.
- `sparse.rbj` returns its 5 authored keys as exactly 5 keys with **0
  corrective**, and the 36 frames After Effects rebuilt agree with Nuke's to
  **3.05e-05 px** - the float32 storage floor, not accumulated error. The two
  applications' `linear` is the same line.
- **A bare `ease` comes back carrying AE's default**, influence 0.16667 speed 0.
  The one thing the crossing changes, and it is honest: spec §10.3's "parameters
  unknown" has to become a real curve to exist in a comp. The dense layer is
  still the ground truth. Worth knowing that a file which crosses twice is no
  longer parameterless.

It does **not** replace Phase 5. The mock answers the AE API but is not AE, and
nothing here renders a pixel. What it buys is that a Phase 5 mismatch is now
attributable: the document-level conversion is exact, so a pixel-level
disagreement is the host or the render, not the geometry core.

Everything is committed on `main`, working tree clean.

## In flight

**Phase 4 is now clean in both hosts.** Both After Effects import bugs are
fixed and **confirmed in After Effects itself**: six shapes import in one pass,
and `feathered` converges at 0.2148 px with 3 corrective keys where it used to
burn every pass on a phantom 27.0000. Both Nuke runs pass. Nothing is blocked on
a bug.

**Nothing is waiting on After Effects.** The last open Phase 4 question -
whether `.rbj` ease reproduces AE's own curve - was answered in the host on
2026-08-21 and the answer is yes, exactly. See "Bezier ease, answered".

**Nuke is not blocked on anyone** - it runs headless from this shell. Both Nuke
runs pass: Phase 6 open splines, and the AE-to-Nuke crossing.

No open questions in the `prd.md` §15 sense - Q10 closed 2026-08-20.

**Open splines are a PERMANENT draft** (`spec/rbj-v2-draft.md`), decided
2026-08-21 - see "Open splines may not be worth a version number". `closed`
becomes a real boolean and a file containing an open shape declares
`version: 2`. Four things worth carrying forward:

- **The bump is per file, not per adapter.** A v2 exporter with nothing open to
  say still writes `version: 1`. Every file that would have been written before
  this still is, byte for byte, and still opens in a v1 reader - which is what
  makes the draft cheap to abandon. `core.rbj.version_for` and
  `RB.rbj.versionFor` are the one rule, mirrored, because two writers deciding
  it independently is how they drift apart.
- **`version` is an integer, so there is no 1.1.** v1 §5 types it that way, and
  a reader meeting `1.1` rejects it as "not an integer" - loud but misleading.
  That is the whole reason the draft is v2 and not a minor bump.
- **`outward_normals` was wrong for a polyline** and now takes `closed`. The
  wraparound gives an endpoint a neighbour it does not have. Interior vertices
  are untouched; an endpoint takes the chord to its single neighbour, and the
  global sign is a **fixed** quarter turn rather than area-derived, because the
  area of a near-straight polyline flips on a perturbation and would flip the
  feather frame to frame. It stays a stated convention rather than a measured
  one, and that got cheap: the sign only ever mattered for what an open path
  renders as, and the only host that renders one at all is Nuke.
- **The document round trip is exact; the rendered one does not exist.** This
  is now measured on both sides and is why v2 is a permanent draft. After
  Effects produces **no alpha at all** from an open mask path. Nuke renders one
  as a stroke, but its width and end caps are **node** knobs
  (`openspline_width` 10.0, both end types `rounded`) with no per-shape
  attribute to carry them, so even Nuke to Nuke arrives at defaults. Both
  adapters warn, and the AE importer warns on **every** open spline rather than
  only on a crossing one.

The other three Phase 6 extras are deliberately not in the draft. The
**inverted flag** would be an additive member, and §2.5 requires a v1 reader to
*ignore* what it does not recognise - so an old reader would render the
un-inverted matte silently, which is the failure mode `prd.md` §11 exists to
prevent. It needs its own answer, not a field. **Mask expansion** is After
Effects-only. **Richer ease fitting** is blocked on the AE-to-Nuke ease
measurement that Phase 5 owns.

**Q10 is closed, and Phase 2 had it wrong.** Nuke roto has **no boolean shape
operations at all** - not union, not difference, not intersection. `bm` is an
index into fifteen **pixel** blend operations, and a shape composites against
the accumulated matte below it, only inside its own outline. `over` (0) is union
exactly; nothing is difference or intersection. Full table and readings in
`prd.md` §15 Q10 and `test/golden/nuke_probe/17.1v1/q10/`.

Two things worth carrying forward from how it was found:

- **The control is a NODE knob**, `blending_mode`, an `Enumeration_Knob` of 15
  values each carrying its stored number. Cases 73, 75 and 76 all missed it
  because all three searched the curves tree. It is a proxy for the GUI
  selection and `setFlag(eSelectedFlag)` does **not** drive it, so it is
  unusable from Python - but its value list is the `bm` numbering, which was all
  that was needed.
- **Case 75 was wrong twice over, and both errors are the same shape.** It swept
  0-29 because case 73 assumed `bm` indexed the 30-entry Merge list; the menu has
  15 entries. And it swept the **lower** of two shapes, where a blend cannot
  affect the overlap at all, because the top shape's opaque `over` restores it.
  A sweep that finds nothing is evidence about the sweep as much as the subject.

**Stacking is the reverse of AE's.** `rootLayer` index 0 renders on top and a
blend reaches downward, so in Nuke the *earlier* shape cuts the later ones; in
AE the *later* mask cuts the earlier ones. This matters for Phase 5, not Phase 4:
any future `difference` mapping has to reverse shape order as well as set `bm`,
which is why it is not a two-line change and is not being guessed at now.

**Unchanged behaviour, better warning.** `blend_to_rbj` / `blend_from_rbj` still
carry `union` only. The warning now names the mode (`'minus'`) via
`BLEND_NAMES` instead of printing a bare float, which is what `prd.md` §11 asked
for and could not deliver while the numbering was unknown.

The open-spline sign convention of `spec/rbj-v2-draft.md` section 4 is in this
same class and should be settled in the same run.

`ff` (feather falloff) is still unverified in the same class as blend was: it
defaults to `1.0`, the API never names its values, and the adapters treat
non-zero as `smooth`. It round trips Nuke to Nuke because the same rule runs both
ways, so it is only exposed once a file actually crosses between the two
applications. That is Phase 5, not Phase 4: the AE adapters name their falloff
values (`FFO_LINEAR` 7213, `FFO_SMOOTH` 7212) and carry them faithfully, which
narrows the question to Nuke's half but does not answer it.

## The first After Effects host run, 2026-08-21

Phase 4 finally met the host. **The export passed. The import did not.** Neither
result has anything to do with open splines; Phase 6 rode along and was fine.

Fixture: `test/probe/setup_ae_scene.jsx` on a 1920x1080 24 fps comp, After
Effects 25.6x101. The exported file is committed as **`test/golden/ae_scene.rbj`**
- the first real After Effects export in the project, and the only artefact of
this run that survived the session.

### The export passed, and settled two things

6 shapes, 600 points baked, 0.29 s, 27 authored keys, 4 warnings - and all four
warnings are ones the design predicted, none is a surprise:

- `feathered`: 3 feather points mid-segment, snapped to the nearer vertex
- `feathered`: two points resolved to vertex 3, kept radius 12 and dropped 0
  (the collision rule, and the zero competing on equal terms, both as specified)
- `opened`: the open-spline render-settings warning
- `offgrid`: a key 0.400 of a frame off the grid, snapped

The file **validates against `core/rbj.py`** and stamps **`version: 2`**, purely
because one of six shapes is open. Two findings worth keeping:

- **AE ease survives to `.rbj` exactly.** Keys 0, 12, 24 of `eased` came back
  `in: [0.91176, 0]`, `out: [0.33333, 0]` - influence 91.176 / 33.333 over 100,
  nowhere near the 16.667 default, so it cannot be a default in disguise. The
  factor of 100 in spec section 10.3 is now measured in the host, not just the
  mock.
- **The asymmetric key survives the export.** `mixed` frame 12 exported
  `{in: linear, out: hold}` - the exact key run 6 produced and the one the v4.2
  single-valued schema could not represent. It also means
  `setInterpolationTypeAtKey` after `setTemporalEaseAtKey` took, on the export
  side. Whether it survives the *import* is still unanswered, because the
  import failed.

**`feather_falloff: smooth` on all six masks is correct, not a bug.** Only
`feathered` had falloff set. AE's default `maskFeatherFalloff` is 7212 = SMOOTH,
measured in probe runs 4, 5 and 6. Checked before flagging; do not re-flag it.

### The import failed: "object invalid"

The alert read `RotoBridge import failed: ... object invalid`. **The exact line
number was never captured - get it.** The catch block at the foot of
`ae/rotobridge_import.jsx` appends `(line N)` when After Effects supplies one.

**Hypothesis, not a diagnosis.** `importShapes` creates all six masks up front
and then goes back and writes into them:

```js
for (s = 0; s < specs.length; s++) { masks[s] = createMask(layer, specs[s]); }
var targets = bakeTargets(comp, layer, specs, frames, offset, warn);
for (s = 0; s < specs.length; s++) { buildOne(comp, masks[s], ...); }
```

`createMask` keeps what `addProperty("ADBE Mask Atom")` returned. If adding
masks 2-6 invalidates the reference to mask 1, every held reference is stale by
the second loop - and "object invalid" is what After Effects says about a stale
one. This is the **same hazard the Nuke side already documented**: `append()`
copies into the tree, the object you passed goes stale, re-fetch the live child
from its parent. Different API, same shape. The mock cannot see it because its
`addProperty` returns a plain object that never goes stale, and this is the
**first multi-shape After Effects import that has ever run**, so nothing earlier
could have caught it.

**The one experiment that decides it:** re-run the import and type a single
name - `opened` - at the shape-subset prompt. One shape succeeding where six
failed confirms the stale reference, and the fix is to re-fetch each mask from
the parade by index rather than hold what `addProperty` returned. Failing
identically on one shape means the hypothesis is wrong and the line number is
the only lead.

Ruled out already: the open-spline import path itself. Driving a version-2 open
spline from a Nuke source through the real importer under the mock builds the
mask, reports 2 authored keys and 0 corrective, and raises the cross-host
warning. That path is clean.

### AE to Nuke: the crossing works, measured in the host

`test/test_ae_to_nuke.py`, run 2026-08-21, report committed at
`test/golden/nuke_probe/17.1v1/phase6/ae_to_nuke_report.txt`. It takes the real
`test/golden/ae_scene.rbj` into Nuke and back out. **PASS.** This is the
direction nothing had ever tested with a host: `test_ae_crossapp.js` goes Nuke
to AE with no application present, and a Nuke round trip returns what it was
given even if a convention were wrong at both ends.

- **Geometry survives to 6.1e-05 px** worst over all six shapes, all 25 frames -
  the float32 storage floor, not accumulated error.
- **The open spline arrives open** and a closed one stays closed.
- **At tolerance inf the field-by-field comparison is empty.** Every shape's
  `closed`, `feather_model`, `feather_falloff`, `blend`, key frames and per-side
  `interp` came back identical, `{in: linear, out: hold}` included. That is
  acceptance criteria 3, 6, 6a and 10 met on a real crossing.
- The re-export **validates and is `version: 2`**, carrying the open spline back.

**Read the three imports as three different questions.** Tolerance 0 keys every
frame by definition, so its key list says nothing about key preservation - an
earlier pass of this test compared it field-by-field and produced a page of
"losses" that were nothing but dense mode working. The docstring of
`test_ae_to_nuke.py` exists to stop that being repeated.

**The corrective-key counts mean nothing about interpolation, and the fixture is
why.** `eased` needed 20 corrective keys on top of its 5 authored, in Nuke and
again in After Effects. That looks like a verdict on `ease` and **is not one.**

Every mask in `setup_ae_scene.jsx` sits on a scaled and **rotating** layer,
chosen so the derived-affine path is exercised. The transform is baked into the
exported points, so the canonical geometry never moves the way any key type
claims. Measured off `test/golden/ae_scene.rbj` directly:

| shape | key sides | bows off its own chord |
|---|---|---|
| `linear` | `linear`/`linear` | **13.223 px** at frame 12 |
| `opened` | `linear`/`linear` | 4.637 px |
| `eased` | `ease` | 49.175 px |
| `mixed` | includes `linear`/`hold` | 300.177 px |

**A `linear` key pair whose geometry bows 13 px off the straight chord needs
corrective keys however perfect the mapping is.** So the counts measure the
rotation, not the interpolation, and this scene cannot answer the Phase 4 ease
question at all. Corroborating it: `sparse.rbj`, a Nuke file with no layer
transform, imports with **0 corrective**.

Masks **7 and 8 were added 2026-08-21** to answer it - `eased_static` and
`linear_static`, on a second solid, `RotoBridge static`, that does not move.
**They ran, and the answer is that `.rbj` ease reproduces AE's own curve
exactly**: both came back with 0 corrective keys and 0.0000 px. See "Bezier
ease, answered in the host".

**The two hosts agree to a thousandth of a pixel**, which is the result that
does survive from this run. The same shapes, imported independently by two
adapters into two applications:

| shape | After Effects | Nuke |
|---|---|---|
| `mixed` | **0.1000 px @ frame 16** | **0.1000 px @ frame 16** |
| `feathered` | 0.2148 px @ 8 | 0.2143 px @ 12 |
| `opened` | 0.2584 px @ 16 | 0.2577 px @ 12 |

Two independent drift passes over two independent geometry pipelines landing on
the same residual at the same frame is the geometry core being genuinely shared,
rather than two implementations that merely both look plausible. `mixed` is the
sharpest version of it: before the gap-splitting fix the two read 0.4615 and
0.4616 at frame 8, and afterwards **both** moved to 0.1000 at frame 16. A change
in shared arithmetic showed up identically on both sides of the project.

`feathered` is the second-sharpest, and by a stranger route: After Effects
carries its per-vertex feather and Nuke carries none at all, since
`feather_offset` is Nuke-only. The two agree to 0.0005 px anyway, which is the
geometry agreeing while the feather is not even in the comparison on one side.

### The AE import: two bugs, both fixed and CONFIRMED IN THE HOST, 2026-08-21

Importing each shape on its own isolated them. Five of six converged; **only
`feathered` failed**, and it is the only mask with per-point feather. Both bugs
are now fixed and **a six-shape import has run in After Effects and passed**.

| shape | corrective, before | worst drift, before | corrective, after | worst drift, after |
|---|---|---|---|---|
| `linear` | 7 | 0.3733 px @ 8 | 11 | **0.0002 px @ 19** |
| `eased` | 20 | converged, every frame keyed | 20 | converged, every frame keyed |
| `mixed` | 9 | 0.4615 px @ 8 | 11 | **0.1000 px @ 16** |
| `feathered` | 18 | **27.0000 px @ 15** | **3** | **0.2148 px @ 8** |
| `offgrid` | 4 | 0.3957 px @ 17 | 4 | 0.3809 px @ 13 |
| `opened` | 3 | 0.2584 px @ 16 | 3 | 0.2584 px @ 16 |

"Before" is six separate single-shape imports, because six at once could not run
at all. "After" is one import of all six, which is itself the confirmation of
bug 1. Three things in that table are worth reading twice:

- **`feathered` went from 18 corrective keys and a residual nothing could
  remove, to 3 and the second-cheapest shape in the file.** It was never
  drifting. Every one of those 18 keys was chasing the host's array order.
- **`mixed` lands on 0.1000 px at frame 16, which is Nuke's number to four
  decimals and the same frame.** Two independent importers, two applications,
  two drift passes over the shared core, same residual at the same frame - and
  both moved there together when the gap-splitting fix landed, from 0.4615 (AE)
  and 0.4616 (Nuke).
- **`linear` reaches 0.0002 px.** Its worst frame moved from 8 to 19 as well,
  so the residual it used to report was partly the same phantom.

The four warnings replayed are the export's own, recorded in the file when it
was written, and all four are the ones the design predicts: three feather points
mid-segment on `feathered`, the vertex-3 collision keeping radius 12 and
dropping 0, `opened` being an open spline, and `offgrid`'s key 0.400 of a frame
off the grid. None is a new finding.

**Bug 1, FIXED: stale mask handles.** Every multi-shape import failed with
"object invalid"; every single-shape import succeeded. `createMask` returned
what `addProperty("ADBE Mask Atom")` handed back, and `importShapes` collected
all of them before writing into any - but After Effects invalidates a handle
into the mask parade whenever the parade changes, so all but the last were stale
by the time they were written to. `createMask` now returns the mask's **index**
and each is re-fetched at the moment it is used. `test/ae_mock.js` now models the
invalidation (a handle goes stale on `addProperty` and throws "object invalid"),
and `test/test_ae_import.js` gained a two-shape case that fails on the old code
with "mask 0 got no keys". Every previous import fixture was single-shape, which
is exactly why nothing caught it. **Confirmed in the host**, 2026-08-21: all six
shapes imported in one pass, where every previous attempt died on the second.

**Bug 2, FIXED 2026-08-21: `deviation` compared `featherRadii` by array
index.** The residual was **exactly 27.0000** against a file whose per-vertex
feather is `[30, -15, 0, 12]`, where `12 - (-15) = 27`.

**Two probes, and the answer needed both.**

`probe_ae_feather_order.jsx` set a value once and read it straight back: order
**preserved**, `[30, -15, 0, 12]` in and out. That looked like it killed the
type-grouping hypothesis, and `deviation` was correctly left alone.

`probe_ae_feather_interpolated.jsx` wrote **keys** and read at a frame
**between** them, which is the path the drift pass actually measures on. There
the array comes back `[30, 0, 12, -15]` with types `[0, 0, 0, 1]` - **grouped by
type, non-negative before negative** - and index-wise that is 0, 15, 12, 27.
So the original hypothesis had the right rule and the wrong code path, and only
splitting the two reads apart could show it.

**It happens for LINEAR keys as well as BEZIER**, so it is interpolation that
does it, not the curve type.

**Nothing is lost in the reorder, which is what makes a fix possible.** The
anchors move with the radii: on a key, `segLocs [3, 0, 1, 2]` against
`[30, -15, 0, 12]`; between keys, `segLocs [3, 1, 2, 0]` against
`[30, 0, 12, -15]`. Both describe the same four points. Add the always-on rename
that probe 1 found - a point written at `(segment i, rel 0)` returns at
`(segment i-1, rel 1)` - and the invariant is `seg + rel`, the position in
segment units, which wraps to the same value under both.

**The fix.** `deviation` now compares feather as a map keyed by
`(seg + rel) % vertexCount` instead of by array index, in
`ae/rotobridge_import.jsx`. It is deliberately **not** a raw anchor match on
`(segLocs, relSegLocs)`, which is the obvious fix and would have matched nothing:
the target shape is built in JS and never sees the host, so it carries
`(i, 0)` while everything from the host carries `(i-1, 1)`.

**Reproduced host-free before it was fixed.** `test/ae_mock.js` now models both
measured behaviours - the rename on every read, the regroup on interpolated
reads only. With the model in and the old comparison still in place, the
pre-existing "honours a real Nuke export's sparse layer" test failed with **41
keys instead of 5**: the pass keying every frame in pursuit of drift that was
never there. That is the `feathered` failure, off the host. Four new tests in
`test/test_ae_import.js` pin it, including one that a **genuine** feather drift
is still measured, because a fix that simply stopped looking at the feather
would pass every other test here.

**The exporter already had this right, and now says so.** `snapFeatherPoints`
resolves each point through its own anchor rather than its array position, so
the frame-major bake - which reads mostly in-between frames - was never
affected. `test/test_ae_export.js` gained a keyed-path feather test to keep it
that way, since index-by-index would look like a simplification.

**Confirmed in the host**, 2026-08-21: `feathered` came back with 3 corrective
keys and 0.2148 px, against 18 and an unremovable 27.0000 px before. Nuke
measures 0.2143 px on the same shape by a route that carries no feather at all,
which is about as independent a second opinion as this project can get.

### After Effects cannot matte an open path, 2026-08-21

**A mask whose path is open produces no alpha in After Effects.** Reported by
the user after `setup_ae_scene.jsx` authored one. Open paths do exist in AE - on
shape layers, for strokes, trim paths and paths-as-data - but masking is not one
of their uses.

**The API does not object, which is why nothing caught this.**
`maskPath.closed = false` is accepted, reads back `false`, and exports as
`closed: false`. That is why `test/golden/ae_scene.rbj` says so and stamps
`version: 2` honestly, and why the AE-to-Nuke crossing legitimately passes. The
document is right. The matte is empty.

**Both warnings were wrong and are fixed.** They said "unverified across
applications". It is not unverified any more, and the import warning is no
longer gated on `source.app`: an open mask produces no alpha whoever wrote the
file, After Effects included.

**This is deliberately still a soft failure**, not a refusal. The geometry is
real, it mattes in Nuke, and an artist may want it in a comp to move onto a
shape layer. Refusing would destroy data to prevent a surprise a warning covers;
closing it would invent a segment nobody drew.

**And it puts a serious question over v2 as a whole - see below.**

### Open splines may not be worth a version number

Raised by the user 2026-08-21: in roto, across applications, open splines are
not used. That matches what the two hosts actually do, and the numbers are now
measured on both sides:

- **After Effects renders nothing at all** from an open mask path (above).
- **Nuke does render one, but as a stroke**, and the parameters that make it a
  stroke are **node** knobs the format has no member for: `openspline_width`
  defaults to **10.0**, both end types to **`rounded`**, `toolbar_openspline_
  falloff` to 0.0 (measured headless, 17.1v1). So an open spline that crosses
  through `.rbj` into a fresh Roto node arrives at those defaults, not at
  whatever the author set.

So the format moves an open spline's **geometry** faithfully and cannot make it
render correctly anywhere: nothing in AE, and a default-width stroke in Nuke.
Even the Nuke-to-Nuke case loses the stroke, because the importer builds a new
node. What Phase 6 built is a data-carrying feature wearing a matte feature's
clothes, and `spec/rbj-v2-draft.md` section 8 now says so.

**DECIDED 2026-08-21, by the user: v2 stays a PERMANENT draft.** Not a document
waiting to be frozen - a record of a feature that works and has no demonstrated
use. `spec/rbj-v1.md` remains the format.

Rejected, and why. **Deleting it**: the code exists, is tested, is honest about
what it drops, and costs the v1 paths nothing, since a writer emits `version: 1`
unless a shape is actually open. **Extending it** with stroke width and end
caps: that would make the feature real in exactly one host by inventing members
for something After Effects has no equivalent of, and would commit an
interchange format for roto mattes to a paint model it was not designed for.

The practical rule: no file should be written with `version: 2` on purpose. If a
Silhouette or Mocha adapter ever turns up a real use for open splines, the work
is already done. Do not reopen this without one.

### Bezier ease, answered in the host 2026-08-21

**`.rbj` ease reproduces After Effects' own curve exactly.** This was the last
open Phase 4 question and the one the crossing test could never reach.

Fixture: `test/golden/ae_static_ease.rbj`, a two-shape export of masks 7 and 8
of `setup_ae_scene.jsx`, both on `RotoBridge static`, a solid that does not
move. Exported and reimported in After Effects 25.6x101.

| shape | authored | corrective | worst drift |
|---|---|---|---|
| `eased_static` | 3 | **0** | **0.0000 px** |
| `linear_static` | 2 | **0** | **0.0000 px** |

**What makes 0.0000 px mean something.** `eased_static`'s dense layer bows
**135.4 px** off the straight chord between its own keys, against a 0.5 px
tolerance - so if the ease were being dropped, defaulted or mis-scaled, the
drift pass could not have hidden it. The three authored keys alone rebuilt all
135 px of that curve. Influence 91.176 in / 33.333 out reached the file as
`[0.91176, 0]` and `[0.33333, 0]` and came back as the same curve, which
confirms spec section 10.3's factor of 100 **in both directions on a real
curve** rather than on a default.

`linear_static` is the calibration and it passes: its dense layer is straight to
0.0001 px and it reimported with zero corrective keys, so the rig contributes
nothing and the eased number is readable.

**This retires the last doubt about `eased`'s 20 corrective keys.** That count
was the baked rotation, exactly as the correction in "AE to Nuke" says, and not
the cost of a bare `ease`. Two masks with the same interpolation on a layer that
does not move need **no** corrective keys at all.

**It does not settle the Nuke half.** AE ease to `.rbj` is now measured in both
directions; `.rbj` ease to Nuke's `lslope` / `rslope` and `la` / `ra` is still
unmeasured and still Phase 5. `core/interp.to_nuke` is the one function that
changes.

**A side effect worth remembering.** This file is the first measurement of what
AE's temporal ease actually does to a mask path - a known influence and speed
against 25 frames of sampled geometry. `test/ae_mock.js` refuses BEZIER on the
grounds that nothing had measured it (`prd.md`, "the mock draws one line").
Something has now. Raising that line is optional and nothing needs it yet, but
the evidence exists where it did not before.

### A `hold` can contradict its own dense layer

Found while investigating the above, unrelated to it, and **a Phase 4 problem
rather than a Phase 6 one**.

`mixed` exported `out: hold` at frame 12. The layer rotates from frame 6 to 18,
so the geometry genuinely moves through 12-18 while the sparse layer says it is
frozen. `hold` is a claim about **layer** space; `.rbj` keys describe
**canonical** space with the transform baked in, where the claim is false.

Reproduced host-free - `test/golden/held_over_moving_layer.rbj`, a steadily
moving dense layer under `out: hold` at frame 12. Run it through the AE importer
under the mock and the drift pass cannot converge:

```
held: 3 authored key(s), 8 corrective; worst drift 60.0000 px at frame 15
  - the drift pass ran out of passes with 60.0000 px still unaccounted for
```

It burns all eight passes and gives up. **It fails loudly rather than deforming
silently**, which is the policy working as intended.

**But "structurally cannot converge" was too strong, and the host says so.**
That claim was made from this synthetic case alone, before the crossing test
ran. In Nuke, at the default tolerance, the real `mixed` mask converged to
**0.4616 px with 14 corrective keys**, and its worst frame was 8 - *before* the
hold, not inside it. So it was a severity question, not a categorical one.

### RESOLVED 2026-08-21: the drift pass owns this, not the exporter

**The mechanism, exactly.** Inside a held gap the destination is frozen while
the dense layer keeps moving, so the deviation climbs steadily and the worst
frame of the gap is always its **last**. `drift._survey` picked the worst frame,
and a key on the end of a run does not split it - it shortens it by one frame.
Bisection degenerated into a backward walk of one frame per pass and ran out of
the eight. The corrective keys it landed on the synthetic file were exactly
`[16, 17, 18, 19, 20, 21, 22, 23]`, contiguous from the end of the gap, which is
the signature of the walk rather than of a split.

**Why the exporter is the wrong place to fix it.** `hold` is a claim about
**layer** space, and it is *correct* there - reimported onto a layer carrying
the same transform, the layer-space targets really are frozen across the
interval and the pass lands **zero** corrective keys. The exporter cannot know
what transform the destination layer will have, so downgrading `hold` to
`linear` on the way out would destroy a lossless same-rig round trip in order to
help a destination that may not exist. The dense layer is the ground truth and
the drift pass is what reconciles the two layers, so the drift pass has to be
able to.

**The fix.** `_survey` now adds a gap's **midpoint as well as** its worst frame,
when the worst frame is one of the gap's two ends. Mirrored in
`RB.drift.survey`. The worst frame is still always added, so this can only
reduce the passes a gap needs, never increase them.

**Adding the midpoint *instead of* the worst frame was measured and rejected.**
It looks leaner on the synthetic file - 4 corrective keys against 6 - but on the
real crossing it lands the same key count on five of six shapes and leaves
`mixed` at 0.4503 px where adding both reaches 0.1000 px. Once the error is not
perfectly monotone, pinning the measured worst frame is what closes the gap; the
midpoint only guarantees the run gets split. Recorded in the `_survey` docstring
so it is not tried again.

**Measured.** `held_over_moving_layer.rbj` through the real After Effects
importer under the mock: **8 corrective keys and 60.0000 px unaccounted at frame
15, before; 6 corrective and converged, after.** Re-running both Nuke acceptance
tests over the real `ae_scene.rbj` moves nothing else - five of six shapes keep
their worst deviation to the digit (0.3723, 0.2143, 0.3665, 0.2577) and pay one
or two extra keys, while `mixed`, the one shape carrying the `hold`, improves
**0.4616 px to 0.1000 px**. Both reports are re-committed under
`test/golden/nuke_probe/17.1v1/phase6/`.

Still genuinely unknown, and unchanged by this: whether After Effects behaves
like Nuke over a held interval at all, since the AE import has never completed
in the host. Do not restate the strong claim without measuring it.

## Decisions made, so they are not relitigated

**Phase 3 writes `ease` without parameters, on purpose - and reads no slopes
either.** Q9 left a hypothesis that Nuke's `lslope`/`rslope` correspond to AE
ease `speed` and `la`/`ra` to `influence`. It is still unmeasured, and there is
no way to calibrate the units from the Nuke side alone. Rather than guess a
normalisation into a frozen format, Phase 3 emits eased sides as `ease` with no
`ease` entry, which spec §10.3 defines as "smooth, parameters unknown, rely on
the drift pass". The same reasoning killed the mirror path: `prd.md` §9.2 step 3
asks the importer to set `lslope`/`rslope` per side on an asymmetric key, and
Phase 3 does not, because an asymmetric key cannot arrive from a Nuke source, so
there is nothing to exercise or verify it with. Positional truth is preserved by
tier 3 in both directions. Settle the correspondence in **Phase 5**, when a file
has actually crossed between the two applications; that is the only place both
sides of the mapping are observable at once. Phase 4 narrowed it rather than
answering it - AE ease to `.rbj` ease is now a measured factor of 100 in both
directions, so what is left is specifically the Nuke half.
`core/interp.to_nuke` is the one function that changes.

**A curve with fewer than two keys abstains from the interp vote.** Considered
and rejected: letting every curve vote. `.rbj` carries one `interp` per key and
Nuke carries one per axis per control point, so the export reduces - and the
constant z axis that the importer writes on every control point would outvote
the axes that actually move, marking every genuinely eased shape as mixed. A
curve with fewer than two keys cannot describe an interval, so it has no
interpolation to report. **No votes at all is not a disagreement** either: a key
frame can come from the transform or from the pinned range endpoints with no
control point keyed there, and nothing was collapsed, so nothing is warned about.

**The export always pins the range endpoints as keys.** A key outside the
exported range still drives the values inside it, and the dense layer covers
exactly `[first, last]`, so without the endpoints a shape keyed at 60 and 200
and exported over 1 to 100 would claim to be static for its first 59 frames. Two
keys, and the sparse layer brackets the truth instead of flattening at the edge.

**Corrective keys are linear, not smooth.** A corrective key exists precisely
because the host's own interpolation left the dense layer, so a cubic one could
overshoot between corrective keys and manufacture fresh drift; straight segments
between measured frames cannot, which is what makes each pass reduce the error
rather than move it around.

**Considered and rejected: classifying a cubic key's side as `linear` when its
slope matches the chord to the next key.** It reads plausible and `prd.md` hints
at it, but the slope units are unverified, the only case it provably gets right
is slope 0 against chord 0 - where the segment is flat and `linear` and `ease`
render identically - and it needs neighbour lookups on every axis of every
point. Cubic and the unset sentinel both go to `ease` on both sides.

**Nuke to Nuke does not drift, and that is the round trip working.** The same
key type through the same key frames re-evaluates to the same curve, so tier 3
has nothing to do on a Nuke-sourced file. The acceptance test therefore thins a
file's sparse layer to two straight keys over its own curved dense layer, which
is exactly what a foreign exporter's tier-2 output looks like. Do not "fix" the
absence of corrective keys in the Nuke-to-Nuke path.

**Phase 2 overturned two `prd.md` claims, both measured.** `getPosition` is
pre-transform, so the export bake is required rather than a precaution (case
70). And **`curveType` is not the linear control** - it selects the spline basis
and has no linear member at all. The control is per key,
`AnimCurveKey.interpolationType = InterpolationType.eLinear + 1` (cases 71 and
74). Every place that said `curveType` is corrected in `prd.md` §7, §9.2 and
`test/probe/README.md`.

**The freeze departed from `prd.md` §6 in four places, 2026-08-20.** All four
are recorded in spec §14 and folded back into `prd.md` v4.4, so the two agree.
They were resolved rather than deferred because each was ambiguous or
self-contradictory in §6:

1. **`opacity` moved into the dense layer**, per frame. Both hosts animate it
   (AE `maskOpacity` is a `Property`, Nuke `opc` is an `AnimAttributes` curve),
   so the static shape-level field §6 showed would have frozen it at frame 1 -
   the identical defect case 62 found in uniform feather. There is now no
   shape-level `opacity`: one location, no shadowing.
2. **`feather_model` lost its `uniform` value**, leaving `per_point | none`
   describing the per-point layer only. Once case 62 proved the two layers
   independent, `uniform` said nothing that `feather_uniform != [0,0]` did not,
   and two members encoding one fact can disagree with no tiebreak rule.
3. **`ease`'s second element is `speed`, not `value_offset`.** Same position,
   same meaning, and it is what both the AE API and the probe output call it.
4. **`feather` is conditional, not universal**: present on every point when
   `feather_model` is `per_point`, absent entirely under `none`. Writing `0.0`
   under `none` would be indistinguishable from an authored zero-width point,
   which run 3 proved is a real distinction.

**Q8, uniform feather - settled by AE run 6 and Nuke case 62.** Both sides have
a 2-D uniform feather that animates and composes with per-point feather rather
than replacing it. AE `maskFeather` ↔ Nuke `fx`/`fy` is 1:1 and lossless, so the
old collapse-to-mean rule and its anisotropy warning are deleted. `.rbj` gains
`feather_uniform: [x, y]` **per frame** (it animates) and `feather_falloff`
(static). Run 6 also proved the feather-point **write** path: radii `[30, -15]`
with types `[0, 1]` at mid-segment positions round-tripped exactly.

**Q9, key interpolation - decided by the user, 2026-08-20.** `.rbj` `interp` is
an object `{"in": ..., "out": ...}`, each `hold` | `linear` | `ease`. No string
shorthand, so no adapter branches on type. Interval between keys A and B is
governed jointly by `A.interp.out` and `B.interp.in`, except that `hold` on the
outgoing side dominates. Driver: run 6's first real mixed-interpolation mask
produced `in=LINEAR, out=HOLD` immediately, which the old single-valued field
could not represent. `ease` was already per-side, so this makes the two
consistent. All four adapter paths in §9.1/§9.2 carry the per-side translation.

**Q7, feather representation - settled by run 3.** AE's `featherRadii` came back
**signed**: `[89.5565, 0, -46.6171, -1e-8]` against `featherTypes [0,0,1,1]`.
Type 0 is non-negative, type 1 non-positive, so the sign already carries the
direction and `featherTypes` is redundant on read. `.rbj` v1 therefore carries:

- `feather`: signed float per point, positive outward along the path normal.
  This is AE's `featherRadii` verbatim - no conversion at the AE adapter.
- `feather_offset`: optional `[x, y]`, canonical space. Nuke only. Carries the
  tangential component the scalar cannot express; other adapters ignore it.

Acceptance criteria 8 / 8a / 8b were rewritten against this and are now
satisfiable. Reversible if a Mocha adapter turns up a case that needs more.

**AE feather points are not one per vertex.** Run 3: four points on a
seven-vertex mask, three mid-segment, two on the same segment. Mid-segment
placement and same-vertex collisions are normal, not edge cases. `prd.md` §9.3
specifies snapping plus a keep-larger-magnitude collision rule. A zero radius is
an authored point that pins feather to zero width, not an absent one.

## Environment gotchas

Both host applications are **Windows-side**; this repo lives in WSL.

- **Nuke is drivable straight from the WSL shell** - it is headless (`--nc -t`),
  so the acceptance test needs no human. After Effects is not: its scripts are
  reached through `File > Scripts > Run Script File...` and it genuinely needs a
  person. Do not treat the Nuke half as blocked on the user.
- Nuke: non-commercial licence. `-t` alone fails (asks for a render licence);
  `--nc -t` works. NC caps Python-visible nodes at 10, and `scriptSaveAs(".nk")`
  silently writes nothing - only `.nknc` saves. Full invocation in
  `test/probe/README.md`.
- AE runs `C:\Users\shann\OneDrive\Desktop\probe_ae.jsx`, a **copy**. Sync it
  before every run or the old version runs and the results look unchanged:

  ```bash
  cp test/probe/probe_ae.jsx "/mnt/c/Users/shann/OneDrive/Desktop/probe_ae.jsx"
  ```

  The adapters are a **folder**, not one file - all five `#include` each other,
  so they only run from a directory that holds every one of them:

  ```bash
  cp ae/*.jsx "/mnt/c/Users/shann/OneDrive/Desktop/rotobridge_ae/"
  ```

  Synced there 2026-08-21, along with `test/probe/setup_ae_scene.jsx`, which
  lives in the same folder. Re-copy after any edit under `ae/`, for the same
  reason the probe needs it.

## Nuke is the hub, and that reorders everything, 2026-08-21

Stated by the user this session: every roto application on the team - After
Effects included, and Mocha, Silhouette and Flame later - ultimately feeds a
final Nuke comp. Interop should be as complete as possible in all directions,
but **X to Nuke is the product** and Nuke to X is convenience.

Two things follow, and they are not small.

**The Nuke importer is the most load-bearing file in the project.** Every
future adapter is another source pointed at it. Its warnings are what an artist
has to trust, which is why the silent-loss bug below was worth fixing the
moment it was found rather than after Phase 5.

**Phase 5 is no longer symmetric.** It was written as "comp AE's matte against
Nuke's". What matters is the AE-to-Nuke direction rendered in Nuke. The
Nuke-to-AE half of `test/test_ae_crossapp.js` is already exact at the document
level and can stay where it is.

### After Effects ease does not survive the crossing, and now says so

**Measured, `test/golden/ae_static_ease.rbj` through the Nuke importer:**

    eased_static    3 authored, 22 corrective   <- 25-frame range, fully dense
    linear_static   2 authored,  0 corrective   <- exact, free

AE linear to Nuke linear is perfect and costs nothing. An AE ease costs a key on
every frame. This file is the one that can say so: its layer does not move, so
nothing can be blamed on a baked ancestor transform. It also retro-explains
`ae_scene.rbj`, where `linear` needed 13 corrective keys - that was the layer
rotation, not an interpolation failure.

**The 22 keys are not waste.** A greedy optimal piecewise-linear fit of that
curve needs all 25 frames at 0.5 px over its 700 px of travel. The drift pass
used exactly 25. It is already doing the best available thing, and corrective
keys were already LINEAR by design for exactly the right reason
(`_apply_key_types`). Do not "optimise" this.

**What was actually broken was the silence.** `interp.to_nuke` reports an
ease/ease pair as `exact`, so `_key_plan` counted nothing and warned nothing.
For a Nuke-sourced file that is correct - Nuke writes no ease parameters, so
there are none to lose. For an AE-sourced file it meant a compositor opened a
shape keyed on every frame with no idea why. `_key_plan` now warns on the
presence of an `ease` block rather than on the interp pair, so it fires on
After Effects files and stays quiet on Nuke ones. Confirmed both ways.

### Why Nuke cannot hold it: probe `test/probe/probe_nuke_ease.py`

Output in `test/golden/nuke_probe/17.1v1/ease/`. Run it with no host setup;
it needs only Nuke. Four things it measured, two of which reversed an earlier
conclusion in this file:

- **A two-key roto AnimCurve is exactly the chord**, whatever interpolation
  type, slope or accel is written - except step, which holds. Case 109. Any
  measurement on two keys says nothing about tangents; use three.
- **Under the cubic types Nuke recomputes the slope** out from under whatever
  was written. Case 115 reads back `lslope=1.0101` after writing 5.0. So
  "stored and ignored" was the wrong description; it is stored and overwritten.
- **interpolationType 5 is a user-tangent mode.** Case 63 labelled 4, 5 and -1
  "other" and never identified them. Under 5, `lslope`/`rslope`/`la`/`ra`
  genuinely drive the curve. This reopened the question and then closed it the
  other way.
- **Only INTERIOR keys honour an authored tangent.** Case 117: every value of
  the first key's outgoing `rslope`/`ra` changes nothing, while the interior
  key's incoming `lslope`/`la` moves the segment hard. An After Effects ease
  needs both endpoints of a segment, so half of it is unreachable by
  construction. Best achievable fit to the real AE curve is 0.11 in unit terms,
  about 77 px on that shape against a 0.5 px tolerance, at parameters
  (`ra=-3.06`) that look nothing like AE's.

So `core/interp.to_nuke` dropping the ease parameters is not a deferral waiting
on Phase 5. It is the whole available vocabulary. **The dense layer is not
belt-and-braces for the hub direction - it is the mechanism.** `to_nuke`'s
docstring still says the question is deferred to Phase 4 because "After Effects
is the only place both sides of the mapping are observable at once"; that reason
died when `ae_static_ease.rbj` closed the AE half, and the answer is now above.

`test/test_ae_to_nuke.py` takes an optional second argument, a source `.rbj`, so
the static-ease file can be crossed without disturbing the six-shape run. Report
names are derived from it.

## The format has to be falsifiable, 2026-08-21

The failure the user named, in their words: an artist does a super tight, clean,
approved roto in After Effects and hands the `.rbj` to the Nuke artist who will
finalise the shot. There is a complaint about the roto. Someone opens the AE
file, it is perfect, and **the `.rbj` gets the blame.**

That is a trust requirement, not an accuracy one, and "be accurate" does not
cover it. The format is the only link in the chain nobody can inspect, so it
takes the blame by default unless a complaint can be settled with a number in
about thirty seconds.

**`.rbj` is already built for this and the project has not been exploiting it.**
The file carries the dense layer, which is the source application's own answer
for every vertex on every frame, so an importer can always measure what it
produced against what the source said. That number already exists - it is the
drift residual, and it is per shape and names its worst frame. No coordinate
claim in this project needs to be believed; it can be checked against the file.

**The hole in that argument, and it is the whole reason Phase 5 matters.** The
dense layer is what the source reported *through its API*, not what the source
*rendered*. A mis-sampling exporter produces a wrong reference that every
downstream check agrees with, reporting 0.0000 px while looking wrong. Rendered
pixels are the only thing that validates the reference the other checks depend
on.

### Where the blame would actually land

**Not on the ease bake.** It converges to the float32 storage floor, 3e-05 px.
It costs editability, not quality. Say so plainly when it comes up, so it does
not get blamed for something else's fault.

The three that can, none of which are vertex positions - which is where all of
the current verification lives:

1. **Feather anchor snapping. The most likely complaint by some distance.** A
   tight AE roto with feather points mid-segment has them moved to the nearest
   vertex, because Nuke can only anchor feather at a vertex. Geometry is
   bit-perfect and the softness edge is subtly different: exactly the scenario
   above. Measured on the real crossing - `feathered` logged **3 feather points
   snapped** from mid-segment, plus a collision on vertex 3 that kept radius 12
   and dropped a radius-0 point. The collision is the worse half: it turns a
   corner the artist pinned to zero width into a 12 px soft one. See "Where the
   fix has to live" below for the measurement.
2. **`ff`, the feather falloff profile.** Same signature: geometry identical,
   edge softness wrong, invisible to every check that exists.
3. **Motion blur.** Off-grid keys snap to whole frames. At whole frames that is
   harmless - the dense layer is baked from the source's own evaluation, so the
   rendered frame is right wherever the keys sat. But motion-blurred roto
   samples *between* frames, where Nuke interpolates linearly between baked
   frames and the source had a sub-frame shape. "The roto chatters under blur"
   is a plausible complaint and nothing here would catch it.

### The feather fix that may be available

Snapping is currently unrecoverable. It may not have to be: **split the bezier
segment at the feather anchor's parameter with de Casteljau and insert a vertex
there.** Subdivision reproduces the original curve exactly, so the geometry does
not move, and Nuke then has a vertex to anchor the feather on - carried exactly
rather than snapped. The cost is extra vertices the compositor sees.

#### Where the fix has to live, 2026-08-21

The gate written here used to be "are AE feather anchors static or animated,
answerable from `test/golden/ae_scene.rbj`". Both halves were wrong, and the
second one is the useful correction.

**The golden file cannot answer it, and no `.rbj` can.** `.rbj` v1 has no field
for a feather anchor location. Spec section 8 gives a point `c`, `in`, `out`,
`feather` and an optional `feather_offset`; section 11.1 defines `feather` as a
signed distance along the normal *at that vertex*. There is nowhere to put
`(segLoc, relSegLoc)`. The AE exporter calls `geom.snapFeatherPoints` at
`ae/rotobridge_export.jsx:163`, **per frame, before anything is written**, so
the anchor is destroyed at the source adapter. Nuke never had the chance to lose
it. Confirmed by dumping `feathered`: every frame carries four scalars and no
anchor, and they are constant only because that mask's path is never keyed
(`setup_ae_scene.jsx` calls `setValue`, not `setValueAtTime`; the motion in its
`c` values is the baked layer transform). The shape could not have shown anchor
animation even if AE had it.

**And animation is not the gate anyway.** A de Casteljau split is exact at
whatever parameter you give it, so an anchor that moves just means a different
split parameter on each frame. The vertex count stays constant, which is what
spec section 7.3 actually requires, and the dense layer stays exact frame by
frame. What degrades is the *sparse* layer: Nuke would interpolate the inserted
vertex as a vertex, in a straight line between authored keys, while the truth is
a point sliding along a curve. That is ordinary drift, and the drift pass
already measures and corrects it. Animated anchors cost keys, not accuracy,
which by the standing decision below is a price already agreed.

**The one case that genuinely breaks it** is narrow and worth naming: a feather
anchor that slides *past* an original vertex. The inserted vertex has to occupy
a fixed index in `points`, and crossing a vertex changes its ordinal position
around the ring. That is a topology change mid-shape and section 7.3 forbids it.
Detectable (watch for `seg + rel` crossing an integer) and warnable.

**So the fix is a format change, not an importer change.** The information has
to survive the AE adapter before Nuke can use it:

- Carry the anchor in the file. `spec/rbj-v2-draft.md` is where it goes. Either
  a `feather_anchor` alongside `feather` on the point, or better, lift feather
  out of `points` into its own per-frame list with its own `seg` and `rel`,
  which is what AE, Mocha (`edge_width`) and Silhouette all actually look like.
- Do the de Casteljau split in the **Nuke** importer, not the exporter. Nuke is
  the only host that needs the extra vertices; splitting at export would put a
  Nuke-shaped compromise into a host-neutral format and hand a 7-vertex shape
  back to the AE artist who authored 4.

**The unmeasured fact that now gates it**, and it needs a host: is
`featherRelSegLocs` the **bezier parameter** or an **arc-length fraction**? De
Casteljau splits at the parameter. If AE means arc length, splitting at `rel`
directly puts the anchor in the wrong place on any segment with asymmetric
tangents, and the fix quietly reintroduces the error it was built to remove. No
probe here has ever asked. Reading the value back cannot answer it either, since
AE returns what was written; it needs a render, so it is Phase 5 work rather
than a cheap scripted probe.

**What the snap actually costs, on the one real shape measured.** `feathered` is
a 300 px square with anchors `segLocs [0, 0, 2, 3]`, `relSegLocs [0.25, 0.75,
0.5, 0]`, `radii [30, -15, 12, 0]`. The radius-12 anchor sat at the midpoint of
segment 2 and landed on vertex 3: **150 px along the path**. Worse than the
distance, it collided with the artist's authored radius-**0** point on vertex 3
and won. So a corner deliberately pinned to zero feather width arrives 12 px
soft. The HANDOFF text above calls that collision "benign"; it is not, and this
supersedes it. Geometry bit-perfect, softness visibly wrong at a corner the
artist went out of their way to harden. That is the blame scenario, on file, in
the golden scene.

### A policy worth adopting, cheap

On a shape whose keys carry ease, tolerance 0.5 is the worst of both worlds:

    tolerance 0.5   3 authored + 22 corrective = 25 keys   0.5 px bound
    tolerance 0     25 keys (every frame)                  3e-05 px

**Identical key count.** The drift pass converged to dense on its own, so the
sparse mode paid every key of a full bake and accepted a four-orders-of-
magnitude worse bound for it. `_key_plan` already knows whether a key carries an
`ease` block, so a shape whose source shaped the curve could simply go dense.
Same keys, far better accuracy. Shapes with linear or hold keys keep the sparse
path, where it is genuinely exact and cheap (`linear_static`: 0 corrective).

The user's standing decision on the trade: **accuracy first, keys are an
acceptable cost.** "If that means more keyframes, we need to do it. If we later
find a way to more closely translate between systems, we can start to reduce
the additional keyframes." Do not optimise key counts at the expense of
fidelity; for ease specifically, plan on the bake being permanent rather than
temporary.

### `interp` is about the segment, not the property, 2026-08-21

**The defect.** `.rbj` read `interp` off the mask path property while `frames`
carried the composite, path through layer transform. Wherever the transform
animates the two disagree, and the sparse layer described timing the dense layer
next to it contradicted. Both directions were wrong on one shape:

- `mixed` frames 19-23 are **byte-identical** and frame 24 jumps 360 px. That is
  a hold. The key at 18 said `ease`, so Nuke ramped and the drift pass paid five
  corrective keys to put it back.
- `mixed` key 12 carries the artist's authored `out: hold`, but the layer moves
  underneath at ~11 px/frame, so the shape is **not** flat. Nuke stepped it and
  sat ~66 px wrong until the drift pass paid again.

**The spec already settled it**, which is what removed the design fork. Section
10.1 defines `hold` as "constant, no interpolation" and 10.2 as "the segment is
flat". That is a property of the **segment**, and `frames` is what the segment
renders as. Deriving it from the path property alone was never right; a hold in
layer space is not a hold in comp space.

**The fix.** `sparseKeys` now takes the baked header - `buildDocument` already
had it in hand, one line above the call - and `segmentVerdict` decides the
outgoing side from the bake. Only the outgoing side, because only it governs a
segment. Only the hold question, because linear-versus-eased is a fit and
belongs to the drift pass. An authored hold the bake contradicts warns once per
shape: geometry is unaffected, an editable held key is what is lost.

**The part that took two tries, and it is the session's recurring lesson.** The
first predicate asked "is every frame in [from, to) equal to `from`?" and was
**vacuously true** for adjacent keys, since there are no interior frames. It
turned four passing tests red by stamping `hold` on everything keyed on every
frame. The real rule is that a hold and a smooth interpolation are
**indistinguishable whenever their endpoints agree**, so there are two ways the
question is not observable at all: no interior frame, and a shape that is flat
at the far key too. `segmentVerdict` returns **null for cannot tell** and leaves
the authored answer alone. A `hold` is only claimed where the shape stands still
and then jumps, which is the only thing nothing else expresses.

**Verified on real host data, not only on the mock.** Replaying the predicate
over `test/golden/ae_scene.rbj` changes exactly two labels across six shapes:
`mixed` 12 `hold -> ease` and `mixed` 18 `ease -> hold`. Every other key of
every other shape is untouched.

**`test/ae_mock.js` gained an animating transform.** `spec.transform` members
may now be functions of time, the idiom `spec.pathAt` already used. Without it
the mock could not build a path that holds while the shape moves, so the larger
half of the defect was not reproducible host-free. Key times and transform
geometry stay independent on purpose: a mismatch between them is a state a real
comp can be in.

**Still outstanding, and it needs the host.**
`test/golden/ae_scene.rbj` was exported by the old code and still carries the
old labels. Until it is re-exported the golden files disagree with the exporter,
and the Nuke crossing report (`ae_to_nuke_report.txt`, `mixed` 5 authored + 15
corrective) is measured against the stale file. Expect roughly 15 corrective
keys to become 3.

The procedure is written down at `test/probe/README.md`, "Re-exporting the scene
golden". The part worth knowing before starting: **the re-export is only
believable if its diff is the one predicted here** - geometry identical, and
exactly two label changes, `mixed` key 12 out `hold -> ease` and key 18 out
`ease -> hold`. Anything else means the fixture moved rather than the exporter,
and the two are indistinguishable in the committed file afterwards.

`test/probe/diff_rbj.py` is what makes that check possible. A plain `diff` on a
thousand lines of pretty-printed floats cannot separate a one-ulp wobble in the
bake from a flipped `interp` label, so the tool reports geometry as a worst-case
pixel distance and labels one at a time. It was verified against a synthetic
copy of the golden carrying exactly the predicted change, and against one with a
key dropped and a vertex moved 0.75 px, so both halves are known to report.

## Next

**The frontier is feather anchoring, then Phase 5.** The AE ease question that
used to sit here is closed - see "Nuke is the hub" above. It is a "cannot", not
a "not yet", and it is recorded in `core/interp.to_nuke`.

1. **Implement `spec/rbj-v2-draft.md` section 6, feather anchors.** The format
   decision is taken - the user said yes on 2026-08-21 and the delta is written:
   `feather_model: anchored`, a per-frame `feather_points` list keyed by a
   single `t` in segment units, and a de Casteljau split in the Nuke importer.
   **Nothing of it is implemented.** `FEATHER_MODELS` in `core/rbj.py` is still
   `("per_point", "none")`, `version_for` knows only the `closed` clause, the AE
   exporter still calls `geom.snapFeatherPoints` unconditionally, and there is
   no split. Order: schema in both implementations, then `version_for`, then the
   AE exporter, then the Nuke importer.

   **One thing is unmeasured and it gates exactness, not the work.** Is AE's
   `featherRelSegLocs` a bezier parameter or an arc-length fraction? Section 6.4
   picks the parameter and pushes any conversion into the AE adapter, so the
   implementation is not blocked - but on curved segments the two differ, and
   until Phase 5 renders a comparison the result is "better than the snap",
   not "exact". Do not claim exact.

2. **Phase 5, one direction.** AE to Nuke, rendered in Nuke, same plate. It was
   written as a symmetric comparison; it is not one any more. The Nuke-to-AE
   half is already exact at the document level (`test/test_ae_crossapp.js`) and
   can stay there. Phase 5 is what validates the dense layer itself, and it is
   the only thing that can catch `ff` and the motion-blur gap.

3. **A durable per-shape verification record.** Small, and outsized value for
   the blame scenario. The import already computes everything needed - source
   contents, what arrived, measured deviation per shape, anything that could not
   be carried - and then puts it in console warnings that scroll away. Written
   next to the comp instead, the argument happens over evidence.

4. **Ease-then-type ordering, the last Phase 4 loose end, and a drift number
   cannot answer it.** `setTemporalEaseAtKey` forces a key to BEZIER and the
   importer sets the types afterwards. The export side of `mixed` proves the
   ordering works when *reading*. The symptom on import is a **hold key that
   renders smooth**, and the drift pass corrects positions either way, so it
   will never show up as drift. Someone has to look at the imported `mixed`
   mask's frame-12 key in the AE timeline and confirm it is still a hold. Low
   risk: the code does ease first and types after, the documented order.

   Optional, not blocking: `test/golden/ae_scene.rbj` is the **six**-shape
   export and predates masks 7 and 8, whose export is a separate golden
   (`ae_static_ease.rbj`). An eight-shape export would fold the static pair into
   the crossing test. `test/test_ae_to_nuke.py` reads `ae_scene.rbj`, so it
   would need re-running afterwards.

**Both Nuke acceptance tests pass and are re-runnable without anyone**, most
recently 2026-08-21 after the drift-gap change. Reports at
`test/golden/nuke_probe/17.1v1/phase6/`. `test_nuke_roundtrip.py` covers Phases
2, 3 and 6; `test_ae_to_nuke.py` is the AE-to-Nuke crossing. Sync, then run
either:

```bash
rm -rf "/mnt/c/Users/shann/rotobridge/rb" \
  && mkdir -p "/mnt/c/Users/shann/rotobridge/rb" \
  && cp -r core nuke test "/mnt/c/Users/shann/rotobridge/rb/"
mkdir -p "/mnt/c/Users/shann/rotobridge/out/run"
"/mnt/c/Program Files/Nuke17.1v1/Nuke17.1.exe" --nc -t \
    "C:\Users\shann\rotobridge\rb\test\test_nuke_roundtrip.py" \
    "C:\Users\shann\rotobridge\out\run"
```

The output directory must exist first - `test_ae_to_nuke.py` does not create it
and fails at the end if it is missing.

2. **Phase 5 - verify across both applications.** Same plate in both, comp AE's
   matte against Nuke's at each import mode, confirm the tolerance bounds hold.
   `test/test_ae_crossapp.js` already does the document-level half of the
   Nuke-to-AE direction and finds it exact, so what is left for Phase 5 is what
   a document comparison cannot reach: rendered pixels, and the AE-to-Nuke
   direction. Two questions are waiting on exactly this and should not be
   guessed at before it:

   - **AE ease ↔ Nuke `lslope` / `rslope` and `la` / `ra`.** Narrowed hard by
     Phase 4 rather than answered. AE ease to `.rbj` and back is not merely a
     measured factor of 100 now: `ae_static_ease.rbj` proved the whole curve
     reconstructs, 135 px of bow rebuilt from three keys to 0.0000 px. So the AE
     half is **exact and closed**, and everything unknown is on Nuke's side.
     `core/interp.to_nuke` is the one function that changes, and it should not
     change until a file has actually crossed and been rendered.
   - **`ff`, Nuke's feather falloff.** Nuke defaults it to 1.0 and its API never
     names the values; After Effects names both of its (`FFO_LINEAR` 7213,
     `FFO_SMOOTH` 7212). It round trips Nuke to Nuke because the same rule runs
     both ways, so only a crossing file exposes it.

3. **Phase 6 - extras. CLOSED, and open splines are done.** Both hosts have run
   them: the Phase 6 section of `test/test_nuke_roundtrip.py` passes, and After
   Effects carries one as data. `spec/rbj-v2-draft.md` is a **permanent draft**
   by decision, not a document awaiting a freeze - see "Open splines may not be
   worth a version number". Nothing here is outstanding, and no file should be
   written with `version: 2` on purpose.

   The inverted flag, mask expansion and richer ease fitting are still dropped
   with a warning, which is the correct behaviour and is tested as such. See
   `In flight` for why none of the three followed open splines into the draft.

## What Phase 4 decided, so it is not relitigated

**The plan said "port all four core modules". That was wrong, and smaller.**
Most of `core/geom.py` and all of `core/interp.py`'s tier machinery is Nuke's:
the matrix bake, `outward_normals`, `feather_scalar` and `off_normal_angle` have
no AE caller, and `sides_from_nuke` / `reduce_sides` / `to_nuke` exist to
collapse one type per axis per control point down to one per key, which After
Effects does not need because it already has one per key. What the AE side
needed was new code - `side_from_ae` / `side_to_ae` / `ease_from_ae` /
`ease_to_ae` - added to `core/interp.py` first, so the Python stays the
reference the ES3 mirrors. `timing` and `drift` ported whole. `drift.correct`
kept its signature exactly; it already took its host calls as arguments, which
is what made the ES3 version a transcription rather than a redesign.

**Two files, not one.** The schema is half the ported volume and mirrors
`core/rbj.py` one-to-one; folding it into the algorithms file would make one
unreadable file where `core/` has five readable ones. Both adapters `#include`
both.

**One divergence between the two implementations, and it is not fixable.**
JavaScript has a single number type, so the ES3 writer emits `1` where Python
emits `1.0`, and its validator cannot reject a `version` of `1.0` the way
`core/rbj.py` does. Both are the same JSON value and both readers accept either.
`test_the_only_divergence_is_how_whole_numbers_are_spelled` pins it, so a
*second* divergence fails a test instead of surfacing in a host.

**`json2.js` is not bundled**, though `prd.md` §9.1 asked for it. The only thing
it was wanted for is parsing, since the writer had to be hand-rolled anyway to
keep number arrays on one line (spec §2.1). `RB.rbj.parse` uses native `JSON`
when the host has it and falls back to json2's own documented technique
otherwise - prove the text holds only JSON tokens with a regex chain, then let
the language read it. That is about ten lines against about five hundred of
vendored code nothing here can verify. `prd.md` now says so.

**The mock interpolates, but only what has been measured or is definitional.**
It used to raise on any request between keys. That was the right instinct and
the wrong line: it made every drift-pass test impossible, so the pass would have
shipped with its arithmetic tested against a parabola and its *wiring* tested
against nothing. The line now sits at: two LINEAR sides interpolate straight
(run 6 section H measured it), a HOLD outgoing side freezes the segment (that is
what hold means), past the last key the last value stands (AE does not
extrapolate), and **BEZIER raises**. A file whose sparse layer is two straight
keys over a curved dense layer now really does drift under test - the same
construction `test_nuke_roundtrip.py` uses on the Nuke side.

**The import converts to layer space once, up front, frame-major.**
`compPointToSource` has no time parameter, but `setValueAtTime` and
`valueAtTime` both take their own - so baking every frame's target before the
drift pass starts means the playhead never moves again and the pass costs
nothing per iteration but arithmetic. Setting `comp.time` measured 5.75-20.89 ms
in Phase 0; paying it per pass would have cost more than the rest of the import.
Do not "simplify" this back into the pass.

**Interpolation is pushed by key time, never by key index.** The drift pass
inserts keys, and every index above an insertion moves. Re-push after every
pass, and match on the time - the Nuke side learned the same thing for the same
reason.

**Two performance decisions are assertions, not comments.** Criterion 11 is met
by loop shape, and loop shape is invisible in the output: an exporter making a
host call per vertex writes a byte-identical file and misses the criterion by
20x. So `test/ae_mock.js` counts host calls. `comp.time` is set once per frame,
not once per mask per frame. And the layer transform is **derived, not asked per
vertex** - three probes fix an affine, a fourth checks it at runtime, and a
frame that disagrees by more than 1e-4 px falls back to per-vertex host calls
and warns. 64 vertices cost what 4 do.

## Things the adapters must not lose

Phase 1 encoded what it could; the rest is still on the adapters.

- The AE export loop is **frame-major**. Across five runs a `comp.time`
  assignment plus one `sourcePointToComp` measured **5.75 to 20.89 ms**, against
  **0.02 to 1.52 ms** for `valueAtTime`. The absolute numbers swing by 4x run to
  run and are not trustworthy on their own; the ordering is, and `comp.time` was
  the more expensive one in every run. Mask-major blows criterion 11 on any
  multi-shape export. See `prd.md` §9.1 step 4.
- The Nuke importer must set the interpolation **per key**, not per curve.
  Nuke's default point-curve interpolation is curved, so writing keys and
  stopping produces smooth motion the artist did not ask for. See the
  enum-plus-one bullet below; `curveType` is the wrong knob.
- Feather is signed everywhere. Taking a magnitude anywhere in the pipeline
  silently flips inward feather to outward.
- Uniform feather animates, so it belongs in the dense `frames` layer, not on
  the shape. Reading it once per shape freezes it at frame 1.
- **Nuke key interpolation is the enum plus one** (cases 63 and 74). Write
  `InterpolationType.eLinear + 1`, never the bare value; `256` is the unset
  sentinel a fresh key reports. Step is outgoing-only, like AE's
  `keyOutInterpolationType`. This is the linear control, not `curveType`.
- **Nuke stores control point positions as float32.** The serialised form is
  eight hex digits (`x42c80000` is `100.0f`). A tolerance-0 round trip is exact
  to about 3e-05 px at typical magnitudes, not bit-identical to the file's
  float64. Do not chase that residual; it is the storage, not the arithmetic.
- **Apply a Nuke matrix as `mat * CVec3(x, y, 1)`.** `vec * mat` returns
  nonsense. `list(CMatrix4)` is 16 floats row-major with translation at indices
  3 and 7, which is what `core.geom.apply_matrix_point` assumes and what
  `test_nuke_roundtrip.py` cross-checks against Nuke's own operator.
- Transform tangents by moving the vertex and subtracting, never by zeroing the
  homogeneous term. Both are correct for an affine matrix, but only the first is
  independent of how Nuke maps a CVec3's third component. The AE adapters do the
  same thing for the same reason, through `sourcePointToComp`.
- **Layers carry their own transform** and neither matrix knows about the other
  (case 77). Flattening the tree means composing the whole ancestor chain, or
  geometry moves silently. Fixed in `_chain_matrix`; the round-trip test proves
  a shape authored at (100, 100) inside a layer translated (500, 25) exports at
  (600, 125). **Still unmeasured:** the order when a layer and a shape in it are
  both transformed. The export assumes shape-first and warns when it matters.
- **A layer transform contributes key times to the shape**, on both sides. It is
  baked into the exported points, so a layer that moves animates the geometry
  even when the path never does. On the AE side, read only the transform
  properties that move geometry - layer opacity is in the same group.
- **`append()` copies into the tree.** The object you passed goes stale and
  raises "associated c++ object is NULL" when touched. Re-fetch the live child
  from its parent, and again after `knob.changed()`, which invalidates
  `AnimAttributes` handles.
- **`getValue` auto-vivifies unknown attribute names** and returns 0.0 rather
  than raising, so it cannot tell an unset attribute from an absent one. That is
  why the layer blend question took four probes. Enumerate with `getName(i)`
  before believing a value.
- **`isDefault()` is not an identity test** - it returns False on an untouched
  transform (cases 30 and 77). Compare against identity numerically.
- Both apps use a breakable two-sided bezier handle. AE adds a discrete type per
  side; Nuke has one type per key plus `lslope`/`rslope` and `la`/`ra`. Untested
  hypothesis worth one probe: `lslope`/`rslope` may correspond to AE ease
  `speed`, and `la`/`ra` to `influence`, which would make tier-1 ease a direct
  numeric conversion rather than the approximation §7 assumes.
- **AE ease on a mask path is one-dimensional** (run 6 section G, "1 dim" on all
  three keys), which is what makes a single shape-wide `ease` the right storage.
  AE also reports an ease on every key whatever its type - it read influence
  16.667 off a LINEAR key - so read one only for a side that is actually `ease`.
- Writing a Nuke shape attribute: `attrs.getCurve(name)` then
  `AnimCurve.addKey(time, value)`. `AnimAttributes.addKey` introspects with four
  parameters but accepts two and is unusable. Never call `attrs.add(name, val)`
  on an attribute you also key - the constant shadows the curve silently.
- **Seconds to frames must round, never truncate.** AE reports 8.333333 s for
  frame 200 at 24 fps; truncation yields 199. `core/timing.py` rounds half up
  rather than using Python's `round`, which rounds half to even and would make
  the snap direction depend on the parity of the frame number.
- **`json.dumps` needs `allow_nan=False`.** It is not the default, and without
  it Python emits bare `NaN` / `Infinity` literals that spec §2.2 forbids and
  no JSON parser must accept. `core/rbj.dumps` sets it and validates first.
- The reference writer keeps arrays of numbers on one line. `indent=2` alone
  puts every coordinate on three lines, which defeats the diffability the format
  exists for.
