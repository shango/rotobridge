# RotoBridge - working state

Scratch record of where things stand. Detail lives in `prd.md` and
`test/probe/README.md`; this file only holds what those two do not.

Last updated: 2026-08-22. **Phase 4 is complete and has met both hosts.**

Earlier this session: both After Effects import bugs found, fixed and confirmed
in the host (stale mask handles; feather compared by array index); the drift
pass now splits a monotone gap instead of walking back from its end, which
closed the `hold`-over-a-moving-ancestor question; bezier ease measured and
exact; and open splines settled as a **permanent draft** after After Effects
turned out to produce no alpha from an open mask path at all.

Then the project got a use case, and it reordered the work. **Nuke is the hub**
and **the format has to be falsifiable** - see the two sections under Status.
The AE ease question is closed as a "cannot", not a "not yet". Feather anchoring
closed 2026-08-22, and the durable import record with it. **Phase 5's Nuke half
is built and passing** (`test/test_ae_to_nuke_render.py`, 2026-08-22), with the
measurement checked against arithmetic before it is trusted. **The rendered
comparison is out of scope** - this tool moves roto spline data between
applications, and that is what is measured. Everything that was blocked on
After Effects has now been answered in After Effects except the matte, which is
not being rendered.

**The last change of the session, and the largest behavioural one: the After
Effects exporter now conforms `ease` to `linear` before the file is written**
(section "The export conforms ease to linear"). An AE `.rbj` no longer carries
an `ease` block at all. Read that section before touching the exporter, the
crossapp suite or the goldens.

**Confirmed in the host 2026-08-22**, and it is the wiring rather than the rule:
`test/golden/ae_static_conformed.rbj` is a real conformed export, and the
ExtendScript fit inside After Effects chose exactly the key frames
`core.drift.linear_fit` chooses here. **The scene golden was then re-exported
too, and the last open item with it** - the alert matched a prediction derived
from the committed bake, and the crossing went from 78 corrective keys to 2.
See "Next". The 2 that remain are a Nuke step key bending the segment
that arrives at it - measured, and the mislabel it exposed is now fixed in both
directions.

## Status

`prd.md` is at **4.11**. Phase 0 is complete on both sides and **every open
question is closed** (Q6-Q9). **`spec/rbj-v1.md` is FROZEN** (2026-08-20).
Raw probe output is committed under `test/golden/nuke_probe/17.1v1/` (12 files,
10/10 cases) and `test/golden/ae_probe/` (6 runs; run 3 is the only one with
feather points, run 6 the only one with mixed key interpolation - both are
load-bearing evidence).

**Phases 1, 2, 3 and 4 are complete**, and Phase 4 has now met both hosts: the
export and the six-shape import both pass in After Effects, and both Nuke
acceptance tests pass. `core/` holds the host-free geometry, timing, schema,
interpolation, drift and import-record code: stdlib only, no host imports, no
file access, so it runs unchanged under plain Python and under Nuke's embedded
Python. `nuke/` holds the Nuke adapter pair and `ae/` the After Effects one,
over an ES3 mirror of `core/`. `test/test_core.py` is **303 passing tests**, run
with `python3 test/test_core.py` (not `unittest discover` - `test/` is
deliberately not a package). `./test/run.sh` runs all five host-free suites:
**578 tests**.

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
the file that answered the ease question),
**`test/golden/ae_static_conformed.rbj`** (that same comp exported again with
the conform in place, 2026-08-22 - the pair is what pins the exporter's
ExtendScript fit against `core.drift.linear_fit`) and
**`test/golden/held_over_moving_layer.rbj`** (hand-built: a `hold` the dense
layer contradicts - see below) and **`test/golden/ae_scene_via_nuke.rbj`**
(that scene after a round trip through Nuke - the AE-to-Nuke artefact, and the
only committed evidence of what Nuke *writes* after reading an After Effects
file). All of them are validated with no Nuke present by `test/test_core.py`,
and `ae_static_ease.rbj` and `held_over_moving_layer.rbj` are **run through the
After Effects adapters** by `test/test_ae_crossapp.js` - see below.

**That sentence was not true until 2026-08-22, and two files were the reason.**
`ae_scene.rbj` - the largest artefact in the project and the only v2 one - was
read by nothing at all; every mention of it in the tree was a comment. And
`ae_scene_via_nuke.rbj` was committed once at `3db2477`, referenced nowhere,
regenerated by nothing, and had drifted **286 px of geometry** from what the
same pipeline produces, because the conform, the anchored re-export and the
step-key fix all landed underneath it. Both now have a class in
`test/test_core.py`, and both were mutation-checked rather than merely run:
the wrong solid selected, a hand-edited `version`, a stale build leaving an
`ease`, an anchor sliding 0.05 on one frame, the open spline reverting, a
dropped key, the anchored feather arriving snapped instead of split, and the
step key claiming a straight arrival again - each one fails, and the last four
fail exactly one test each.

**`ae_scene_via_nuke.rbj` is regenerated by the crossing run**, which writes it
to the output directory as `ae_to_nuke_back.rbj`. Copy it back whenever
`ae_scene.rbj` or either adapter moves, the same way the reports are copied
back. A derived file nobody reads is not evidence; it is a claim with no date
on it.

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
`ae/lib/rotobridge_import.jsx` appends `(line N)` when After Effects supplies one.

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

### The second After Effects host run, 2026-08-22

`test/probe/probe_ae_phase5.jsx`, four items in one visit. **Three closed, and
the fourth was declined by the user: no matte is being rendered.** Report kept
by the user at `Desktop/rotobridge_ae/rotobridge_phase5_probe.txt`.

**`File.open("a")` APPENDS. The import record is sound.** Two records written
and read back in order, in After Effects 25.6x101. This was the one call in the
adapters no test could reach - `test/ae_mock.js` honoured `"a"` because the
JavaScript Tools Guide documents it, not because a host had ever done it. The
read-then-write fallback through `ae.readText` / `ae.writeText` is not needed
and should not be built. The live import wrote its record the same run, to
`ae_scene.rotobridge.txt` beside the `.rbj`, which is the unsaved-project
anchor working as designed.

**The `mixed` hold key survives the import, and so does every other side.**
Frame 18 reads `BEZIER` in, `HOLD` out, so `setInterpolationTypeAtKey` after
`setTemporalEaseAtKey` keeps what the ease call set. That closes the last Phase
4 loose end. The stronger result is the whole key list, file against host:

| frame | `.rbj` says | After Effects has |
|---|---|---|
| 0 | `linear` / `linear` | LINEAR / LINEAR |
| 6 | `ease` / `ease` | BEZIER / BEZIER |
| 12 | `linear` / `ease` | LINEAR / BEZIER |
| 18 | `ease` / `hold` | BEZIER / HOLD |
| 24 | `linear` / `linear` | LINEAR / LINEAR |

Every authored key round trips per side, which is the Q9 model arriving intact
in the host rather than only in the mock.

**Two host facts about rendering, kept because they cost a run.**

- **A stock After Effects 25.6x101 offers no EXR and no PNG output-module
  template.** The sequence templates it has are `Alpha Only`,
  `Multi-Machine Sequence`, `Photoshop` and `TIFF Sequence with Alpha`. Adobe
  documents `Format` as readable and **not settable**, so a script can only
  reach a format by applying a named template - the Output Module dialog does
  offer OpenEXR by hand, but no script can select it. Anything automating a
  render here has to go through `TIFF Sequence with Alpha`.
- **`Channels` and `Color` are read-only when the format cannot offer a
  choice.** Under the default H.264 both refuse with "Property is read-only",
  because H.264 carries no alpha. They are settable once an alpha-capable
  template is applied. So a refusal there is a symptom of the format, not of
  the API.

Also measured, and it changes an instruction that has been repeated since
Phase 5 was written: **the project is ACEScg at 32 bpc, and that cannot move
the measurement.** Alpha is not colour managed. "No colour management" was
never a requirement; an alpha channel is.

**And the rendered comparison is out of scope, stated by the user 2026-08-22:
this tool moves roto spline data from one application to another.** That is the
job, and it is the thing that is measured - geometry to 6.1e-05 px across the
crossing, every per-side key intact, feather carried by anchor rather than
snapped. A rendered matte was only ever a proxy for those, and it is a proxy
for two questions that are about how a host *draws* a shape rather than about
whether the shape arrived: `ff`, and where an anchored feather sits along a
curve (`spec/rbj-v2-draft.md` section 6.4). Both stay open as rendering
questions and neither is a data loss - the file carries what the source said in
both cases.

Do not reopen this by proposing a render. `test/test_ae_to_nuke_render.py` and
`test/probe/probe_ae_phase5.jsx` stay in the tree on the same footing as
`spec/rbj-v2-draft.md`: built, passing, costing the live paths nothing, and
waiting on a use that has not appeared.

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
bug 1.

**The table above is against the PRE-re-export golden. Five of its six rows
survived the re-export unchanged; `mixed` did not.** Re-measured in After
Effects 2026-08-22 against the current `ae_scene.rbj`: `linear` 11 corrective /
0.0002 px at 19, `eased` 20, `feathered` 3 / 0.2148 px at 8, `offgrid` 4 /
0.3809 px at 13 and `opened` 3 / 0.2584 px at 16 all come back to the digit -
`feathered` included, which went from `per_point` to `anchored` between the two
runs and is the strongest confirmation available that the re-export moved no
vertex. **`mixed` is now 6 corrective and 0.2007 px at frame 17**, against 11
and 0.1000 px at 16, because the re-export moved its hold from frame 12 to 18.

