# Probes

Scripts that answer open API questions by measuring, rather than trusting
introspection. `probe_nuke.py` and `probe_ae.jsx` are Phase 0; everything
downstream was blocked on their output. `probe_nuke_phase2.py` is Phase 2 and
answers what the dense adapter pair actually has to call.

**Run the Nuke probe first, and read `10_tangent_persistence_CRITICAL.txt`
before anything else.** If bezier tangents do not survive the API write path in
your Nuke version, shapes import as straight polylines and the Nuke importer
cannot ship as specified. That result changes the project, not just the code.

## Nuke

This machine has Nuke on the **Windows** side with a **non-commercial** licence
(`nukenc` token). Two consequences: `-t` alone requests a render licence and
fails, so `--nc` is required; and NC caps Python-visible nodes at 10, so the
probe calls `scriptClear()` between cases.

From WSL:

```bash
cp test/probe/probe_nuke.py "/mnt/c/Users/shann/rotobridge/probe/"
"/mnt/c/Program Files/Nuke17.1v1/Nuke17.1.exe" --nc -t \
    "C:\Users\shann\rotobridge\probe\probe_nuke.py" \
    "C:\Users\shann\rotobridge\out"
```

Both paths must be Windows paths - the Windows exe cannot read `/home/...`.
Copy the results back into `test/golden/nuke_probe/<version>/` and commit them.

Nuke 16.0v8 is also installed; swap the exe path to capture a second version.

**Status: run against 17.1v1, 10/10 cases passing.** Results are committed under
`test/golden/nuke_probe/17.1v1/`.

Two stages. **Stage 1** dumps the real API surface using only `dir()`, so it
cannot fail - `00_api_surface.txt` and `01_attribute_names.txt` are the files
that unblock everything else. **Stage 2** exercises behaviour; those calls use
signatures we have not confirmed yet, so each case is guarded. A case that fails
writes `<name>.FAILED.txt` with the traceback and the run continues.

| Case | Result on 17.1v1 |
|---|---|
| `10_tangent_persistence_CRITICAL` | **PASS.** Bezier tangents survive save/reload unchanged. The `prd.md` 9.2 risk is retired |
| `20_animcurve_key_introspection` | `AnimControlPoint.dim` is 3; `getControlPointKeyTimes()` returns the key times. That call is the key-union source for `prd.md` 9.2 step 3 |
| `21_hermite_tangent_semantics` | **Default point-curve interpolation is NOT linear** - it undershoots by up to 5.5 units across a 3-key span. The fix is per key, not per curve; see Phase 2 cases 71 and 74 |
| `30_shape_transform_matrix` | **`getMatrixAt()` does not exist.** Real path is `evaluate(frame)` -> `CTransform` -> `getMatrix()` / `getInverseMatrix()`. `isDefault()` detects identity, `getTransformKeyTimes()` feeds the union |
| `40_lifetime_defaults` | Default `ltt=0, ltn=1, ltm=1`; `getVisible()` true on frames 1-500. Lifetime is a non-issue at the default |
| `50_element_type_dispatch` | `isinstance` against `Shape`/`Stroke`/`Layer` works as specified |
| `60_feather_attributes` | `ShapeControlPoint` has exactly six members, all `AnimControlPoint` |
| `61_feather_representation` | **`featherCenter` is a 2D offset, not a width scalar**, and carries its own tangents. See Known gaps |
| `62_uniform_feather` | The **other** feather layer. `fx`/`fy` is 2-D and maps 1:1 to AE `maskFeather`; it animates; it is independent of `featherCenter`. Three API traps, see Known gaps |
| `63_key_interp_asymmetry` | `AnimCurveKey` has one `interpolationType` but independent `lslope`/`rslope`, and asymmetric slopes stick. **The key field is the `InterpolationType` enum plus one**; step is outgoing-only. See Known gaps |

Nuke 16.0v8 is also installed; swap the exe path to capture a second version and
diff the two directories.

## After Effects

Open a comp, select **one** layer that has **at least one mask**. Key the mask
path on a few frames first, with mixed interpolation (one hold, one linear, one
eased) - sections C and G have nothing to report on a static mask.

Section E reads your mask, so it reports only what you happened to set up. **E2
builds its own mask** and needs no preparation - it exists because four runs in a
row failed to exercise uniform feather through manual setup. Prefer adding
coverage to E2 over writing setup instructions here.

```
File > Scripts > Run Script File...  ->  probe_ae.jsx
```

