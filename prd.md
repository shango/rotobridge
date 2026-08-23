# RotoBridge - Product Requirements Document

**Version:** 4.13
**Status:** Phases 0-4 complete, and Phase 4 has now met both hosts: the After Effects export and the six-shape import both pass in After Effects (2026-08-21), and both Nuke acceptance tests pass headless (re-run 2026-08-22). `spec/rbj-v1.md` **frozen** 2026-08-20. Q10 closed 2026-08-20; no open questions. Phase 6 open splines implemented and tested 2026-08-21, and that half of `spec/rbj-v2-draft.md` is a **permanent draft**: they carry geometry correctly and cannot render anywhere the format reaches (After Effects produces no alpha from an open mask path; Nuke strokes them through node knobs `.rbj` has no member for), so v1 remains the format. **The draft's second delta - feather anchors, §6 - is the reverse case: a measured defect in the AE → Nuke direction with no other available fix, and it is now implemented end to end** (both schemas, both AE adapters, the Nuke importer's de Casteljau split, the scene golden re-exported and the crossing re-run, 2026-08-22). What is left of it is §6.4's open question - whether AE's `featherRelSegLocs` is the bezier parameter the split uses or an arc-length fraction - which is observable only in rendered pixels, so an anchored After Effects file is better than the v1 snap and not known to be exact. **Phase 4 is fully closed as of 2026-08-22**: `File.open("a")` appends in the host, so the durable import record is sound, and the imported `mixed` mask's frame-18 key is still a HOLD, with every other per-side key surviving too. **Phase 5's rendered comparison is retired as out of scope, 2026-08-22** (§13 criterion 2): this tool moves roto spline data between applications, and a matte difference measures how a host draws a shape rather than whether the shape arrived. Its Nuke half is built and passing (`test/test_ae_to_nuke_render.py`, §12) and stays in the tree unused. Three questions were only ever observable in rendered pixels and stay open as **rendering** questions rather than data losses: `ff`, §6.4's split parameter, and the mapping from AE ease to Nuke's `lslope`/`rslope` and `la`/`ra` - the last of which Phase 4 already established Nuke cannot hold at all.
**Phase 0 results:** `test/golden/nuke_probe/17.1v1/`, `test/golden/ae_probe/` (six AE runs; run 3 carries the feather points, run 6 the mixed key interpolation)
**Verified against:** Nuke 17.1v1 (non-commercial), After Effects 25.6x101
**Scope:** After Effects ↔ Nuke roto spline interchange via a neutral format, designed for later expansion to Mocha Pro, Flame, and others
**Companion document:** MatteTrace PRD (matte-to-spline source adapter, separate scope)

---

## 1. Summary

RotoBridge moves animated roto splines between Adobe After Effects and Foundry Nuke without rendering to matte and without a licensed intermediary.

**Architecture: hub-and-spoke.** A neutral JSON file (`.rbj`) is the interchange format. Each application gets an *exporter* that reads its native shapes and writes `.rbj`, and an *importer* that reads `.rbj` and builds native shapes.

**Dual-layer animation model.** Every `.rbj` carries both the artist's authored keyframes (sparse, with interpolation metadata) and a dense per-frame bake (ground truth). Importers reconstruct sparse, editable animation from the authored keys and use the dense layer to bound interpolation drift. Sparse-vs-dense is an import-time decision - one export serves every fidelity/editability trade-off.

v1 ships two spokes - four components:

| App | Export path | Import path |
|---|---|---|
| After Effects | ExtendScript (`.jsx`) reads `maskPath` | ExtendScript builds `Shape` objects, `setValueAtTime` |
| Nuke | Python reads `node['curves'].rootLayer` | Python `nuke.rotopaint` API builds Roto node |

Mocha Pro, Flame, and others are planned (§16) and shape the format design now, but no code for them is in v1 scope.

**Key insight:** both v1 targets expose a documented scripting API capable of creating splines. No proprietary binary format needs to be written or parsed.

---

## 2. Problem

Roto is expensive to create and currently non-portable. A shape animated in After Effects cannot be reused in Nuke, and vice versa, without rebuilding it by hand. Existing options:

- **Mocha Pro / Silhouette as intermediary** - works, but requires a license on both ends and a round trip through a third application.
- **Rendered matte (EXR/DPX alpha)** - universal and lossless, but destroys editability. Any note requiring a shape tweak means starting over.
- **Manual re-roto** - the status quo. Hours of duplicated labor per shot.

The cost is highest exactly when it hurts most: late-stage notes, where a shape exists in the wrong package and there is no time to rebuild it.

A tool that transfers shapes but destroys their keyframe structure only half-solves the problem: a shape keyed on every frame is barely more editable than a rendered matte. **Preserving the artist's authored keys is a first-class requirement, not an optimization.**

---

## 3. Goals

**In scope for v1:**

- A documented neutral format (`.rbj`) sufficient to represent animated bezier roto - including features v1 apps cannot exercise (see §5.2)
- **Sparse keyframe preservation**: authored key times and interpolation survive transfer wherever the destination can represent them
- **Bounded drift**: dense ground-truth layer + tolerance-based corrective key insertion guarantee positional accuracy regardless of interpolation mismatch
- Export and import adapters for After Effects and Nuke - four components
- Sub-pixel positional accuracy on every round trip (at tolerance 0)
- Preserve per-frame vertex positions and bezier tangents, shape name, closed flag, blend mode, shape opacity
- Minimal UI: source selection, output path, frame offset, import mode
- Human-readable, diffable output

**Explicit non-goals for v1:**

- Adapters for Mocha Pro, Flame, Silhouette, Resolve/Fusion (planned; §16)
- Full bezier temporal-ease translation (tier-1 and tier-2 mapping only; §7)
- B-splines, X-splines (Bezier only). Open splines were a v1 non-goal too and are now drafted in `spec/rbj-v2-draft.md`, still behind a version bump, still unrendered in either host
- Paint strokes, RotoPaint layer hierarchies
- 3D layers, parented layers, camera-affected transforms in AE
- Mask expansion, motion blur settings, non-square pixel aspect
- Any GUI beyond a file dialog and a small options group

---

## 4. Users

Compositors and roto artists working across both packages, typically in small studios. They are technical enough to run a script from a menu or paste code into a script editor. They are not expected to install Python packages, configure paths, or read tracebacks.

**Primary success story:** an artist receives roto done in the other package, opens it, and finds *their kind* of roto - sparse keys at sensible times they can grab and adjust - not a wall of keys on every frame.

---

## 5. Design decisions

### 5.1 Why a neutral hub with only two apps

For AE↔Nuke alone, a direct converter and a hub lose exactly the same information - the hard problems (variable vertex count, AE layer space, feather model mismatch, keyframe model mismatch) are intrinsic to the app pair. The hub is not a fidelity play at N=2. It is justified by four things:

1. **Superset, not intersection.** A direct AE↔Nuke converter would discard the tangential component of Nuke's feather offset at write time, because no AE feather point can hold it. `.rbj` stores it anyway in `feather_offset`; when the Mocha Pro adapter lands, Nuke exports written *today* still carry their full feather. The format stores the union of what target apps will support, not the intersection of what the current pair supports.
2. **Archival.** `.rbj` files remain readable as new adapters arrive. Direct conversion produces nothing durable.
3. **Testability without licenses.** Golden `.rbj` files allow unit-testing the AE adapter without Nuke present, and vice versa.
4. **Debuggability.** A wrong shape bisects instantly: inspect the `.rbj`, and you know which adapter broke.

Marginal cost is near zero: the geometry core must hold canonical-space points in memory regardless; `.rbj` is that structure serialized, plus a schema document.

Known future targets (Mocha Pro next, then Flame; §16) make the hub the correct call now - point-to-point converters scale as N², and at five apps that is 20 converters versus 10 adapters.

### 5.2 Design the format against the known future

The schema includes fields no v1 adapter can fully exercise, because retrofitting them later means format versioning and migration:

- `feather` per point, with `feather_model` - Nuke writes it, and AE can carry it as mask feather points (§9.3). Mocha Pro's per-point `edge_width` maps directly when its adapter arrives.
- `blend` - full set now, so no shape written today needs re-export later.
- `keys` + `interp` - authored keyframe structure, usable by every future adapter.
- `warnings` - lossy conversions are recorded in the file itself, so a `.rbj` carries its own provenance.

### 5.3 Why scripts, not native file formats

Alternatives considered and rejected:

- **Writing `.nk` `curves` knob text directly** - undocumented, version-sensitive serialization with a nested layer tree, per-layer transform block, and per-point encoding that changes depending on whether a point is static or animated.
- **Writing `.ffx` (AE animation preset)** - binary RIFX container, undocumented, and unverified as to whether mask paths survive the preset round-trip. Failure mode is a silent no-op or a crash.

Both v1 targets expose a documented scripting API. Generated output is readable, diffable, and degrades with a traceback rather than silent corruption.

### 5.4 The dual-layer animation model

Earlier drafts specified a dense bake only, which guaranteed fidelity but destroyed editability - the authored keys *are* the artist's work product. The two keyframe models cannot be reconciled directly:

- **AE** keys the entire `maskPath` at once; each key carries one shape-wide temporal ease.
- **Nuke** keys each control point independently - an AnimCurve per point per axis, with per-key tangents.

The resolution is to store **both layers**:

- **`keys` (sparse)** - the frame numbers the artist actually keyed, with interpolation metadata. For Nuke sources, the *union* of key times across all points of the shape.
- **`frames` (dense)** - every frame in range, evaluated through the source app's own interpolation. Ground truth.

The importer then: (1) sets keyframes at `keys` only; (2) evaluates the destination's interpolation at every intermediate frame against the dense layer; (3) inserts corrective keys only where drift exceeds tolerance.

Properties: authored keys always survive verbatim; extra keys appear only where interpolation mismatch is actually visible; positional error is bounded by the tolerance no matter how exotic the source curves; worst case degrades gracefully toward dense, never toward wrong.

### 5.5 Canonical coordinate space

**Nuke's:** origin bottom-left, Y-up, pixel units, tangents stored vertex-relative.

Chosen because it is a pixel space (no normalization ambiguity), bottom-left origin is the more common VFX convention, and it requires no aspect-ratio term. Every adapter converts to and from this on its own side.

| App | Origin | Y direction | Units |
|---|---|---|---|
| Nuke | bottom-left | up | pixels |
| After Effects | top-left | down | pixels, **layer space** |
| Mocha Pro (planned) | TBD | TBD | pixels |
| Silhouette (planned) | center | down | normalized, aspect-scaled X |
| Flame (planned) | TBD | TBD | TBD |

---

## 6. The `.rbj` format