**So the "two hosts agree to a thousandth of a pixel on `mixed`" result below is
superseded, and what replaced it is not a disagreement.** Nuke reads the same
file as 11 corrective and 0.4503 px at frame 10 (committed in
`phase6/ae_to_nuke_report.txt`, and re-run 2026-08-22 to confirm it is not a
regression). The gap is the documented one: a key that is `linear` in and `hold`
out cannot exist in Nuke, so Nuke sets it smooth and buys the positions back
with corrective keys, while After Effects represents it exactly and needs five
fewer. Both are inside the 0.5 px tolerance. The shapes that still agree across
the two hosts are the ones carrying no per-side key - `feathered` 0.2148 against
0.2143, `opened` 0.2584 against 0.2577. Three things in that table are worth reading twice:

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
`ae/lib/rotobridge_import.jsx`. It is deliberately **not** a raw anchor match on
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

## The export conforms ease to linear, 2026-08-22

**Decided by the user**, on the grounds that the Nuke artist should get an
accurate spline without touching a tolerance control, and that After Effects is
likely the only source application needing this reinterpretation - so the onus
belongs on it. Implemented in `ae/lib/rotobridge_export.jsx` `conformEase`, over
`core/drift.linear_fit` / `RB.drift.linearFit`.

**And a correction to what this file used to say.** The masks in
`setup_ae_scene.jsx` sit on a scaled, rotating layer, which is why `linear`
bows 13.2 px off its own chord and every shape there needs corrective keys.
**That is a fixture property, not a roto property.** In production the layer is
static and only the shape animates, so the derived-affine path barely matters
and the corrective-key counts from the six-shape scene say almost nothing about
what the tool costs. The numbers that do are masks 7 and 8, on `RotoBridge
static`, crossing to Nuke at the default tolerance:

| shape | authored | corrective | worst |
|---|---|---|---|
| `linear_static` | 2 | **0** | 0.0001 px |
| `eased_static` | 3 | **22** | 0.0000 px |

**Linear costs nothing and ease costs a key on every frame.** That is the whole
problem, and it is one member of the vocabulary.

**The rule is narrow on purpose.** Only `ease` sides are rewritten. `linear`
already crosses exactly and `hold` maps to Nuke's step, so **rewriting a hold
would be paying keys to destroy something that transfers for free**: a frozen
interval becomes a slide, and the fit then buys a key on every frame of it to
flatten it again. `linear_fit` takes the held key frames for exactly this
reason and prices a held segment as flat. Both implementations have a test that
fails without it.

**Verified end to end on real host data, which the mock cannot produce.**
`test/ae_mock.js` refuses to bake a bezier segment, so the only genuinely eased
dense layer in the project is one After Effects really wrote. Applying the same
rule to `test/golden/ae_static_ease.rbj` and crossing the result into Nuke
17.1v1:

    before   eased_static   3 authored, 22 corrective
    after    eased_static  25 authored,  0 corrective, 0.0000 px

Same 25 keys either way. The difference is that they are now in the file rather
than manufactured at the far end, the count no longer depends on a tolerance
the compositor chose, and Nuke's "carries authored ease" warning does not fire.

**And now crossed as a host artefact rather than as a Python rewrite,
2026-08-22.** The measurement above applied `core.drift.linear_fit` to the
pre-conform file here and crossed the result, so the keys were Python's. The
crossing documented at `test/probe/README.md`, "AE to Nuke crossing", now names
`test/golden/ae_static_conformed.rbj` - the file After Effects wrote with its
own `RB.drift.linearFit` - and it lands the same numbers: **25 authored, 0
corrective**, geometry 3.0518e-05 px, field-by-field diff empty, PASS. The
pre-conform file was re-run the same day through the same harness and still
reads 3 / 22, so the pair is a like-for-like comparison. Reports at
`test/golden/nuke_probe/17.1v1/hub/`.

**One warning does fire, and it is not a loss.** The prediction said none
would; the run prints the **exporter's** conform warning, replayed, because
`import_document` seeds its list with the file's own. The discriminator is the
wording rather than the count, and the two hub reports sit side by side saying
it: `shape 'eased_static': 3 key(s) carry authored ease` is the Nuke importer
reporting what it cannot hold, and `mask 'eased_static': 6 key side(s) carried
temporal ease` is After Effects quoting what it already paid. Only the first
must be absent.

**The cost, and it is real: an After Effects `.rbj` no longer carries an `ease`
block at all.** Pinned endpoints and transform keys are spelled `ease` too
(spec section 10.3, "parameters unknown"), so the conform fires on essentially
every export and the vocabulary disappears from AE-written files. Consequences
worth carrying forward:

- **AE to `.rbj` to AE no longer reproduces authored ease timing.** It
  reproduces the shape within 0.5 px on every frame. That is the same trade
  Nuke has always taken, and the dense layer is still the ground truth - but
  the 0 corrective / 0.0000 px round trip recorded under "Bezier ease, answered
  in the host" was measured before this and describes the old behaviour.
- **`interp.easeFromAe` is still live and still tested.** The presence of an
  `ease` entry is what separates a curve the artist drew from one the exporter
  invented, and only the first is warned about. A file whose only eased sides
  are pinned endpoints is conformed silently, because nothing the artist made
  was lost.
- **The crossapp finding "a bare ease comes back carrying AE's default" is
  retired.** It was true and is not any more: a parameterless key now stays
  parameterless instead of acquiring influence 16.667 on the way through.

**One line turns it off**: `CONFORM_TOLERANCE` in `ae/lib/rotobridge_export.jsx`.
Nothing else branches on it.

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
- **AE runs the scripts out of this repo, over the WSL share** (2026-08-24).
  The Windows desktop copies are gone; everything lives here and nothing is
  deployed. The host reaches the tree at

  ```
  \\wsl.localhost\Ubuntu-24.04\home\sgold\dev\repos\rotobridge\
  ```

  so `Run Script File...` points at `ae/rotobridge_panel.jsx` or anything under
  `test/probe/` directly. This removes the stale-deployment failure below
  rather than guarding against it: there is no second copy to fall behind.

  Not yet measured in the host - see `test/probe/README.md` for what to check
  and what to fall back to if `#include` will not resolve across the share.

  Superseded, kept because the reasoning still applies to any copy: the
  adapters are a **folder**, not one file - all six `#include` each other, so
  they only run from a directory holding every one of them, and
  `setup_ae_scene.jsx` is not among them. What follows described the copy that
  no longer exists. `test/probe/probe_ae_phase5.jsx` goes to the same
  desktop folder and is standalone - it includes nothing, so it runs from
  anywhere.

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
`ae/lib/rotobridge_export.jsx:163`, **per frame, before anything is written**, so
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

**Done, 2026-08-21.** `test/golden/ae_scene.rbj` was re-exported and the diff
was the one predicted: `mixed` key 12 out `hold -> ease`, key 18 out
`ease -> hold`, the new `mask 'mixed'` warning, and geometry **bit-identical**
rather than merely within tolerance. `mixed` holds its mask path from frame 12
to 24, but the layer's rotation is keyed at 6 and 18, so the composite only
stops moving at 18, which is where the hold now sits.

The crossing was re-run against the fresh file and
`test/golden/nuke_probe/17.1v1/phase6/ae_to_nuke_report.txt` updated. `mixed`
went from 5 authored + 15 corrective to 5 + 11, which puts it in line with every
other moving shape (11 to 13) instead of being the outlier. **The prediction
written here beforehand said "roughly 3" and that was wrong** - the reasoning
behind it only ever accounted for the false hold over 12 to 18, and the drift
pass still has to fit a cubic to a real After Effects curve over that segment
like it does on every other shape. What the fix actually bought is the 19 to 23
block, now exactly flat and needing nothing. Worst error rose from 0.1000 px to
0.4503 px, still inside the 0.5 tolerance: fewer corrective keys means more
residual, and that is the trade the tolerance exists to make.

**How the first attempt failed, because the procedure was blind to it.**
The scene rebuilt and re-exported cleanly, the alert read 6 shapes / 600 points
/ 4 warnings, and the diff came back with no key changes at all - which reads
exactly like "the exporter change did nothing". It had not run. The scripts on
the Windows side were a copy taken before `0c1b3af`, and nothing in the
procedure looked at them. That is the arrangement's structural blind spot: the
code under test lives on one machine and the acceptance check on another, and a
stale deployment produces a plausible file, a plausible alert, and a
wrong-shaped diff whose natural reading is that the *fixture* moved. The
procedure at `test/probe/README.md`, "Re-exporting the scene golden", now opens
by copying the scripts and `diff`-ing them, and the alert's warning count is
part of the check - four instead of five is the fingerprint of a pre-`0c1b3af`
build.

That run still paid for itself. Its geometry was bit-identical to the committed
golden, so `setup_ae_scene.jsx` plus the exporter reproduce the bake exactly
across a fresh project, and any geometry line in a future diff is signal rather
than host noise.

The prediction was also wrong by omission, and the fix for that generalises: it
was written from the two label changes alone and missed that the new code emits
a warning, so the real diff is three lines and the alert reads five. It was
caught by simulating the exporter's `segmentVerdict` in Python over the bake
from the failed run before asking for the re-export, which is worth doing
whenever a host artefact is about to be regenerated - the bake is already in
hand, and a prediction derived from it is cheaper than a second host round.

`test/probe/diff_rbj.py` is what makes the check possible at all. A plain `diff`
on a thousand lines of pretty-printed floats cannot separate a one-ulp wobble in
the bake from a flipped `interp` label, so the tool reports geometry as a
worst-case pixel distance and labels one at a time. It was verified against a
synthetic copy of the golden carrying exactly the predicted change, and against
one with a key dropped and a vertex moved 0.75 px, so both halves are known to
report.

## Next

**Nothing is blocked, nothing is in flight, and as of 2026-08-22 nothing is
open.** Phases 0-4 are complete and both hosts have run them; Phase 5's
rendered comparison is retired as out of scope; the export conform is built,
tested, verified against real host data and now carried by both goldens. The
list below is history. The one finding that was open when the goldens were
re-exported - `out: hold` reporting exact in Nuke when the arriving side is
`linear` - was measured, fixed in both directions and verified in the host the
same day.