It prompts for where to save a text report. Your mask is only read; the
transform and write tests build temporary layers and delete them, all inside one
undo group.

| Section | Answers |
|---|---|
| B | `maskPath` value structure; are tangents relative or absolute? |
| C | Reading authored key times and interpolation types |
| D | Whether `BEZIER`/`HOLD` are legal on `maskPath`. If not, tier 1 is unreachable and everything falls to tier-3 drift correction |
| E | Whether variable-width feather is scriptable at all, and so whether per-point feather has any landing place in AE. Reads **your** mask, so it only reports what you set up |
| E2 | Uniform feather anisotropy, animation, feather-point **writing**, and composition. Builds its own mask, so it needs no setup and cannot be defeated by how yours is configured |
| F | Whether the transform-then-subtract tangent method survives scale + rotation. If not, scope narrows to identity-transform layers |
| G | Temporal ease dimensions and values - the input to the `.rbj` `ease` params |
| H | Key write round-trip, and how long 100 `valueAtTime` read-backs take. This is the drift-pass budget (`prd.md` 15 Q6) |

**Status: run six times against 25.6x101.** Results are committed under
`test/golden/ae_probe/`. Two runs are load-bearing and must not be pruned as
redundant: **run 3** is the only one with feather points authored on the test
mask, and **run 6** is the only one with mixed key interpolation, which is what
exposed Q9. Runs 1 and 2 are kept because they document two probe defects that
were fixed (`sourcePointToComp` arity, and section E searching the mask property
group instead of the `Shape` object).

## After Effects adapters

Not probes - the Phase 4 adapter pair. They install like any other script:

```
File > Scripts > Run Script File...  ->  ae/rotobridge_export.jsx
File > Scripts > Run Script File...  ->  ae/rotobridge_import.jsx
```

Both `#include` `rotobridge_ae.jsx`, which includes `rotobridge_core.jsx` and
`rotobridge_rbj.jsx`, so **all five files must sit in the same folder**. Copy
the whole `ae/` directory rather than one script.

Unlike the Nuke pair, most of this is testable with no application present:

```bash
./test/run.sh          # 369 tests, no host needed
```

`test/ae_mock.js` stands in for After Effects - `valueAtTime`,
`sourcePointToComp` with no time parameter, mask properties by matchName,
feather points on the `Shape` object, and an exactly affine layer transform.

**Between keys it interpolates only what has been measured or is definitional.**
Two LINEAR sides interpolate straight, which run 6 section H measured on a real
mask path; a HOLD outgoing side freezes the segment, which is what hold means;
and past the last key the last value stands, because After Effects does not
extrapolate. **BEZIER raises.** Its shape depends on influence and speed in a
way nothing here has measured, and a plausible-looking guess would make the
drift pass look tested while doing nothing in the host.

That line is what makes the drift pass genuinely testable rather than
decorative: a file whose sparse layer is two straight keys over a curved dense
layer really does drift in the mock, and the pass really does have to find it.
Anything resting on AE's *bezier* interpolation still has to be measured in the
host.

`test/test_ae_crossapp.js` goes one step further than the mock's own round
trip. It takes the two Nuke goldens through the importer and straight back out
through the exporter, which is the only place in the project where the two
applications' conventions are **compared** rather than cancelled - a same-app
round trip returns what it was given even if Y, feather's sign or ease's scale
were all wrong. `roundtrip.rbj` comes back bit-identical, dropping only the
`feather_offset` it documents; `sparse.rbj` keeps its 5 authored keys with 0
corrective and rebuilds the 36 frames between them to within 3.05e-05 px of what
Nuke wrote. It renders no pixels, so it narrows Phase 5 rather than replacing it.

The import asks three questions: start frame, shape subset, and drift tolerance
in pixels. The third only appears when the file has keys to honour - `0` keys
every frame and is exact but uneditable, `inf` keeps only the authored keys, and
the `0.5` default lands corrective keys where the mismatch would show.

**Build the scene with `test/probe/setup_ae_scene.jsx`** rather than by hand.
It adds one solid carrying six masks, one per row below that needs something
authored, on a layer that is both scaled and rotating so the derived-affine path
is live. Everything is inside one undo group, and it ends in an alert saying
what to look for in each mask. A hand-drawn mask differs run to run, and a
difference in the fixture reads exactly like a difference in the adapters.