UTF-8 JSON. Human-readable, diffable, version-tagged. **Frozen as `spec/rbj-v1.md` on 2026-08-20**, which is now the authoritative document; this section is the summary and the rationale. The freeze resolved four things this section left ambiguous or self-contradictory (spec §14), and they are folded in below.

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
  "range": [1001, 1157],
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
        {"frame": 1015, "interp": {"in": "ease", "out": "linear"},
         "ease": {"in": [0.91, 0.0]}},
        {"frame": 1032, "interp": {"in": "linear", "out": "hold"}},
        {"frame": 1057, "interp": {"in": "hold", "out": "linear"}}
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
        }
      }
    }
  ],
  "warnings": ["Shape 'hair' had inverted flag; dropped."]
}
```

**Rules:**

- Coordinates in canonical space (§5.5), pixels, floats.
- Tangents vertex-relative.
- `frames` is **required** and dense: one entry per frame in `range` (inclusive), evaluated through the source app's interpolation. This is ground truth. Each frame record carries `points`, `opacity` and `feather_uniform`, all three required.
- **Everything that animates lives in `frames`.** The shape object holds only what both hosts model as static. `opacity` is per frame, not per shape: AE `maskOpacity` is a `Property` and Nuke `opc` is an `AnimAttributes` curve, so a static field would freeze it at the first frame - the same defect case 62 found in uniform feather.
- `keys` is **optional** sparse metadata. Absent `keys` means importers treat every frame as a key (dense import). Each key:
  - `frame` - integer, must exist in `frames`.
  - `interp` - **an object with `in` and `out`**, each `hold` | `linear` | `ease`. `out` describes the handle leaving this key, `in` the handle arriving at it. Both are always present; there is no string shorthand, so readers never branch on type. On the first key `in` is ignored, on the last key `out` is ignored; write `linear` there.
  - **Interval rule.** The segment between keys A and B is governed jointly by `A.interp.out` and `B.interp.in`, because both applications model a key as a two-sided bezier handle that can be broken (§15 Q9). One exception: **`hold` on the outgoing side dominates** - when `A.interp.out` is `hold` the segment is flat and `B.interp.in` is ignored for it. That matches AE, where a hold keyframe freezes the segment leaving it, and Nuke, where step affects only the outgoing interval.
  - `ease` - optional parameters, keyed by side: `{"in": [influence, speed], "out": [...]}`. `influence` is handle length as a fraction 0-1 (AE reports a percentage; divide by 100). `speed` is handle direction, AE's ease `.speed` verbatim. Present only for sides whose `interp` is `ease`; a side that is `hold` or `linear` has no entry. Shape-wide, matching AE's single ease per key for the whole `maskPath`. An adapter that cannot derive a shape-wide ease (Nuke with divergent per-point tangents) writes the side as `ease` with no matching `ease` entry, meaning "smooth, parameters unknown, rely on drift correction".
- `frames` keys and `keys[].frame` are integers in the source application's frame numbering. Importers apply their own offset.
- Vertex count must be identical across all frames of a shape.
- `blend` ∈ `union` | `difference` | `intersection`.
- `feather_model` ∈ `per_point` | `none`, describing the **per-point layer only**. The two feather layers are independent and compose (§9.3), so `feather_uniform` is written regardless of this value. The freeze dropped the old third value `uniform`: with the layers independent it means nothing that `feather_uniform != [0, 0]` does not already say, and two members encoding one fact can disagree with no tiebreak rule.
- `feather_uniform` - `[x, y]` per shape **per frame**, in the dense layer. Maps 1:1 to AE `maskFeather` and Nuke `fx`/`fy`, both measured 2-D and independent per axis. It animates on both sides, which is why it is per frame rather than per shape.
- `feather_falloff` - `linear` | `smooth` per shape, static. AE `maskFeatherFalloff` (an attribute, not keyframable) and Nuke `ff`.
- `feather` - **signed** float per point: distance along the outward path normal, positive outward, negative inward. Present on every point of every frame when `feather_model` is `per_point`, absent entirely when it is `none` - writing `0.0` under `none` would be indistinguishable from an authored all-zero shape, which §9.3 says is a real distinction. It is AE's `featherRadii` verbatim (§9.3) and Mocha's `edge_width`.
- `feather_offset` - **optional** `[x, y]` per point, canonical space. Only Nuke writes it, carrying the tangential component that `feather` cannot express. A Nuke importer that finds it uses it in place of `feather`, making Nuke → Nuke lossless; every other adapter ignores it. Never present without `feather`.
- `warnings` accumulates lossy conversions on export; importers append their own.

---

## 7. Interpolation translation

Three tiers, applied per key interval:

**Tier 1 - exact.** `hold` ↔ AE hold keyframe ↔ Nuke constant interpolation. `linear` ↔ AE linear ↔ Nuke linear. Run 6 read the first real authored ease off a mask path - influence 91.176 in / 100 out with speed 0, against the 16.667 default every earlier run reported - confirming the `keyInTemporalEase` path returns authored values and not just defaults. It also exposed Q9, now closed: AE keys carry an independent type on each side, so `interp` is per-side (§6). **Nuke's default point-curve interpolation is curved, not linear** - Phase 0 measured keys at f1=0, f50=20, f100=100 undershooting piecewise-linear by up to 5.5 units mid-span - so an importer that writes keys and stops gets a smooth curve the artist did not ask for. **The control is per key, not per curve.** Versions of this document through v4.4 said to set `AnimCurve.curveType`, and that is the wrong knob: Phase 2 case 71 found `CurveType` has no linear member at all (`eBezier`, `eHermite`, `eBSpline`, `eCardinal`, `eCatmullRom`, `eNurbs`), because it selects the spline basis. Case 74 confirmed the real control on point position curves is `AnimCurveKey.interpolationType`, set to the `InterpolationType` enum **plus one** (§15 Q9): with `eLinear + 1 = 2` on every key of both axes, a 1/10/20 key sequence evaluated to exactly its piecewise-linear values. AE's three legal types on `maskPath` (`LINEAR`, `BEZIER`, `HOLD`) are all confirmed valid and round-trip through `setInterpolationTypeAtKey`. `ease` with parameters ↔ derived tangents. AE's shape-wide temporal ease (a 1D value-over-time bezier) converts to Hermite slopes applied uniformly to every Nuke point curve; the reverse applies when all Nuke points share an interpolation style.

**Tier 2 - best single fit.** Nuke shapes with individually-authored per-point tangents have no AE representation ("point 5 eases differently than point 12" cannot be expressed on a mask path). Export writes `interp: "ease"` without parameters; the AE importer applies default smooth ease. Positional truth is preserved by tier 3, not by the fit.

**Tier 3 - tolerance-based corrective keys.** After setting authored keys with tier-1/2 interpolation, the importer evaluates the destination's actual interpolation per frame against the dense layer and inserts additional keys wherever any point drifts beyond tolerance. This is the universal backstop that makes tier 2 safe.

For AE as destination, evaluating "the destination's actual interpolation" means setting keys and reading back `maskPath.valueAtTime()` - slower than closed-form, but correct by construction.

---

## 8. Import modes

Every importer exposes one control: **drift tolerance**, in pixels.

| Mode | Tolerance | Result |
|---|---|---|
| Authored keys only | ∞ | Maximum editability; drift possible between keys |
| Corrected (default) | 0.5 px | Authored keys + corrective keys only where interpolation mismatch is visible |
| Every frame | 0 | Bit-exact to source; heavy curves |

Because the dense layer is always in the file, switching modes is a **re-import of the same `.rbj`** - no round trip to the source application. An artist who finds drift re-imports at a tighter tolerance or at 0.

Importers accept a **shape subset** (by name) so a single drifting shape can be re-imported dense without disturbing the others. The import completion report lists, per shape, how many corrective keys were inserted and the frames of worst drift - this tells the artist exactly which shapes to re-import if the defaults were too loose.

**The completion report is also written to disk, next to the host project.** Every import appends a record to `<project>.rotobridge.txt` - beside the saved script or comp, or beside the source `.rbj` when the project has never been saved. It carries the file it came from and who exported it, the comp it was built against, the import settings, the per-shape numbers above, and **both** warning lists kept apart: what the exporting application recorded losing, and what this import lost. Rendered by `core/report.py` and its ExtendScript mirror, which are held to byte-identical output, so the two hosts write the same document.

The reason it is a file rather than a dialog is the argument it has to survive. When a shot comes back with a note about a soft edge, the question is which application dropped what, and by then the dialog is gone and the console has scrolled. Records are appended, never overwritten, because a comp gets imported into more than once and the second import is not entitled to erase the evidence of the first. A record that cannot be written warns and does not fail the import - the shapes are already in the comp by then.

---

## 9. Functional requirements

### 9.1 After Effects

**Panel (`rotobridge_panel.jsx`)** - Window > RotoBridge when installed in `Scripts/ScriptUI Panels/`, or `File > Scripts > Run Script File...` for a floating palette with no install. Two buttons over the two adapters below, and nothing else: each one `$.evalFile`s the adapter exactly as `Run Script File...` does, so the panel adds an entry point without adding a second code path to keep in step. It collects no parameters of its own - both adapters already prompt for everything they need. A footer shows the folder it is running scripts from, because a stale deployment is this project's one recurring failure and it is otherwise invisible from inside the host.

**Export (`rotobridge_export.jsx`)** - File > Scripts, or the panel.

1. Validate: active comp, ≥1 layer selected, ≥1 mask present. Alert and abort otherwise.
2. Prompt for output path.
3. Read authored keys: `maskPath.numKeys` / `keyTime(i)` → `keys` array. Read **both sides of every key**: `keyInInterpolationType` and `keyOutInterpolationType` → `interp.in` / `interp.out`, and `keyInTemporalEase` / `keyOutTemporalEase` → the matching `ease` entries. AE stores the two sides independently and run 6 produced an asymmetric key (`in=LINEAR, out=HOLD`) on the first real mask tried, so reading one side is not an acceptable simplification. `LINEAR` → `linear`, `HOLD` → `hold`, `BEZIER` → `ease` with normalized influence pairs; anything unrecognised is `ease` with no parameters, which is a truthful description of an unknown type. Two things this step also owes the file, both learned during Phase 4: **union in the layer transform's key times**, since the transform is baked into the exported points and therefore animates the geometry even when the path never moves (only the properties that move geometry - layer opacity is in the same group and is not one of them); and **pin the range endpoints**, because a key outside the exported range still drives the values inside it. Snap any key that sits off the frame grid and warn: spec §9 requires every `keys[].frame` to name a frame that exists in `frames`.
4. Build the dense layer **frame-major**: for each frame in the work area, set `comp.time` once, then convert every mask's points at that time.
   - Read `mask.property("maskPath").valueAtTime(t, false)` → `Shape` with `vertices`, `inTangents`, `outTangents`, `closed`.
   - Convert each vertex to comp space via `layer.sourcePointToComp(pt)`. **The call takes one argument and evaluates at the current `comp.time`** - there is no time parameter. Set `comp.time` before converting.
   - Convert tangents by transforming `vertex + tangent` to comp space, then subtracting the transformed vertex. Phase 0 confirms this reproduces rotation and non-uniform scale exactly, so AE support does not need to narrow to identity-transform layers.
   - Flip: `y_out = comp.height - y_comp`; negate tangent Y.

   **Loop order is a performance requirement, not a style choice.** Across Phase 0's six AE runs a `comp.time` assignment plus one `sourcePointToComp` measured **5.75 ms to 20.89 ms**, against **0.02 ms to 1.52 ms** for `valueAtTime`. The absolute numbers swing by about 4x between runs and are not trustworthy on their own; the ordering is, and `comp.time` was the more expensive call in every run, by between 4x and 1000x. Plan against the slow end, 20.89 ms. Mask-major ("for each mask, for each frame") pays that cost once per mask per frame: ten shapes over 150 frames is about **31 s** of time-setting alone, which breaks acceptance criterion 11 before any real work happens. Frame-major pays it 150 times total - **3.1 s** at the slow end, 0.9 s at the fast end - independent of shape count. Even frame-major leaves under 7 s of the criterion-11 budget for real work at the slow end, so the dense loop has no room for a second per-frame host call.
5. Map `maskMode`: ADD→union, SUBTRACT→difference, INTERSECT→intersection; anything else→union with a warning.
6. Feather: read both layers, which compose (§9.3). `maskFeather` is a **2-D** `[x, y]` that **animates**, so read it per frame inside the frame loop into `feather_uniform` - reading it once per shape freezes it at the first frame. Read `maskFeatherFalloff` once into `feather_falloff`. When the mask path `Shape` carries feather points, also write `feather_model: "per_point"` and take `featherRadii` **signed and verbatim** into `feather`, resolving each point's segment location to a vertex. Never write `feather_offset` from AE.
6a. **Conform the sparse layer to what a Nuke roto curve can hold, 2026-08-22.** Every key side that says `ease` is rewritten as `linear`, its `ease` parameters dropped, and `core/drift.linear_fit` (`RB.drift.linearFit`) adds the keys that costs, so a straight line between keys stays within **0.5 px** of this comp on every frame. `hold` and `linear` are left exactly as they are: both cross losslessly - `hold` maps to Nuke's step - and rewriting a hold would turn a frozen interval into a slide and then buy a key on every frame of it to flatten it again, which is paying keys to destroy something that was free. The fit is told which keys hold so it prices a held segment as flat rather than as a line.

    **Why the export side and not the import side.** Nuke's roto curves have no vocabulary for After Effects' temporal ease at all (§15 Q9, `test/probe/probe_nuke_ease.py`), so the cost is not avoidable - only its location is. Measured on a static layer, which is what roto actually sits on: an AE `linear` mask crosses with **0 corrective keys** and an eased one with **22** over a 25-frame range. Paid at import, the compositor opens a shape keyed on every frame with nothing saying why, and the number of keys depends on a tolerance they chose. Paid here, the file that arrives is already in Nuke's vocabulary. Verified end to end against the file **After Effects itself wrote**, 2026-08-22: `test/golden/ae_static_conformed.rbj` crossed into Nuke 17.1v1 gives `eased_static` **25 authored, 0 corrective**, geometry 3.0518e-05 px, against 3 authored and 22 corrective for the pre-conform `ae_static_ease.rbj` re-measured the same day through the same harness. Nuke's own ease warning does not fire; the one warning the run prints is the **exporter's**, carried in the file and replayed by the importer, which is the import record keeping the two applications' losses apart rather than a loss at this end. Earlier runs of this comparison applied `core.drift.linear_fit` to the pre-conform file in Python; this one crosses the host artefact, so After Effects' own `RB.drift.linearFit` is what produced the keys. Reports at `test/golden/nuke_probe/17.1v1/hub/`.

    **The consequence, stated plainly: an After Effects `.rbj` no longer carries an `ease` block at all**, since pinned endpoints and transform keys are spelled `ease` too. The AE → `.rbj` → AE round trip therefore no longer reproduces authored ease timing; it reproduces the shape within 0.5 px on every frame, which is the same trade Nuke already takes. `interp.ease_from_ae`'s factor of 100 stays measured, tested and live, because the presence of an `ease` entry is what separates a curve the artist drew from one this exporter invented - and only the first is warned about.

7. Write `.rbj`. Alert with shape count, key count, frame count, warnings.

**Import (`rotobridge_import.jsx`)** - File > Scripts.

1. Prompt for `.rbj` path, AE start frame, drift tolerance (default 0.5 px; 0 = every frame), optional shape subset.
2. Create masks on the selected layer, or on a new comp-sized solid if none selected.
3. Undo the canonical transform: `y_ae = height - y_rbj`, negate tangent Y. Points land in comp space; if the target layer has a non-identity transform, invert it via `compPointToSource`.
4. Set `maskPath.setValueAtTime()` at authored `keys` only, then apply **both sides** of each key: `setInterpolationTypeAtKey(i, inType, outType)` from `interp.in` / `interp.out` (`hold`→`HOLD`, `linear`→`LINEAR`, `ease`→`BEZIER`, all three confirmed legal on `maskPath`), and `setTemporalEaseAtKey` for the sides carrying `ease` entries. AE stores the two sides independently, so writing one and letting the other default loses authored structure. **Ease first, types after.** `setTemporalEaseAtKey` is documented to force the key to BEZIER, so setting the types afterwards is what puts a `hold` or `linear` side back; the other order leaves a hold side rendering smooth, which is a wrong matte rather than a wrong knob. Match keys by **key time**, not by index, and re-push after every drift pass: the pass inserts keys and every index above an insertion moves.
5. Drift pass: read back `valueAtTime` per intermediate frame, compare to dense layer, insert corrective keys where any point exceeds tolerance. Iterate until clean.
6. Feather: set `maskFeather` per frame from `feather_uniform` and `maskFeatherFalloff` once from `feather_falloff`. Rebuild `per_point` feather as mask feather points (§9.3) - run 6 confirmed the write path round-trips signed radii and mid-segment positions exactly.
7. Report per shape: corrective keys inserted, worst-drift frames.

**Constraints:** ExtendScript is ES3 - no native `JSON`, no `Array.forEach`, no `let`/`const`, and **no `Array.indexOf`**, which is the one that bites hardest. Target layers must be 2D and unparented. **`json2.js` is not bundled**, contrary to what this line used to say: the writer had to be hand-rolled anyway to keep number arrays on one line (spec §2.1), so the only thing json2 was wanted for was parsing. `RB.rbj.parse` uses native `JSON` where the host has it and otherwise falls back to json2's own documented technique - prove the text holds only JSON tokens with a regex chain, then let the language read it. That is about ten lines against about five hundred of vendored code nothing here can verify.

### 9.2 Nuke

**Export (`rotobridge_export.py`)** - menu item via `menu.py`, which registers a `RotoBridge` menu with both directions on it. Put the `nuke/` directory on `NUKE_PATH`, or copy its two `addCommand` lines into an existing `menu.py`. Nuke runs `menu.py` only when the GUI starts, and `nuke.menu()` raises "not in GUI mode" under `--nc -t` (measured 2026-08-22), so the registration itself is not reachable from the headless suites; `TestUiEntryPoints` checks the half that is, which is that each command names a function that exists.

1. Validate: exactly one Roto/RotoPaint node selected, ≥1 shape in `node['curves'].rootLayer`.
2. Prompt for output path and frame range (default: script range).
3. Read authored keys: walk every point's AnimCurves, collect key times, union per shape → `keys`. Where all points share an interpolation style at a key, derive both sides of `interp`: `interpolationType - 1` back through the `InterpolationType` enum, with `eStep` → `out: "hold"` and `in: "ease"` (it freezes only the interval it leaves; the one it arrives on is a cubic with a flat handle, so `linear` there would be a claim the curve does not make - corrected 2026-08-22), `eLinear` → both sides `linear`, `eCubic` → the side is `linear` when its slope equals the chord slope and `ease` otherwise, with params from `lslope`/`rslope` and `la`/`ra`. Where points diverge, write both sides as `ease` with no params (tier 2).
4. Dense layer: per `Shape`, per frame, read each `ShapeControlPoint`'s `center.getPosition(frame)`, `leftTangent`, `rightTangent`, and feather attributes.
5. Bake the shape transform: `shape.getTransform()` returns an `AnimCTransform`, which has **no `getMatrixAt`**. Evaluate it as `shape.getTransform().evaluate(frame)` → `CTransform`, then take `.getMatrix()` (or `.getInverseMatrix()`) and apply that to every point. `AnimCTransform.isDefault()` detects an identity transform cheaply, and `getTransformKeyTimes()` supplies the key times. **Note:** if the transform is animated, those key times join the `keys` union - a static shape under an animated transform is keyed animation.
6. Already canonical - no flip.
7. Feather: `feather_model: "per_point"` when any `featherCenter` is non-zero, else `"none"`. Write both `feather` (the signed normal projection) and `feather_offset` (the raw vector) on every point. Independently, read `fx`/`fy` **per frame** into `feather_uniform` and `ff` into `feather_falloff` - they animate (§9.3).
8. Write `.rbj`. Report to Script Editor.

**Import (`rotobridge_import.py`)** - menu item.

1. Prompt for `.rbj` path, frame offset, drift tolerance (default 0.5 px), optional shape subset.
2. Create a Roto node, build shapes and control points.
3. Key every point at authored `keys`, translating both sides of `interp`. `AnimCurveKey.interpolationType` takes the **`InterpolationType` enum plus one** (§15 Q9) - write `eStep + 1` etc., never the bare value. Because Nuke has one type per key but independent `lslope` / `rslope`:
   - `out: "hold"` → `eStep + 1`, which affects only the outgoing interval, exactly matching AE.
   - both sides `linear` → `eLinear + 1`.
   - anything asymmetric or eased → `eCubic + 1`, then set `lslope` and `rslope` per side, using the chord slope for a `linear` side and the `ease` entry for an `ease` side. A side with `ease` and no params gets the smooth default.
   Set the interpolation **per key**, never through `AnimCurve.curveType` - that selects the spline basis and has no linear member (§7, Phase 2 case 71). **Phase 3 implements the three-way type mapping only and writes no slopes** - see §12 Phase 3 for why, and `core/interp.to_nuke`, which is where it changes when Phase 5 calibrates them.
4. Drift pass: evaluate each point's AnimCurve per intermediate frame against the dense layer; insert corrective keys where tolerance is exceeded.
5. Identity shape transform (geometry is pre-baked).
6. Feather: use `feather_offset` when present, else `feather * n`. Write `feather_uniform` to `fx`/`fy` and `feather_falloff` to `ff` via `getCurve` + `AnimCurve.addKey`, never `attrs.add` on the same attribute (§9.3).
7. Report per shape: corrective keys inserted, worst-drift frames.

**Constraints:** flatten nested RotoPaint layers to root on export, warn. Skip paint strokes, warn.

**Known API risk - RETIRED for 17.1v1.** Some Nuke versions of the rotopaint API were reported not to persist bezier tangents through certain write paths, leaving shapes as straight polylines (documented by the AlphaToRoto project, which disables potrace curve optimisation for this reason). Phase 0 tested it directly: a 4-point shape written with `cp.leftTangent` / `cp.rightTangent`, saved and reloaded, returned every tangent unchanged. See `test/golden/nuke_probe/17.1v1/10_tangent_persistence_CRITICAL.txt`. Re-run the probe before supporting any other Nuke version.

**Confirmed API details (Phase 0):**

- Key times come from `cp.center.getControlPointKeyTimes()`. That call is the source for the step 3 union.
- `AnimControlPoint.dim` is 3 (x, y, w); per-axis curves via `getPositionAnimCurve(d)`. `AnimCurve` exposes `getKey` / `getNumberOfKeys` / `curveType` / `curveTension` - there is no `keys()` or `getKeyTimes()`.
- **Default point-curve interpolation is curved, not linear.** Keys at f1=0, f50=20, f100=100 undershoot piecewise-linear by up to 5.5 units mid-span. An importer that writes keys and stops does not get linear motion between them. Fix it per key with `AnimCurveKey.interpolationType = eLinear + 1`, not with `curveType` (§7).
- **`getPosition` is pre-transform** (Phase 2 case 70). A shape translated +200, +50 still reported its authored `(100, 100)`, so the step 5 bake is required rather than a precaution.
- **Applying the transform matrix**: `list(CMatrix4)` gives 16 floats, row-major, translation at indices 3 and 7. Nuke's own `matrix * CVec3(x, y, 1)` agrees with reading it that way; `vector * matrix` does not and returns nonsense. `CVec2`/`CVec3` expose `.x` / `.y` and are iterable, so nothing needs to parse a repr.
- **Control point positions are float32.** The serialised form carries eight-hex-digit values (`x42c80000` is `100.0f`). A tolerance-0 round trip is therefore exact to about 3e-05 px at typical coordinate magnitudes, not bit-identical to the float64 in the `.rbj`. That floor is Nuke's storage, not accumulated error.
- **Keying a control point**: `AnimControlPoint.addPositionKey(frame, CVec3(x, y, w))`, with `w = 1` for a position and `w = 0` for a vertex-relative tangent or feather offset (Phase 2 case 71).
- Lifetime defaults are safe: `ltt=0, ltn=1, ltm=1`, and `getVisible()` is true across frames 1-500. Shapes built through the API are live everywhere without intervention.
- `isinstance` against `nuke.rotopaint.Shape` / `Stroke` / `Layer` correctly separates tree elements.
- Attribute names: `opc` opacity, `bm` blend mode, `inv` inverted, `fo`/`fx`/`fy`/`ff`/`ft` feather, `ltt`/`ltn`/`ltm` lifetime. Full list in `01_attribute_names.txt`.

### 9.3 Feather: two representations that do not align

Phase 0 established that neither application stores feather the way v4.0 assumed, and that an early probe run reached the wrong conclusion about AE.

**Nuke.** A `ShapeControlPoint` has six `AnimControlPoint` members: `center`, `leftTangent`, `rightTangent`, and `featherCenter`, `featherLeftTangent`, `featherRightTangent`. Feather is therefore **a second bezier curve**, offset per vertex, with its own tangents - not a width. Setting `featherCenter` to `(12, 7)` reads back as `(12, 7)`.

Nuke **also** has a per-shape uniform layer, measured by case 62. On the shape's `AnimAttributes`: `fo` (feather on, default 1), `fx` and `fy` (default 0), `ff` (falloff, default 1), `ft` (type, default 0). Writing `fx=20, fy=5` reads back as 20 and 5 independently, so **Nuke's uniform feather is 2-D exactly like AE's `maskFeather`**, and the two map 1:1 with no mean and no anisotropy warning. Case 62 also confirms the two layers are **independent**: `featherCenter` reads `(12, 7)` while `fx`/`fy` read 20/5 on the same shape, so `.rbj` must carry both rather than choosing.

**Uniform feather animates, and three API traps sit on the path to writing it** (case 62):

- `AnimAttributes.addKey` introspects as `(time, name, value, view)` but the binding accepts **two** arguments and raises on four. It is unusable. The working route is `attrs.getCurve(name)` to a live `AnimCurve`, then `AnimCurve.addKey(time, value)`. A re-fetch of the curve reports the keys, confirming the handle is live rather than a copy. This is the same class of introspection lie as `getMatrixAt` (§9.2).
- **`attrs.add(name, value)` shadows the curve.** On a shape where `add("fx", 20.0)` ran first, `getValue` returned 20.0 at every frame while `evaluate()` returned the animated 5 → 40. On a clean shape that never saw `add`, `getValue` tracked the curve exactly. The importer must write a constant **or** keys for a given attribute, never both, or the animation is silently dead.
- `getValue`'s third argument is a **view name string** (`'main'`), not an integer index. `getValue(25, "fx", 0)` raises.

Attribute curves default to `curveType=0`, which is curved: keys at (1, 5) and (50, 40) evaluate to 22.14 at frame 25 against a linear 22.5. The same `curveType` caveat as §7 applies to attributes, not just point curves.

**After Effects.** Two independent mechanisms, and a mask may use either or both:

1. **Whole-mask feather** - `MaskPropertyGroup.maskFeather`, a **2-D** `[x, y]` pixel value applied uniformly to the entire mask, plus `maskFeatherFalloff` (`FFO_LINEAR` / `FFO_SMOOTH`, an *attribute*, so it cannot be keyframed). Separate x and y is why it is 2-D, and why an anisotropic value cannot collapse to one number without loss. **`maskFeather` is a `Property`, so it animates** - measured in run 6 (Q8).
2. **Feather points along the spline** - fully scriptable, living on the `Shape` object returned by `maskPath` rather than as a property of the mask group. Each point sits at a location on the path and feathers a given distance **either outward or inward**. The attributes are `featherSegLocs` (segment index), `featherRelSegLocs` (0-1 along that segment), `featherRadii` (distance), `featherTypes` (0 outer / 1 inner), `featherRelCornerAngles`, `featherInterps`, and `featherTensions`, all read/write.

The consequence that drives the mapping: **an AE feather point is a signed distance along the path normal**, never a free vector.

**Measured, not inferred (probe run 3).** A seven-vertex mask with four feather points authored in the UI read back as:

```
featherSegLocs:    [3, 6, 1, 3]
featherRelSegLocs: [0.9029, 0.9715, 0.0975, 1.0]
featherRadii:      [89.5565, 0, -46.6171, -1e-8]
featherTypes:      [0, 0, 1, 1]
```

Three things follow, and each changes the mapping:

- **`featherRadii` is signed, and its sign agrees with `featherTypes`.** Type 0 came back non-negative, type 1 non-positive. The signed radius alone therefore carries the direction; `featherTypes` is redundant on read. On write, set both consistently - the scripting guide notes a point's direction cannot be changed after creation, so the importer must create each point with the correct type up front rather than fixing it afterwards.
- **Feather points are not one per vertex.** Four points on a seven-vertex shape, three of them mid-segment, and two of them (indices 0 and 3) on the same segment. Mid-segment placement is the normal case in AE, not an edge case.
- **A zero radius is authored, not absent.** Index 1 has `featherRadii = 0` at a real location; such a point pins the feather back to zero width and is load-bearing. Dropping zero-radius points on read changes the shape.

An early Phase 0 run reported variable-width feather as unreachable from ExtendScript. That was a probe defect - it searched the mask property group instead of the `Shape` object. Corroborated against the After Effects Scripting Guide; the corrected probe reads the `Shape` attributes above.

**Why they still do not map cleanly.** AE anchors a feather point **anywhere on a segment** and gives it a **signed distance along the normal**. Nuke anchors feather **at a vertex** and gives it a **free 2-D offset with its own tangents**. So each side can express something the other cannot: Nuke can offset feather tangentially, AE cannot; AE can place a feather point mid-segment, Nuke has no vertex there to hold it.

The v1 rule is to map what aligns and warn about the rest. Both directions use the **signed** projection onto the outward unit normal `n`, never the magnitude - taking `|featherCenter|` would discard whether the feather goes outward or inward:

- **Nuke to AE.** For each vertex compute `d = featherCenter · n`. Emit a feather point at `featherRelSegLocs = 0` on that vertex's segment with `featherRadii = d`, signed, and `featherTypes = 0` when `d >= 0`, `1` when `d < 0`. Warn per shape when any offset departs from the normal by more than a degree, since the tangential component is dropped.
- **AE to Nuke.** Set `featherCenter = n * featherRadii` directly - one rule for both types, because the radius is already signed. Ignore `featherTypes` on read.
- **AE to Nuke, mid-segment points.** Snap to the nearer of the segment's two vertices and warn. **This is v1 behaviour and it is lossy: `spec/rbj-v2-draft.md` §6 drafts the fix** - carry the anchor in the file and split the segment with de Casteljau on the way into Nuke, so the anchor arrives exact and the cost is extra vertices instead of moved feather. Nothing below changes until that is implemented. **When two AE points snap to the same vertex, keep the one with the larger `|featherRadii|` and warn that the other was dropped** - run 3's real data hits this case, so it is not hypothetical. A `featherRadii` of exactly 0 is a real point and competes on equal terms; it is not treated as absent.
- **Either direction, the uniform layer is independent.** `maskFeather` ↔ `fx`/`fy` is a 1:1 2-D mapping (case 62, run 6) that applies whether or not feather points exist. No mean, no anisotropy warning; the two layers compose (§11).

A Nuke shape with zero feather offsets on **every** vertex is `feather_model: "none"`. A shape with some zero and some non-zero offsets is `per_point`, and the zeros are preserved.

See §15 Q7 for the format question this raises.

---

## 10. Data mapping

| Concept | After Effects | Nuke | `.rbj` field | v1 handling |
|---|---|---|---|---|
| Vertex position | `Shape.vertices`, layer space, Y-down | `ShapeControlPoint.center`, Y-up | `c` | Convert to canonical |
| Bezier tangents (spatial) | `inTangents`/`outTangents`, relative | `leftTangent`/`rightTangent`, relative | `in`/`out` | Relative; negate Y on AE side |
| Keyframe times | whole-shape `maskPath` keys | per-point AnimCurve keys | `keys[].frame` | AE: direct; Nuke: union across points + transform keys |
| Temporal interpolation | one ease per shape key | per-point per-axis tangents | `keys[].interp` + `ease` | Three-tier translation (§7) |
| Shape name | `mask.name` | `Shape` name | `name` | Direct |
| Closed flag | `Shape.closed` | shape attribute | `closed` | v1 requires closed |
| Blend mode | `maskMode`, a boolean set operation | `bm`, an index into fifteen **pixel** blend operations - no set operations exist | `blend` | `union` ↔ `over` exactly; `difference` and `intersection` are unreachable in Nuke, so both warn and degrade to `union` (Q10, closed) |
| Opacity | `maskOpacity` | `opc` shape attribute | `frames[].opacity` | Per frame; animates on both sides |
| Feather | 2-D `maskFeather` **and** scriptable per-segment feather points on `Shape` | second bezier: `featherCenter` plus feather tangents, per vertex | `feather` + `feather_model` | Structurally different; map the normal component, warn on the rest (§9.3) |
| Inverted | `mask.inverted` | - | (warning) | Warn, drop |
| Baked transform | none (layer space) | animated transform stack | - | Baked into points; key times joined into `keys` |
| Hierarchy | flat mask list | nested layer tree | - | Flattened |

---

## 11. Constraints and failure policy

**Fail loudly, never silently deform.** Partial or approximate output is worse than no output, because it looks correct until it is composited.

**Hard failures (abort, name the offending shape, write nothing):**

- Variable vertex count across frames within a shape (AE permits this; Nuke does not). Report the frames where the count changes.
- Open splines **in a v1 file**, and a shape that opens or closes partway through its range - the same argument as a changing vertex count, since the file carries one `closed` for the whole shape. An open spline in a file declaring `version: 2` is carried (`spec/rbj-v2-draft.md`).
- 3D layer, parented layer, or unresolvable transform in AE.
- No shapes found.
- `.rbj` with an unrecognized `format` or a `version` newer than the importer.
- On import: a `keys` entry referencing a frame absent from `frames`.

**Soft failures (warn, continue, record in `warnings`):**

- Unmappable blend mode → union, with the mode **named** in the warning, not just its number (Q10)
- Nuke feather offset with a tangential component → normal component only into AE; `feather_offset` preserves it in `.rbj` (§9.3)
- AE feather point mid-segment → snapped to the nearer vertex (§9.3)
- Two AE feather points snapping to the same vertex → larger `|featherRadii|` kept, other dropped (§9.3)
- ~~Feather points absent on either side → `uniform` from the mean~~ **Removed by case 62.** Nuke's `fx`/`fy` is 2-D, so AE `maskFeather [x, y]` ↔ Nuke `fx`/`fy` is lossless in both directions. No mean, no anisotropy warning.
- Divergent per-point interpolation → tier-2 `ease` without params
- Inverted flag → dropped
- Open spline → carried at `version: 2`, but its host render settings are not: Nuke's `openspline_width` and end caps are node knobs, and what After Effects renders an open mask as is unmeasured. Warned on export, and again on import when the file came from the other application
- Paint strokes, nested layers → skipped
- Non-square pixel aspect → treated as square
- Resolution mismatch between `.rbj` source and destination project

---

## 12. Build phases

**Phase 0 - Probe. COMPLETE.** Run against Nuke 17.1v1 and After Effects 25.6x101; raw output in `test/golden/nuke_probe/17.1v1/` and `test/golden/ae_probe/`, probes in `test/probe/`. Re-run both before supporting another application version. Findings are folded into §7, §9.1, §9.2, §9.3 and §13; the checklist below records what was asked.

*After Effects:*
- Dump one mask's `maskPath.valueAtTime()`; confirm vertex/tangent structure and `closed` reporting.
- Test `sourcePointToComp` on a layer with non-identity scale and rotation. If it misbehaves, scope narrows to identity-transform layers - that must be known on day one.
- Confirm `keyInTemporalEase` / `keyOutTemporalEase` semantics on a mask path property, and that `setInterpolationTypeAtKey` + temporal ease round-trip through `valueAtTime` as expected.

*Nuke:*
- Confirm feather attribute names and the `getTransform().getMatrixAt()` signature.
- Confirm AnimCurve key introspection: key times, interpolation type, tangent slopes per key.
- Characterize the tangent-persistence bug (§9.2): write a bezier shape via the API in the studio's Nuke version, save, reload, confirm tangents survive.
- Confirm Hermite tangent semantics on point curves (weighted vs. unweighted) for the tier-1 ease conversion.

**Phase 1 - Format and geometry core. COMPLETE.** `spec/rbj-v1.md` is **frozen** (2026-08-20). Write one geometry conversion function per app per direction, factored apart from I/O, plus the frame/time conversions and a schema validator that makes the frozen spec executable. Validate with a static square: export, import, confirm corners land within a pixel. The core is host-free stdlib Python in `core/`, so it tests without either application present (§5.1).

**Phase 2 - Nuke adapter pair, dense path. COMPLETE.** `nuke/rotobridge_export.py` and `nuke/rotobridge_import.py`, sharing `nuke/rotobridge_nuke.py`. Round trip measured against Nuke 17.1v1 by `test/test_nuke_roundtrip.py`: a 4-point animated bezier with a baked non-identity transform, per-point feather including a deliberately off-normal point, animated opacity and animated uniform feather returns with a worst deviation of 3.05e-05 px, which is the float32 storage floor (§9.2). Phase 2 wrote no `keys` array, which spec §9 defines as dense import; Phase 3 added it. A 20-point 150-frame export took 0.30 s against criterion 11's 10 s, and the import 0.05 s against 30 s. Output committed as `test/golden/roundtrip.rbj` and validated with no Nuke present by `test/test_core.py`.

**Phase 3 - Sparse path in Nuke. COMPLETE.** Key extraction, union, interpolation translation, drift pass. Two new host-free modules carry it: `core/interp.py` maps Nuke's per-key type to and from `.rbj`'s per-side `interp`, and `core/drift.py` is the tier-3 corrective pass with the two host calls injected, so the algorithm tests without a licence.

Acceptance met on 17.1v1: a shape keyed on frames 1, 11, 21, 31 and 41 exports as exactly those 5 keys, imports as the same 5 keys with **0 corrective keys** at 6.1e-05 px, and every key sits on the control point curves where the artist can grab it. Also measured:

- **An animated transform is shape animation.** A shape with no control point keyed at all, under a translation keyed at frames 1 and 20, exports `keys` of `[1, 20]` with a baked travel of exactly 400.0 px. The key union therefore reads every family of key time an `AnimCTransform` exposes, not just `getTransformKeyTimes` - case 30 only ever measured those on an untouched transform, where all four families report the same single time, so it never showed whether one subsumes the others.
- **Drift bound (criterion 4).** Nuke to Nuke does not drift: the same key type through the same key frames re-evaluates to the same curve. So the test thins a file's sparse layer to two straight keys over its own curved dense layer - what a foreign exporter's tier-2 output looks like - and measures 30.9 px unbounded against **0.465 px at tolerance 0.5**, using 13 keys of a possible 20.
- **Mode switching (criterion 5).** Re-importing that same thinned file at tolerance 0 reaches 3.05e-05 px with no trip back to the source application.
- **Criterion 11 still holds** with the drift pass in the loop: 20 points over 150 frames imports in 0.07 s at either tolerance.
- **The pass splits a gap, it does not walk back from its end** (2026-08-21). It keys the worst frame of each offending gap, plus that gap's **midpoint** when the worst frame is one of the gap's two ends. A key on the end of a run shortens it by one frame instead of splitting it, so error that climbs steadily across a run - which is exactly what an outgoing `hold` produces once an ancestor transform moves the geometry through the held interval - degenerated into one frame per pass and exhausted `max_passes`. See `core/drift.py` `_survey` and `HANDOFF.md`.

Two things Phase 3 deliberately does **not** do, both for the same reason - the units are unmeasured and nothing on the Nuke side calibrates them:

1. **The export never writes `ease` parameters.** A Nuke source emits eased sides as bare `ease`, which spec §10.3 defines as "smooth, parameters unknown, rely on the drift pass".
2. **The import never writes `lslope` / `rslope`,** contrary to §9.2 step 3 below. Case 63 made asymmetric slopes stick but never measured what a slope value renders as, and an asymmetric key cannot arrive from a Nuke source, so Phase 3 has no way to exercise or verify the path. Both settle in Phase 5, which is the first time a file crosses between the two applications and both sides of the mapping are observable at once. Phase 4 narrowed the question rather than answering it: AE ease is now read and written exactly (spec §10.3, a factor of 100), so what is left unmeasured is specifically AE ease ↔ Nuke `lslope` / `rslope`.

Corrective keys are written **linear**, not smooth. A corrective key exists precisely because the host's own interpolation left the dense layer, so a cubic one could overshoot between corrective keys and manufacture fresh drift; straight segments between measured frames cannot, which is what makes each pass reduce the error rather than move it.

**Phase 4 - AE adapter pair. COMPLETE, both layers.** `ae/rotobridge_export.jsx` and `ae/rotobridge_import.jsx`, sharing `ae/rotobridge_ae.jsx`, over a host-free `ae/rotobridge_core.jsx` (timing, geometry, interpolation, drift) and `ae/rotobridge_rbj.jsx` (the schema). **Both halves have now run in After Effects.** The export produced `test/golden/ae_scene.rbj` (6 shapes, 600 points, 0.29 s, `version: 2`), and a six-shape import came back clean after two host-only bugs were found and fixed: mask parade handles going stale as the parade grows, and `deviation()` comparing `featherRadii` by array index when the host reorders them. Both are described in `HANDOFF.md` and both are now caught host-free by `test/ae_mock.js`. **The ease question is answered**, 2026-08-21: masks 7 and 8 of `setup_ae_scene.jsx`, on a solid that does not move, exported and reimported with **0 corrective keys and 0.0000 px** on both. `eased_static`'s dense layer bows 135.4 px off the straight chord between its keys against a 0.5 px tolerance, so the three authored keys rebuilt all of that curve from the file alone - which confirms §10.3's factor of 100 in both directions on a real curve rather than on a default. `linear_static` is the calibration and passes at zero. Committed as `test/golden/ae_static_ease.rbj`. What is left of the checklist is ease-then-type ordering, which a drift number cannot answer: the symptom is a hold key that renders smooth, and the pass corrects positions either way.

**The ES3 side is tested without After Effects, all of it.** The two core files touch no host and load under plain node, so `node test/test_ae_core.js` runs 77 tests. `test/ae_mock.js` then stands in for the host - `valueAtTime`, `sourcePointToComp` with no time parameter, mask properties by matchName, feather points on the `Shape` object, and an exactly affine layer transform - which lets the adapters themselves run end to end: 51 export tests and 51 import tests, among them an export/import/export round trip that returns every vertex to within 1e-9 px through a layer at scale [150, 220] and 30 degrees, with the whole `shapes` array - `keys` included - comparing byte-equal. `test/run.sh` runs the five host-free suites; 369 tests.

**The crossing itself is tested, in one direction, with neither application present.** `test/test_ae_crossapp.js` reads a `.rbj` that Nuke really wrote, builds the masks in the mock, exports them straight back out and compares the two documents. This is the one thing a same-app round trip cannot do: a round trip that flipped Y the wrong way, inverted feather's sign or stored ease a factor of 100 out would still return exactly what it was given, which is the same reason Nuke to Nuke does not drift. Four results:

- **A dense Nuke file crosses exactly.** `roundtrip.rbj` at tolerance 0 returns every vertex, tangent, opacity, uniform feather and signed per-point feather **bit-identical**, over all 20 frames. Not "within a tolerance" - equal.
- **`feather_offset` is the only field dropped**, which is the documented loss and the one the file names in its own warnings. The test compares the key set of every point both ways, so a second omission fails rather than passing quietly.
- **The two applications' `linear` is the same line.** `sparse.rbj` keyed on 5 frames of 41 comes back as exactly those 5 keys with **0 corrective**, and the 36 frames After Effects rebuilt by interpolating agree with the ones Nuke wrote to **3.05e-05 px** - the float32 storage floor `test_nuke_roundtrip.py` hits, not accumulated error.
- **A bare `ease` comes back carrying AE's default**, influence 0.16667 and speed 0. This is the one thing the crossing changes, and it is honest: spec §10.3's "parameters unknown" has to become a real curve to exist in a comp at all, and the dense layer stays the ground truth. Recorded because a file that crosses twice is no longer parameterless.

It is not a substitute for Phase 5 - the mock answers the After Effects API but is not After Effects, and nothing here renders a pixel. What it establishes is where a Phase 5 mismatch could and could not come from.

**The mock draws one line, and it is what makes the drift pass testable.** Between keys it interpolates only what has been measured or is definitional: two LINEAR sides interpolate straight (run 6 section H put the midpoint of [100,100] and [500,200] at [300,150]), a HOLD outgoing side freezes the segment, and past the last key the last value stands. **BEZIER raises.** Its shape depends on influence and speed in a way nothing has measured, and a plausible guess would make the pass look tested while doing nothing. Drawing the line there means a file whose sparse layer is two straight keys over a curved dense layer really does drift under test, and the pass really does have to find it - which is the same construction `test/test_nuke_roundtrip.py` uses on the Nuke side. What still needs the host is whether AE's *bezier* interpolation matches the ease values `.rbj` carries.

**The mock also reorders feather points, because After Effects does.** Two probes measured it: a point written at `(segment i, rel 0)` always reads back at `(segment i-1, rel 1)`, the same place on the path renamed, and at an **interpolated** frame the points are additionally regrouped by type, non-negative before negative, for LINEAR keys as well as BEZIER. Nothing is lost either way - each radius keeps its own anchor - but it means an adapter must resolve a feather point through `(seg, rel)` and never through its array index. The export always did, via `snapFeatherPoints`; the import's `deviation()` did not, and measured 27 px of drift on a shape whose feather never moves. Modelling it in the mock is what turns that from a host-only failure into a test.

**`core/rbj.py` has a second implementation now, and they check each other.** `test/test_ae_core.js` reads every golden `.rbj` the Python wrote; `test_core.py`'s `TestEs3CrossCheck` drives the port through node and reads what ExtendScript writes. Neither direction establishes the other, and the second is what decides whether an AE export opens in Nuke at all. One divergence exists and is not fixable: JavaScript has a single number type, so the ES3 writer emits `1` where Python emits `1.0`, and its validator cannot reject a `version` of `1.0`. Both are the same JSON value. A test pins it, so a *second* divergence fails a test rather than surfacing in a host.

**Two performance decisions became assertions.** Criterion 11 is met by loop shape, and loop shape is invisible in the output - an exporter making a host call per vertex writes a byte-identical file and misses the criterion by 20x, so the mock counts calls:

- `comp.time` is set **once per frame**, never once per mask per frame (§9.1 step 4).
- **The layer transform is derived, not asked per vertex.** A 2D unparented layer's transform is affine, and an affine map is fixed by where it sends three points - so the adapters probe three points per layer per frame and do the rest in arithmetic. 64 vertices cost exactly what 4 do. Ten shapes of 20 points over 150 frames would otherwise be ~90,000 `sourcePointToComp` calls. The derivation is checked against Phase 0 section F's measured readings, exactly, and **checked again at runtime**: a fourth probe per frame transforms a real point both ways, and a frame disagreeing by more than 1e-4 px falls back to per-vertex host calls and warns. 3D and parented layers are already hard failures (§11), which is what makes the affine claim safe to rest on.

**The sparse layer, and where it differs from Nuke's.** The export reads `numKeys` / `keyTime(i)` and **both sides** of every key, and `keys` is never omitted - an absent `keys` means "treat every frame as a key", which is a different claim. Three things the Nuke direction needed and this one does not, and one it did not need and this one does:

1. **No tier machinery.** After Effects carries one keyframe per time for the whole mask path and `.rbj` carries one key per frame for the whole shape, so there is nothing to reduce and nothing to expand. `sides_from_nuke` / `reduce_sides` / `to_nuke` have no caller here.
2. **Ease is real, both ways.** Run 6 section G measured the ease on a mask-path key as **one-dimensional** - "1 dim" on all three keys - which is what makes a single shape-wide `ease` the right storage. A side gets an `ease` entry only when its interp is `ease`: After Effects reports an ease on every key whatever its type (it read influence 16.667 off a LINEAR key), so reading unconditionally would write parameters that describe nothing.
3. **The layer transform contributes key times.** It is baked into the exported points, so a layer that moves animates the geometry even when the path never does - the same reason case 77 made the Nuke side walk its layer chain. Only the transform properties that move geometry are read; layer opacity lives in the same group and would otherwise plant a key in the middle of a shape that never moved.
4. **Off-grid keys.** After Effects permits a keyframe anywhere in continuous time and spec §9 requires every `keys[].frame` to name a frame in `frames`. The export snaps and warns. Nuke had no equivalent.

On the import side, `drift.correct` is wired with `applyKeys` on `setValueAtTime` and `measure` on `valueAtTime`, and the tolerance control matches Nuke's exactly: `inf` keeps the authored keys, `0` keys every frame, `0.5` by default. **The layer-space conversion happens once, frame-major, before the pass starts.** `compPointToSource` has no time parameter, but `setValueAtTime` and `valueAtTime` both take their own - so once the targets are in hand the playhead never moves again, and the pass costs nothing per iteration but arithmetic. Setting `comp.time` measured 5.75-20.89 ms; paying it per pass would have cost more than the rest of the import.

**One ordering that only the host can confirm.** `setTemporalEaseAtKey` is documented to force a key to BEZIER, so the importer sets the ease **first** and the per-side types **after** - the other order leaves a `hold` side rendering smooth, which is a wrong matte rather than a wrong knob. The mock reproduces the forcing and a test pins the result; whether the ease *survives* that second call is on the by-hand checklist.

**AE ease is settled and no longer blocks anything.** AE ↔ `.rbj` ease is a factor of 100 (spec §10.3) and `core/interp` carries it in both directions with tests. What is still unmeasured is AE ease ↔ **Nuke** `lslope` / `rslope`, which needs a file crossing between the two applications - so it belongs to Phase 5, not here. `core/interp.to_nuke` remains the one function that changes, and should not change until that file exists.

**Phase 5 - Verify.** Same plate in both applications. Comp AE's matte against Nuke's at each import mode; confirm tolerance bounds hold. Sub-pixel at tolerance 0 or the geometry core is wrong. `test/test_ae_crossapp.js` already takes Nuke's files through the AE adapters at the document level and finds them exact, so what Phase 5 adds is the two things a document comparison cannot reach: rendered pixels, and the Nuke direction of the crossing.

**The Nuke half is built and passing, 2026-08-22.** `test/test_ae_to_nuke_render.py` renders Nuke's matte from `test/golden/ae_scene.rbj` and measures it as criterion 2 is written - the fraction of pixels past 0.01 alpha delta - entirely in memory through a thresholded difference and a CurveTool average, so nothing depends on what a non-commercial licence will write to an image file. The measurement is checked before it is used: the same file imported twice reads zero on all 25 frames, and a square moved 4 px reads 0.00100418 against the 0.00100418 the same script computes by hand. It also answers a question criterion 4 could not: **tolerance 0.5 against tolerance 0 leaves no pixel on any frame differing by more than 0.01 alpha**, worst delta 0.000266, so the default drift tolerance costs nothing an artist can see. **The rendered comparison is out of scope, decided 2026-08-22** - see criterion 2 in §13. `test/test_ae_to_nuke_render.py` and `test/probe/probe_ae_phase5.jsx` stay in the tree on the same footing as `spec/rbj-v2-draft.md`: built, passing, costing the live paths nothing, and waiting on a use that has not appeared. Do not reopen this by proposing a render.

**Phase 6 - Extras.** Open splines, inverted flag, mask expansion, richer ease fitting.

**Feather anchors are implemented, 2026-08-22.** `spec/rbj-v2-draft.md` §6 adds `feather_model: anchored` and a per-frame `feather_points` list, each entry anchored by a single `t` in segment units (`segment + fraction`, the invariant AE's rename and regroup both preserve). A v2 import into Nuke splits the segment at `t` with de Casteljau and inserts a vertex, so a mid-segment anchor arrives exact instead of snapped; the price is extra vertices, warned per shape. `per_point` is untouched, so Nuke files stay v1. An AE file goes v2 **only** when an anchor is genuinely mid-segment or two share a vertex - which is exactly the set of files v1 was damaging. All four layers are built and both hosts have run them: `test_nuke_roundtrip.py` Phase 7 measures 4 points and 3 anchors in, 6 points out, worst vertex placement 0.000e+00 px; `test/golden/ae_scene.rbj` was re-exported with `feathered` anchored and the crossing re-run, where it arrives with 3 inserted vertices at 6.1035e-05 px and the same 12 corrective keys as before. What is left is §8 condition 4, which is a Phase 5 rendered measurement: until it is taken an anchored file is better than the snap, not known to be exact.

**Open splines are drafted, 2026-08-21.** `spec/rbj-v2-draft.md` is a delta against the frozen v1: `closed` becomes a real boolean, and a file containing an open shape declares `version: 2`. The bump is per **file**, not per adapter - a v2 exporter with nothing open to say still writes `version: 1`, so every file that would have been written before the draft is written byte-identically and still opens in a v1 reader. Both adapter pairs carry it, both schema implementations gate it, and `test/test_nuke_roundtrip.py` gained a section for the next Nuke run. `spec/rbj-v1.md` is untouched and still FROZEN.

Two things the draft does not settle, both in its §7. What After Effects **renders** an open mask path as is unmeasured - no probe run ever authored one - and Nuke's own open-spline width and end caps are node knobs with no per-shape attribute to carry them (probe `q10/93_node_knobs.txt` against `phase2/72_shape_attributes.txt`). So the document round trip is exact in both hosts and the rendered one is only claimed within a host. Mask 6 of `test/probe/setup_ae_scene.jsx` exists to answer the first.

The other three extras are **not** in the draft, and their absence is a decision. The inverted flag is an additive member, which §2.5 says a v1 reader must ignore - so an old reader would render the un-inverted matte silently, the exact failure mode §11 exists to prevent. Mask expansion is After Effects-only. Richer ease fitting is blocked on a measurement nobody has taken (AE ease ↔ Nuke `lslope`/`rslope`, Phase 5).

---

## 13. Acceptance criteria

1. A 4-point static square round-trips AE→Nuke and Nuke→AE with all corners within 0.1 px.
2. ~~A 20-point animated organic shape over 100 frames round-trips at tolerance 0 with a matte difference under 1% of pixels at >0.01 alpha delta.~~ **RETIRED 2026-08-22, out of scope.** This tool moves roto spline data from one application to another, and a matte difference measures how a host *draws* a shape rather than whether the shape arrived. The transfer itself is measured by criteria 1, 3, 4, 6, 6a, 7, 8, 8a, 8b and 10, all of which are met: geometry across a real AE-to-Nuke crossing lands at 6.1e-05 px, the float32 storage floor, and every per-side key survives. Two questions were only ever observable in rendered pixels and stay open as **rendering** questions rather than data losses - `ff`, Nuke's feather falloff profile, and where an anchored feather sits along a curved segment (`spec/rbj-v2-draft.md` §6.4). The file carries what the source said in both cases.
3. **Key preservation:** a shape authored with 5 keys in AE arrives in Nuke with exactly those 5 key times present on every point curve (plus corrective keys only as reported). Same in reverse, using the key-time union.
4. **Drift bound:** at default tolerance, no point on any intermediate frame deviates from the dense layer by more than the tolerance, verified programmatically.
5. **Mode switching:** re-importing the same `.rbj` at tolerance 0 after a sparse import produces the bit-exact dense result, with no re-export from the source app.
6. **Hold fidelity:** a hold keyframe in AE produces constant interpolation in Nuke - no drift and no interpolation before the next key. Same in reverse.
6a. **Asymmetric key fidelity:** an AE key authored `in=LINEAR, out=HOLD` survives AE → Nuke → AE with both sides intact. This is the exact key run 6 produced, and it is the case the v4.2 schema could not represent.
7. A shape on an AE layer with animated scale, rotation, and position exports correctly to comp space.
8. A Nuke shape with per-point feather, **including offsets with a tangential component**, exports to `.rbj` with `feather_model: "per_point"` intact and re-imports into Nuke within 0.1 px, measured on the **feather offset vector**. Nuke has no edge-width scalar (§9.3); the `feather_offset` field of Q7 is what makes this reachable.
8a. A Nuke shape whose feather offsets lie along the path normal survives Nuke → AE → Nuke within 1 px of the original signed offset, sign preserved, and raises no more than one warning per shape.
8b. An AE mask with four feather points, at least one inward and one mid-segment, survives AE → Nuke → AE with each surviving point within 1 px of its original signed radius, and warns once per dropped or snapped point. Two points snapping to the same vertex is an expected loss, not a failure. **Measured 2026-08-21 and the loss is larger than "expected" suggests:** on `feathered` the radius-12 anchor moved 150 px along the path and overwrote an authored radius-0 point, so a corner pinned to zero feather width arrives 12 px soft. `spec/rbj-v2-draft.md` §8 condition 6 restates this criterion as a pass rather than an accepted loss.
9. Variable vertex count aborts with the shape name in the message and writes no file.
10. A `.rbj` written by either adapter is readable by the other with no manual editing.
11. Export of a 20-point, 150-frame shape completes in under 10 seconds in both applications, and a **ten**-shape 150-frame export also completes in under 10 seconds - the frame-major loop of §9.1 step 4 is what makes the second bound reachable. Import with drift pass completes in under 30 seconds. Phase 0 measured the real costs as 5.75-20.89 ms per `comp.time` assignment against 0.02-1.52 ms per `valueAtTime`, so the export loop, not the drift pass, is the bottleneck.
12. Golden `.rbj` files in `test/golden/` validate both importers without the other application present.

---

## 14. Deliverables

```
rotobridge/
├── spec/
│   ├── rbj-v1.md               # format specification, FROZEN 2026-08-20
│   └── rbj-v2-draft.md         # open splines + feather anchors, DRAFT 2026-08-21
├── core/                       # host-free, stdlib only, no I/O
│   ├── geom.py                 # canonical-space conversion, per app per direction
│   ├── timing.py               # frame/second conversion, ranges, offsets
│   └── rbj.py                  # schema validation and serialization
├── ae/
│   ├── rotobridge_panel.jsx    # Window > RotoBridge: two buttons, no logic
│   ├── rotobridge_export.jsx
│   ├── rotobridge_import.jsx
│   ├── rotobridge_ae.jsx       # host calls, shared by both adapters
│   ├── rotobridge_core.jsx     # ES3 mirror of core/ (timing, geom, interp, drift)
│   └── rotobridge_rbj.jsx      # ES3 mirror of core/rbj.py
├── nuke/
│   ├── rotobridge_export.py
│   ├── rotobridge_import.py
│   ├── rotobridge_nuke.py      # host calls, shared by both adapters
│   └── menu.py                 # registers the RotoBridge menu
├── test/
│   ├── probe/                  # Phase 0 probes
│   │   ├── probe_nuke.py
│   │   ├── probe_ae.jsx
│   │   └── README.md
│   ├── square.aep / square.nk
│   ├── organic_20pt.aep
│   ├── sparse_5key.aep / sparse_5key.nk   # key-preservation fixtures
│   └── golden/
│       ├── nuke_probe/<version>/   # Phase 0 raw output
│       ├── ae_probe/              # Phase 0 raw output
│       └── *.rbj                  # reference files
└── README.md
```

---

## 15. Open questions

1. Does the AE side need a ScriptUI panel, or is a File > Scripts menu item sufficient for v1?
2. On AE import, create a new solid to hold masks, or require a pre-selected layer?
3. Frame offset: derive automatically from comp `displayStartTime` and the destination's first frame, or always prompt?
4. Should `.rbj` be gzipped? A 50-shot sequence of dense-baked shapes will not be small. (The dense layer is the cost of the mode-switching guarantee; compression is the likely answer, but v1 can ship uncompressed.)
5. Is there value in emitting a `.nk` snippet alongside `.rbj` for artists who prefer drag-and-drop?
6. **Answered by Phase 0.** `valueAtTime` read-back costs 0.02-1.52 ms, so the drift pass needs no sub-sampling: 150 frames is under 230 ms per shape per iteration even at the slow end. The real cost is `comp.time` assignment at 5.75-20.89 ms, on the export side, addressed by the frame-major loop in §9.1 step 4.
7. **Feather representation - DECIDED by probe run 3.** `.rbj` stores `feather` as a scalar per point, which cannot represent Nuke's 2-D `featherCenter` offset (§9.3). Three options were on the table:
   - **Keep the scalar, but make it signed.** Store `featherCenter · n` and reconstruct along the path normal. Positive is outward, negative inward, which is exactly AE's `featherTypes` distinction in one field and maps to Mocha's `edge_width` directly. Simplest, and lossy only for Nuke shapes with off-normal feather. Acceptance criterion 8 must then be scoped to normal-direction feather.
   - **Make `feather` a 2-D offset.** Lossless for Nuke round trips. AE and Mocha both need the projection anyway, so it adds a conversion at two of three adapters to serve one.
   - **Both: scalar `feather` plus optional `feather_offset`.** Every adapter reads the scalar; Nuke also writes and reads the vector, so Nuke → Nuke is lossless and everything else ignores it. Costs one optional field and matches how §5.2 already treats superset data.

   **Decision: the third, with the scalar signed as described in the first.** Run 3 settled the premise the choice rested on. AE's `featherRadii` came back **signed** - `[89.5565, 0, -46.6171, -1e-8]` - so a signed scalar is not a RotoBridge invention layered over AE's model; it *is* AE's model, read back verbatim with no conversion at the AE adapter. Mocha's `edge_width` is the same shape of value. Only Nuke has a genuine 2-D offset, so only Nuke pays for the optional vector.

   Concretely, `.rbj` v1 carries:

   - `feather`: signed float per point. Positive is outward along the path normal, negative inward. Every adapter reads and writes it.
   - `feather_offset`: optional `[x, y]` per point, in canonical space. Nuke writes and reads it; other adapters ignore it. When present it wins on a Nuke import, making Nuke → Nuke lossless including tangential offsets.
   - `feather_model`: `"none"` | `"uniform"` | `"per_point"`, unchanged.

   This settles the *per-point* layer; Q8 settles the whole-shape layer. Both are closed, and `spec/rbj-v1.md` freezes on them. Reversible if a Mocha adapter later turns up a case that needs more, but nothing in Phase 0 suggests one.
8. **Uniform feather - DECIDED, both sides.** Q7 settled the per-point layer; the whole-shape layer was unprobed on both sides. **Nuke case 62 answered its side completely** (§9.3): `fx`/`fy` is a 2-D uniform feather that maps 1:1 to AE's `maskFeather`, it animates via `getCurve`, and it is independent of `featherCenter`. Three consequences are already settled:

   - **`.rbj` gains `feather_uniform: [x, y]` and `feather_falloff`.** Because both sides are 2-D, this is lossless in both directions and it **deletes** the collapse-to-mean rule and its anisotropy warning rather than adding a lossy path.
   - **The read-feather-once bug is confirmed real on the Nuke side.** §9.1 step 6 and §9.2 step 7 read feather outside the frame loop. Nuke uniform feather demonstrably animates, so the fix is required regardless of what AE does: uniform feather belongs in the dense `frames` layer, not on the shape.
   - **The two feather layers compose.** Case 62 read `featherCenter (12, 7)` and `fx`/`fy` 20/5 on one shape. §9.3's exclusive rule ("uniform only when no feather points exist") was wrong and is replaced.

   **AE side closed by run 6**, via a self-contained probe section (E2) that builds its own mask rather than depending on manual setup - four runs had failed to exercise it that way. All four answers match Nuke:

   - **Anisotropic values survive.** `[20, 5]` written and read back as `[20, 5]`, so AE's two components are genuinely independent and `feather_uniform` must be 2-D. Nuke's `fx`/`fy` is the same shape, so the mapping is 1:1 and lossless.
   - **It animates.** Keyed `[10,10]` → `[80,80]`, `valueAtTime` at the midpoint returned `[45,45]`. Uniform feather therefore belongs in the dense `frames` layer, not on the shape.
   - **Feather points are writable, not just readable.** Writing `featherRadii [30, -15]` with `featherTypes [0, 1]` at `featherRelSegLocs [0.5, 0.25]` read back **exactly**, negative sign and mid-segment positions intact. This is the first test of the *write* path; every earlier run only read. §9.3's Nuke → AE rule is implementable, and the signed convention holds on write as well as read.
   - **The two layers compose.** `maskFeather [10,10]` and two feather points coexisted on one mask, as in Nuke case 62.

   Also confirmed: `maskFeatherFalloff` is readable and static (`FFO_SMOOTH = 7212`, `FFO_LINEAR = 7213`), and `maskExpansion` is present, animatable, and still absent from this PRD.

   **Resulting schema additions:** `feather_uniform: [x, y]` and `feather_falloff`, both per shape per frame in the dense layer.
9. **Asymmetric in/out interpolation - DECIDED. `interp` is an object with `in` and `out`.** Run 6 is the first run with mixed interpolation authored on a real mask, and it broke the single-valued key model that §6 carried through v4.2:

   ```
   key 1  in=LINEAR  out=LINEAR
   key 2  in=BEZIER  out=BEZIER
   key 3  in=LINEAR  out=HOLD
   ```

   AE stores an **independent type on each side of every key**. `.rbj` stores one `interp` per key, "describing interpolation *leaving* this key". That cannot express the interval between keys 2 and 3, which leaves key 2 as bezier and arrives at key 3 as linear.

   This is only lossy at drift tolerance ∞, where the sparse `keys` layer is authoritative and `frames` is not consulted - which is precisely the mode this project exists to serve. At tolerance 0.5 px or 0 the drift pass corrects it from `frames`, so the error is bounded but the authored key structure is still wrong.

   **Nuke's side, measured by case 63.** `AnimCurveKey` carries a single `interpolationType` but **independent `lslope` / `rslope`**, and the asymmetric write sticks: setting `lslope = 0, rslope = 5` reads back as `0` and `5`. So Nuke expresses a different *shape* on each side of a key through slopes, even though its *type* is one value per key. That is enough to receive most of AE's asymmetry.

   **Decision: `interp` is an object, `{"in": ..., "out": ...}`,** matching the `ease: {in, out}` that was already per-side. AE stores two types per key outright, Nuke honours the distinction through a broken handle, and the single-valued form could not represent data that the first real-world mask produced on the first attempt. No string shorthand: one form means no adapter branches on type. §6 carries the schema and the interval rule; §9.1 and §9.2 carry the per-side translation on all four adapter paths.

   **Nuke's key interpolation encoding: resolved.** It looked like a bitmask because a fresh key reports `interpolationType = 256` while `nuke.rotopaint.InterpolationType` defines `eStep = 0`, `eLinear = 1`, `eCubic = 2`, `eUndefine = -1`. A value sweep against known reference curves settles it - **the key field is the enum plus one**, with `256` a separate unset sentinel that behaves as the cubic default:

   | key field | behaviour on a 0.0@1, 1.0@50, 0.0@100 curve | meaning |
   |---|---|---|
   | `0` | eval(25) 0.6759, eval(75) 0.6875 | unset, falls back to cubic |
   | `1` | eval(75) **1.0**, outgoing held flat | `eStep` + 1 |
   | `2` | eval(25) **0.4898**, eval(75) **0.5** | `eLinear` + 1, exactly linear |
   | `3` | eval(25) 0.6759, eval(75) 0.6875 | `eCubic` + 1 |
   | `4`, `5` | eval(25) 0.6722, eval(75) 0.6913 | undocumented smooth variants |
   | `256` | as `0` | unset sentinel |

   So the importer writes `InterpolationType.eLinear + 1`, and never the bare enum value. There is no blocking unknown here; §7's "set `curveType` explicitly" stands, with this offset as the per-key companion.

   **Both applications use a two-sided bezier handle that can be broken.** This is not an AE-versus-Nuke difference; it is the same model twice, and `.rbj`'s single `interp` is the only one-sided representation in the chain.

   | | per-side type | per-side handle direction | per-side handle weight |
   |---|---|---|---|
   | After Effects | `keyInInterpolationType` / `keyOutInterpolationType` | `keyInTemporalEase` / `keyOutTemporalEase` `.speed` | same objects, `.influence` |
   | Nuke | one `interpolationType` per key | `lslope` / `rslope` | `la` / `ra` (left/right bicubic) |

   AE carries a discrete type on each side *in addition to* the handle; Nuke carries one type per key and leans on the handle for the rest. Case 63 confirmed Nuke's handle genuinely breaks - writing `lslope = 0, rslope = 5` read back as `0` and `5`.

   The sweep adds a detail that closes most of the remaining gap: **Nuke's step is outgoing-only in what it FREEZES.** Setting `1` moved eval(75) to 1.0 while leaving eval(25) at the cubic default, exactly the way an AE key's `keyOutInterpolationType` governs only the interval leaving it. Linear moved both sides.

   **Corrected 2026-08-22, and the correction was in this reading all along.** The sentence that used to follow said AE's `in=LINEAR / out=HOLD` maps to a step "plus a linear incoming slope". It does not. eval(25) staying at **0.6759, the cubic default**, is the measurement: the arriving segment is a cubic with a flat handle, not the 0.4898 an exact linear reads. Not freezing the incoming interval is not the same as leaving it alone. Measured in the host on `mixed`, the segment arriving at a hold lands **2.55 px** off the straight line the file asked for - about 8% of that segment's travel. `sides_from_nuke` now writes `in: ease` for a step, and `to_nuke` reports `in: linear` into a `hold` as **not exact**, so the import warns and the drift pass buys the arrival back. Straightening it instead is not available: probed, a key made to honour an incoming slope draws the arrival exactly and then lets the frozen interval drift 280 px, because it stops being constant.

   **Hypothesis worth one probe in Phase 1, not yet measured:** if `lslope`/`rslope` correspond to AE's ease `speed` and `la`/`ra` to `influence`, then tier-1 ease is a direct per-side numeric conversion rather than the lossy approximation §7 currently assumes. Both sides would be "direction plus weight, per side of the key". Worth testing before writing the tier-2 fallback, since it may not be needed as often as planned.
10. **Nuke roto blending - CLOSED. Nuke has no boolean shape operations at all.** §10 claimed Nuke has union / difference / intersection per shape. It has none of them, and the reason took a UI-authored script to find.

    **Why Phase 2 could not see it.** Case 75 swept a shape's `bm` across 0-29 and read the overlap of two squares as 1.0 at every value, concluding that nothing subtracts. Two independent method errors produced that. The range was wrong - `bm` is an index into a **fifteen**-entry menu, not the thirty-entry Merge operation list case 73 guessed from. And the probe swept the **lower** shape: a blend composites against what is below, so only the shape on top can change the overlap, and the top shape's opaque `over` restored it every time. Case 76 then looked on the `Layer`, found no `bm` there, and the question stalled.

    **What closed it.** A `.nknc` saved from the UI with a layer's blending mode set to `minus`. The saved tree turned out to hold two empty layers and no shapes, so nothing rendered and nothing serialised - but diffing every **node knob** against a fresh RotoPaint found the control in one line: `blending_mode = 'minus'` against a default of `'over'` (case 93). It is a node knob, which is why two probes searching the curves tree never found it. It is a proxy for the GUI selection, and `setFlag(eSelectedFlag)` does not drive it (cases 95, 96) - so the knob is unusable from Python, but it names and numbers the values, which is all that was needed.

    **The mapping, measured** (case 94 for the numbering, case 98 for the behaviour):

    | `bm` | mode | `bm` | mode | `bm` | mode |
    |---|---|---|---|---|---|
    | 0 | over | 5 | screen | 10 | hard-light |
    | 1 | max | 6 | color-dodge | 11 | from |
    | 2 | multiply | 7 | plus | 12 | minus |
    | 3 | color-burn | 8 | overlay | 13 | difference |
    | 4 | min | 9 | soft-light | 14 | exclusion |

    **These are pixel operations, not set operations, and that is the finding.** A shape composites against the accumulated matte below it and **only inside its own outline**. With A on top of B, sweeping A: `over`/`max`/`screen`/`color-dodge`/`overlay` all give union; `difference`/`exclusion`/`from` give (A 1, overlap 0, B 1), which is symmetric difference, not `A - B`; `minus` gives (A **-1**, overlap 0, B 1), because outside B there is nothing to subtract from and the result is a negative alpha; `min` gives (A 0, overlap 1, B 1), which is the intersection inside A but leaves B untouched outside it. Not one row is a boolean operation over the whole matte.

    Stacking is also the reverse of AE's. `rootLayer` index 0 renders **on top**, and a blend reaches downward, so in Nuke the **earlier** shape cuts the later ones; in AE the **later** mask cuts the earlier ones. Any future difference mapping has to reverse the shape order as well as set `bm`, which is why it is not a two-line change.

    **v1 behaviour, unchanged - but now a measured limit rather than a hedge.** `blend` is written as `union` whatever `bm` says, and on import anything other than `union` warns and uses `over`. The warning now names the mode (`'minus'`) instead of printing a bare float, which is what §11 asked for. `union` ↔ `over` is exact and is the default on both sides, so the common case is lossless.

    **What would change it,** if an artist ever needs subtractive AE masks in Nuke: reverse the shape order on import, write `bm = 12` for `difference`, and accept negative alpha wherever the cutter extends past its target. That is a real deformation, so it belongs behind an explicit opt-in, measured end to end once the AE adapter exists - not inferred now.

    **Fixed along the way, not deferred.** Chasing this exposed a real bug rather than a mapping question. Nuke keeps a transform on the **layer** as well as the shape, and neither matrix contains the other (case 77: a layer translated +500, +25 left the shape's own matrix at +7, +9 and left `getPosition` reporting the authored coordinates). §9.2's "flatten nested layers to root, warn" was therefore moving geometry silently. The export now composes the whole ancestor chain, verified by `test/test_nuke_roundtrip.py`: a shape authored at (100, 100) inside a layer translated (500, 25) exports at exactly (600, 125).

    One piece of that is still unmeasured: **the composition order when a layer and a shape in it both have non-identity transforms.** The two orders differ (case 78 computed 499.12/100.87 against 499.11/104.36 for a layer rotation plus a shape translation), and `Shape.evaluate()` turned out to be pre-transform as well, so Phase 0's obvious oracle does not exist. The export assumes the shape's own transform applies first and **warns whenever more than one link in the chain is active**, which is the only case where the order is observable.

    **Also unverified, same class:** `ff` (feather falloff) defaults to `1.0` and the API never names its values. The adapters treat non-zero as `smooth`, which round trips Nuke to Nuke because the same rule runs both ways, but the AE mapping to `FFO_LINEAR` / `FFO_SMOOTH` rests on a guess.

---

## 16. Future scope

**v2 - Mocha Pro.** Confirmed feasible: the Mocha Python API supports spline creation (`add_bezier_contour`, `BezierControlPointData`, `insert_point`), available since Mocha Pro 4. Preferred export route is the `mocha.exporters` framework (`AbstractShapeDataExporter`), which registers `.rbj` in Mocha's native Export Data dialog. Per-point `edge_width` maps to `.rbj` per-point feather - the field v1 Nuke exports already populate. Phase 0 unknowns: coordinate space Y direction, `BezierControlPointData` tangent representation, Python version across Mocha releases, and whether the exporter framework delivers track-baked or raw contour positions.

**v3 - Flame.** No scripting path for spline creation is known; the Python API drives the Batch environment at node level. Destination route: generate GMask Tracer setup text, reverse-engineered using Mocha as an oracle (export known geometry, diff). Source route: parse saved GMask Tracer setups - precedent exists in the Logik community's Axis-to-Nuke-Transform converter. Interim: once the Mocha adapter exists, Flame is reachable as a destination via Mocha's existing GMask Tracer export, at zero additional code.

**v4 - Silhouette.** Adapters via the `fx` Python module. Normalized, center-origin, aspect-scaled coordinate space - the one adapter where pixel aspect cannot be ignored. Secondary benefit: `.sfx` becomes a second route into Mocha.

**Deferred indefinitely:** Resolve/Fusion (small user count; `.comp` is readable Lua-style text, making it the cheapest adapter to add if demand appears); Mocha AE (no import path, no API; escape hatch is opening its project in Mocha Pro).

**Later:** richer temporal-ease fitting (tier-2 least-squares); tracking and transform data alongside splines; open splines.

---

## 17. Related tooling

**MatteTrace** (separate PRD) - a host-independent matte-to-spline converter that emits `.rbj`, acting as a source adapter with no host application. Shares the `spec/rbj-v1.md` dependency. Note: MatteTrace output has no authored keys; it omits `keys`, and importers treat it as dense - exactly the correct semantics for traced mattes.