**THE LAST OPEN ITEM IS CLOSED, 2026-08-22.** `test/golden/ae_scene.rbj` is
now a conformed export, re-exported from the same comp with the current
adapters and committed over the old one (the pre-conform six-shape file is at
`5f732e2`). **The alert matched the prediction exactly** - 6 shapes, 600
points, 10 warnings, 74 authored keys, and every per-shape count with it:
`linear` +11, `eased` 6 sides and +20, `mixed` +6, `feathered` +3, `offgrid`
+4, `opened` +3. `diff_rbj.py` reports label changes only and **`geometry:
identical`**, which is what a conform that reads the bake and never writes to
it has to look like.

**The prediction was derived, not guessed, and that is the part worth reusing.**
The conform's fit input is the dense layer, which is already committed, so
running `core.drift.linear_fit` over the golden's own frames predicted the
whole run before it happened - key frame lists, residuals, which of the two
warning texts each shape gets. Method and table are in `test/probe/README.md`
under "The export conforms ease". A re-export whose diff cannot be predicted
that way is measuring a fixture that moved.

**What the conform bought, measured in Nuke 17.1v1** (`test_ae_to_nuke.py`
PASS, report at `test/golden/nuke_probe/17.1v1/phase6/`), at the default 0.5 px
tolerance, before against after:

| shape | was | now |
|---|---|---|
| `linear` | 4 authored, 13 corrective | **15, 0** |
| `eased` | 5 authored, 20 corrective | **25, 0** |
| `mixed` | 5 authored, 11 corrective | **11, 2** |
| `feathered` | 4 authored, 12 corrective | **7, 0** |
| `offgrid` | 5 authored, 11 corrective | **9, 0** |
| `opened` | 4 authored, 11 corrective | **7, 0** |

Five of six shapes arrive needing **no correction at all**, and the file is
also *cheaper*: 76 keys in Nuke against 105 before. The exporter's fit spends
keys better than the importer's binary search does, because it can see the
whole curve at once where the drift pass only ever splits a gap. Geometry is
unchanged at 6.1e-05 px worst, the float32 floor. Two warnings stopped firing:
Nuke's "carries authored ease", and "1 key(s) carry a different interpolation
on each side" - the latter because `mixed` key 12 was `linear`/`ease` and is
now `linear`/`linear`.

**`mixed`'s 2 corrective keys were a real finding, and they are not the
conform's. FIXED 2026-08-22.** Probed in the host: frames 16 and 17 sit **2.55
px and 2.05 px** off the dense layer before correction, and every other frame is
at the float32 floor or inside the conform's promise. That is the segment
15 -> 18 arriving at `mixed`'s `hold`. Nuke's point at frame 16 is 507.561 where
both the file's bake and a straight line say 505.155 - so Nuke is not drawing
the line the file asked for; **a step key flattens its own incoming tangent and
the arriving segment decelerates into it.**

**The evidence was in Phase 0 the whole time, and the inference on top of it was
the bug.** Case 63 recorded `set 1 -> eval(25)=0.6759`, which its own table
labels the *cubic* default, against `0.4898` for an exact linear. That was read
as "step is outgoing-only, so the incoming side says nothing", and section
10.1's "writers put `linear` where a side is meaningless" was applied to it. Not
freezing an interval is not the same as leaving it alone. **`linear` was
doing double duty as "no information", and one side of the code wrote it in that
sense while the other read it as a claim.** Section 10.3 already had the honest
spelling: `ease`, "smooth, parameters unknown, rely on the drift pass", which is
exactly what a flat-handled cubic is.

**Both directions were mislabelling it, because it is one function each way.**

- `sides_from_nuke(STEP)` now returns **`{in: ease, out: hold}`**, not
  `{in: linear, ...}`. A Nuke file with a step key used to claim a straight
  arrival Nuke never drew, and an After Effects importer would have built one.
- `to_nuke` now returns **`exact=False` when `out` is `hold` and `in` is
  `linear`**, so the importer's asymmetric-key warning fires and names the
  drift correction. `ease` or `hold` arriving stays exact and silent, which is
  what keeps a Nuke-authored step quiet on the way home - and the
  Nuke-to-`.rbj`-to-Nuke identity test still passes.

Verified in the host the same day. `test_ae_to_nuke.py` PASS, `mixed` now warns
`1 key(s) carry a different interpolation on each side`, geometry unchanged at
6.1e-05 px, and the crossing's field-by-field section reports the honest
relabel: `mixed frame 18 interp {'in': 'linear', 'out': 'hold'} -> {'in':
'ease', 'out': 'hold'}`. `test_nuke_roundtrip.py` PASS.

**The straight arrival is not available, so do not propose fixing the
geometry.** `test/probe/probe_nuke_step.py` is that measurement, re-runnable,
with its report at `test/golden/nuke_probe/17.1v1/step/`: a key made to honour an incoming slope draws frames 16-17
at 0.2003 px - the conform's own residual, so the arrival is then exact - and
then lets frames 19-23 drift **47, 99, 154, 214, 280 px**, because the outgoing
side stops being constant. Within Nuke's one-type-per-key model you can have
the straight approach or the freeze. The freeze is what the artist authored;
the drift pass buys the arrival back for 2 keys.

**The frozen spec did not need changing, and that is worth noting.** Section
10.2 says the step "was measured as outgoing-only (case 63: setting step moved
eval(75) to 1.0 while leaving eval(25) at the cubic default)" - which is
accurate, and even quotes the reading that contradicts the inference. The
correction belonged in `prd.md` section 15 Q?/9.2, the two docstrings and
`test/probe/README.md`, all of which now carry it.

**Deliberately not done, so it is not proposed again.** The Nuke exporter also
writes `ease`, and it is not conformed: After Effects can hold an ease exactly,
so there is nothing to reinterpret in that direction. The conform exists
because one specific destination has no vocabulary for one specific feature,
not as a general policy of writing linear files.

1. **`spec/rbj-v2-draft.md` section 6, feather anchors: DONE 2026-08-21,**
   all four layers, verified in Nuke. `feather_model: anchored`, a per-frame
   `feather_points` list keyed by a single `t` in segment units, and a de
   Casteljau split in the Nuke importer. What is left of this item is one host
   run - re-export the scene golden - and one measurement that gates the
   *claim* rather than the code, both at the bottom.

   **Schema and `version_for`: done, 2026-08-21.** Both implementations carry
   `anchored`, the `feather_points` validator, and the version clause, and they
   are checked against each other by
   `TestEs3CrossCheck.test_anchored_feather_survives_the_other_implementation`.
   51 new tests across `TestAnchoredFeather` in `test/test_core.py` and the
   matching block in `test/test_ae_core.js`.

   **AE exporter: done, 2026-08-21.** `geom.feather_anchors` /
   `RB.geom.featherAnchors` is the lossless reading, mirrored and tested over
   run 3's own vectors; `finishFeather` makes section 6.7's decision. The snap
   still runs on every frame, because which reading the file carries is a
   per-shape question and this is a per-frame loop - so both are computed and
   the loser is deleted. That is also what keeps a vertex-aligned file
   byte-identical to what v1 wrote.

   **Two writers' warnings moved.** The mid-segment and collision warnings used
   to fire inside the frame loop; they now fire from `finishFeather`, because
   under `anchored` nothing is snapped and nothing is dropped and warning about
   it would describe damage the file does not take.

   **A shape whose anchor count changes between frames cannot be anchored** and
   falls back to the v1 snap with a warning saying so. That is the case section
   6.8 keeps `snapFeatherPoints` around for.

   **AE importer: done, 2026-08-21.** `geom.feather_points_from_anchors` /
   `RB.geom.featherPointsFromAnchors` is the inverse, mirrored and tested both
   ways including the host's `(i, 0)` to `(i-1, 1)` rename. Into After Effects
   this is the easy direction: the host anchors feather anywhere along a
   segment, so every entry lands where the file says and nothing is snapped,
   split or dropped. The round trip is covered end to end by
   `test/test_ae_import.js`, "keeps anchored feather where the artist put it" -
   the mid-segment anchor and the authored zero both survive, which is the
   round trip that could not be written before.

   The drift pass needed nothing: `featherByAnchor` already keyed on `seg + rel`
   for an unrelated reason (the 27 px phantom), and that is the same invariant
   section 6.4 stores.

   **Nuke importer: done, 2026-08-21, and verified in the host.**
   `geom.split_cubic` and `geom.insert_anchor_vertices` do section 6.5;
   `_anchored_dense` in `nuke/rotobridge_import.py` is the policy and
   `_snapped_dense` the fallback. An anchored shape is resolved to vertices
   before the Shape is built, then read as `per_point` - which is Nuke's own
   model - so nothing downstream needed a special case.

   Measured in Nuke 17.1v1, `test_nuke_roundtrip.py` Phase 7: 4 points and 3
   anchors in, 6 points out, **worst vertex placement 0.000e+00 px** and worst
   feather radius error 3.129e-07, which is the float32 floor. The shape does
   not move; the price is vertices, exactly as section 6.5 says.

   The crossing case falls back per shape rather than per anchor. A vertex
   count that differs between frames says a crossing happened but not which
   pair crossed, and guessing would be worse than saying so - which it does.
   That branch is tested host-free in `TestNukeAnchoredFeather`, by stubbing
   the host modules, because it is the one nobody will reach by hand.

   **Section 6 is implemented end to end.** What is NOT settled is 6.4's open
   question - whether After Effects' `featherRelSegLocs` is the bezier
   parameter the split uses or an arc-length fraction. On a curved segment the
   two differ, and reading the value back cannot answer it because the host
   returns what was written. It needs a rendered comparison, which is Phase 5.
   **Until then an anchored After Effects file is better than the snap, not
   known to be exact.** Do not claim exact.

   **Golden re-exported and the crossing re-run, 2026-08-22. Section 6 is
   closed except for the measurement below.** The diff was the one
   `test/probe/README.md` predicted before the run, line for line: four
   warnings not five, `feathered` `per_point -> anchored`, its four anchors at
   t 0.25 / 0.75 / 2.5 / 3.0 on every frame, its points giving up their
   feather, and **no vertex differing on any frame**. `anchor added at t 3,
   feather 0` is in the file - the zero-width corner v1 was overwriting with
   the radius-12 anchor 150 px away.

   Crossing, Nuke 17.1v1: `feathered` arrives with **3 inserted vertices**, its
   geometry at 6.1035e-05 px - the same float32 floor as every other shape -
   and **the same 12 corrective keys at tolerance 0.5 as before**. The extra
   vertices cost nothing here, because these anchors hold still relative to the
   path; section 6.5's warning about sliding anchors costing keys is about a
   case this fixture does not contain.

   **`test_ae_to_nuke.py` had to be fixed and the failure is worth keeping.**
   It compared the Nuke shape's points against the file's index by index, which
   an anchored shape breaks by construction - 7 points in Nuke against 4 in the
   file, reported as 379 px of geometry loss. The importer was right the whole
   time; the test was measuring the mismatch. It now builds the expected ring
   from the file with `expected_centres`, evaluating each inserted position
   from the **Bernstein form** rather than the de Casteljau the importer
   splits with, so a split that is wrong in its own terms cannot pass by
   agreeing with itself. Verified independently before touching the test:
   `insert_anchor_vertices` against Bernstein over all 25 frames of the real
   golden is 2.2737e-13 px.

   `test/probe/diff_rbj.py` was taught the anchored layer for that check
   (`ebaa2f4`): anchors compared by `t` rather than index, reported as geometry
   rather than as labels, and repeated per-frame lines collapsed to
   "on every frame" - a shape whose model changed says the same thing 25 times
   and 200 lines of it buries the one line naming the model. It also fixes a
   latent bug that only ever checked the last point of each frame, which was
   harmless before and load-bearing now. Verified against the golden, against a
   copy carrying exactly the predicted change, and against one with a single
   anchor moved 0.05 on a single frame.