The scene deliberately cannot be exported under the mock: its `eased` mask is
bezier on every side, and the dense bake would have to interpolate one. That is
the whole reason it has to be built in the host at all. Three tests in
`test_ae_export.js` check that the builder still runs and authors what it
claims, because a typo in it is otherwise only discovered on another machine.

### Re-exporting the scene golden

`test/golden/ae_scene.rbj` is a host artefact, so a change to the exporter does
not update it - it makes it stale, and every downstream measurement keeps being
taken against the old answer. Re-exporting is a by-hand run, and the last
step is the one that matters.

```bash
cp ae/*.jsx "/mnt/c/Users/shann/OneDrive/Desktop/rb-ae/"   # all five together
```

1. Make an **empty comp, 1920 x 1080, 24 fps, at least 25 frames** and leave it
   active. Those numbers land in the file's `source` block and the builder takes
   its solid size from the comp, so a comp that differs is a different fixture.
   Build in a fresh project rather than one that already has the scene - the
   builder adds solids, it does not replace them, and a second copy exports as
   twice the masks.
2. `File > Scripts > Run Script File...` -> `setup_ae_scene.jsx`. It authors two
   solids: `RotoBridge test` with the six masks, and `RotoBridge static` with
   the two control masks.
3. **Select the `RotoBridge test` layer, and only that one.** With nothing
   selected the exporter takes every masked layer in the comp, which is eight
   shapes and a different file. (`ae_static_ease.rbj` is the other solid,
   exported the same way with the other layer selected.)
4. Same menu -> `rotobridge_export.jsx`. Save as `ae_scene.rbj`.
5. Read the alert: **6 shapes, 600 points, 4 warnings**. Any other count means
   step 1 or step 3 went wrong, and the file is not this fixture.
6. Copy the file back over `test/golden/ae_scene.rbj`.
7. **Check the diff before committing it**, against the version you replaced:

```bash
git show HEAD:test/golden/ae_scene.rbj > /tmp/ae_scene_was.rbj
python3 test/probe/diff_rbj.py /tmp/ae_scene_was.rbj test/golden/ae_scene.rbj
```

Step 7 is the point of the exercise, and `diff_rbj.py` exists because a plain
`diff` cannot do it: the file is a thousand lines of pretty-printed floats, so a
one-ulp wobble in the bake and a flipped `interp` label look identical in it.
The tool reports geometry as a worst-case distance and labels one at a time.

**The re-export is only believable if the diff is the one that was predicted.**
Geometry identical, and exactly two lines under labels:

    mixed key 12 out: hold -> ease
    mixed key 18 out: ease -> hold

Anything else means the fixture moved, not the exporter - a different AE build,
a stale project, a hand-tweaked mask - and the file should not be committed
until that is explained. Geometry drifting by a float epsilon is fine and worth
recording; geometry drifting by a pixel is a different scene.

Then re-run the crossing, because `ae_to_nuke_report.txt` is measured against
this file. `mixed` currently reports 5 authored + 15 corrective at tolerance
0.5; with the hold in the right place the drift pass has a flat segment to
agree with, so expect roughly 3.

What still has to be run by hand, and what to look for:

| Check | Why the mock cannot do it |
|---|---|
| Export a real animated mask, reimport it | The mock's transform is affine by construction; the host's is affine by assumption, and the adapters verify that at runtime. A warning naming a layer as "not affine" is the interesting result |
| A mask keyed with **bezier** ease, reimported | The one interpolation the mock refuses. The question is whether the drift pass reports near-zero residual on a file that came from After Effects in the first place - if it does not, AE's ease is not being reproduced by the ease values `.rbj` carries |
| **Ease then type, in that order** | `setTemporalEaseAtKey` is documented to force the key to BEZIER, and the importer sets the types afterwards to put a `hold` or `linear` side back. The mock reproduces the forcing, but whether the ease *survives* that second call is the host's answer, not the mock's. Look for a hold key that renders smooth |
| A mask with feather points authored in the UI | Run 3 showed mid-segment placement and same-vertex collisions are the normal case. The snapping rule is tested; what is not is whether the host writes back what the importer hands it |
| A keyframe placed off the frame grid | The export snaps it and warns. Placing one needs a comp the artist retimed, which is easier to make by hand than to fabricate |
| `addProperty("ADBE Mask Atom")` on a real layer | Probe section E2 exercised it, so this is corroboration rather than a first run |
| `maskFeatherFalloff` on a shape from Nuke | The last mapping resting on a guess. Nuke's `ff` defaults to 1.0 and its API never names the values; After Effects names both of its. A file crossing from Nuke is where the two get compared |
| Timing against acceptance criterion 11 | Ten shapes, 150 frames, under 10 s. The loop shape that makes it reachable is asserted; the constant is not |
| **An open mask path, exported and looked at** | `spec/rbj-v2-draft.md` section 5. The document side is covered host-free - `closed: false`, `version: 2`, and it comes back open. What no probe run has ever authored is an open mask *at all*, so what After Effects renders one as is unmeasured, and it is the last thing between that draft and a freeze. Mask 6, `opened` |

