# RotoBridge - working state

Scratch record of where things stand. Detail lives in `prd.md` and
`test/probe/README.md`; this file only holds what those two do not.

Last updated: 2026-08-21 (both After Effects import bugs fixed host-free - stale
mask handles, and feather compared by array index; the drift pass now splits a
monotone gap instead of walking back from its end, which closes the
`hold`-over-a-moving-ancestor question; Phase 6 open splines drafted and
implemented host-free; Q10 closed)

## Status

`prd.md` is at **4.10**. Phase 0 is complete on both sides and **every open
question is closed** (Q6-Q9). **`spec/rbj-v1.md` is FROZEN** (2026-08-20).
Raw probe output is committed under `test/golden/nuke_probe/17.1v1/` (12 files,
10/10 cases) and `test/golden/ae_probe/` (6 runs; run 3 is the only one with
feather points, run 6 the only one with mixed key interpolation - both are
load-bearing evidence).

**Phases 1, 2, 3 and 4 are complete**, Phase 4 pending a run in After Effects
itself. `core/` holds the host-free geometry, timing, schema, interpolation and
drift code: stdlib only, no host imports, no file access, so it runs unchanged
under plain Python and under Nuke's embedded Python. `nuke/` holds the Nuke
adapter pair and `ae/` the After Effects one, over an ES3 mirror of `core/`.
`test/test_core.py` is **170 passing tests**, run with `python3
test/test_core.py` (not `unittest discover` - `test/` is deliberately not a
package). `./test/run.sh` runs all five host-free suites: **357 tests**.

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
first real After Effects export, 6 shapes, `version: 2`, 2026-08-21) and
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

**STOP HERE FIRST. One thing is waiting on After Effects.**

**Re-run the six-shape import with the subset prompt blank.** Both import bugs
are now fixed and tested host-free, and neither has ever run in After Effects.
It confirms two things at once:

- the **stale mask handle** fix - six shapes importing at all, rather than
  failing with "object invalid";
- the **feather anchor** fix - `feathered` converging, rather than warning that
  27.0000 px is unaccounted for at frame 15.

Re-copy `ae/*.jsx` to the Desktop folder first; both fixes are in there. Both
probes have run and both are described in full under "The AE import".

**Nuke is not blocked on anyone** - it runs headless from this shell. Both Nuke
runs pass: Phase 6 open splines, and the AE-to-Nuke crossing.

No open questions in the `prd.md` §15 sense - Q10 closed 2026-08-20.

**Open splines are drafted, not frozen** (`spec/rbj-v2-draft.md`). `closed`
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
  global sign still comes from the implicitly-closed area. That last part is
  **unverified across applications**, exactly like `ff`: one rule run both ways
  round trips within a host and is only exposed by a crossing file.
- **The document round trip is exact; the rendered one is not claimed.** Nuke
  renders an open spline as a stroke whose width and end caps are **node**
  knobs (`openspline_width`, the two end types) with no per-shape attribute to
  carry them, and what After Effects renders an open mask path as has never
  been measured - no probe run authored one. Both adapters warn, and the
  importers warn again when the file came from the other application.

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
`linear_static` is the calibration: it must come back with **zero** corrective
keys, and if it does not, nothing about 8 is worth reading. `eased_static` is
then the real test of whether `.rbj` ease reproduces After Effects' own curve.
**Not yet run.**

**The two hosts agree to a thousandth of a pixel**, which is the result that
does survive from this run. The same shapes, imported independently by two
adapters into two applications:

| shape | After Effects | Nuke |
|---|---|---|
| `linear` | 0.3733 px @ frame 8 | 0.3723 px @ frame 9 |
| `mixed` | 0.4615 px @ frame 8 | 0.4616 px @ frame 8 |
| `opened` | 0.2584 px | 0.2577 px |

Two independent drift passes over two independent geometry pipelines landing on
the same residual at the same frame is the geometry core being genuinely shared,
rather than two implementations that merely both look plausible.

### The AE import: two bugs, both fixed host-free, 2026-08-21

Importing each shape on its own isolated it. Five of six converged; **only
`feathered` failed**, and it is the only mask with per-point feather. Both bugs
are now fixed host-free and neither has been confirmed in the host.

| shape | corrective | worst drift | |
|---|---|---|---|
| `linear` | 7 | 0.3733 px @ 8 | ok |
| `eased` | 20 | converged, every frame keyed | ok |
| `mixed` | 9 | 0.4615 px @ 8 | ok |
| `offgrid` | 4 | 0.3957 px @ 17 | ok |
| `opened` | 3 | 0.2584 px @ 16 | ok |
| `feathered` | 18 | **27.0000 px @ 15** | **ran out of passes**, fixed below |

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
is exactly why nothing caught it. **Not yet confirmed in the host.**

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

**Not yet confirmed in the host.** The six-shape import is the confirmation, and
`feathered` should now converge instead of warning.

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

## Next