2. **Phase 5, one direction: RETIRED AS OUT OF SCOPE 2026-08-22** - this tool
   moves roto spline data between applications, and a matte difference
   measures how a host draws a shape rather than whether the shape arrived.
   See `prd.md` section 13 criterion 2. The Nuke half is built and passing and
   stays in the tree unused; do not reopen it by proposing a render. What
   follows is the record of what it measured. AE to Nuke, rendered in
   Nuke, same plate. It was written as a symmetric comparison and is not one
   any more: the Nuke-to-AE half is already exact at the document level
   (`test/test_ae_crossapp.js`) and can stay there.

   `test/test_ae_to_nuke_render.py` builds Nuke's matte from `ae_scene.rbj` and
   measures it in the unit criterion 2 is written in - the fraction of pixels
   past 0.01 alpha delta. Invocation in `test/probe/README.md` under "Phase 5
   render"; report at `test/golden/nuke_probe/17.1v1/phase5/`.

   **The measurement is verified before it is used, which is the part worth
   keeping.** Section 1 imports the same file twice and must read zero
   everywhere; section 2 measures a square moved 4 px against arithmetic done
   in Python - 2 edges x 4 px x 400 px - and read `0.00100418` against
   `0.00100418`. Section 1 alone would pass on a chain that always says zero,
   which is exactly the chain that would declare the crossing perfect.

   **Section 3 is a number this project did not have.** Tolerance 0 against
   tolerance 0.5 on the same file: **no pixel on any frame differs by more
   than 0.01 alpha**, worst delta anywhere 0.000266. Criterion 4 bounds the
   drift pass at 0.465 px of *geometry*; this says what that is worth in the
   render, and it is nothing an artist can see.

   **What is still needed from After Effects**, and it is the whole of what is
   left: frames 0 to 24 of the `setup_ae_scene.jsx` comp as a matte sequence,
   straight alpha, EXR or PNG, numbered by the comp's own frames. Then re-run
   with the pattern as the second argument.
   **`test/probe/probe_ae_phase5.jsx` does that in one run**, 2026-08-22, and
   reports the pattern and the frame offset by reading the output folder back
   rather than predicting it.

   Building that script turned up two things about the comparison that were
   wrong in every earlier description of it, and both would have been read as
   Phase 5 failures:

   - **The layer has to be soloed.** The comp also carries `RotoBridge
     static`, whose masks 7 and 8 are not in `ae_scene.rbj`, and an imported
     `RotoBridge` layer from any earlier run. Their alpha would measure as
     geometry Nuke was never given.
   - **The open spline is held out, on the Nuke side.** After Effects renders
     no alpha at all from an open mask path and Nuke strokes one at the node's
     default width, so `opened` would be a Nuke-only stroke against empty film.
     `closed_names()` in the harness holds it out and the report names it.
     Verified in Nuke: the subset builds exactly the five closed shapes.

   **And the standing warning about a bad render was wrong in mechanism.** It
   said a matte with no alpha "reads as zero everywhere and looks like a pass".
   Measured 2026-08-22: it reads as **0.0708 of the frame** differing on frame
   12, seven times the budget, because the difference is then Nuke's own matte
   against nothing. A wrong render fails loudly. What it does not do is fail
   *informatively*, which is what the report's `channels` line is for.
   Corrected in the harness and in `test/probe/README.md`.

   Two questions are waiting on exactly that render and should not be guessed
   at before it:

   - **AE ease ↔ Nuke `lslope` / `rslope` and `la` / `ra`.** Narrowed hard by
     Phase 4 rather than answered. AE ease to `.rbj` and back is not merely a
     measured factor of 100 now: `ae_static_ease.rbj` proved the whole curve
     reconstructs, 135 px of bow rebuilt from three keys to 0.0000 px. So the
     AE half is **exact and closed**, and everything unknown is on Nuke's side.
     `core/interp.to_nuke` is the one function that changes, and it should not
     change until a file has actually crossed and been rendered.
   - **`ff`, Nuke's feather falloff.** Nuke defaults it to 1.0 and its API
     never names the values; After Effects names both of its (`FFO_LINEAR`
     7213, `FFO_SMOOTH` 7212). It round trips Nuke to Nuke because the same
     rule runs both ways, so only a crossing file exposes it.

   Section 6.4's anchored-feather question is the third, and it is the same
   render that answers it.

3. **A durable per-shape verification record: DONE 2026-08-22, both adapters,
   verified in Nuke.** Every import appends one to `<project>.rotobridge.txt` -
   beside the saved script or comp, beside the source `.rbj` when the project
   has never been saved. `core/report.py` renders it and `RB.report` mirrors
   it; `TestEs3CrossCheck.test_both_implementations_write_the_same_import_record`
   holds the two to **byte-identical** output, which is stricter than the .rbj
   writers are held to and deliberately so - a record is one document about one
   import, and two hosts writing different ones would make it an argument
   rather than settle one. `prd.md` section 8 now describes it.

   Four decisions worth carrying forward:

   - **The two warning lists stay apart.** What the exporting application
     recorded losing is evidence about that application; what this import lost
     is evidence about this one. `import_document` seeds its list with the
     file's own, in order and first, so `build_record` splits them back at
     `len(doc["warnings"])`. Run together they would answer "which one dropped
     it?" with "one of them did".
   - **Appended, never overwritten.** A comp is imported into more than once
     and the second import is not entitled to erase the first. Measured in the
     host: two runs of `test_nuke_roundtrip.py` leave four records in
     `roundtrip.rotobridge.txt`, and the exporter's own feather-offset warning
     is in each one.
   - **An unwritable record warns and does not fail the import.** The shapes
     are in the script by the time it runs, and losing an import over a
     read-only folder would be a worse failure than the one being reported.
     Both sides are tested for it, the AE one through a mock whose `open("a")`
     refuses.
   - **A number the drift pass never measured says so.** `drift.correct`
     returns `at = None` both when every frame is a key and when nothing
     between the keys moved, so the record says "nothing drifted from the
     file" rather than naming either case or printing a 0.0000 that was never
     taken. The same `None` also stopped the two dialogs disagreeing about
     the offset: `worst_frame` is now in **host** numbering on both sides.

   **The one call in this that no test can reach is `File.open("a")` in After
   Effects.** The JavaScript Tools Guide documents `"a"` for append and the
   mock honours it, but no host run has exercised it. If it turns out
   unsupported the import still lands and warns once per import; the fallback
   would be read-then-write through the existing `ae.readText` / `ae.writeText`.
   **ANSWERED IN THE HOST 2026-08-22: `"a"` appends.** Two records written and
   read back in order in After Effects 25.6x101, and the live import wrote its
   own record the same run. The fallback is not needed and should not be
   built. See "The second After Effects host run".

