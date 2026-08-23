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
| `63_key_interp_asymmetry` | `AnimCurveKey` has one `interpolationType` but independent `lslope`/`rslope`, and asymmetric slopes stick. **The key field is the `InterpolationType` enum plus one**; step freezes only the interval it leaves and draws the one it arrives on as a cubic - `eval(25)=0.6759`, not linear's `0.4898`. See Known gaps and "the step key's incoming side" |

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
DEST="/mnt/c/Users/shann/OneDrive/Desktop/rotobridge_ae"
cp ae/*.jsx test/probe/setup_ae_scene.jsx "$DEST/"
for f in ae/*.jsx; do diff -q "$f" "$DEST/$(basename $f)"; done
```

Do the copy and the `diff` even when you are sure, because a stale deployment is
the one failure this whole procedure cannot see. The scripts run on the Windows
side and the acceptance check runs here; nothing connects them. An export from a
script one commit behind produces a plausible file, a plausible alert, and a
diff that is simply the wrong shape - and the natural reading of that diff is
that the fixture moved. This has already happened once. The five `ae/*.jsx` load
each other and must go together; `setup_ae_scene.jsx` lives elsewhere in the
tree, so a `cp ae/*.jsx` on its own leaves it behind.

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
5. Read the alert: **6 shapes, 600 points, 10 warnings, 74 authored keys**.
   Any other count means step 1 or step 3 went wrong, and the file is not this
   fixture. **2 shapes and 200 points is the `RotoBridge static` layer**, the
   other solid in the same comp - the commonest way to get a plausible file
   that is not this one, and it has happened. The warning count has moved three
   times and the number alone is a deployment check: four means a build before
   `0ccfcbb`, which is where the ease conform landed; five means one before
   `fc712d5`, where `feathered` stopped being snapped; four before that meant a
   build predating `0c1b3af`.
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
That prediction changes every time the exporter does, so it is written down
here beside the commit that moved it. The exporter last moved at `0ccfcbb`,
which conforms ease, and the prediction for the next run is under "The export
conforms ease" below - it is long enough to need its own section, and it is
derived rather than guessed.

The previous one is kept because it is the shape a prediction should have. As
of `fc712d5`, against the golden committed at `df8584f`:

    --- labels ---
    feathered feather_model: 'per_point' -> 'anchored'
    warning changed: ... 3 feather point(s) sat mid-segment ...   (gone)
    warning changed: ... two feather points resolved to vertex 3 ... (gone)
    warning changed: ... feather is anchored along the path ...    (new)

    --- geometry ---
    feathered: anchor added at t 0.25, feather 30 on every frame
    feathered: anchor added at t 0.75, feather -15 on every frame
    feathered: anchor added at t 2.5, feather 12 on every frame
    feathered: anchor added at t 3, feather 0 on every frame
    feathered: point 0: feather 30 -> None on every frame
    feathered: point 1: feather -15 -> None on every frame
    feathered: point 2: feather 0 -> None on every frame
    feathered: point 3: feather 12 -> None on every frame

Nothing about the vertices, and nothing about any other shape. `feathered` is
the only mask in the scene whose feather sits off a vertex, so it is the only
one section 6.7 promotes; the rest stay exactly as they were.

The four anchors are the ones `setup_ae_scene.jsx` authors, at `seg + rel` of
`[0.25, 0.75, 2.5, 3.0]`. Under v1 the radius-12 one travelled 150 px along the
path to reach vertex 3 and landed on the authored radius-0 point, which was
discarded - a corner deliberately pinned to zero width arriving 12 px soft.
That is the defect this whole section exists to fix, so the line that matters
most in that diff is `anchor added at t 3, feather 0`.

Anything else means the fixture moved, not the exporter - a different AE build,
a stale project, a hand-tweaked mask - and the file should not be committed
until that is explained. Geometry drifting by a float epsilon is fine and worth
recording; geometry drifting by a pixel is a different scene.

Then re-run the crossing, because `ae_to_nuke_report.txt` is measured against
this file. Two things to expect from it after the feather work: `feathered`
arrives in Nuke with **more vertices than the artist drew** - three anchors sit
mid-segment, so three vertices are inserted to hold them - and the import warns
saying so. The subdivision is exact, so its geometry should not move.

Run 2026-08-21, before the feather work: `mixed` went from 5 authored + 15
corrective at tolerance 0.5 to 5 + 11, which is in line with every other moving
shape rather than an outlier. The prediction beforehand was "roughly 3" and was
wrong; it counted only the false hold and forgot that segment 12 to 18 still
needs a cubic fitted to a real After Effects curve, same as everywhere else.
What the fix bought is frames 19 to 23, now exactly flat and needing nothing.
Worst error rose from 0.1000 px to 0.4503 px and stayed inside the 0.5
tolerance - fewer corrective keys means more residual, which is the trade the
tolerance is for.

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

## Nuke, the step key's incoming side

`test/probe/probe_nuke_step.py`. One question, measured on the file it costs
something in: what a step key does to the segment **arriving** at it. Result
committed at `test/golden/nuke_probe/17.1v1/step/nuke_step_incoming.txt`.

```bash
rm -rf "/mnt/c/Users/shann/rotobridge/rb" \
  && mkdir -p "/mnt/c/Users/shann/rotobridge/rb" \
  && cp -r core nuke test "/mnt/c/Users/shann/rotobridge/rb/"
mkdir -p "/mnt/c/Users/shann/rotobridge/out/step"
"/mnt/c/Program Files/Nuke17.1v1/Nuke17.1.exe" --nc -t \
    "C:\Users\shann\rotobridge\rb\test\probe\probe_nuke_step.py" \
    "C:\Users\shann\rotobridge\out\step"
```

It imports `mixed` from `test/golden/ae_scene.rbj` at tolerance inf, so nothing
corrects anything - at the default the drift pass buys the answer back before it
can be read - and prints two variants:

| | frames 16-17, arriving | frames 19-23, frozen |
|---|---|---|
| **A** step, as the importer writes it | **2.55 px, 2.05 px** | 0.0000 |
| **B** the same key made to honour an incoming slope | 0.2003 px, 0.2007 px | **47 -> 280 px** |

A is the claim `to_nuke` used to make - `out: hold` is exact, nothing is lost on
the incoming side - in pixels. The arrival is not held flat, which would read as
the frame 15 value; it overshoots and decelerates in, because a constant key
carries a flat handle. That is case 63's `eval(25)=0.6759` where an exact linear
reads `0.4898`, three phases later and in the units that matter.

B is the reason the fix was a label and not geometry. Straightening the arrival
costs the freeze outright: once the key is not constant, its outgoing side
travels to frame 24 and the held interval slides up to 280 px. **One type per
key means the straight approach or the freeze, not both.** The freeze is what
the artist authored; the drift pass buys the arrival back for 2 keys.

0.2003 px in B is the export conform's own residual, not this key's - which is
also the calibration: it says the fit and the host agree about the segment once
Nuke is drawing the line the file asked for.

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

The output directory must exist first; the test does not create it. **It writes
`ae_to_nuke_back.rbj` beside the report, and that file is a golden** - copy it
over `test/golden/ae_scene_via_nuke.rbj` whenever `ae_scene.rbj` or either
adapter moves, the same way the report is copied back. It is the AE-to-Nuke
artefact, the only committed evidence of what Nuke writes after reading an
After Effects file, and `TestGoldenAeSceneViaNuke` holds it against its own
source with no host: every authored key survived, the open spline came back
open, the anchored feather arrived as three inserted vertices, and the one
asymmetric key is `mixed` frame 18 at `{in: ease, out: hold}`. Left
unregenerated from 2026-08-21 to 2026-08-22 it drifted 286 px from what the
same pipeline produces.

An optional **second argument names a different source `.rbj`**, and report names are
derived from it so one run does not overwrite another's. That is how the
**static pair** is crossed - masks 7 and 8, on the solid that does not move, so
nothing they measure can be blamed on a baked ancestor transform. They are the
numbers the roadmap turns on, because production roto animates the shape and
not the layer:

```bash
mkdir -p "/mnt/c/Users/shann/rotobridge/out/hub"
"/mnt/c/Program Files/Nuke17.1v1/Nuke17.1.exe" --nc -t \
    "C:\Users\shann\rotobridge\rb\test\test_ae_to_nuke.py" \
    "C:\Users\shann\rotobridge\out\hub" \
    "C:\Users\shann\rotobridge\rb\test\golden\ae_static_conformed.rbj"
```

**The source is `ae_static_conformed.rbj`, and it used to be
`ae_static_ease.rbj`.** Changed 2026-08-22. Both are real exports of the same
two masks from the same comp; the difference is that the second predates the
ease conform at `0ccfcbb` and **no adapter writes a file like it any more**, so
crossing it measured a behaviour the tool no longer has. The pre-conform file
stays in the tree and stays valuable - it is the only fixture in the project
carrying a real After Effects ease over a real dense bake, which is what
`TestConformAsAfterEffectsWroteIt` needs - but it is evidence about the old
export, not a live measurement.

**This is also the first time the conform crosses as a host artefact.** The
conformed numbers already in `prd.md` §9.1 were measured by applying
`core.drift.linear_fit` to `ae_static_ease.rbj` in Python and crossing the
result. This run crosses the file **After Effects itself wrote** with its own
`RB.drift.linearFit`, which is the end-to-end version of the same claim.

### The predicted crossing, derived before the run

Computable with no host, because the file carries both layers: reconstruct each
shape linearly from its own `keys` and measure that against its own `frames`.

| shape | keys | linear reconstruction vs the bake | so at tolerance 0.5 |
|---|---|---|---|
| `eased_static` | **25**, frames 0-24, every side `linear/linear` | exact - 25 keys over a 25-frame range leaves nothing to interpolate | **25 authored, 0 corrective** |
| `linear_static` | **2**, frames 0 and 24, `linear/linear` | **0.000117 px** worst, at frame 22 | **2 authored, 0 corrective** |

Neither key carries an `ease` block, so **Nuke's "carries authored ease"
warning must not fire** - it fired on every run of the pre-conform file, and
its absence is the cheapest single check that the right source was crossed.
Geometry should land at the float32 storage floor, ~3.05e-05 px, as it did
before. The field-by-field section should be empty.

**Run 2026-08-22, and every number held: PASS.** 25 / 0 and 2 / 0 at tolerance
0.5, geometry 3.0518e-05 px on both shapes, field-by-field empty.

**One line of the prediction was wrong, and the correction is a better check
than the original.** "No warning must fire" is not what happens - the run
prints one, and it is the *file's own*, replayed. `import_document` seeds its
warning list with the source file's (the import-record decision in
`HANDOFF.md`: the exporting application's losses and this import's are kept
apart but both reported), so the exporter's conform warning arrives with the
file. The discriminator is therefore the wording, not the count, and the two
reports in `hub/` sit side by side saying it:

    pre-conform   shape 'eased_static': 3 key(s) carry authored ease ...
    conformed     mask 'eased_static': 6 key side(s) carried temporal ease ...

`shape '...'` is the **Nuke importer** saying it cannot hold what it was
given. `mask '...'` is the **After Effects exporter** saying what it already
paid, quoted back. Only the first is a loss at this end, and only the first
must be absent.

Against the pre-conform run, which is kept because it is what the conform was
bought to change:

    was    eased_static    3 authored, 22 corrective   <- dense, and paid for at the far end
    now    eased_static   25 authored,  0 corrective   <- the same 25 keys, in the file
           linear_static   2 authored,  0 corrective   <- exact and free, both times

An After Effects ease costs a key on every frame in Nuke either way; what the
conform moves is **who pays and whether the count depends on a tolerance the
compositor chose**. Reports at `test/golden/nuke_probe/17.1v1/hub/`. See
`HANDOFF.md`, "Nuke is the hub", for why that is a "cannot" rather than a bug.

**The pre-conform report in `hub/` used to say FAIL, and that was the harness,
not the crossing.** The open/closed section asked for two masks by name -
`linear` and `opened`, which only `ae_scene.rbj` has - so every source without
them failed on two shapes that were never in it, and that verdict sat in the
tree being read past while the numbers above it were quoted as a result. Fixed
2026-08-22: the section now asks the file which shapes it contains and checks
each one's `closed` against the flag Nuke gives it, which also means a shape
that fails to import is reported rather than silently skipped.

Both hub files were then re-run under the fixed harness, so the "was" and the
"now" are measured the same way. The pre-conform crossing is a **PASS** and its
numbers did not move - 3 / 22 and 2 / 0, geometry 3.0518e-05 px - which is what
says the FAIL was the harness. On the six-shape golden the fix changed the
report **only** in that section: geometry, every key count, every warning and
the verdict are byte-identical to the run committed before it.

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

### What the conform did to the crossing, 2026-08-22

Re-run on the conformed golden, Nuke 17.1v1, at the default 0.5 px tolerance:

| shape | was | now |
|---|---|---|
| `linear` | 4 authored, 13 corrective | **15, 0** |
| `eased` | 5 authored, 20 corrective | **25, 0** |
| `mixed` | 5 authored, 11 corrective | **11, 2** |
| `feathered` | 4 authored, 12 corrective | **7, 0** |
| `offgrid` | 5 authored, 11 corrective | **9, 0** |
| `opened` | 4 authored, 11 corrective | **7, 0** |

Five of six need no correction, and the file is **cheaper in Nuke as well**: 76
keys against 105. The exporter's fit sees the whole curve at once where the
drift pass can only split a gap. Geometry is unchanged at 6.1e-05 px, the
float32 floor.

**`mixed`'s remaining 2 are not the conform's, and they say something about
Nuke.** Probed at tolerance inf, so nothing corrects anything: every frame is
at the float32 floor or inside the conform's 0.5 px except frames 16 and 17,
which are **2.55 px and 2.05 px** off. That is the segment 15 -> 18, arriving
at `mixed`'s `hold`. Nuke evaluates point 0 at frame 16 as 507.561 where both
the bake and a straight line between the keys say 505.155 - so **a step key
flattens its own incoming tangent, and the segment arriving at it decelerates
instead of running straight.**

`core/interp.to_nuke` says the opposite and returns `exact=True` for `out:
hold` on the grounds that "Nuke's step governs only the outgoing interval".
Measured, it does not. The geometry that ships is still right - the drift pass
buys the 2 keys - but the import is silent about a side it could not hold. See
`HANDOFF.md` "Next" for the narrow fix and why it has not been made.

## Phase 5 render

`test/test_ae_to_nuke_render.py` is the half of Phase 5 that needs nobody. It
builds Nuke's matte from `test/golden/ae_scene.rbj` and measures it in rendered
pixels, which is the unit acceptance criterion 2 is written in - "under 1% of
pixels at >0.01 alpha delta" - and the only unit the two open questions (`ff`,
and section 6.4's anchored-feather placement) are observable in.

```bash
rm -rf "/mnt/c/Users/shann/rotobridge/rb" \
  && mkdir -p "/mnt/c/Users/shann/rotobridge/rb" \
  && cp -r core nuke test "/mnt/c/Users/shann/rotobridge/rb/"
"/mnt/c/Program Files/Nuke17.1v1/Nuke17.1.exe" --nc -t \
    "C:\Users\shann\rotobridge\rb\test\test_ae_to_nuke_render.py" \
    "C:\Users\shann\rotobridge\out\run"
```

A **second argument** points it at a matte sequence rendered out of After
Effects and turns on the comparison that closes Phase 5; a **third** is a frame
offset if that sequence is not numbered the way the comp is. Without them the
first three sections still run and still mean something.

**Status: PASS on 17.1v1**, 2026-08-22, sections 1 to 3. Report at
`test/golden/nuke_probe/17.1v1/phase5/ae_to_nuke_render_report.txt`.

| Section | Result |
|---|---|
| the chain against itself | `0.000000` on all 25 frames - the measurement can report zero |
| the chain against arithmetic | a 4 px offset measured `0.00100418` against `0.00100418` computed by hand, so it can also report a number, and the right one |
| what tolerance 0.5 costs the matte | **zero pixels past 0.01 alpha on any frame**, worst delta anywhere `0.000266` |
| against AE's own render | NOT RUN - needs the matte sequence |

The third row is a number this project did not have. Criterion 4 bounds the
drift pass in pixels of **geometry** and is met at 0.465 px; this says what that
is worth in the render, and the answer is nothing an artist can see.

**What After Effects has to produce** for the fourth section, from the comp
`setup_ae_scene.jsx` built - the same one `ae_scene.rbj` came from: frames 0 to
24 of the layer **`RotoBridge test` alone, soloed**, as a matte sequence,
**straight alpha**, 16-bit or float, EXR or PNG, numbered by the comp's own
frame numbers. `probe_ae_phase5.jsx` does all of that in one run and reports
the pattern and frame offset to pass back - see "The last After Effects run"
below.

**Soloing is not a nicety.** The comp also carries `RotoBridge static`, whose
masks 7 and 8 are not in this file, and an imported `RotoBridge` layer from any
earlier run. Their alpha would measure as geometry Nuke was never given.

**The open spline is held out of the comparison, on the Nuke side.** After
Effects renders no alpha at all from an open mask path and Nuke strokes one at
the node's default width, so `opened` would contribute a Nuke-only stroke
against empty film. That is spec/rbj-v2-draft.md section 8's known limitation
rather than anything about the crossing, and measuring it here would read as a
Phase 5 failure. `closed_names()` names what it holds out in the report.

The comparison is against **alpha**, and a render with none does not quietly
pass: measured 2026-08-22, a matte carrying no alpha reads as **0.0708 of the
frame** differing on frame 12, seven times the budget. What a wrong render
fails to be is *informative* - so read the report's `channels` line before
reading a failure as geometry.

### Two host facts this cost a probe to learn

**Nuke NC hands Python at most 10 `Node` objects per script, cumulatively.** Not
ten live nodes: a `nuke.toNode` on a node already held costs another one, and
deleting a node does not give the budget back. `nuke.scriptClear()` is the only
reset, and it also invalidates every `Node` object already handed out. Any
harness that builds a tree per shape or per frame has to be written around this.

**A Roto with no input carries only its shapes' bounding box.** `nuke.sample`
outside it raises rather than returning 0, and an average is taken over the
wrong area. Ground it on a `Constant` and the frame is the frame.

## The export conforms ease, so a re-export will differ

`ae/rotobridge_export.jsx` rewrites every `ease` key side as `linear` and adds
the keys that costs (`prd.md` section 9.1 step 6a), so **a file exported with
the current adapters carries no `ease` block at all** and has more keys than
`test/golden/ae_scene.rbj` does. That is the intended change, not a regression:
Nuke's roto curves cannot hold an AE ease, so the cost is paid in the
application that created it rather than at the far end.

**The new file replaces `ae_scene.rbj`, it does not sit beside it.** Decided
2026-08-22. A golden is what the exporter produces now; keeping the
pre-conform one in the tree would leave `test_ae_to_nuke.py` and the render
harness measuring an answer no exporter writes any more, which is the exact
staleness the top of this section warns about. The eased evidence is not lost:
`test/golden/ae_static_ease.rbj` is kept as it is - it is the only file in the
project carrying a real After Effects ease over a real dense bake, which makes
it the only fixture that can exercise the conform against host-produced data
(`test/ae_mock.js` refuses to bake a bezier segment) - and the old six-shape
file stays in git history at `5f732e2`.

**`test/golden/ae_static_conformed.rbj` is that same comp exported again with
the conform in place**, 2026-08-22, and the pair is the only place the two
implementations of the fit meet over real host data: After Effects running
`RB.drift.linearFit` chose the same key frames `core.drift.linear_fit` chooses,
and the dense layer is bit-identical between the two files because the conform
never writes to it. `TestConformAsAfterEffectsWroteIt` in `test/test_core.py`
holds it. It exists because a run aimed at the scene golden came back with the
wrong layer selected, which is what step 5 above is for.

### The predicted diff, and it is derived rather than guessed

**Run 2026-08-22, and the prediction held line for line.** The alert read 6
shapes, 600 points, 10 warnings, 74 authored keys, with every per-shape count
below matching; `diff_rbj.py` reported label changes only and `geometry:
identical`. Kept as written, because a prediction is only worth anything
recorded before the run - and this is the method to reuse next time the
exporter moves: the conform's input is the committed bake, so the whole run is
computable here.

The conform does not touch the dense layer. It reads it, fits a linear sparse
layer to it and rewrites the keys, so the input to the fit in a re-export is
byte-identical to the dense layer already committed in `ae_scene.rbj`. That
makes the whole prediction computable here, with no host: run
`core.drift.linear_fit` over the golden's own frames with each shape's authored
key frames as `wanted`, its held frames as `holds`, and tolerance 0.5
(`CONFORM_TOLERANCE`). Against the golden committed at `5f732e2`:

| shape | keys | becomes | worst residual | which warning |
|---|---|---|---|---|
| `linear` | 4 | **15** | 0.0001 px | keys added |
| `eased` | 5 | **25** | 0.0000 px | authored ease, 6 sides |
| `mixed` | 5 | **11** | 0.2006 px | keys added |
| `feathered` | 4 | **7** | 0.2147 px | keys added |
| `offgrid` | 5 | **9** | 0.3809 px | keys added |
| `opened` | 4 | **7** | 0.2584 px | keys added |

    linear     [0, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 24]
    eased      every frame, 0 to 24
    mixed      [0, 6, 7, 8, 9, 10, 11, 12, 15, 18, 24]
    feathered  [0, 6, 9, 12, 15, 18, 24]
    offgrid    [0, 6, 8, 10, 11, 14, 16, 18, 24]
    opened     [0, 6, 9, 12, 15, 18, 24]

So the alert at step 5 reads **6 shapes, 600 points, 10 warnings**, and the
authored key count goes **27 -> 74**. The point count does not move: `points
baked` counts the dense layer, and the conform never writes to it. A different
warning count is the cheap deployment check - **4** means the running scripts
predate `0ccfcbb`.

The four warnings already in the file stay, unchanged and in the same order
(`feathered` anchored, `opened` open spline, `mixed` false hold, `offgrid`
snapped). The six new ones follow, one per shape.

Three things in that table are worth reading rather than just checking:

- **`eased` lands on every frame, and that is the honest price.** 3 authored
  keys of real ease over a moving layer cannot be spelled in Nuke's vocabulary
  at all, so the file now says so in keys instead of leaving the compositor's
  drift pass to discover it at whatever tolerance they happened to import at.
- **`linear` gains 11 keys despite having no authored ease anywhere.** Pinned
  endpoints and transform keys are spelled `ease` with no parameters (spec
  section 10.3), so the conform fires on them too, and on this fixture's
  scaled, rotating layer a straight line between keys really does leave the
  baked path. That is a fixture property - see the same note in `HANDOFF.md`.
  On a static layer, which is what roto actually sits on, `linear_static`
  crosses at 2 keys and 0 corrective.
- **`mixed` keeps frame 18's outgoing `hold`,** and 18 is in its key list
  above. If a re-export loses it the conform is wrong: `hold` maps to Nuke's
  step, and rewriting one would pay a key on every frame of a frozen interval
  to flatten it again.

Two checks after the run, in this order:

1. `python3 test/probe/diff_rbj.py` old new, as step 7 says. Expect label
   changes only - every `interp` side reading `ease` becomes `linear`, every
   `ease` member disappears, and the keys above appear. **No geometry line at
   all**: the dense layer is untouched, so a vertex moving means the fixture
   moved, not the exporter.
2. Re-run the crossing, `test/test_ae_to_nuke.py`. This is what the conform was
   built for, so it is the number that says whether it worked: every shape
   should arrive with **0 corrective keys** at the default tolerance and no
   "carries authored ease" warning, where the current golden pays corrective
   keys on every moving shape.

## The last After Effects run

`test/probe/probe_ae_phase5.jsx`. Everything still open in this project needs a
person in front of After Effects, and it is four separate things. This does all
four in one run and writes `rotobridge_phase5_probe.txt` beside the project.

Run it with the `setup_ae_scene.jsx` comp built, open and frontmost:
`File > Scripts > Run Script File...`. Sections 2 and 3 are read-only; section 1
adds a render queue item and, if you say yes, renders. Nothing in it touches a
mask.

| Section | What it settles |
|---|---|
| 1. the matte | Solos `RotoBridge test`, configures the output module, renders, then **reads the folder back** and prints the pattern and frame offset to hand `test_ae_to_nuke_render.py`. Closes Phase 5, `ff` and section 6.4. |
| 2. `File.open("a")` | Appends twice to a temp file and reads it back. The one call in the adapters no test can reach. |
| 3. the `mixed` hold key | Prints every key of every mask named `mixed`, per side, and names the layer. |
| 4. the eight-shape golden | Instructions only, and optional. |

**Why it reads the folder back rather than predicting the filenames.** Whether
After Effects numbers a sequence by the comp's frames or from zero is a setting,
and the Nuke test takes a frame offset for exactly that reason. Measuring the
numbering costs one `getFiles` and removes the question.

**The format comes from a template, not from `setSettings`.** After Effects
documents `Format` as readable and not settable, so the script lists what
`om.templates` offers on this host, picks the first matching EXR or PNG, and
records the list in the report. `Channels` and `Color` are settable and are the
two that decide whether the file carries an alpha and whether it is straight;
they are set separately so a host refusing one still applies the other.

**`OutputModule` goes stale when its settings change**, which Adobe documents
and this script honours by re-fetching after every write. That is the same
hazard as the stale mask handles that broke the first multi-shape import, and
the same shape as Nuke's `append()` copying into the tree. Three APIs, one rule:
do not hold what you handed to a host.

**Section 2 has three outcomes, not two.** Append working and `open("a")`
failing are the obvious ones; the third is `"a"` silently truncating, which
would mean every import erases the record of the last. The script distinguishes
them by reading the file back rather than by trusting the return of `open`.

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
**step is outgoing-only in what it freezes** - it holds the interval leaving the
key, matching AE's `keyOutInterpolationType`.

**It does not leave the incoming side alone, and this table says so.** Under
`1`, eval(25) reads `0.6759` - the cubic default - where an exact linear reads
`0.4898`. The interval arriving at a step key is a cubic with a flat handle, so
a writer reporting that side as `linear` is claiming a line the curve does not
draw. Believed until 2026-08-22, when it turned up as 2.55 px on the segment
arriving at `mixed`'s hold; see "What the conform did to the crossing".

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