1. **Confirm both import fixes in the host.** Both probes have run, both bugs
   are fixed, and the reasoning is above. What is left is a six-shape import
   with the subset prompt blank. Nothing needs rebuilding: the export is
   committed as `test/golden/ae_scene.rbj`. Re-copy `ae/*.jsx` to the Desktop
   folder first.

   Then re-run the **six-shape** import to confirm the stale-handle fix in the
   host. Nothing needs rebuilding: the export is committed as
   `test/golden/ae_scene.rbj`. Re-copy `ae/*.jsx` to the Desktop folder after
   any edit.

1b. **Two Phase 4 checklist entries are still unanswered, and the current scene
   cannot answer either.** Both need a run of the rebuilt scene, whose masks 7
   and 8 sit on a static layer:

   - **Bezier ease reimported.** The export half is settled - AE ease reaches
     `.rbj` exactly, factor of 100, measured. Whether the *importer* reproduces
     AE's own curve is what `eased_static` is for. Read `linear_static` first:
     it must come back with zero corrective keys or the rig is wrong before ease
     is reached.
   - **Ease-then-type ordering.** `setTemporalEaseAtKey` forces a key to BEZIER
     and the importer sets the types after. The export side of `mixed` proves
     the ordering works when *reading*. The symptom on import is a hold key that
     renders smooth.

1a. **The Nuke Phase 6 run PASSED, 2026-08-21.** Report committed at
   `test/golden/nuke_probe/17.1v1/phase6/roundtrip_report.txt`. The new section
   read `exported closed=False, version=2`, the render-settings warning present,
   `rebuilt 'open_spline' with 4 points, open=True`, and worst deviation
   **0.000e+00 px** - exact, not merely inside the float32 floor, because the
   fixture is static so nothing re-evaluates through an interpolation. Every
   Phase 2 and 3 stage still passes unchanged and `roundtrip.rbj` / `sparse.rbj`
   regenerate **byte-identical** to the committed goldens, so open splines cost
   the existing paths nothing.

   To re-run it:

   ```bash
   rm -rf "/mnt/c/Users/shann/rotobridge/rb" \
     && mkdir -p "/mnt/c/Users/shann/rotobridge/rb" \
     && cp -r core nuke test "/mnt/c/Users/shann/rotobridge/rb/"
   "/mnt/c/Program Files/Nuke17.1v1/Nuke17.1.exe" --nc -t \
       "C:\Users\shann\rotobridge\rb\test\test_nuke_roundtrip.py" \
       "C:\Users\shann\rotobridge\out\phase6"
   ```

   It writes `phase6/roundtrip_report.txt` whether it passes or fails. Wanted
   from the new Phase 6 section: `exported closed=False, version=2`, the shape
   rebuilt `open=True`, deviation at the float32 floor, the render-settings
   warning present rather than `MISSING`, and the verdict line ending "dense,
   sparse and open".

1c. **A `hold` over an animated ancestor transform is RESOLVED**, 2026-08-21 -
   in the drift pass, not the exporter. See the section above for the mechanism
   and for why the exporter is the wrong place. Nothing is outstanding.

2. **Phase 5 - verify across both applications.** Same plate in both, comp AE's
   matte against Nuke's at each import mode, confirm the tolerance bounds hold.
   `test/test_ae_crossapp.js` already does the document-level half of the
   Nuke-to-AE direction and finds it exact, so what is left for Phase 5 is what
   a document comparison cannot reach: rendered pixels, and the AE-to-Nuke
   direction. Two questions are waiting on exactly this and should not be
   guessed at before it:

   - **AE ease ↔ Nuke `lslope` / `rslope` and `la` / `ra`.** Narrowed by Phase 4
     rather than answered: AE ↔ `.rbj` ease is now a measured factor of 100 in
     both directions, so what is left is specifically the Nuke half.
     `core/interp.to_nuke` is the one function that changes, and it should not
     change until a file has actually crossed.
   - **`ff`, Nuke's feather falloff.** Nuke defaults it to 1.0 and its API never
     names the values; After Effects names both of its (`FFO_LINEAR` 7213,
     `FFO_SMOOTH` 7212). It round trips Nuke to Nuke because the same rule runs
     both ways, so only a crossing file exposes it.

3. **Phase 6 - extras.** Open splines are **done host-free** and drafted as
   `spec/rbj-v2-draft.md`; what they need is a run, and both checklists already
   carry it. On the Nuke side that is the new Phase 6 section of
   `test/test_nuke_roundtrip.py`, which asserts `closed: false`, `version: 2`,
   the flag surviving the round trip and the geometry holding to the float32
   floor. On the After Effects side it is **mask 6, `opened`**, of
   `test/probe/setup_ae_scene.jsx` - and the thing to do there is not to read
   the file but to **look at the matte**, because whether After Effects fills
   an open path, and how, is the one unmeasured fact standing between that
   draft and a freeze (`spec/rbj-v2-draft.md` section 7).

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