4. **Ease-then-type ordering, the last Phase 4 loose end, and a drift number
   cannot answer it.** `setTemporalEaseAtKey` forces a key to BEZIER and the
   importer sets the types afterwards. The export side of `mixed` proves the
   ordering works when *reading*. The symptom on import is a **hold key that
   renders smooth**, and the drift pass corrects positions either way, so it
   will never show up as drift. Someone has to look at the imported `mixed`
   mask's key in the AE timeline and confirm it is still a hold. **That key is
   now frame 18, not frame 12** - the re-export moved the hold to where the
   composite actually stands still, so a check aimed at 12 would fail on
   correct behaviour. Low risk: the code does ease first and types after,
   which is the documented order. **ANSWERED IN THE HOST 2026-08-22: frame 18
   is still a HOLD, and every other side survives too.** The whole per-side key
   list round trips - see the table in "The second After Effects host run".
   Phase 4 has no loose ends left.

   Optional, and **decided against 2026-08-22 - do not re-propose it.**
   `test/golden/ae_scene.rbj` is the **six**-shape export and predates masks 7
   and 8, whose export is a separate golden. Folding them in as an eight-shape
   re-export was costed and dropped, because the thing it was wanted for
   already exists: `test/test_ae_to_nuke.py` takes a **second `.rbj` on the
   command line**, so the static pair is in the crossing test as a second
   invocation and always was. What an eight-shape golden adds is one command
   instead of two. What it costs is real - `eased_static` and `linear_static`
   would exist byte-identically in two goldens, free to drift apart the next
   time one of them is re-exported, and `ae_scene.rbj` would stop being "every
   mask on the scaled, rotating layer", which the corrective-key reasoning
   above leans on.

   **The prediction was derived before it was dropped, and it is kept because
   it costs nothing and a future run would need it.** The two layers bake
   independently, so an all-layers export is the two committed files
   interleaved, not a new measurement: **8 shapes, 800 points, 11 warnings, 101
   authored keys**, shapes in the order `eased_static, linear_static, linear,
   eased, mixed, feathered, offgrid, opened` (`comp.layers.addSolid` puts the
   newer solid at index 1, so the static layer exports first - note
   `test/ae_mock.js` appends instead, so the mock cannot answer this), and
   `diff_rbj.py` against the current golden reporting exactly two shapes added,
   one warning added, **geometry identical**. Verified here by building that
   file from the two goldens and running the diff. Warning order is the cheap
   check on the layer order: warnings 1-2 come from the bake phase and do not
   move, and `eased_static`'s conform warning heads the sparse group at
   position 3 if the static layer went first.

## DONE: the six would-do-differently items, 2026-08-24

All six landed, plus one bug found along the way, each chunk with red tests
first and the suite green after (626 host-free tests at the end, up from 585).
Commits: item 4 prd mirror-cost paragraph `95ace9d`; item 1 warnings registry
`faf321c` (38 codes, cross-checked byte for byte); item 3 mock-vs-probe
fixtures `4fda421`; item 2 v3 frame refs `7cceceb` (spec/rbj-v3-draft.md);
item 5 pre_conform_keys `0096bfe`; item 6 shape ids `cb6a010` (AE writes none
until probe_ae_mask_id.jsx runs on a host - top of the next AE visit alongside
the panel checks); sweep: degenerate-vertex warning said once per shape
`5effc36`. AE files re-deployed to the Desktop folder after each AE chunk.
The plan as it was worked follows.

## The plan (was: IN PROGRESS), 2026-08-24

The user asked for all six suggestions from the post-review reflection to be
implemented, "and anything else you encounter and feel needs improvement."
Work in chunks, red test first where checkable, `bash test/run.sh` green and a
commit after each. Deploy `ae/*.jsx` to the Desktop folder after AE edits.
Design facts settled up front: the validator IGNORES unknown members, so items
5 and 6 need no version bump; only item 2's frame refs do (old readers hard-fail
on a `same_as` record). `report.py`'s `_num`/`_pixels` are the cross-identical
number renderers to reuse. `conformEase` mutates the authored key objects in
place, so item 5 must deep-copy before the conform runs.

Chunks, in order (mark each DONE with its commit as it lands):

1. **prd.md paragraph: the ES3 mirror is a chosen cost** (item 4). State the
   alternative (CEP/UXP shared-JS core) and why it loses: the panel runs what
   Run Script File runs, deployment is copy-five-files, acceptance measured
   that path.
2. **Structured warnings** (item 1). New `core/messages.py` + `RB.messages` in
   `ae/lib/rotobridge_core.jsx`: every warning is `render(code, params)` producing
   "[code] prose". Params are strings/ints only; floats pre-formatted via
   shared helpers mirroring report's `_num`. Migrate all ~37 warn sites in the
   four adapters + core-side warners in `nuke/rotobridge_import.py`. Cross-check
   test renders every code with fixed samples in both implementations and
   byte-compares; also compares the code LISTS so a code added to one side only
   fails. Tests matching prose substrings migrate to codes. Goldens keep their
   old-prose warnings (writer provenance): tests on goldens keep matching old
   strings, tests on live exports match codes. Add `messages` to the
   `rotobridge_nuke` shared module AND to `_WithoutNuke`'s stub in test_core.py.
3. **Mock fidelity anchored to probe measurements** (item 3). Fixture file
   encoding the measured feather reorder cases (probe_ae_feather_order: segLocs
   [0,1,2,3] rel [0,0,0,0] -> [3,0,1,2] rel [1,1,1,1]; probe_ae_feather_interpolated:
   regroup outer-before-inner, stable, at interpolated frames, for LINEAR too)
   with source attribution; node test asserts `feathersAsHostReturns` reproduces
   them exactly.
4. **v3 frame refs** (item 2). `{"same_as": <int>}` as a frame record: writer
   folds runs of data-equal consecutive frames (equality by data compare - safe
   cross-implementation since Python == treats 1 == 1.0 and JS has one number
   type), reader expands with deep copies at loads/parse so everything
   downstream still sees dense frames. Explicit `fold_frames(doc)` in both
   implementations, called by both exporters right before dumps/stringify; it
   bumps version to 3 ONLY if it folded something (section 6.7 policy: only
   files that benefit pay). Validator: `same_as` legal at version >= 3, must
   resolve to an earlier dense frame in the same shape, no chains. MAX_VERSION
   becomes 3. New spec/rbj-v3-draft.md. Cross-check: fold+dumps vs
   fold+stringify byte-compare. Goldens untouched (v1/v2, full frames).
5. **pre_conform_keys** (item 5). Optional shape member: the authored keys
   exactly as they were before conformEase, ease blocks intact. Written only
   when the conform changed something. Validated with the same key machinery
   (ease allowed). Importers ignore it. No version gate (unknown-member-tolerant
   readers, and validator validates it when present). Spec it in v3 draft as
   version-independent optional member.
6. **Stable shape ids** (item 6). Optional `id` string per shape, non-empty,
   unique across shapes when present (the value-add over names). Nuke exporter
   writes deterministic ids (node name + "/" + shape name). AE exporter does
   NOT write ids yet: no probed stable mask identity exists - add a probe
   script to test/probe and a line to the AE host-visit checklist instead of
   shipping unprobed API use. Subset import matches id first, then name.
7. **Sweep**: anything else encountered along the way, this section updated to
   DONE, everything pushed.

## DONE: review findings F1-F4 fixed, 2026-08-23

A full code and architecture review found four findings, all verified against
the tree at `485cbd6`, none in tested paths. All four are fixed, each with a
red test first, plus the F5 cosmetics. The suite is 588 host-free tests, all
green, and `ae/*.jsx` is re-deployed to the Desktop folder, diffed identical.

- F3 `a500164`: the Nuke tolerance parser refuses "nan" (`value != value`
  check); `TestNukeToleranceParser` pins the whole parse surface.
- F4 `8ded984`: interp errors route through the capped key list in both
  implementations; the twin cap tests agreed on the failure (20 errors each)
  before the fix.
- F2 `ea0a7ba`: the AE adapter writes stringify's output plus "\n", matching
  Nuke's `export_to_file`. The three AE-written goldens still end 0x7d; the
  next host re-export differs by that one byte BY DESIGN - do not read it as
  drift and do not regenerate for it alone.
- F1 `a290044`: the export warns once per shape when `featherInterps`,
  `featherTensions` or `featherRelCornerAngles` hold non-default values
  (state.shaping, said in finishFeather before the model decision). The mock
  now carries the three arrays through its host-return reorder and lerp, as
  the real host does.
- F5 `bedd06c`: `held` locals renamed `edge` in both linearError
  implementations; shapeHeader's unrelated guard on maskMode removed.

The findings' full descriptions as reviewed follow.

**F1. AE export silently drops feather tension / corner type / interp.**
`prd.md` section 9.3 names `featherRelCornerAngles`, `featherInterps`,
`featherTensions` as readable, the export never reads them, the import writes
zeros (`ae/lib/rotobridge_import.jsx:195-197`), and no warning fires - unlike
maskExpansion and the inverted flag, which warn for the same class of loss.
Fix: in `applyFeather` (`ae/lib/rotobridge_export.jsx`), record whether any of the
three arrays holds a non-default value (0 is the default for all three); warn
once per shape in `finishFeather`. Match existing warning style ("mask '...':").

**F2. The two exporters disagree on the trailing newline.** Verified byte by
byte in the goldens: Nuke-written files end 0x0a (`export_to_file` writes
`text + "\n"`, `nuke/rotobridge_export.py:339`), AE-written files end 0x7d
(main() writes `RB.rbj.stringify(doc)` bare). Diffability is spec section 2.1's
goal. Fix: AE `main()` appends "\n" (adapter level, matching Nuke's placement -
do NOT change dumps/stringify, whose outputs are compared byte-equal by tests).
The four AE-written goldens will differ by one byte on next re-export; note it
in the commit, do not regenerate.

**F3. Nuke tolerance parser accepts "nan".** `_parse_tolerance`
(`nuke/rotobridge_import.py:528`): `float("nan") < 0.0` is False, so nan slips
through and the drift pass silently behaves as tolerance inf while the record
prints "nan px". AE side throws via isNaN - a divergence. Fix:
`if value != value or value < 0.0: raise ValueError(...)`.

**F4. Validator error cap bypassed for interp errors, both implementations.**
`core/rbj.py:_validate_keys`: frame/order errors go into the capped `key_errs`,
but `_validate_interp` (line 440) appends straight to `errs` and the break
watches only `key_errs`, so 150 bad interps emit 150+ errors past
MAX_ERRORS_PER_SHAPE. Same bypass mirrored in `ae/lib/rotobridge_rbj.jsx`
validateKeys/validateInterp. Fix: route interp errors through key_errs on both
sides; keep the two implementations' messages aligned.

