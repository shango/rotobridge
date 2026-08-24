# `.rbj` version 3 - frame references (DRAFT)

**Status: DRAFT, implemented and live in both writers.** One delta against
`spec/rbj-v1.md` (composing with the v2 draft, which is orthogonal): the dense
layer may fold runs of identical frames. `spec/rbj-v1.md` stays **FROZEN** and
nothing here weakens a v1 or v2 file.

## 1. Why

The dense layer is the format's ground truth and it does not compress. Roto is
full of held spans - a matte painted once and held, a shape parked until the
cut - and a shape held over 1000 frames wrote 1000 identical frame objects.
That is O(frames x points) growth for shots where most of the data is
repetition, and it was the first practical complaint waiting to happen on a
real shot.

## 2. Version rule

Unchanged from v2 (its §2): a writer emits the **lowest** version that can
express the file. Frame references are the only thing here that costs a
version, because a v1/v2 reader hard-fails on the reference record (it has no
`opacity`, no `points`). A file with no references never says `version: 3` on
their account. `core/rbj.py` `fold_frames` and its ES3 mirror `foldFrames` own
the decision: they bump the version **only when something actually folded**,
which is v2 §6.7's policy - only the files that benefit pay the compatibility
cost.

## 3. Frame references

A frame in `shapes[i].frames` may be, instead of a frame record:

```json
"241": { "same_as": 240 }
```

meaning: this frame is identical to frame 240, every member, every point.

Rules, enforced by both validators:

- The record is **exactly** `{"same_as": N}` - one member, nothing else.
- `N` is an integer, present in the same shape's dense layer as a key.
- `N` is **earlier** than the referencing frame. Backward references keep a
  reader single-pass and make a cycle impossible to write.
- The target is itself a full frame record, **never another reference** -
  every reference resolves in one step. A writer folds a run by pointing every
  frame of the run at the run's head.
- Requires `version >= 3`.

Readers expand references immediately after validation (`loads` /
`parse`), into **copies**, so everything downstream - the drift pass, the
importers, the tests - still sees a dense layer on every frame and two frames
never share one mutable record.

Equality, for writers, is data equality: `1` and `1.0` are the same value.
Both implementations agree on this by construction (Python's `==`, and
JavaScript's one number type), so the two writers make the same folding
decisions - pinned by the cross-check.

Diffability (v1 §2.1) survives: a reference is one short line, and a change to
a held span shows up as exactly the frames that stopped being identical.

## 4. What this is not

Not delta encoding, not sampling, not a claim about "close enough" frames.
A reference asserts byte-level sameness of meaning, and expansion restores the
ground truth exactly. Anything cleverer would trade away the property the
dense layer exists for.

## 5. Optional members (version-independent)

Both validators ignore members they do not know, so an **additive** member
does not cost a version - but the v2 draft's warning about the inverted flag
still stands: silently ignoring a member is only acceptable when ignoring it
**cannot change what renders**. The members below qualify because they are
provenance and identity, not geometry. Anything that renders differently when
ignored must cost a version instead.

### 5.1 `pre_conform_keys`

Optional, per shape: the authored `keys` array **exactly as it was before the
exporter conformed it**, ease blocks intact. Written only when the conform
actually changed something. Same schema as `keys`, validated with the same
machinery; `ease` entries are legal here even though the conformed `keys`
beside it carry none.

Why: the ease conform (prd.md §9.1 step 6a) destroys authored timing
irreversibly at export. The shape survives via the bake, but without this the
artist's curves were gone from the file forever, foreclosing any future
importer that could honour them - including an AE-to-AE round trip. Importers
today ignore it, exactly as they ignore `warnings`.