## What Nuke's roto curves can and cannot be told

`test/probe/probe_nuke_ease.py` needs Nuke and nothing else - no scene, no
authored file. It answers what `lslope` / `rslope` / `la` / `ra` on a roto
`AnimCurve` actually do, which `core/interp.to_nuke` had been deferring since
Phase 3.

```bash
mkdir -p "/mnt/c/Users/shann/rotobridge/out/ease"
"/mnt/c/Program Files/Nuke17.1v1/Nuke17.1.exe" --nc -t \
    "C:\Users\shann\rotobridge\rb\test\probe\probe_nuke_ease.py" \
    "C:\Users\shann\rotobridge\out\ease"
```

Output in `test/golden/nuke_probe/17.1v1/ease/`. Four findings:

| Case | Finding |
|---|---|
| 109 | A **two-key** roto AnimCurve is exactly the chord whatever is written on it - except step, which holds. Any tangent measurement on two keys is degenerate; use three |
| 108 | On a three-key curve that demonstrably bends, `interpolationType` moves it and the four tangent fields do not |
| 115 | Under the cubic types Nuke **recomputes** a written slope: write 5.0, evaluate, read back 1.0101. And `interpolationType` **5 is a user-tangent mode** - case 63 labelled it "other" and never identified it |
| 117 | Only **interior** keys honour an authored tangent. Every value of the first key's outgoing slope and accel changes nothing |

An ease describes a segment from both ends, so the outgoing half is unreachable
by construction. Best fit to a real AE curve is 0.11 in unit terms, about 77 px
on that shape against a 0.5 px tolerance, at parameters that look nothing like
After Effects'.

**Do not sweep `curveType`.** It crashes Nuke outright, which is why the probe
does not.

## AE to Nuke crossing

`test/test_ae_to_nuke.py` takes the real `test/golden/ae_scene.rbj` - what After
Effects actually wrote from `setup_ae_scene.jsx` - into Nuke and back out. It is
the only test in the project that crosses applications **with a host running**,
so it is what acceptance criterion 10 rests on.

```bash
rm -rf "/mnt/c/Users/shann/rotobridge/rb" \
  && mkdir -p "/mnt/c/Users/shann/rotobridge/rb" \
  && cp -r core nuke test "/mnt/c/Users/shann/rotobridge/rb/"
"/mnt/c/Program Files/Nuke17.1v1/Nuke17.1.exe" --nc -t \
    "C:\Users\shann\rotobridge\rb\test\test_ae_to_nuke.py" \
    "C:\Users\shann\rotobridge\out\phase6"
```

The output directory must exist first; the test does not create it. An optional
**second argument names a different source `.rbj`**, and report names are
derived from it so one run does not overwrite another's. That is how
`ae_static_ease.rbj` is crossed - the file whose layer does not move, so nothing
it measures can be blamed on a baked ancestor transform:

```bash
mkdir -p "/mnt/c/Users/shann/rotobridge/out/hub"
"/mnt/c/Program Files/Nuke17.1v1/Nuke17.1.exe" --nc -t \
    "C:\Users\shann\rotobridge\rb\test\test_ae_to_nuke.py" \
    "C:\Users\shann\rotobridge\out\hub" \
    "C:\Users\shann\rotobridge\rb\test\golden\ae_static_ease.rbj"
```

What that run measured, and it is the number the roadmap turns on:

    eased_static    3 authored, 22 corrective   <- 25-frame range, fully dense
    linear_static   2 authored,  0 corrective   <- exact, free

An After Effects ease costs a key on every frame in Nuke; linear costs nothing.
Report at `test/golden/nuke_probe/17.1v1/hub/`. See `HANDOFF.md`, "Nuke is the
hub", for why that is a "cannot" rather than a bug.

**Status: PASS on 17.1v1**, 2026-08-21. Report at
`test/golden/nuke_probe/17.1v1/phase6/ae_to_nuke_report.txt`.