**F5 (cosmetic, opportunistic).** `linearError` in `ae/lib/rotobridge_core.jsx:665`
declares `var held` shadowing the `held` parameter (same binding under ES3
hoisting; correct only because the branch returns immediately) - rename the
local; `core/drift.py:204` rebinds `held` the same way, rename to match.
`shapeHeader`'s odd guard on the path property before reading maskMode
(`ae/lib/rotobridge_export.jsx:72`) deserves either removal or a comment.

**Also in flight, unrelated:** `prd.md` section 18 (host API facts moved from
this file) sits UNCOMMITTED in the tree - step 1 of the consolidation above,
paused mid-move. Commit or continue it separately from the F1-F4 work.

## PLANNED, NOT STARTED: consolidating this record

**Approved by the user 2026-08-22, "relocate and compress". Nothing has been
moved yet** - the analysis below is the whole of the work done, and it exists
here because it was worked out in a conversation that is about to be compacted.
Tree was clean when this was written.

**The trigger.** This file's own header says "Detail lives in `prd.md` and
`test/probe/README.md`; this file only holds what those two do not". At 1919
lines that is no longer true, and roughly 60% is self-declared history:

| section | lines | disposition |
|---|---|---|
| The first After Effects host run, 2026-08-21 | 523 | compress hard; both bugs are fixed and confirmed, so keep the lessons and drop the blow-by-blow |
| Next | 383 | its own first line says "The list below is history" - reduce to the genuinely open items |
| The format has to be falsifiable, 2026-08-21 | 253 | the trust argument is design rationale and belongs in `prd.md`; the feather-fix analysis is superseded by section 6 being implemented |
| Decisions made, so they are not relitigated | 120 | reference - dedupe against `prd.md` §15, which already carries Q7/Q8/Q9 |
| In flight | 99 | mostly not in flight; Q10's narrative duplicates `prd.md` §15 Q10 |
| Status | 94 | keep, compress to a tight block |
| Things the adapters must not lose | ~180 | **the most valuable section in the file and not history** - host API facts and invariants; move to `prd.md` beside "Confirmed API details (Phase 0)" |
| What Phase 4 decided | 67 | reference, to `prd.md` |
| Environment gotchas | 32 | operational, to `test/probe/README.md`, which already holds the invocations |
| Nuke is the hub | 81 | decision is live, keep compressed; the `probe_nuke_ease` findings go to `test/probe/README.md` |

Target: `HANDOFF.md` as live state plus pointers, roughly 350 lines. `prd.md`
grows to hold the reference material, which is what it already is.

**Four cross-references name a HANDOFF section by title and must keep
resolving.** This is the part that is easy to break and hard to notice:

- `test/test_core.py:1135` -> "A `hold` can contradict its own dense layer"
- `test/probe/README.md:469` -> "Nuke is the hub"
- `test/probe/README.md:535` -> "Next"
- `spec/rbj-v2-draft.md:251` -> "Two probes, and the answer needed both"

Plus a dozen bare `HANDOFF.md` mentions in `core/drift.py`, `core/interp.py`,
`test/ae_mock.js`, `test/test_ae_import.js` and `spec/rbj-v2-draft.md` that
only need the *fact* to survive somewhere in the file.

**Staging, so a compaction mid-way is recoverable:** (1) move the reference
sections out to `prd.md` and `test/probe/README.md`, (2) compress the history
sections in place, (3) rewrite the header, Status and Next, (4) fix the four
named references and re-grep. Commit after each. The host-free suite must stay
green throughout - it does not read these files, so a green suite is necessary
and not sufficient; the real check is the grep in step 4.

## The UI entry points, 2026-08-22

**Nuke already had one.** `nuke/menu.py` registers a `RotoBridge` menu with
both directions, and `prd.md` §9.2 has specified it since Phase 2. Nothing had
ever executed it: Nuke runs `menu.py` only when the GUI starts, and
`nuke.menu()` raises **"not in GUI mode"** under `--nc -t`, so the registration
cannot be reached from this shell at all. Measured 2026-08-22 by exec'ing
`menu.py` under `--nc -t` and reading the exception.

**After Effects now has `ae/rotobridge_panel.jsx`.** Two buttons, a footer, and
no logic of its own. Each button `$.evalFile`s the adapter exactly as
`File > Scripts > Run Script File...` does, which is deliberate: the adapters
already prompt for everything they need, and a panel that collected its own
parameters and passed them in would be a second entry point to keep in step
with the one every test and every host run goes through. It works as a floating
palette with no install, or docked from `Scripts/ScriptUI Panels/` with the
adapters in a subfolder beside it - `lib` since 2026-08-24, see below.

The footer names the folder the scripts are being run from. That is not
decoration: the recurring failure here is a stale deployment, and it produces a
plausible file, a plausible alert and a diff that reads as the fixture moving.
The footer cannot say the copy is a commit behind, but it can say **which**
copy, which is the question that failure turns on.

**Neither is reachable by the host-free suites, and `TestUiEntryPoints` checks
the half that is.** Nothing here models ScriptUI, and `nuke.menu` needs a GUI,
so what a test can hold is the *wiring* - that every `addCommand` in `menu.py`
names a module and function that exist, and that the panel names adapter files
that exist. That is the half that rots on a rename and breaks silently on an
artist's machine. Mutation-checked: a renamed function, a deleted command and a
renamed adapter each fail exactly one test.

**The panel itself has never run in After Effects.** It is in the same class
`File.open("a")` was in before 2026-08-22 - written against the documented API,
unreachable by any test here, and needing exactly one host visit to confirm.
What to check: it opens, the footer names the right folder, both buttons run
their adapter, and the Change... button finds a folder and remembers it across
a restart. Nothing downstream depends on the answer, because the adapters are
unchanged.

## DONE: the AE side is a panel over a `lib` folder, 2026-08-24

`ae/` is now `rotobridge_panel.jsx` alone, over `ae/lib/` holding the five it
evaluates: the two adapters, `rotobridge_ae.jsx`, and the two host-free ports.
The zip mirrors it - `after_effects/rotobridge_panel.jsx` beside
`after_effects/lib/`.

**Why**: the drop handed a non-technical tester six files with similar names
and asked them to pick. One file at the top is the whole point; nothing about
the code needed it. `#include` is relative to the including file and all five
moved together, so not one include path changed.

**The repo moved too, not just the zip.** Shipping a layout the tests never
load is the stale-deployment failure this project keeps paying for, in a new
costume.

**Three places name `lib` and none can see the other two**: `ae/lib/` on disk,
`after_effects/lib` in `tools/package.sh`, and `var LIB` in the panel.
`TestUiEntryPoints.test_the_panel_looks_where_the_drop_puts_the_adapters`
holds all three equal, because disagreement surfaces as "I click the button
and nothing happens" - the least debuggable report that can arrive from
someone else's machine. Mutation-checked: renaming `LIB` fails it.

The panel searches `lib`, then beside itself, then `rotobridge`. The last is
kept only so a docked install predating this still works; the flat case is
kept because someone will assemble one by hand.

`tools/bump_version.py` now points at `ae/lib/rotobridge_core.jsx`. Verified
by re-running it at 0.9.0: all three sites still match exactly once.

**`locate()` measured against the real zip, 2026-08-24.** No suite models
ScriptUI, so this was run under node with a `File`/`Folder` stub thin enough
to be honest - `fsName`, `parent`, `exists`, nothing else - over the actual
unzipped drop, pulling `locate()` out of the IIFE rather than reaching
`build()`:

| layout | result |
| --- | --- |
| the drop as shipped | `after_effects/lib` |
| flat folder assembled by hand | beside the panel |
| legacy `rotobridge/` subfolder | found |
| panel with nothing else | `null` |
| `lib` missing `rotobridge_import.jsx` | `null` |

The last two are the ones worth having: `holdsAdapters` wants both adapters,
so a half-copied folder prompts rather than half-running. This does **not**
retire the host visit below - it says the folder arithmetic is right, not
that After Effects evaluates any of it.

## The crossing harness only worked on one file, 2026-08-22

**`test_ae_to_nuke.py` takes any `.rbj` as a second argument, and until today it
FAILED every one that was not `ae_scene.rbj`.** Its open/closed section asked
for two masks **by name** - `linear` and `opened` - and appended "shape is
missing after import" for each one the source did not contain. The committed
report for the static pair therefore ended in `FAIL` on two shapes that were
never in the file, while the numbers above that verdict were being quoted in
`prd.md` and here as a result. Nobody read to the bottom.

The fix is smaller than what it replaces: the section now walks `doc["shapes"]`
and checks each shape's own `closed` against the flag Nuke gives it. That also
closes a second hole in the same block - a shape that failed to import used to
be skipped by the geometry loops rather than reported, because the only
missing-shape check was the two hardcoded names.

**Both halves were then re-run.** The pre-conform crossing is a PASS with its
numbers unmoved (3 / 22 and 2 / 0), which is what says the FAIL was the harness
and not the file. On the six-shape golden the fix changed the report in that
section and **nowhere else** - geometry, every key count, every warning and the
verdict are byte-identical to the run it replaced, checked with `diff`.

Worth carrying forward: a harness written against one fixture will pass on that
fixture forever and say nothing useful about any other, and the failure is
quiet because the *numbers* stay right. The verdict line is the part that goes
wrong first.

**All three Nuke tests pass and are re-runnable without anyone**, most recently
2026-08-22. `test_nuke_roundtrip.py` covers Phases 2, 3, 6 and 7 and now the
import record; `test_ae_to_nuke.py` is the AE-to-Nuke crossing at the document
level, over any `.rbj` named as its second argument; `test_ae_to_nuke_render.py` is the Phase 5 render measurement. Reports at
`test/golden/nuke_probe/17.1v1/phase6/`, `.../hub/` (the static pair, both the
conformed file and the pre-conform one) and `.../phase5/`. Sync, then run any of
them - the last argument is the output directory in every case:

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
- **Nuke NC hands Python at most 10 `Node` objects per script, cumulatively**
  (measured 2026-08-22). Not ten live nodes: a `nuke.toNode` on a node already
  held costs another one, and deleting a node does not give the budget back.
  `nuke.scriptClear()` is the only reset, and it invalidates every `Node`
  object already handed out. A harness that builds a tree per shape or per
  frame has to be written around this - `test_ae_to_nuke_render.py` caches
  every node in a local, reconfigures one Expression rather than adding a
  second, and clears between sections.
