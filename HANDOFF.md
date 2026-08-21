# RotoBridge - working state

Scratch record of where things stand. Detail lives in `prd.md` and
`test/probe/README.md`; this file only holds what those two do not.

Last updated: 2026-08-20 (Q10 closed; Phase 4 complete, both layers;
Nuke-to-AE crossing tested host-free)

## Status

`prd.md` is at **4.8**. Phase 0 is complete on both sides and **every open
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
`test/test_core.py` is **153 passing tests**, run with `python3
test/test_core.py` (not `unittest discover` - `test/` is deliberately not a
package). `./test/run.sh` runs all five host-free suites: **324 tests**.

`test/test_nuke_roundtrip.py` is the Phase 2 **and Phase 3** acceptance test and
needs Nuke; the invocation, including the sync step, is in
`test/probe/README.md`. Last run: **PASS**. Dense worst deviation 3.05e-05 px,
which is Nuke's float32 storage floor and not accumulated error; sparse 5-key
round trip 6.1e-05 px with **0 corrective keys**; drift bound 30.9 px unbounded
against 0.465 px at tolerance 0.5. Report committed at
`test/golden/nuke_probe/17.1v1/phase3/roundtrip_report.txt`.

Golden files: `test/golden/square.rbj` (hand-built), `test/golden/roundtrip.rbj`
(a real Nuke export carrying every v1 field) and `test/golden/sparse.rbj` (a
real export of a shape keyed on 5 frames of 41). All three are validated with no
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

Nothing is committed to git - the repo has an initialised `.git` with zero
commits.

## In flight

Nothing blocking, no phase half-done, and **no open questions** - Q10 closed
2026-08-20. Phase 4 is complete in code and in the host-free tests; what it has
not had is a run inside After Effects. See `Next`.

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

`ff` (feather falloff) is still unverified in the same class as blend was: it
defaults to `1.0`, the API never names its values, and the adapters treat
non-zero as `smooth`. It round trips Nuke to Nuke because the same rule runs both
ways, so it is only exposed once a file actually crosses between the two
applications. That is Phase 5, not Phase 4: the AE adapters name their falloff
values (`FFO_LINEAR` 7213, `FFO_SMOOTH` 7212) and carry them faithfully, which
narrows the question to Nuke's half but does not answer it.

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

  Synced there 2026-08-20. Re-copy after any edit under `ae/`, for the same
  reason the probe needs it.

## Next

1. **Phase 4 needs a run in After Effects.** Everything else about it is done
   and tested with no host present. The by-hand checklist is in
   `test/probe/README.md` under "After Effects adapters" and names what the mock
   cannot reach.

   **Run `test/probe/setup_ae_scene.jsx` first.** It authors the whole scene -
   five masks, one per checklist row that needs something built, on a scaled and
   rotating layer - so the run is the same every time and a difference in the
   fixture cannot be mistaken for a difference in the adapters. It ends in an
   alert saying what to look for in each mask. Its own final line is worth
   reading too: an authoring step that failed is reported rather than thrown,
   and `setTemporalEaseAtKey` is the one call in it that no probe run has ever
   made in the host.

   The two entries that matter most:

   - **A mask keyed with bezier ease, exported and reimported.** This is the one
     interpolation `test/ae_mock.js` refuses to guess at. The question is
     whether the drift pass reports a near-zero residual on a file that came out
     of After Effects in the first place. If it does not, the ease values `.rbj`
     carries are not reproducing AE's own curve, and spec §10.3 needs looking at
     rather than the adapter.
   - **Ease-then-type ordering.** `setTemporalEaseAtKey` is documented to force
     a key to BEZIER, so the importer sets the ease first and the per-side types
     after. The mock reproduces the forcing and a test pins the outcome, but
     whether the ease *survives* that second call is the host's answer. The
     symptom to look for is a hold key that renders smooth.

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

3. **Phase 6 - extras.** Open splines, the inverted flag, mask expansion, richer
   ease fitting. All three are currently dropped with a warning, which is the
   correct behaviour for v1 and is tested as such.

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