| Stage | Result |
|---|---|
| geometry, tolerance 0 | worst **6.1e-05 px** over 6 shapes and 25 frames - the float32 storage floor |
| the open spline | arrives open; closed shapes stay closed |
| key preservation, tolerance inf | the field-by-field diff is **empty** - `closed`, `feather_model`, `feather_falloff`, `blend`, key frames and per-side `interp` all identical, `{in: linear, out: hold}` included |
| drift, tolerance 0.5 | every shape inside tolerance; worst `mixed` at 0.1000 px |
| corrective counts | **Do not read these as a verdict on interpolation.** Every mask is on a rotating layer whose transform is baked into the points, so even `linear` bows 13.2 px off the straight chord between its own LINEAR keys and must need corrective keys. Masks 7 and 8, on the static solid, are what answer that |
| re-export | validates, `version: 2`, carries the open spline back |

**It imports three times and the modes are not interchangeable.** Tolerance 0
keys every frame by definition (`prd.md` §8), so its key list says nothing about
key preservation; reading one off it produces a page of "losses" that are only
dense mode working. Tolerance inf is the one that speaks to criterion 3.

## AE feather point order

Two probes, both about one number: importing `feathered` from
`test/golden/ae_scene.rbj` leaves exactly **27.0000 px** at frame 15 that the
drift pass cannot remove. The file's per-vertex feather is `[30, -15, 0, 12]`
and `12 - (-15) = 27`. `deviation()` in `ae/rotobridge_import.jsx` compares
`featherRadii` by array index, which is only sound if the host preserves order.

Both need any open comp and are run with `File > Scripts > Run Script File...`.
Sync first, as with every AE script:

```bash
cp test/probe/probe_ae_feather_interpolated.jsx \
   "/mnt/c/Users/shann/OneDrive/Desktop/probe_ae_feather_interpolated.jsx"
```

**`probe_ae_feather_order.jsx` - RUN 2026-08-21.** Sets the value once and reads
it straight back.

| Written | Read back |
|---|---|
| `radii [30, -15, 0, 12]` | `[30, -15, 0, 12]` |
| `types [0, 1, 0, 0]` | `[0, 1, 0, 0]` |
| `segLocs [0, 1, 2, 3]` | `[3, 0, 1, 2]` |
| `relSegLocs [0, 0, 0, 0]` | `[1, 1, 1, 1]` |

**Order is preserved**, so index-wise comparison is legitimate and `deviation`
was left alone. The anchors are **re-encoded**: "start of segment *i*" comes
back as "end of segment *i-1*", the same four positions renamed. Entry *i* keeps
its own radius. That kills the obvious fix - matching feather points by
`featherSegLocs` plus `featherRelSegLocs` would match nothing.

**`probe_ae_feather_interpolated.jsx` - RUN 2026-08-21.** Probe 1 tested a
static write and read. The importer writes **keys** and reads at frames
**between** them, which is where the drift pass measures.

| Frame | radii | types | segLocs | worst vs written |
|---|---|---|---|---|
| 0, on a key | `[30, -15, 0, 12]` | `[0, 1, 0, 0]` | `[3, 0, 1, 2]` | 0 |
| 6, **interpolated** | `[30, 0, 12, -15]` | `[0, 0, 0, 1]` | `[3, 1, 2, 0]` | **27** |
| 12, on a key | `[30, -15, 0, 12]` | `[0, 1, 0, 0]` | `[3, 0, 1, 2]` | 0 |

Identical for **LINEAR keys and BEZIER**, so it is interpolation that reorders,
not the curve type. The rule is **grouped by type, non-negative before
negative** - which was the original hypothesis, right about the rule and wrong
about the code path. Only splitting the static read from the interpolated one
could tell those apart.

**Nothing is lost.** The anchors move with the radii: `segLoc 3` carries 30 in
both rows, `segLoc 0` carries -15 in both. So `seg + rel`, the position in
segment units, identifies a point under both the rename and the regroup, and
that is what `deviation()` in `ae/rotobridge_import.jsx` now keys on. A raw
`(segLocs, relSegLocs)` match would **not** work: the target shape is built in
JS and never sees the host, so it carries `(i, 0)` while the host returns
`(i-1, 1)`.

`test/ae_mock.js` models both behaviours now, so this is caught without the
host: with the model in and the old comparison still in place, the pre-existing
"honours a real Nuke export's sparse layer" test fails with 41 keys instead of
5 - the pass keying every frame chasing drift that was never there.