- **A Roto with no input carries only its shapes' bounding box.**
  `nuke.sample` outside it raises rather than returning 0, and a frame-wide
  average is taken over the wrong area. Ground it on a `Constant` and the
  frame is the frame. This is why the render harness builds a black.
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

## DONE: the tester drop and build versioning, 2026-08-24

Goal: hand a single zip to non-technical Windows testers today, and be able to
tell from a screenshot which build they were running.

Decisions taken with the user before starting:

- **Windows only.** No Mac installer.
- **One zip, both sides.** A Nuke-only tester ignores the `after_effects`
  folder. Everyone is on the same build of everything.
- **After Effects installs as a floating palette, not a docked panel.** Unzip,
  `File > Scripts > Run Script File...`, pick the panel. No elevation, nothing
  to uninstall before the next drop, and it avoids the two unverified things in
  the docked route: whether `#include` resolves under `$.evalFile` from
  `ScriptUI Panels`, and whether AE scans the user-level
  `AppData\Roaming\Adobe\After Effects\<ver>\Scripts\ScriptUI Panels`.
- **One build version, reported per side**, not a version per component.
  `core/`, `ae/` and `nuke/` change together in nearly every commit, so separate
  counters would drift while answering a question nobody asks. One number,
  printed independently by each side, still catches the case that matters: a
  tester who updated After Effects but not Nuke.
- The build version is **not** the `.rbj` format version. That stays an integer
  at 3 and bumps only when an old reader would break.

Starting at `0.9.0`. Patch bump per tester drop.

Chunks, each a commit:

1. Version single source: `core/version.py`, `RB.VERSION` in
   `ae/lib/rotobridge_core.jsx`, a literal in `ae/rotobridge_panel.jsx` (it includes
   nothing by design), a cross-check test that all three agree, and
   `tools/bump_version.py`.
2. The After Effects scripting-preference guard. `Allow Scripts to Write Files
   and Access Network` is off by default and no tester will find it; with it off
   `ae.writeText` throws a bare "cannot write ...". Name the exact menu path.
3. Version into every AE alert: the shared title, plus a footer line in the two
   summary alerts, because a cropped screenshot can lose the title bar.
4. Version into the Nuke dialogs. `nuke.message` takes no title so it goes in
   the body; the two `nuke.Panel` dialogs do take one. Add `RotoBridge > About`.
5. `source.tool_version` in the file. Additive optional member, no format bump:
   the validator ignores unknown members and ignoring this one cannot change
   what renders, which is the test spec section 5 sets.
6. Import record rows for both builds. The record already names the source file,
   host, format version, every shape and both warning lists; with the two tool
   versions it is a complete bug report a tester can email with no explanation.
7. Packaging: `tools/package.sh` builds `dist/RotoBridge-<ver>.zip` holding both
   sides, `install_nuke.bat`, and a one-page tester README.
8. Run everything host-free. (This chunk originally said "deploy to the
   Desktop folder"; that folder is being deleted - see below.)

All eight chunks are in, 343 + 293 host-free tests green:

- `d0ebaf2` the version itself, three files and the fence that keeps them equal
- `e0c0e95` the scripting-preference probe at panel launch
- `91e294f` the build named in every dialog either host can raise
- `e8569bb` `source.tool_version` in the file
- `1806088` both builds in the import record
- `8e40d66` `tools/package.sh`, the Nuke installer and the tester READ ME
- `7e190af` a listing fix in the packager

Cutting a drop:

    python3 tools/bump_version.py 0.9.1
    bash test/run.sh
    git commit -am "..."
    bash tools/package.sh          # refuses a dirty tree

The packaged Nuke payload was smoke-tested against stubbed `nuke` modules from
the unzipped copy: `core` resolves through `rotobridge_nuke.py`'s walk up one
level, and both adapters import.

**Still needing a host, and now more urgent than before.** None of the drop is
measured in After Effects:

- `test/probe/probe_ae_mask_id.jsx` - unchanged from the last session, still
  the thing standing between the AE exporter and writing shape ids.
- The launch probe's diagnosis. Toggle `Allow Scripts to Write Files and
  Access Network` off, open the panel, confirm the alert fires and names the
  preference; toggle it back on and confirm it does NOT fire. The second half
  matters more: a false alarm on every launch of a working install is the one
  failure mode that would make a tester ignore the panel.
- The version in the alert title. Confirm it is actually legible in a
  screenshot of an alert, since that is the whole reporting channel.
- The panel checks carried over from before: `#include` resolution under
  `$.evalFile`, footer path, both buttons, `Change...` persistence.

On the Nuke side, `Install for Nuke.bat` **has been run on Windows and works**
(2026-08-24). WSL can invoke `cmd.exe`, so the installer is testable from here
with no host and no manual step - point `USERPROFILE` at a sandbox folder so
the real `~/.nuke` is never touched:

```bash
SB=/mnt/c/Users/shann/AppData/Local/Temp/rbtest
# a wrapper .bat that sets USERPROFILE, then calls the installer
cmd.exe /c "$(wslpath -w "$SB/run.bat")"
```

Five cases pass: a clean install lands 13 files and writes `init.py`; the
`pluginAddPath` line comes out as valid Python with both parens intact (the
escaping for the surrounding `if errorlevel 1 ( ... )` block was the thing
most likely to be wrong); a second run leaves `init.py` alone rather than
appending twice; an existing `init.py` with someone else's tool in it is
appended to, not clobbered, and still parses; and `robocopy /MIR` removes a
file an older build left behind. The not-yet-unzipped guard fires with its own
message.

Do this before every drop. It is thirty seconds and it covers the half of the
install that no tester can debug for you.

**The Windows desktop copies are going away, 2026-08-24.** Stated by the user:
they existed only to get the scripts in front of After Effects, and everything
belongs in this repo. Do not copy build output, adapters or probes onto the
desktop again. After Effects reaches the tree over
`\\wsl.localhost\Ubuntu-24.04\home\sgold\dev\repos\rotobridge\`, which
also retires the stale-deployment hazard that `test/probe/README.md` spends a
section guarding against - there is no longer a second copy that can fall
behind. `dist/` stays untracked: `tools/package.sh` regenerates it from a
clean tree, so the zip and both paste sources are reproducible from a commit
rather than kept as artefacts.

**The name `core` was a collision, and a tester found it, 2026-08-25.** The
first install on someone else's machine raised

```
cannot import name 'drift' from 'core' (unknown location)
```

Nothing was wrong with that install. Nuke runs one interpreter for every tool
in the session, so top-level module names are shared, and `core` is a name a
studio tool can plausibly own. If theirs is imported first, `sys.modules`
already holds it and `_bootstrap_core`'s `sys.path.insert` never gets looked
at - the path is only consulted for a name that is not already bound.

Reproduced and then fixed against real Nuke 17.1v1, four cases:

| session | before | after |
| --- | --- | --- |
| clean | imports | imports |
| foreign namespace `core` (bare directory) | **the tester's error, exactly** | imports |
| foreign regular `core` (has `__init__.py`) | same failure, message names their path | imports |
| their `core` afterwards | - | still theirs |

`(unknown location)` is the discriminator worth remembering: it means the
`core` that won is a **namespace** package, a directory with no `__init__.py`.
A foreign regular package fails the same way but prints its path instead. Our
own payload missing its `__init__.py` does **not** produce this - it still
imports, because `drift.py` is in the namespace portion either way. So the
message can only mean someone else's `core`.

The fix is in `nuke/rotobridge_nuke.py`: `_bootstrap_core` no longer touches
`sys.path`. It loads `core/` from its own absolute path with
`importlib.util.spec_from_file_location` under the private name
`rotobridge_core`, which takes the collision off the table in both directions -
we cannot lose the name and we can no longer shadow theirs. `core/report.py`'s
`from core import version` became `from . import version`, the one internal
cross-import in the package, since `core` is not a name the package can count
on any more. Tests still `from core import ...` at the repo root and are
unaffected.

Worth knowing for the next generic name: the top-level names this tool still
puts in Nuke's shared namespace are `rotobridge_nuke`, `rotobridge_export` and
`rotobridge_import`. Those are distinctive enough to leave alone.

Also measured while doing this, and it closes the open question above:
`test/test_nuke_roundtrip.py` **passes when run over the WSL share**, so Python
imports resolve across the UNC path under Nuke. The share is a viable install
route for this machine; the zip installer stays the route for everyone else.

**Opacity and uniform feather keyed every frame, 2026-08-25.** Reported from
the host on an AE to AE crossing: a mask whose opacity was a straight ramp came
back with a key on every frame of the range, and the same for the mask's x/y
feather. The mask path was right - two authored keys, no correctives - which is
the discriminator worth keeping: the import record's `N authored key(s), M
corrective` line counts the **path only**, so `0 corrective` alongside a
timeline full of keys means the extras are on the attributes.

Neither attribute has a sparse layer in the format (spec section 7.2). Both
arrive as one value per frame, and both importers wrote them straight out. The
only reduction either had was a constant check - one key when the value never
moves at all - so anything that moved, however simply, stayed dense.

Both now run the dense samples through `drift.linear_fit`, the same fit the AE
exporter already uses to conform ease, and keep only the frames a linear
reconstruction needs. A straight ramp of 101 samples comes back as 2 keys; a
parabola stays at 87 and converges inside the tolerance. Nothing new in core
and nothing new to cross-check: the ES3 port of `linearFit` was already there
and already checked against the Python.

**Tolerance 0 opts out**, and finding out why is the useful part. The first cut
did not, and `test_ae_crossapp` caught it: a real Nuke file's uniform feather
crossed 7.03e-07 px off, because a line drawn through two float32-quantised
samples reproduces the ones between them to within the arithmetic and not to
the bit. Tolerance 0 is documented as reproducing the file exactly at the cost
of an uneditable shape (prd.md section 8), so the collapse now steps aside
there, exactly as the drift pass does. The constant collapse still runs at 0 -
one key **is** every sample, spelled once, and loses nothing.

The two tolerances are deliberately different and are not the artist's: AE uses
1e-3 (a thousandth of a percent of opacity, a thousandth of a pixel of feather)
and Nuke 1e-4, because Nuke's `opc` runs 0 to 1 rather than 0 to 100 and
because Phase 2 measured its float32 storage residual at about 3e-05 px - a
tolerance under that would buy keys to chase the host's own arithmetic.

Covered by `test_ae_import` (ramp collapses, curve stays dense, tolerance 0
keeps everything, constant still collapses to one). The Nuke half has no unit
test, since `_collapse` cannot be imported without `nuke`; it rides on
`test_nuke_roundtrip.py`, which passes, and on the shared fit.

**Key economy and the ease, 2026-08-26.** Two questions asked together: does
anything reach Nuke that is not needed to hold the shape inside tolerance, and
does an After Effects round trip keep the artist's ease. Both answers were no,
and they failed in three different places.

`test/probe/probe_key_minimality.py` is what settled the first. It computes the
true floor by dynamic programming over the range - the fewest keys any
piecewise-linear fit could use - and prints it beside what the pipeline
actually chooses. Holds are modelled as flat, as spec section 10.2 requires;
the first cut priced a held segment as a line, reported the next key's whole
travel as drift, and made the drift pass look far worse than it was. Pass
`--free` to unpin the authored keys, which answers the different question of
how much of a count is the artist's and how much is ours.

**The drift pass converged above the floor.** `_survey` pins a gap's worst
frame and the gap's midpoint together, because a worst frame that is an end of
the run shortens it instead of splitting it - and the midpoint is usually
redundant the moment the worst frame lands beside it. Nothing revisited it.
`_sweep` now runs after convergence and hands back every added key the fit does
not need: 9 keys became 4 on `held_over_moving_layer.rbj`, and the export side
now lands exactly the DP minimum on all eight goldens. Only keys the pass
invented are candidates.

That cost both importers an assumption. `apply_keys` is documented as writing
exactly the frames it is given, but both were written when the pass only ever
grew, so both only ever added - which the sweep turns into a report describing
a shape nobody has. `AnimControlPoint.removePositionKey(time)` does it in Nuke
(probed on 17.1v1, `test/probe/probe_nuke_key_removal.py`) and `removeKey` past
`nearestKeyIndex` in After Effects, addressed by frame because the host
renumbers every key above the one that goes. The sweep also has to leave the
host holding what it returns, since a trial must be applied to be measured and
the last one is refused as often as not; **the ES3 suite caught that before the
Python suite did**, which is the case for keeping both.

**A layer transform's keys were taken as the shape's own.** They reach a
shape's `keys` because `.rbj` describes canonical space with the transform
baked in, so an animated ancestor moves the geometry even when the path never
does - but that is a reason to consider the frame, not to key it. `sparseKeys`
now pins only the artist's path keys, the two range endpoints and every held
key, and hands the rest to `conformEase` as candidates. The Nuke exporter
unions transform frames the same way and is **deliberately** left alone: its
`keys` carry Nuke's own interpolation rather than a conformed linear one, so
fitting a line to decide what to drop would assert something about the curve
that was never measured. `_sparse_keys` carries that reasoning.

**The ease conform is not a culprit**, which is worth recording because it
reads as one. `ae_static_ease.rbj` conforms 3 keys to 25 of 25 - but that
fixture travels 700 px in 24 frames, 101 px on its worst frame, and 25 is the
DP floor there too. On roto-sized motion it is proportionate: a 25-frame
ease-in-out costs 5 keys over 10 px of travel, 9 over 40 px, 17 over 120 px.

**AE to AE lost the ease, and nothing in the middle was broken.** The format
stores it, the importer restores an `ease` block in the host's own units
exactly, and the exporter has kept the authored keys as `pre_conform_keys`
since `0096bfe`. Nothing read them. The AE importer now prefers them where the
file carries them, and says so - the file also carries the exporter's warning
that the timing was conformed away, and without a line saying otherwise the
artist reads that their ease is gone while looking at it. Nuke goes on reading
`keys`. `test/probe/probe_ae_ease_roundtrip.js` shows all three states.

Also: the two message tables, Python and the ES3 port, are now checked against
each other code for code and byte for byte. Nothing checked them before, and
the ease-restored message was the first new one in a while.

**Two linear keys, fifty frames apart, 2026-08-26.** The plainest thing an
artist can ask of the tool, and the one that found two bugs. Two keys, both
linear, fifty apart, nothing else animated: nothing should be added, either
direction.

AE to Nuke already added nothing - measured in 17.1v1 with
`test/probe/probe_nuke_two_linear.py` against `test/golden/two_linear_keys.rbj`
(what the exporter writes from that comp): key times `[0, 50]` on the node, 0
corrective, 0.0000 px. Tolerance 0 keys all 51, which is the documented dense
mode.

AE to AE added two, on the attributes. Opacity and uniform feather have no
sparse layer in the format, so they arrive one value per frame, and the
collapse of `5f7649e` reduced a constant to **one key rather than none**. One
key is still one more than the artist had, and it stops the property being
editable as the plain value it is. `setSamples` now sets a value where the
collapse leaves a single sample. `ae_mock.setValue` had to grow up for it: it
was an alias for `setValueAtTime(0, ...)`, which creates a key - the opposite
of what the call means, and nothing had ever called it.

**And a regression from `c00eed1`, which is the real lesson.** The scenario's
static variant made the import fail outright. `pre_conform_keys` was written
whenever the conform changed anything, including when all it changed was the
exporter's own placeholders - a pinned endpoint carries `ease` with no
parameters, meaning "unknown, rely on the drift pass", not a curve anyone drew.
A static mask therefore shipped provenance saying "bezier both sides" and the
importer, now that it reads the member, built exactly that. It is now written
only where a real `ease` block was lost, carries the pinned frames rather than
the transform union it had been quietly handing back (which undid the
transform-key work on any AE-to-AE trip), and spells a placeholder side
`linear`.

### Open

- **A mask with no path keys comes back with two.** The exporter pins the range
  endpoints so the sparse layer brackets the truth rather than flattening at
  its edge, and nothing in the file distinguishes an endpoint the exporter
  invented from two identical keys the artist authored. Dropping them on that
  guess breaks the rule that an artist's keys are never ours to remove - a
  first cut that did it failed eight tests whose fixtures rely on authored keys
  being honoured. The fix is for the exporter to say which keys it invented,
  which is a format question. Recorded in `test/probe/README.md`.

- **A circle drawn in After Effects arrives in Nuke as a straight-sided
  polygon.** Reported from the host 2026-08-25 with screenshots, still unfound.
  The Nuke half is cleared: importing `test/golden/ae_scene.rbj`, node tangents
  equal file tangents exactly (22.0000 against 22.0000) at tolerance 0.5 and 0,
  so the importer applies what it is given and a flat shape means a flat file.
  RotoBezier was ruled out by the screenshot - the handles are visible.
  `test_ae_to_nuke.py` passes but reads a committed golden, so it does not
  exercise today's live exporter. What is needed is either the reporter's own
  `.rbj` or a run of `test/probe/probe_ae_tangents.jsx` on the mask in
  question, which alerts the largest in/out tangent the host hands a script:
  zeros mean the host is withholding them, non-zero means the exporter drops
  them between the host and the file.

- **Nothing checks the two message tables** was true until `b8f2ba2`; they are
  now compared code for code and byte for byte by `TestEs3CrossCheck`. Noted
  because the same gap may exist elsewhere in the port.

## IN PROGRESS: invented keys become removable, 2026-08-26

The user's ruling closes the static-mask question: a property the artist never
keyed arrives with no keys, one or two authored keys arrive as one or two, and
ease costs extra keys only where measurement demands them - with every scrap
of authored ease saved in the file for an AE-to-AE trip. The plan, updated as
each chunk commits:

1. [x] core: `correct`/`linear_fit` take `authored`; `_sweep` may drop an
   unauthored endpoint, measuring the truncated span (both hosts hold the
   nearest key beyond it). Python + ES3 + tests.
2. [x] format: `authored_frames` (spline keys the artist authored, may be
   empty) and `authored_attributes` (opacity / feather_uniform keys with
   value, interp, ease) in spec/rbj-v3-draft.md; both validators; tests.
3. [x] AE exporter writes both; Nuke exporter writes `authored_frames` (its
   point-curve union, before the transform union); tests.
4. [x] AE importer: static path when `authored_frames` is empty and the
   measure allows; `authored` threaded into the drift pass; attributes
   restored from `authored_attributes` with host-measured correction; tests.
5. [x] Nuke importer: `_collapse` marks its seeds unauthored; `authored`
   threaded into the path drift pass; static adopted after probing 17.1v1
   (`test/probe/probe_nuke_static.py` and `_static2`): a keyless
   `AnimControlPoint` holds what `setPosition` gives it, and `attrs.add`
   with the curve left empty is a true zero-key constant. A shape whose
   dense frames are identical and whose `authored_frames` is empty now
   arrives with no point keys at all; a single collapsed attribute sample
   arrives as a plain value. The real round trip passes
   (`test_nuke_roundtrip.py`, headless), with `thin_keys` now dropping
   `authored_frames` since it fakes a foreign tier-2 file. The two-linear
   probe still lands [0, 50], 0 corrective, 0.0000 px.
6. [ ] suites + headless Nuke roundtrip, HANDOFF, bump, package.
7. [ ] full code review of the repo.