Eliminated along the way, all host-free: it is not the geometry (`feathered`
bows only 3.856 px off its own chord, against 13.223 for `linear` and 49.175 for
`eased`), and it is invisible to Nuke, which converges the same shape to
0.2143 px carrying no feather at all because `feather_offset` is Nuke-only.

## Known gaps

Everything Phase 0 set out to answer is answered. Two findings that were open
after run 2 and are now closed:

**Feather was a format problem; run 3 closed it.** Case 61 shows Nuke has no
edge-width scalar - each control point carries a `featherCenter` 2D offset plus
`featherLeftTangent` and `featherRightTangent`. Run 3 shows AE's `featherRadii`
is a **signed** scalar (`[89.5565, 0, -46.6171, -1e-8]` against
`featherTypes [0,0,1,1]`). So `.rbj` v1 carries a signed `feather` scalar for
every adapter plus an optional Nuke-only `feather_offset` vector. See `prd.md`
section 15 Q7.

Run 3 also shows AE feather points are **not** one per vertex - four points on a
seven-vertex mask, three mid-segment, two on the same segment. Mid-segment
placement and same-vertex collisions are the normal case, not edge cases.

**Default interpolation is curved.** Case 21 means an importer that writes keys
and stops does not get linear motion between them - it gets a smooth curve that
undershoots. Case 62 shows the same applies to **attribute** curves, not just
point curves: keys at (1, 5) and (50, 40) evaluate to 22.14 at frame 25 against a
linear 22.5.

**The control is per key, and it is not `curveType`.** Phase 0 left this as an
assumption and Phase 2 corrected it. `CurveType` has no linear member at all -
it selects the spline basis (`eBezier`, `eHermite`, `eBSpline`, `eCardinal`,
`eCatmullRom`, `eNurbs`). Set `AnimCurveKey.interpolationType` to the
`InterpolationType` enum **plus one** instead: case 74 wrote `eLinear + 1 = 2`
on every key of both axes of a point position curve and got exactly the
piecewise-linear values.

**Handles go stale, and `append()` copies** (Phase 2 case 76). `rootLayer.append(x)`
puts a **copy** in the tree and leaves your `x` detached; touching it later
raises `internal error - associated c++ object is NULL`. Re-fetch the live child
out of its parent after appending, and re-fetch again after `knob.changed()`,
which invalidates `AnimAttributes` handles. This one at least fails loudly.

**`getValue` on an unknown attribute name auto-vivifies** and returns `0.0`
rather than raising, so a reader cannot distinguish an unset attribute from one
that does not exist on that element type. Use `getName(i)` to enumerate what an
element actually has before believing a `getValue` result.

**`isDefault()` is not an identity test.** It returns False on a transform that
has never been touched (cases 30 and 77), so it cannot be used to skip a bake.
Compare the matrix to identity numerically instead.

**Three traps when writing an animated shape attribute** (case 62), all of which
fail quietly rather than raising:

1. `AnimAttributes.addKey` introspects as `(time, name, value, view)` but the
   binding accepts **two** arguments. Use `attrs.getCurve(name)` to get a live
   `AnimCurve`, then `AnimCurve.addKey(time, value)`.
2. `attrs.add(name, value)` **shadows the curve**. On a shape where `add` ran
   first, `getValue` returned the constant at every frame while `evaluate()`
   returned the animated values. Write a constant or keys, never both.
3. `getValue`'s third argument is a view **name string** (`'main'`), not an
   integer. `getValue(25, "fx", 0)` raises.

Treat every signature in `00_api_surface.txt` as a hypothesis. `getMatrixAt`
(case 30) and `addKey` (case 62) both introspect as things that do not exist or
do not work.

**Nuke key interpolation is offset by one from the documented enum.**
`nuke.rotopaint.InterpolationType` defines `eStep = 0`, `eLinear = 1`,
`eCubic = 2`, `eUndefine = -1`, but `AnimCurveKey.interpolationType` wants the
enum **plus one**. A value sweep against reference curves confirms it:

| key field | behaviour | meaning |
|---|---|---|
| `0` | cubic default | unset |
| `1` | outgoing held flat | `eStep` + 1 |
| `2` | exactly linear both sides | `eLinear` + 1 |
| `3` | cubic | `eCubic` + 1 |
| `4`, `5` | a distinct smooth variant | undocumented |
| `256` | as `0` | unset sentinel, the value a fresh key reports |

Write `InterpolationType.eLinear + 1`, never the bare enum value. Note also that
**step is outgoing-only** - it changes the interval leaving the key and leaves
the incoming side alone, matching AE's `keyOutInterpolationType`.

**Timing varies run to run.** The `comp.time` + `sourcePointToComp` cost measured
5.75 ms on run 2 and 9.22 ms on run 3; `valueAtTime` measured 0.20 ms and
0.15 ms. Plan against the slow end. The conclusion is unchanged and stronger:
the export loop must be frame-major.

Section G's ease dimension count matters more than it looks. AE ease is
influence (%) plus speed (value-units/sec). Influence normalizes across control
points; speed does not, because each point travels a different distance between
two keys. **Resolved at the Phase 1 freeze:** `ease` is `[influence, speed]` per
side, shape-wide, matching AE's own model of one ease per key for the whole
`maskPath`. See spec section 10.3.

## Nuke, Phase 2

Same invocation, different script and a subdirectory of its own so Phase 0's
record is not churned (object reprs carry addresses, so re-running Phase 0
rewrites every file):

```bash
cp test/probe/probe_nuke_phase2.py "/mnt/c/Users/shann/rotobridge/probe/"
"/mnt/c/Program Files/Nuke17.1v1/Nuke17.1.exe" --nc -t \
    "C:\Users\shann\rotobridge\probe\probe_nuke_phase2.py" \
    "C:\Users\shann\rotobridge\out\phase2"
```

Results in `test/golden/nuke_probe/17.1v1/phase2/`.

| Case | Result on 17.1v1 |
|---|---|
| `70_matrix_application` | `mat * CVec3(x, y, 1)` works; `vec * mat` returns nonsense. `list(CMatrix4)` is 16 floats, row-major, translation at 3 and 7. **`getPosition` is pre-transform**, so the export must bake. `CVec` has `.x` / `.y` and is iterable |
| `71_point_keying` | `addPositionKey(frame, CVec3)` works. **`CurveType` has no linear member** - it is the spline basis, so `prd.md`'s "set `curveType` for linear" aimed at the wrong knob |
| `72_shape_attributes` | `getValue(t, name, 'main')` reads; `getCurve` + `addKey` writes and animates. Closed is `not getFlag(eOpenFlag)` |
| `73_blend_mode_identity` | `bm` is an opaque float; `serialise()` never names it. The Merge-list theory fails on the default value |
| `74_linear_point_curve` | **`interpolationType = eLinear + 1` is the linear control on point curves**, confirmed against exact piecewise-linear values. Untouched keys report `256` |
| `75_blend_mode_semantics` | Opened Q10 - and got the answer wrong. **Superseded by cases 94-98**: the sweep ran over 0-29 when the menu has 15 entries, and it swept the lower of two shapes, where a blend cannot reach the overlap |
| `76_layer_blend_semantics` | A `Layer` has **no `bm` attribute** (`vis, opc, mbo, mb, mbs, fo, fx, fy, ff, ft, warp, pt*`); a `Shape` does. Adding one to a layer reads back but renders nothing. Still true; case 93 found the UI control on the **node** instead |
| `77_layer_transform` | **Layers carry their own transform**, independent of the shape's, and `getPosition` reports neither. Flattening without composing the chain moved geometry silently - a real bug, now fixed |
| `78_transform_chain_order` | Composition order when both a layer and a shape are transformed is **still unmeasured**: `Shape.evaluate()` is pre-transform too, so there is no oracle. The export warns when it matters |

## Nuke, Q10

`probe_nuke_q10.py` closes Q10: what a subtractive roto layer actually stores.
Two halves. Cases 90-93 read a script **authored in the UI**, which is the only
authority once Python introspection has been wrong twice; cases 94-98 build
their own scene and need no script.

```bash
cp test/probe/probe_nuke_q10.py "/mnt/c/Users/shann/rotobridge/probe/"
cp test/golden/nuke_probe/17.1v1/q10/layer_minus.nknc "/mnt/c/Users/shann/rotobridge/probe/"
"/mnt/c/Program Files/Nuke17.1v1/Nuke17.1.exe" --nc -t \
    "C:\Users\shann\rotobridge\probe\probe_nuke_q10.py" \
    "C:\Users\shann\rotobridge\probe\layer_minus.nknc" \
    "C:\Users\shann\rotobridge\out\q10"
```

The script argument is optional and is recognised by its extension; drop it and
cases 90-93 are skipped. Results in `test/golden/nuke_probe/17.1v1/q10/`.

**NC saves are encrypted on disk** - `layer_minus.nknc` starts with the plain
line `Nuke NC mode encrypted text (commercial mode uses plain text)` and nothing
else in it is readable. It cannot be diffed as text; it has to be loaded and
serialised from memory, which is what case 91 does.

| Case | Result on 17.1v1 |
|---|---|
| `90_authored_tree` | The saved script holds **two empty layers and no shapes**. Nothing to render, nothing off default in the tree |
| `91_serialised_form` | Confirms it: neither layer serialises a `bm`, and the two are byte-identical to each other |
| `92_rendered_alpha` | Alpha is 0 everywhere, as an empty tree should be |
| `93_node_knobs` | **The answer.** `blending_mode = 'minus'` against a default of `'over'`. It is a **node knob**, which is why cases 73, 75 and 76 all missed it searching the curves tree |
| `94_blending_knob_anatomy` | `blending_mode` is an `Enumeration_Knob` with **15** values, each carrying its stored number. That is the `bm` numbering, and it is **not** the 30-entry Merge list case 73 guessed from |
| `95_shape_blending` | The knob is a proxy for the GUI selection. `setFlag(eSelectedFlag)` does not drive it - the sweep wrote nothing and changed nothing |
| `96_layer_blending` | Same with a layer selected. The knob is unusable from Python; only its value list was needed |
| `97_bm_against_an_input` | Written numerically over 0-14, `bm` **is** live and moves both alpha and colour. Case 75 read only alpha, and only in the one place a blend cannot show |
| `98_shape_to_shape` | **The finding.** `rootLayer` index 0 renders on top; a blend composites against what is below and only inside its own outline. No value is a boolean set operation. See `prd.md` §15 Q10 for the full table |

Two method errors in case 75 produced its wrong conclusion, and both are worth
remembering: it swept 0-29 when the menu has 15 entries, and it swept the
**lower** of the two shapes, where a blend cannot affect the overlap at all.

## Nuke round trip

`test/test_nuke_roundtrip.py` is not a probe but the Phase 2 **and Phase 3**
acceptance test. It builds a shape carrying every field `.rbj` v1 has, exports,
reimports, and compares every point on every frame; then it does the same for
the sparse layer.

```bash
rm -rf "/mnt/c/Users/shann/rotobridge/rb" \
  && mkdir -p "/mnt/c/Users/shann/rotobridge/rb" \
  && cp -r core nuke test "/mnt/c/Users/shann/rotobridge/rb/"
"/mnt/c/Program Files/Nuke17.1v1/Nuke17.1.exe" --nc -t \
    "C:\Users\shann\rotobridge\rb\test\test_nuke_roundtrip.py" \
    "C:\Users\shann\rotobridge\out\phase3"
```

It needs `core/` and `nuke/` copied alongside it, since the Windows exe cannot
read `/home/...`, and the copy is a copy - **sync it before every run** or the
old version runs and the results look unchanged. The report and the two `.rbj`
files it produces are committed as `phase3/roundtrip_report.txt`,
`test/golden/roundtrip.rbj` and `test/golden/sparse.rbj`.

Phase 3 stages and what they establish on 17.1v1:

| Stage | Result |
|---|---|
| sparse layer written | 5 authored linear keys export as exactly `[1, 11, 21, 31, 41]`, all `{in: linear, out: linear}` |
| sparse import | the same 5 keys come back, **0 corrective**, worst 6.1e-05 px - tier 1 is exact |
| transform as animation | a shape with **no point keys** under a translation keyed at 1 and 20 exports keys `[1, 20]` and a baked travel of 400.0 px |
| drift bound, criterion 4 | a dense layer thinned to two straight keys drifts **30.9 px** unbounded, and **0.465 px** at tolerance 0.5 using 12 keys of a possible 20 |
| mode switch, criterion 5 | re-importing that same thinned file at tolerance 0 reaches 3.05e-05 px, with no trip back to the source |
| criterion 11 | 20 points over 150 frames: export 0.39 s (budget 10), import 0.07 s at either tolerance (budget 30) |

The drift stage thins the file on purpose. **Nuke to Nuke does not drift** - the
same key type through the same key frames re-evaluates to the same curve, which
is the round trip working, not a gap in the test. Tier 3 only has something to
do when the sparse layer cannot reproduce the dense one, which is what a foreign
exporter's tier-2 output looks like, so the test constructs exactly that.
