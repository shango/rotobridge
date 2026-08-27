"""Phase 1 core tests: geometry, timing, and the frozen .rbj v1 schema.

Run:  python3 test/test_core.py

Stdlib unittest, no third-party dependency, because this suite must also run
under the Python embedded in Nuke. No host application is needed for any of it
(prd.md section 5.1).

The schema tests walk spec section 12.1 hard failure by hard failure. Each one
starts from a document that validates clean and breaks exactly one thing, so a
test that fails names the rule that regressed.

One class at the end is different: `TestEs3CrossCheck` drives the ExtendScript
port in `ae/` through node and checks that what it writes, this reads. It skips
cleanly when node is absent, so the suite still runs anywhere. Its own side is
covered by `test/test_ae_core.js`; what it adds is the direction neither suite
can test alone - two implementations of one spec are only worth having if a file
one writes is a file the other accepts.
"""

import copy
import io
import json
import math
import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import (drift, geom, interp, messages, rbj, report, timing,
                  version)

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")
GOLDEN_SQUARE = os.path.join(GOLDEN, "square.rbj")
GOLDEN_ROUNDTRIP = os.path.join(GOLDEN, "roundtrip.rbj")
GOLDEN_SPARSE = os.path.join(GOLDEN, "sparse.rbj")
GOLDEN_SCENE = os.path.join(GOLDEN, "ae_scene.rbj")
GOLDEN_VIA_NUKE = os.path.join(GOLDEN, "ae_scene_via_nuke.rbj")
GOLDEN_STATIC_EASE = os.path.join(GOLDEN, "ae_static_ease.rbj")
GOLDEN_STATIC_CONFORMED = os.path.join(GOLDEN, "ae_static_conformed.rbj")

COMP_HEIGHT = 1080

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AE = os.path.join(REPO, "ae")
# The panel sits at the root of `ae/`; everything it evaluates,
# and everything those files include, sits one level down.
AE_LIB = os.path.join(AE, "lib")
NUKE_DIR = os.path.join(REPO, "nuke")
NODE = shutil.which("node") or shutil.which("nodejs")


def valid_doc():
    """A two-frame, three-point shape that validates clean."""
    def points(dx):
        return [
            {"c": [100.0 + dx, 200.0], "in": [-10.0, 0.0], "out": [10.0, 0.0]},
            {"c": [300.0 + dx, 200.0], "in": [-10.0, 0.0], "out": [10.0, 0.0]},
            {"c": [200.0 + dx, 400.0], "in": [0.0, 0.0], "out": [0.0, 0.0]},
        ]

    return {
        "format": "rotobridge",
        "version": 1,
        "source": {
            "app": "test", "app_version": "0", "width": 1920, "height": 1080,
            "pixel_aspect": 1.0, "fps": 24.0,
        },
        "range": [10, 11],
        "shapes": [{
            "name": "tri",
            "closed": True,
            "blend": "union",
            "feather_model": "none",
            "feather_falloff": "linear",
            "keys": [
                {"frame": 10, "interp": {"in": "linear", "out": "ease"},
                 "ease": {"out": [0.16667, 0.0]}},
                {"frame": 11, "interp": {"in": "ease", "out": "linear"},
                 "ease": {"in": [0.91176, 0.0]}},
            ],
            "frames": {
                "10": {"opacity": 1.0, "feather_uniform": [0.0, 0.0],
                       "points": points(0.0)},
                "11": {"opacity": 0.5, "feather_uniform": [20.0, 5.0],
                       "points": points(25.0)},
            },
        }],
        "warnings": [],
    }


class TestGeometry(unittest.TestCase):

    def test_comp_to_canonical_flips_y_about_the_height(self):
        self.assertEqual(geom.comp_to_canonical_point([50.0, 300.0], COMP_HEIGHT),
                         [50.0, 780.0])

    def test_a_point_near_the_top_of_the_comp_lands_near_the_top_canonically(self):
        # The direction of the flip is the whole point of the conversion, and an
        # involution round-trips whether or not the direction is right.
        near_top_comp = [10.0, 5.0]
        canonical = geom.comp_to_canonical_point(near_top_comp, COMP_HEIGHT)
        self.assertGreater(canonical[1], COMP_HEIGHT * 0.9)

    def test_tangents_negate_y_and_ignore_height(self):
        self.assertEqual(geom.comp_to_canonical_tangent([12.0, -3.0]), [12.0, 3.0])
        self.assertEqual(geom.canonical_to_comp_tangent([12.0, 3.0]), [12.0, -3.0])

    def test_nuke_directions_are_the_identity(self):
        self.assertEqual(geom.nuke_to_canonical_point([1.5, -2.5]), [1.5, -2.5])
        self.assertEqual(geom.canonical_to_nuke_point([1.5, -2.5]), [1.5, -2.5])
        self.assertEqual(geom.nuke_to_canonical_tangent([1.5, -2.5]), [1.5, -2.5])
        self.assertEqual(geom.canonical_to_nuke_tangent([1.5, -2.5]), [1.5, -2.5])

    def test_static_square_round_trips_through_ae_space(self):
        """prd.md section 12 Phase 1: export, import, corners within a pixel."""
        square = [[400.0, 300.0], [600.0, 300.0], [600.0, 500.0], [400.0, 500.0]]
        for corner in square:
            there = geom.comp_to_canonical_point(corner, COMP_HEIGHT)
            back = geom.canonical_to_comp_point(there, COMP_HEIGHT)
            self.assertLess(abs(back[0] - corner[0]), 0.1)
            self.assertLess(abs(back[1] - corner[1]), 0.1)

    def test_static_square_round_trips_through_nuke_space(self):
        square = [[400.0, 300.0], [600.0, 300.0], [600.0, 500.0], [400.0, 500.0]]
        for corner in square:
            back = geom.canonical_to_nuke_point(geom.nuke_to_canonical_point(corner))
            self.assertEqual(back, corner)

    def test_point_object_round_trips_with_tangents_and_feather(self):
        point = {"c": [120.0, 240.0], "in": [-8.0, 4.0], "out": [8.0, -4.0],
                 "feather": -3.5}
        there = geom.comp_to_canonical_point(point["c"], COMP_HEIGHT)
        canonical = geom.ae_point_to_canonical(point, COMP_HEIGHT)
        self.assertEqual(canonical["c"], there)
        back = geom.canonical_point_to_ae(canonical, COMP_HEIGHT)
        self.assertEqual(back, point)

    def test_feather_sign_survives_conversion(self):
        # A magnitude anywhere in the pipeline flips inward feather to outward.
        point = {"c": [0.0, 0.0], "in": [0.0, 0.0], "out": [0.0, 0.0],
                 "feather": -46.6171}
        canonical = geom.ae_point_to_canonical(point, COMP_HEIGHT)
        self.assertEqual(canonical["feather"], -46.6171)

    def test_canonical_to_ae_drops_feather_offset(self):
        # spec section 11.1: the tangential component has no AE representation.
        point = {"c": [0.0, 0.0], "in": [0.0, 0.0], "out": [0.0, 0.0],
                 "feather": 2.5, "feather_offset": [2.4, 0.7]}
        self.assertNotIn("feather_offset", geom.canonical_point_to_ae(point, COMP_HEIGHT))


class TestTiming(unittest.TestCase):

    def test_ae_reported_key_time_does_not_truncate_one_frame_early(self):
        # After Effects reported 8.333333 s for frame 200 at 24 fps (probe run 3).
        self.assertEqual(timing.seconds_to_frame(8.333333333333333, 24.0), 200)

    def test_frame_and_seconds_round_trip_across_a_range(self):
        for fps in (24.0, 23.976, 29.97, 25.0):
            for frame in range(0, 300):
                seconds = timing.frame_to_seconds(frame, fps)
                self.assertEqual(timing.seconds_to_frame(seconds, fps), frame,
                                 "fps=%r frame=%d" % (fps, frame))

    def test_start_frame_offsets_the_origin(self):
        self.assertEqual(timing.frame_to_seconds(1001, 24.0, start_frame=1001), 0.0)
        self.assertEqual(timing.seconds_to_frame(0.0, 24.0, start_frame=1001), 1001)

    def test_rounds_half_up_not_half_to_even(self):
        # Built-in round() would give 0 and 2 here, which makes the snap
        # direction depend on the parity of the frame number.
        self.assertEqual(timing.seconds_to_frame(0.5 / 24.0, 24.0), 1)
        self.assertEqual(timing.seconds_to_frame(1.5 / 24.0, 24.0), 2)

    def test_subframe_residual_reports_the_snap_distance(self):
        self.assertAlmostEqual(timing.subframe_residual(10.0 / 24.0, 24.0), 0.0)
        self.assertAlmostEqual(timing.subframe_residual(10.4 / 24.0, 24.0), 0.4)
        self.assertAlmostEqual(timing.subframe_residual(10.6 / 24.0, 24.0), -0.4)

    def test_frame_range_is_inclusive(self):
        self.assertEqual(timing.frame_range(1001, 1003), [1001, 1002, 1003])
        self.assertEqual(timing.frame_range(7, 7), [7])

    def test_frame_range_rejects_a_descending_range(self):
        self.assertRaises(ValueError, timing.frame_range, 1003, 1001)

    def test_offset_to_start_is_added_to_source_frames(self):
        offset = timing.offset_to_start(1001, 1)
        self.assertEqual(1001 + offset, 1)


class TestSchemaAcceptsValid(unittest.TestCase):

    def test_fixture_validates_clean(self):
        self.assertEqual(rbj.validate(valid_doc()), [])

    def test_keys_are_optional(self):
        doc = valid_doc()
        del doc["shapes"][0]["keys"]
        self.assertEqual(rbj.validate(doc), [])

    def test_per_point_feather_with_offsets_validates(self):
        doc = valid_doc()
        shape = doc["shapes"][0]
        shape["feather_model"] = "per_point"
        for rec in shape["frames"].values():
            for i, pt in enumerate(rec["points"]):
                pt["feather"] = 0.0 if i == 1 else -4.25
                pt["feather_offset"] = [1.0, 2.0]
        self.assertEqual(rbj.validate(doc), [])

    def test_an_unknown_member_is_ignored_not_rejected(self):
        doc = valid_doc()
        doc["shapes"][0]["invented_by_a_later_version"] = 7
        self.assertEqual(rbj.validate(doc), [])


class TestSchemaRejects(unittest.TestCase):
    """One test per hard failure in spec section 12.1."""

    def reject(self, mutate, expect):
        doc = valid_doc()
        mutate(doc)
        errs = rbj.validate(doc)
        self.assertTrue(errs, "expected a hard failure mentioning %r" % expect)
        joined = " | ".join(errs)
        self.assertIn(expect, joined,
                      "errors were: %s" % joined)

    def test_wrong_format(self):
        self.reject(lambda d: d.update(format="rotobrige"), "format is")

    def test_missing_version(self):
        self.reject(lambda d: d.pop("version"), "version is None")

    def test_future_version(self):
        self.reject(lambda d: d.update(version=99), "newer than this reader")

    def test_source_tool_version_must_be_a_non_empty_string(self):
        # Optional, but not optional-shaped: a member that is present and
        # empty says the writer tried to identify itself and failed, which is
        # exactly the case a bug report cannot afford to be vague about.
        self.reject(lambda d: d["source"].update(tool_version=""),
                    "tool_version")
        self.reject(lambda d: d["source"].update(tool_version=9),
                    "tool_version")

    def test_source_tool_version_may_be_absent(self):
        # Every file written before this member existed omits it, and they
        # stay legal: it identifies the writer, and nothing renders from it.
        doc = valid_doc()
        doc["source"].pop("tool_version", None)
        self.assertEqual(rbj.validate(doc), [])

    def test_missing_required_source_member(self):
        self.reject(lambda d: d["source"].pop("fps"), "missing fps")

    def test_zero_fps(self):
        self.reject(lambda d: d["source"].update(fps=0.0), "greater than zero")

    def test_non_finite_coordinate(self):
        def nan(d):
            d["shapes"][0]["frames"]["10"]["points"][0]["c"][1] = float("nan")
        self.reject(nan, "not finite")

    def test_descending_range(self):
        self.reject(lambda d: d.update(range=[11, 10]), "not ascending")

    def test_empty_shapes(self):
        self.reject(lambda d: d.update(shapes=[]), "shapes is empty")

    def test_missing_warnings(self):
        self.reject(lambda d: d.pop("warnings"), "warnings is None")

    def test_frames_gap(self):
        self.reject(lambda d: d["shapes"][0]["frames"].pop("11"), "missing 1 frame")

    def test_frames_beyond_range(self):
        def extra(d):
            frames = d["shapes"][0]["frames"]
            frames["12"] = copy.deepcopy(frames["11"])
        self.reject(extra, "outside range")

    def test_padded_frame_key(self):
        def padded(d):
            frames = d["shapes"][0]["frames"]
            frames["010"] = frames.pop("10")
        self.reject(padded, "not a plain decimal integer")

    def test_vertex_count_changes_across_frames(self):
        def drop(d):
            d["shapes"][0]["frames"]["11"]["points"].pop()
        self.reject(drop, "vertex count changes")

    def test_open_spline_in_a_v1_file(self):
        # spec/rbj-v2-draft.md section 3: v1 forbids open splines, and a file
        # claiming to be v1 is held to that whatever wrote it.
        self.reject(lambda d: d["shapes"][0].update(closed=False),
                    "needs version 2")

    def test_closed_is_not_a_boolean(self):
        self.reject(lambda d: d["shapes"][0].update(closed="yes"),
                    "expected a boolean")

    def test_unknown_blend(self):
        self.reject(lambda d: d["shapes"][0].update(blend="darken"), "blend is")

    def test_uniform_is_no_longer_a_feather_model(self):
        # spec section 14 departure 2: the value was removed at the freeze.
        self.reject(lambda d: d["shapes"][0].update(feather_model="uniform"),
                    "feather_model is")

    def test_unknown_falloff(self):
        self.reject(lambda d: d["shapes"][0].update(feather_falloff="gaussian"),
                    "feather_falloff is")

    def test_opacity_out_of_unit_range(self):
        self.reject(lambda d: d["shapes"][0]["frames"]["10"].update(opacity=1.5),
                    "expected 0.0 to 1.0")

    def test_missing_feather_uniform_on_a_frame(self):
        self.reject(lambda d: d["shapes"][0]["frames"]["10"].pop("feather_uniform"),
                    "missing feather_uniform")

    def test_missing_opacity_on_a_frame(self):
        self.reject(lambda d: d["shapes"][0]["frames"]["10"].pop("opacity"),
                    "missing opacity")

    def test_key_frame_absent_from_dense_layer(self):
        self.reject(lambda d: d["shapes"][0]["keys"][1].update(frame=99),
                    "no such frame in the dense layer")

    def test_keys_out_of_order(self):
        def swap(d):
            keys = d["shapes"][0]["keys"]
            keys[0], keys[1] = keys[1], keys[0]
        self.reject(swap, "not sorted ascending")

    def test_duplicate_key_frame(self):
        self.reject(lambda d: d["shapes"][0]["keys"][1].update(frame=10),
                    "duplicate key frame")

    def test_interp_missing_a_side(self):
        self.reject(lambda d: d["shapes"][0]["keys"][0]["interp"].pop("in"),
                    "in is None")

    def test_interp_as_a_bare_string(self):
        # The v4.2 shorthand. Rejecting it is what keeps readers branch-free.
        self.reject(lambda d: d["shapes"][0]["keys"][0].update(interp="linear"),
                    "expected an object with in and out")

    def test_unknown_interp_value(self):
        self.reject(lambda d: d["shapes"][0]["keys"][0]["interp"].update(out="bezier"),
                    "out is 'bezier'")

    def test_ease_on_a_side_that_is_not_eased(self):
        self.reject(lambda d: d["shapes"][0]["keys"][0]["ease"].update(**{"in": [0.5, 0.0]}),
                    "whose interp is 'linear'")

    def test_feather_present_under_model_none(self):
        def add(d):
            d["shapes"][0]["frames"]["10"]["points"][0]["feather"] = 0.0
        self.reject(add, "feather_model is 'none'")

    def test_feather_absent_under_model_per_point(self):
        self.reject(lambda d: d["shapes"][0].update(feather_model="per_point"),
                    "missing feather")

    def test_feather_offset_without_feather(self):
        def orphan(d):
            d["shapes"][0]["frames"]["10"]["points"][0]["feather_offset"] = [1.0, 2.0]
        self.reject(orphan, "feather_offset without feather")

    def test_a_broken_dense_layer_does_not_also_blame_every_key(self):
        # The one error that matters must not be buried under its consequences.
        doc = valid_doc()
        doc["shapes"][0]["frames"] = "not an object"
        errs = rbj.validate(doc)
        self.assertEqual([e for e in errs if "no such frame" in e], [])

    def test_key_errors_are_capped(self):
        doc = valid_doc()
        shape = doc["shapes"][0]
        shape["keys"] = [{"frame": 10, "interp": {"in": "linear", "out": "linear"}}
                         for _ in range(50)]
        errs = rbj.validate(doc)
        self.assertLess(len(errs), 12)
        self.assertIn("suppressed", " | ".join(errs))

    def test_interp_errors_are_capped_with_the_rest(self):
        # Interp problems are still key problems. Routing them around the cap
        # would let 50 bad keys bury the summary under 100 lines.
        doc = valid_doc()
        doc["shapes"][0]["keys"] = [
            {"frame": 10, "interp": {"in": "bezier", "out": "bezier"}}
            for _ in range(50)]
        errs = rbj.validate(doc)
        self.assertLess(len(errs), 12)
        self.assertIn("suppressed", " | ".join(errs))

    def test_a_shape_id_is_accepted_at_any_version(self):
        # Optional identity (spec/rbj-v3-draft.md section 5): stable across
        # re-exports where the name is a display label an artist can edit.
        doc = valid_doc()
        doc["shapes"][0]["id"] = "Roto1/tri"
        self.assertEqual(rbj.validate(doc), [])

    def test_a_blank_or_non_string_id_is_rejected(self):
        self.reject(lambda d: d["shapes"][0].update(id=""),
                    "id is ''")
        self.reject(lambda d: d["shapes"][0].update(id=7),
                    "expected a non-empty string")

    def test_duplicate_ids_are_rejected(self):
        # Uniqueness is the whole value of an id over a name; names may
        # collide (the exporter warns), ids may not.
        def twin(d):
            import copy as _copy
            other = _copy.deepcopy(d["shapes"][0])
            other["name"] = "tri 2"
            d["shapes"][0]["id"] = "Roto1/tri"
            other["id"] = "Roto1/tri"
            d["shapes"].append(other)
        self.reject(twin, "share the id")

    def test_pre_conform_keys_validate_like_keys(self):
        # Optional provenance (spec/rbj-v3-draft.md section 5): the authored
        # keys as they were before the exporter conformed them. Legal at any
        # version - a reader that ignores it loses nothing that renders.
        doc = valid_doc()
        doc["shapes"][0]["pre_conform_keys"] = json.loads(
            json.dumps(doc["shapes"][0]["keys"]))
        self.assertEqual(rbj.validate(doc), [])

    def test_malformed_pre_conform_keys_are_named(self):
        self.reject(
            lambda d: d["shapes"][0].update(
                pre_conform_keys=[{"frame": 10, "interp": "linear"}]),
            "pre_conform_keys")

    def test_null_pre_conform_keys_is_rejected(self):
        self.reject(lambda d: d["shapes"][0].update(pre_conform_keys=None),
                    "omit the member")

    def test_authored_frames_accepts_a_subset_and_accepts_empty(self):
        # Optional provenance (spec/rbj-v3-draft.md section 5.2): the frames
        # the artist keyed on the spline itself. Empty is the member's point -
        # a mask the artist never keyed, whose two file keys are both the
        # exporter's pinned endpoints.
        doc = valid_doc()
        doc["shapes"][0]["authored_frames"] = [10]
        self.assertEqual(rbj.validate(doc), [])
        doc["shapes"][0]["authored_frames"] = []
        self.assertEqual(rbj.validate(doc), [])

    def test_authored_frames_must_name_frames_the_file_can_deliver(self):
        # A frame outside the dense layer, or absent from keys, is one an
        # importer honouring the member would pin and then fail to find.
        self.reject(lambda d: d["shapes"][0].update(authored_frames=[12]),
                    "no such frame in the dense layer")
        self.reject(lambda d: (d["shapes"][0]["keys"].pop(0),
                               d["shapes"][0].update(authored_frames=[10])),
                    "not present in keys")

    def test_authored_frames_are_sorted_unique_integers(self):
        self.reject(lambda d: d["shapes"][0].update(authored_frames=[11, 10]),
                    "not sorted ascending")
        self.reject(lambda d: d["shapes"][0].update(authored_frames=[10, 10]),
                    "duplicate frame")
        self.reject(lambda d: d["shapes"][0].update(authored_frames=["10"]),
                    "expected an integer")

    def test_authored_attributes_validate_like_keys(self):
        # Optional provenance (spec/rbj-v3-draft.md section 5.3): the artist's
        # own keys on the per-frame attributes, in exactly the schema of
        # `keys` - values deliberately absent, the dense layer already has
        # them.
        doc = valid_doc()
        doc["shapes"][0]["authored_attributes"] = {
            "opacity": [{"frame": 10, "interp": {"in": "linear",
                                                 "out": "ease"},
                         "ease": {"out": [0.5, 0.0]}}],
            "feather_uniform": [{"frame": 11, "interp": {"in": "hold",
                                                         "out": "linear"}}],
        }
        self.assertEqual(rbj.validate(doc), [])

    def test_authored_attributes_reject_what_keys_would_reject(self):
        self.reject(
            lambda d: d["shapes"][0].update(authored_attributes={
                "opacity": [{"frame": 12,
                             "interp": {"in": "linear", "out": "linear"}}]}),
            "no such frame in the dense layer")
        self.reject(
            lambda d: d["shapes"][0].update(authored_attributes={
                "opacity": [{"frame": 10, "interp": "linear"}]}),
            "expected an object with in and out")

    def test_authored_attributes_reject_strangers_and_empties(self):
        self.reject(
            lambda d: d["shapes"][0].update(authored_attributes={
                "expansion": []}),
            "unexpected attribute")
        self.reject(
            lambda d: d["shapes"][0].update(authored_attributes={
                "opacity": []}),
            "omit the entry instead")
        self.reject(
            lambda d: d["shapes"][0].update(authored_attributes=[]),
            "expected an object")

    def test_an_empty_keys_array_is_refused(self):
        # A second spelling of "no sparse layer". It used to validate clean
        # and then crash the Nuke import's drift pass ("needs at least one
        # key") after the Roto node was already created; dense is spelled by
        # omitting the member.
        self.reject(lambda d: d["shapes"][0].update(keys=[]),
                    "keys is empty; omit the member instead")

    def test_a_null_attribute_entry_is_refused(self):
        # The null spelling used to slip through the gap between the empty
        # check and _validate_keys, which reads None as an absent member.
        self.reject(
            lambda d: d["shapes"][0].update(authored_attributes={
                "opacity": None}),
            "is null; omit the entry instead")

    def test_an_ease_influence_outside_the_fraction_is_refused(self):
        # Spec section 10.3 bounds influence to 0.0-1.0 of the segment. The
        # likeliest out-of-range value is an undivided After Effects
        # percentage, and dumps() must refuse it rather than write a file
        # whose ease silently clamps at the other end.
        self.reject(
            lambda d: d["shapes"][0]["keys"].__setitem__(0, {
                "frame": 10, "interp": {"in": "linear", "out": "ease"},
                "ease": {"out": [16.667, 0.0]}}),
            "influence is 16.667, expected 0.0 to 1.0")
        self.reject(
            lambda d: d["shapes"][0]["keys"].__setitem__(0, {
                "frame": 10, "interp": {"in": "ease", "out": "linear"},
                "ease": {"in": [-0.1, 0.0]}}),
            "influence is -0.1, expected 0.0 to 1.0")

    def test_an_integer_frames_key_is_an_error_not_a_crash(self):
        # Only the dumps() direction can produce one - JSON keys are always
        # strings - but that is exactly the direction adapters feed with
        # hand-built dicts, and validate() promises a list, never a raise.
        doc = valid_doc()
        doc["shapes"][0]["frames"][10] = doc["shapes"][0]["frames"].pop("10")
        errs = rbj.validate(doc)
        self.assertTrue(any("not a plain decimal integer" in e for e in errs),
                        errs)

    def test_an_invalid_document_names_the_shape(self):
        doc = valid_doc()
        doc["shapes"][0]["frames"]["11"]["points"].pop()
        errs = rbj.validate(doc)
        self.assertIn("'tri'", " | ".join(errs))


class TestFrameRefs(unittest.TestCase):
    """Version 3's dense-layer dedup (spec/rbj-v3-draft.md section 3).

    Roto is full of held spans, and a shape held over 1000 frames used to
    write 1000 identical frame objects. `fold_frames` turns a run of
    data-equal consecutive frames into {"same_as": head}; `loads` expands the
    references back, so everything downstream still sees a dense layer.
    """

    def held(self, count=6):
        """A shape holding one pose over `count` frames."""
        doc = valid_doc()
        shape = doc["shapes"][0]
        rec = shape["frames"]["10"]
        shape["frames"] = dict(
            (str(f), json.loads(json.dumps(rec))) for f in range(1, count + 1))
        shape["keys"] = None
        doc["range"] = [1, count]
        return doc

    def test_a_held_span_folds_to_references_and_costs_version_3(self):
        folded = rbj.fold_frames(self.held())
        frames = folded["shapes"][0]["frames"]
        self.assertEqual(frames["1"], self.held()["shapes"][0]["frames"]["1"])
        for f in range(2, 7):
            self.assertEqual(frames[str(f)], {"same_as": 1}, f)
        self.assertEqual(folded["version"], 3)

    def test_a_moving_shape_does_not_fold_and_stays_version_1(self):
        # Section 6.7's policy again: only the files that benefit pay the
        # compatibility cost.
        doc = valid_doc()
        folded = rbj.fold_frames(doc)
        self.assertEqual(folded, doc)
        self.assertEqual(folded["version"], 1)

    def test_loads_expands_what_fold_wrote(self):
        doc = self.held()
        back = rbj.loads(rbj.dumps(rbj.fold_frames(doc)))
        self.assertEqual(back["shapes"], doc["shapes"])
        self.assertEqual(back["version"], 3)

    def test_expansion_copies_so_frames_stay_independent(self):
        back = rbj.loads(rbj.dumps(rbj.fold_frames(self.held())))
        frames = back["shapes"][0]["frames"]
        frames["2"]["opacity"] = 0.25
        self.assertEqual(frames["1"]["opacity"], 1.0,
                         "editing an expanded frame edited its source")

    def test_fold_does_not_mutate_its_input(self):
        doc = self.held()
        rbj.fold_frames(doc)
        self.assertEqual(doc["version"], 1)
        self.assertNotIn("same_as", json.dumps(doc["shapes"]))

    def ref_doc(self, mutate=None):
        doc = rbj.fold_frames(self.held())
        if mutate:
            mutate(doc)
        return rbj.validate(doc)

    def test_a_reference_validates_at_version_3(self):
        self.assertEqual(self.ref_doc(), [])

    def test_a_reference_needs_version_3(self):
        errs = self.ref_doc(lambda d: d.update(version=1))
        self.assertIn("same_as needs version 3", " | ".join(errs))

    def test_a_reference_must_point_backward(self):
        def forward(d):
            d["shapes"][0]["frames"]["2"] = {"same_as": 3}
        errs = self.ref_doc(forward)
        self.assertIn("does not point at an earlier frame", " | ".join(errs))

    def test_a_reference_must_resolve(self):
        def dangling(d):
            d["shapes"][0]["frames"]["2"] = {"same_as": 0}
        errs = self.ref_doc(dangling)
        self.assertIn("not in the dense layer", " | ".join(errs))

    def test_references_do_not_chain(self):
        def chain(d):
            d["shapes"][0]["frames"]["3"] = {"same_as": 2}
        errs = self.ref_doc(chain)
        self.assertIn("itself a reference", " | ".join(errs))


class TestSerialization(unittest.TestCase):

    def test_dumps_then_loads_round_trips(self):
        doc = valid_doc()
        self.assertEqual(rbj.loads(rbj.dumps(doc)), doc)

    def test_dumps_refuses_to_write_an_invalid_document(self):
        doc = valid_doc()
        doc["shapes"][0]["closed"] = False
        self.assertRaises(rbj.RbjError, rbj.dumps, doc)

    def test_dumps_refuses_a_non_finite_number(self):
        doc = valid_doc()
        doc["shapes"][0]["frames"]["10"]["points"][0]["c"][0] = float("inf")
        self.assertRaises(rbj.RbjError, rbj.dumps, doc)

    def test_loads_rejects_the_nan_literal(self):
        text = rbj.dumps(valid_doc()).replace("[100.0, 200.0]", "[NaN, 200.0]")
        self.assertRaises(rbj.RbjError, rbj.loads, text)

    def test_loads_reports_every_problem_at_once(self):
        doc = valid_doc()
        doc["format"] = "wrong"
        doc["shapes"][0]["closed"] = False
        doc["shapes"][0]["blend"] = "darken"
        try:
            rbj.loads(json.dumps(doc))
        except rbj.RbjError as exc:
            self.assertGreaterEqual(len(exc.errors), 3)
        else:
            self.fail("expected RbjError")

    def test_numeric_arrays_stay_on_one_line(self):
        self.assertIn('"c": [100.0, 200.0]', rbj.dumps(valid_doc()))

    def test_error_message_lists_the_reasons(self):
        try:
            rbj.loads('{"format": "nope"}')
        except rbj.RbjError as exc:
            self.assertIn("format is", str(exc))


class TestGoldenSquare(unittest.TestCase):
    """The committed fixture is the thing Phase 2 will validate adapters against."""

    def setUp(self):
        with io.open(GOLDEN_SQUARE, encoding="utf-8") as handle:
            self.text = handle.read()

    def test_golden_square_validates(self):
        rbj.loads(self.text)

    def test_golden_square_is_byte_stable_through_a_reprint(self):
        doc = rbj.loads(self.text)
        self.assertEqual(rbj.dumps(doc) + "\n", self.text)

    def test_golden_square_corners_survive_a_trip_through_ae_space(self):
        doc = rbj.loads(self.text)
        height = doc["source"]["height"]
        for rec in doc["shapes"][0]["frames"].values():
            for pt in rec["points"]:
                there = geom.canonical_point_to_ae(pt, height)
                back = geom.ae_point_to_canonical(there, height)
                self.assertLess(math.hypot(back["c"][0] - pt["c"][0],
                                           back["c"][1] - pt["c"][1]), 0.1)

    def test_golden_square_dense_layer_covers_its_range(self):
        doc = rbj.loads(self.text)
        first, last = doc["range"]
        expected = set(str(f) for f in timing.frame_range(first, last))
        self.assertEqual(set(doc["shapes"][0]["frames"].keys()), expected)



class TestMatrixBake(unittest.TestCase):
    """core.geom's arithmetic; test_nuke_roundtrip.py checks it against Nuke."""

    # Row-major, translation in the last column, as list(CMatrix4) returns.
    TRANSLATE = [1, 0, 0, 200, 0, 1, 0, 50, 0, 0, 1, 0, 0, 0, 0, 1]
    SCALE = [2, 0, 0, 0, 0, 3, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]

    def test_translation_moves_a_point(self):
        self.assertEqual(geom.apply_matrix_point(self.TRANSLATE, [10.0, 20.0]),
                         [210.0, 70.0])

    def test_translation_leaves_a_tangent_alone(self):
        # The case that separates the two readings of a CVec3's third
        # component: a tangent must not pick up the translation.
        self.assertEqual(
            geom.apply_matrix_tangent(self.TRANSLATE, [10.0, 20.0], [5.0, -3.0]),
            [5.0, -3.0])

    def test_scale_applies_to_both_point_and_tangent(self):
        self.assertEqual(geom.apply_matrix_point(self.SCALE, [10.0, 20.0]),
                         [20.0, 60.0])
        self.assertEqual(
            geom.apply_matrix_tangent(self.SCALE, [10.0, 20.0], [5.0, -3.0]),
            [10.0, -9.0])

    def test_rotation_rotates_a_tangent(self):
        # 90 degrees counterclockwise, with a translation that must not leak in.
        rot = [0, -1, 0, 17, 1, 0, 0, -4, 0, 0, 1, 0, 0, 0, 0, 1]
        out = geom.apply_matrix_tangent(rot, [3.0, 7.0], [1.0, 0.0])
        self.assertAlmostEqual(out[0], 0.0)
        self.assertAlmostEqual(out[1], 1.0)


class TestFeatherNormals(unittest.TestCase):

    CCW = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]

    def test_signed_area_sign_follows_winding(self):
        self.assertGreater(geom.signed_area(self.CCW), 0.0)
        self.assertLess(geom.signed_area(list(reversed(self.CCW))), 0.0)

    def test_normals_point_away_from_the_interior(self):
        centre = [5.0, 5.0]
        for points in (self.CCW, list(reversed(self.CCW))):
            for p, n in zip(points, geom.outward_normals(points)):
                # Outward means the normal has a positive component along the
                # direction from the centroid to the vertex.
                away = [p[0] - centre[0], p[1] - centre[1]]
                self.assertGreater(away[0] * n[0] + away[1] * n[1], 0.0,
                                   "normal %r at %r points inward" % (n, p))

    def test_normals_are_unit_length(self):
        for n in geom.outward_normals(self.CCW):
            self.assertAlmostEqual(math.hypot(n[0], n[1]), 1.0)

    def test_a_degenerate_vertex_gets_a_zero_normal(self):
        # Neighbours coincide, so there is no path direction to rotate.
        points = [[0.0, 0.0], [5.0, 5.0], [0.0, 0.0], [10.0, 0.0]]
        self.assertEqual(geom.outward_normals(points)[1], [0.0, 0.0])

    def test_feather_scalar_is_signed_not_a_magnitude(self):
        normal = [1.0, 0.0]
        self.assertEqual(geom.feather_scalar([4.0, 0.0], normal), 4.0)
        self.assertEqual(geom.feather_scalar([-4.0, 0.0], normal), -4.0)

    def test_feather_round_trips_along_the_normal(self):
        normal = [0.6, 0.8]
        for scalar in (12.5, 0.0, -7.25):
            offset = geom.feather_vector(scalar, normal)
            self.assertAlmostEqual(geom.feather_scalar(offset, normal), scalar)

    def test_a_tangential_component_is_what_the_scalar_loses(self):
        normal = [1.0, 0.0]
        offset = [3.0, 4.0]
        self.assertEqual(geom.feather_scalar(offset, normal), 3.0)
        self.assertAlmostEqual(geom.off_normal_angle(offset, normal),
                               math.degrees(math.atan2(4.0, 3.0)))

    def test_an_on_normal_offset_raises_no_angle(self):
        self.assertAlmostEqual(geom.off_normal_angle([5.0, 0.0], [1.0, 0.0]), 0.0)

    def test_a_zero_offset_never_looks_off_normal(self):
        # Otherwise every corner point of an unfeathered shape would warn.
        self.assertEqual(geom.off_normal_angle([0.0, 0.0], [1.0, 0.0]), 0.0)


class TestOpenSplines(unittest.TestCase):
    """spec/rbj-v2-draft.md. v1 is unchanged and still forbids these."""

    def open_doc(self):
        doc = valid_doc()
        doc["version"] = rbj.VERSION_OPEN_SPLINES
        doc["shapes"][0]["closed"] = False
        return doc

    def test_an_open_shape_validates_at_version_2(self):
        self.assertEqual(rbj.validate(self.open_doc()), [])

    def test_version_for_stamps_1_when_every_shape_is_closed(self):
        # The bump is a property of the file, not of the writer: a v2 exporter
        # with nothing open to say still writes a file a v1 reader can open.
        self.assertEqual(rbj.version_for(valid_doc()["shapes"]), 1)

    def test_version_for_stamps_2_when_any_shape_is_open(self):
        shapes = valid_doc()["shapes"] + self.open_doc()["shapes"]
        self.assertEqual(rbj.version_for(shapes), 2)

    def test_an_open_document_round_trips_through_the_writer(self):
        doc = self.open_doc()
        self.assertEqual(rbj.loads(rbj.dumps(doc)), doc)

    def test_the_endpoint_normal_uses_its_one_neighbour(self):
        # Interior vertices take the chord between neighbours; an endpoint has
        # no such chord, so it takes the chord to the vertex it does have. On a
        # horizontal polyline every normal is therefore the same vertical.
        line = [[0.0, 0.0], [10.0, 0.0], [20.0, 0.0], [30.0, 0.0]]
        normals = geom.outward_normals(line, closed=False)
        for n in normals:
            self.assertAlmostEqual(abs(n[1]), 1.0)
            self.assertAlmostEqual(n[0], 0.0)
        self.assertEqual(normals[0], normals[-1])

    def test_closing_the_path_moves_the_endpoint_normals(self):
        # The wraparound the closed rule uses is wrong for a polyline, which is
        # the bug this parameter exists to fix rather than a stylistic choice.
        square = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]
        closed = geom.outward_normals(square, closed=True)
        opened = geom.outward_normals(square, closed=False)
        self.assertNotEqual(closed[0], opened[0])
        self.assertNotEqual(closed[-1], opened[-1])
        self.assertEqual(closed[1:-1], opened[1:-1])

    def test_open_normals_are_unit_length(self):
        square = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]
        for n in geom.outward_normals(square, closed=False):
            self.assertAlmostEqual(math.hypot(n[0], n[1]), 1.0)

    def test_feather_still_round_trips_on_an_open_path(self):
        # Whatever "outward" means on a path with no inside, the rule is one
        # rule and both directions run it, so a Nuke-to-Nuke open spline keeps
        # its feather exactly. That is the guarantee section 4 of the draft
        # makes; the sign's meaning across applications is the part it does not.
        line = [[0.0, 0.0], [10.0, 5.0], [25.0, 5.0], [30.0, 0.0]]
        normals = geom.outward_normals(line, closed=False)
        for scalar, normal in zip((3.0, -8.5, 0.0, 12.0), normals):
            offset = geom.feather_vector(scalar, normal)
            self.assertAlmostEqual(geom.feather_scalar(offset, normal), scalar)

    def test_the_open_sign_does_not_flip_on_a_perturbation(self):
        # The reason the open rule does not use the signed area. A near-straight
        # polyline encloses almost nothing, so the area's sign turns over on a
        # nudge - and on a moving shape that would flip every feather direction
        # between one frame and the next.
        def line(bow):
            return [[0.0, 0.0], [10.0, bow], [20.0, 0.0], [30.0, -bow]]

        first = geom.outward_normals(line(1e-9), closed=False)
        second = geom.outward_normals(line(-1e-9), closed=False)
        for a, b in zip(first, second):
            self.assertGreater(a[0] * b[0] + a[1] * b[1], 0.0,
                               "the normal turned over: %r against %r" % (a, b))
        # And the area really does change sign across those two, so the test is
        # about the rule rather than about the fixture being too tame.
        self.assertLess(geom.signed_area(line(1e-9))
                        * geom.signed_area(line(-1e-9)), 0.0)

    def test_closed_defaults_to_the_closed_rule(self):
        # Every existing caller passes no flag and must not change behaviour.
        square = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]
        self.assertEqual(geom.outward_normals(square),
                         geom.outward_normals(square, closed=True))


class TestAnchoredFeather(unittest.TestCase):
    """spec/rbj-v2-draft.md section 6. The schema half.

    `anchored` exists because After Effects puts feather anchors mid-segment
    and can put two on one segment, which no per-point member can hold. These
    tests are about the file being able to say that; whether an exporter
    chooses to is section 6.7 and lives with the exporter.
    """

    def anchored_doc(self, *anchors):
        """The valid three-point triangle, with its feather layer moved."""
        doc = valid_doc()
        doc["version"] = rbj.VERSION_ANCHORED_FEATHER
        shape = doc["shapes"][0]
        shape["feather_model"] = "anchored"
        entries = list(anchors) or [{"t": 0.25, "feather": 30.0},
                                    {"t": 2.5, "feather": -15.0}]
        for frame in shape["frames"].values():
            frame["feather_points"] = [dict(e) for e in entries]
        return doc

    def reject(self, doc, expect):
        errs = rbj.validate(doc)
        self.assertTrue(errs, "expected a hard failure mentioning %r" % expect)
        self.assertIn(expect, " | ".join(errs), "errors were: %s" % errs)

    def test_an_anchored_shape_validates_at_version_2(self):
        self.assertEqual(rbj.validate(self.anchored_doc()), [])

    def test_two_anchors_on_one_segment_are_legal(self):
        # The case that decided the whole design: run 3 read two feather points
        # on one segment of a seven-vertex shape, and no per-point field can
        # hold two values for one point.
        self.assertEqual(rbj.validate(self.anchored_doc(
            {"t": 1.25, "feather": 30.0},
            {"t": 1.75, "feather": -15.0})), [])

    def test_an_anchored_document_round_trips_through_the_writer(self):
        doc = self.anchored_doc()
        self.assertEqual(rbj.loads(rbj.dumps(doc)), doc)

    def test_anchored_needs_version_2(self):
        doc = self.anchored_doc()
        doc["version"] = 1
        self.reject(doc, "needs version 2")

    def test_version_for_stamps_2_on_an_anchored_shape(self):
        self.assertEqual(rbj.version_for(self.anchored_doc()["shapes"]), 2)

    def test_version_for_leaves_per_point_at_1(self):
        # Section 6.7: the compatibility cost is paid only by the files that
        # were being damaged. A vertex-anchored file is still a v1 file.
        doc = valid_doc()
        doc["shapes"][0]["feather_model"] = "per_point"
        for frame in doc["shapes"][0]["frames"].values():
            for pt in frame["points"]:
                pt["feather"] = 4.0
        self.assertEqual(rbj.version_for(doc["shapes"]), 1)
        self.assertEqual(rbj.validate(doc), [])

    def test_a_point_may_not_carry_feather_under_anchored(self):
        doc = self.anchored_doc()
        doc["shapes"][0]["frames"]["10"]["points"][0]["feather"] = 3.0
        self.reject(doc, "two places to look is one too many")

    def test_a_frame_must_carry_feather_points_under_anchored(self):
        doc = self.anchored_doc()
        del doc["shapes"][0]["frames"]["11"]["feather_points"]
        self.reject(doc, "missing feather_points")

    def test_feather_points_are_forbidden_under_per_point(self):
        doc = valid_doc()
        doc["shapes"][0]["feather_model"] = "per_point"
        for frame in doc["shapes"][0]["frames"].values():
            for pt in frame["points"]:
                pt["feather"] = 4.0
            frame["feather_points"] = [{"t": 0.5, "feather": 1.0}]
        self.reject(doc, "not 'anchored'")

    def test_feather_points_are_forbidden_under_none(self):
        doc = valid_doc()
        doc["shapes"][0]["frames"]["10"]["feather_points"] = []
        self.reject(doc, "not 'anchored'")

    def test_the_count_must_not_change_between_frames(self):
        doc = self.anchored_doc()
        doc["shapes"][0]["frames"]["11"]["feather_points"].pop()
        self.reject(doc, "feather_points count changes across frames")

    def test_the_count_error_names_both_frames(self):
        doc = self.anchored_doc()
        doc["shapes"][0]["frames"]["11"]["feather_points"].pop()
        joined = " | ".join(rbj.validate(doc))
        self.assertIn("2 at frame 10", joined)
        self.assertIn("1 at frame 11", joined)

    def test_zero_anchors_is_a_legal_count(self):
        # Section 6.3 says so, and adds that such a shape should be `none`
        # instead. "Should" is section 2 advice to a writer, not a rule a
        # reader may reject a file over.
        doc = self.anchored_doc()
        for frame in doc["shapes"][0]["frames"].values():
            frame["feather_points"] = []
        self.assertEqual(rbj.validate(doc), [])

    def test_t_at_the_vertex_count_is_out_of_range_on_a_closed_shape(self):
        # Section 6.4: t = n names the same anchor as t = 0 and must be
        # written as 0, so the upper bound is exclusive.
        self.reject(self.anchored_doc({"t": 3.0, "feather": 1.0}),
                    "expected 0 to 3")

    def test_t_just_below_the_vertex_count_is_in_range(self):
        self.assertEqual(
            rbj.validate(self.anchored_doc({"t": 2.999, "feather": 1.0})), [])

    def test_t_at_the_last_vertex_is_in_range_on_an_open_shape(self):
        # One segment fewer, and the path genuinely ends on its last vertex,
        # so there the bound is inclusive.
        doc = self.anchored_doc({"t": 2.0, "feather": 1.0})
        doc["shapes"][0]["closed"] = False
        self.assertEqual(rbj.validate(doc), [])

    def test_t_past_the_last_vertex_is_out_of_range_on_an_open_shape(self):
        doc = self.anchored_doc({"t": 2.5, "feather": 1.0})
        doc["shapes"][0]["closed"] = False
        self.reject(doc, "expected 0 to 2")

    def test_a_negative_t_is_out_of_range(self):
        self.reject(self.anchored_doc({"t": -0.5, "feather": 1.0}),
                    "expected 0 to 3")

    def test_anchors_must_be_ordered_by_t_ascending(self):
        self.reject(self.anchored_doc({"t": 2.5, "feather": 1.0},
                                      {"t": 0.5, "feather": 2.0}),
                    "ordered by t ascending")

    def test_equal_t_values_are_not_a_disorder(self):
        # Ascending, not strictly ascending: two anchors at one vertex is the
        # per-point case that section 6.1 says v1 cannot express, and it is
        # exactly what `anchored` is for.
        self.assertEqual(rbj.validate(self.anchored_doc(
            {"t": 1.0, "feather": 12.0},
            {"t": 1.0, "feather": 0.0})), [])

    def test_an_anchor_needs_a_t(self):
        self.reject(self.anchored_doc({"feather": 1.0}), "missing t")

    def test_an_anchor_needs_a_feather(self):
        self.reject(self.anchored_doc({"t": 1.0}), "missing feather")

    def test_an_anchor_may_carry_a_feather_offset(self):
        self.assertEqual(rbj.validate(self.anchored_doc(
            {"t": 1.5, "feather": 4.0, "feather_offset": [1.0, -2.0]})), [])

    def test_a_malformed_feather_offset_is_caught(self):
        self.reject(self.anchored_doc(
            {"t": 1.5, "feather": 4.0, "feather_offset": [1.0]}),
            "expected a two-element array")

    def test_a_non_finite_t_is_caught(self):
        self.reject(self.anchored_doc({"t": float("inf"), "feather": 1.0}),
                    "not finite")

    def test_feather_points_must_be_an_array(self):
        doc = self.anchored_doc()
        doc["shapes"][0]["frames"]["10"]["feather_points"] = {"t": 1.0}
        self.reject(doc, "expected an array")

    def test_a_zero_radius_anchor_is_authored_not_absent(self):
        # Section 6.3 and v1 section 11.1. The golden scene depends on it: the
        # `feathered` mask pins a corner to zero width on purpose, and the v1
        # snap discarded exactly that value.
        self.assertEqual(rbj.validate(self.anchored_doc(
            {"t": 1.5, "feather": 12.0},
            {"t": 3.0 - 1e-9, "feather": 0.0})), [])


class TestGoldenNukeExport(unittest.TestCase):
    """A real Nuke export, validated with no Nuke present.

    Acceptance criterion 12: golden .rbj files validate both importers without
    the other application. This one was produced by test_nuke_roundtrip.py
    against Nuke 17.1v1 and carries every field v1 has - baked transform,
    per-point feather with a deliberately off-normal point, animated opacity
    and animated uniform feather.
    """

    def setUp(self):
        with io.open(GOLDEN_ROUNDTRIP, encoding="utf-8") as handle:
            self.doc = rbj.loads(handle.read())

    def test_it_validates(self):
        self.assertEqual(rbj.validate(self.doc), [])

    def test_it_carries_both_layers(self):
        shape = self.doc["shapes"][0]
        first, last = self.doc["range"]
        self.assertEqual(len(shape["frames"]), last - first + 1)
        # The fixture is keyed on every frame, so the union is every frame.
        self.assertEqual([k["frame"] for k in shape["keys"]],
                         list(range(first, last + 1)))

    def test_it_carries_signed_per_point_feather(self):
        shape = self.doc["shapes"][0]
        self.assertEqual(shape["feather_model"], "per_point")
        feathers = [p["feather"] for p in shape["frames"][str(self.doc["range"][0])]["points"]]
        self.assertTrue(any(f < 0 for f in feathers),
                        "the fixture has an inward feather point; sign was lost")

    def test_it_records_the_off_normal_warning(self):
        # The fixture has one point whose feather is deliberately tangential.
        self.assertTrue(any("normal" in w for w in self.doc["warnings"]),
                        "an off-normal feather offset should warn on export")

    def test_uniform_feather_animates_across_frames(self):
        shape = self.doc["shapes"][0]
        first, last = self.doc["range"]
        self.assertNotEqual(shape["frames"][str(first)]["feather_uniform"],
                            shape["frames"][str(last)]["feather_uniform"])

    def test_opacity_animates_across_frames(self):
        shape = self.doc["shapes"][0]
        first, last = self.doc["range"]
        self.assertNotEqual(shape["frames"][str(first)]["opacity"],
                            shape["frames"][str(last)]["opacity"])


class TestInterpFromNuke(unittest.TestCase):
    """Nuke key types to .rbj sides (spec section 10.1)."""

    def test_step_freezes_what_it_leaves_and_curves_what_it_arrives_on(self):
        # Case 63: a step key moved eval(75) to the key value and left eval(25)
        # at 0.6759, the CUBIC default, where an exact linear reads 0.4898. So
        # the arriving segment is not straight and must not say it is - this
        # read `linear` until 2026-08-22, and the incoming side of every
        # Nuke-authored hold was a line nobody drew.
        self.assertEqual(interp.sides_from_nuke(interp.NUKE_STEP),
                         {"in": "ease", "out": "hold"})

    def test_linear_is_both_sides(self):
        self.assertEqual(interp.sides_from_nuke(interp.NUKE_LINEAR),
                         {"in": "linear", "out": "linear"})

    def test_cubic_is_ease_both_sides(self):
        self.assertEqual(interp.sides_from_nuke(interp.NUKE_CUBIC),
                         {"in": "ease", "out": "ease"})

    def test_the_unset_sentinel_reads_as_cubic(self):
        # 256 is what a fresh key reports, and case 63 measured it evaluating
        # identically to cubic. Reporting it as anything else would make an
        # untouched Nuke shape claim an interpolation it does not have.
        self.assertEqual(interp.sides_from_nuke(interp.NUKE_UNSET),
                         interp.sides_from_nuke(interp.NUKE_CUBIC))

    def test_unidentified_types_degrade_to_ease(self):
        # Case 63 swept the field and found 4 and 5 evaluating to neither
        # linear nor cubic. "Smooth, parameters unknown" is the honest report.
        for key_type in (-1, 4, 5):
            self.assertEqual(interp.sides_from_nuke(key_type),
                             {"in": "ease", "out": "ease"})

    def test_constants_carry_the_plus_one_offset(self):
        # The whole point of the module owning these: prd.md section 9.2 and
        # every adapter must never write a bare InterpolationType value.
        self.assertEqual((interp.NUKE_STEP, interp.NUKE_LINEAR,
                          interp.NUKE_CUBIC), (1, 2, 3))


class TestInterpReduce(unittest.TestCase):
    """Many per-axis votes down to the one .rbj key (tier 1 vs tier 2)."""

    def test_unanimous_votes_survive_intact(self):
        votes = [{"in": "linear", "out": "linear"}] * 12
        sides, mixed = interp.reduce_sides(votes)
        self.assertEqual(sides, {"in": "linear", "out": "linear"})
        self.assertFalse(mixed)

    def test_disagreement_degrades_that_side_only(self):
        votes = [{"in": "linear", "out": "hold"},
                 {"in": "linear", "out": "ease"}]
        sides, mixed = interp.reduce_sides(votes)
        self.assertEqual(sides, {"in": "linear", "out": "ease"})
        self.assertTrue(mixed, "an out-side disagreement is the tier-2 case")

    def test_no_votes_is_unknown_not_mixed(self):
        # A key frame with no control point keyed on it - a transform key, or
        # a range endpoint the export pins. Nothing was collapsed.
        sides, mixed = interp.reduce_sides([])
        self.assertEqual(sides, {"in": "ease", "out": "ease"})
        self.assertFalse(mixed)


class TestInterpToNuke(unittest.TestCase):
    """.rbj sides back to the one type a Nuke key can hold."""

    def test_hold_out_becomes_step(self):
        self.assertEqual(interp.to_nuke({"in": "linear", "out": "hold"})[0],
                         interp.NUKE_STEP)

    def test_a_straight_arrival_into_a_hold_is_not_exact(self):
        # The measurement, in one assertion. Nuke's step draws the segment
        # arriving at it as a cubic with a flat handle, so a file asking for a
        # straight one does not get it: `mixed` frames 16-17 of ae_scene.rbj
        # land 2.55 px and 2.05 px off the bake with nothing correcting them,
        # about 8% of that segment's travel. The drift pass buys it back; this
        # flag is what makes the import say so.
        self.assertEqual(interp.to_nuke({"in": "linear", "out": "hold"}),
                         (interp.NUKE_STEP, False))

    def test_a_curved_or_flat_arrival_into_a_hold_is_exact(self):
        # `ease` is "smooth, parameters unknown" (spec section 10.3), which is
        # what a flat-handled cubic is, and `hold` arriving is that same flat
        # handle named. Both are what Nuke actually draws, so neither warns -
        # which is what keeps a Nuke-authored step silent on the way home.
        self.assertEqual(interp.to_nuke({"in": "ease", "out": "hold"}),
                         (interp.NUKE_STEP, True))
        self.assertEqual(interp.to_nuke({"in": "hold", "out": "hold"}),
                         (interp.NUKE_STEP, True))

    def test_linear_both_sides_becomes_linear(self):
        self.assertEqual(interp.to_nuke({"in": "linear", "out": "linear"}),
                         (interp.NUKE_LINEAR, True))

    def test_ease_both_sides_becomes_cubic(self):
        self.assertEqual(interp.to_nuke({"in": "ease", "out": "ease"}),
                         (interp.NUKE_CUBIC, True))

    def test_an_asymmetric_key_collapses_and_says_so(self):
        # After Effects can hold in=LINEAR out=BEZIER on one key; Nuke cannot.
        # The flag is what makes the importer warn instead of silently fitting.
        key_type, exact = interp.to_nuke({"in": "linear", "out": "ease"})
        self.assertEqual(key_type, interp.NUKE_CUBIC)
        self.assertFalse(exact)

    def test_hold_arriving_alone_collapses(self):
        # A flat arriving handle with a live outgoing one has no Nuke form:
        # step would freeze the segment this key leaves, which is not asked for.
        key_type, exact = interp.to_nuke({"in": "hold", "out": "linear"})
        self.assertEqual(key_type, interp.NUKE_CUBIC)
        self.assertFalse(exact)

    def test_nuke_to_rbj_to_nuke_is_the_identity_on_nuke_types(self):
        for key_type in (interp.NUKE_STEP, interp.NUKE_LINEAR,
                         interp.NUKE_CUBIC):
            back, exact = interp.to_nuke(interp.sides_from_nuke(key_type))
            self.assertEqual(back, key_type)
            self.assertTrue(exact)


class FakeHost(object):
    """A destination that interpolates linearly between the keys it holds.

    Truth is a parabola, which straight segments cannot follow, so the
    deviation is real, largest mid-gap, and shrinks as keys are added - the
    same shape as the error a real host produces when the interpolation
    translation was not exact.
    """

    def __init__(self, truth):
        self.truth = truth
        self.applied = None
        self.applications = 0

    def apply_keys(self, key_frames):
        self.applied = list(key_frames)
        self.applications += 1

    def evaluate(self, frame):
        keys = self.applied
        if frame <= keys[0]:
            return self.truth(keys[0])
        if frame >= keys[-1]:
            return self.truth(keys[-1])
        for a, b in zip(keys, keys[1:]):
            if a <= frame <= b:
                t = (frame - a) / float(b - a)
                return self.truth(a) + t * (self.truth(b) - self.truth(a))
        raise AssertionError("frame %r outside the key span" % frame)

    def measure(self, frame):
        return abs(self.evaluate(frame) - self.truth(frame))


def parabola(frame):
    return (frame - 1.0) ** 2 / 10.0


class TestDriftGaps(unittest.TestCase):

    def test_runs_are_maximal_and_ordered(self):
        self.assertEqual(drift.gaps([1, 2, 3, 4, 5, 6], [1, 4, 6]),
                         [[2, 3], [5]])

    def test_no_keys_is_one_run(self):
        self.assertEqual(drift.gaps([1, 2, 3], []), [[1, 2, 3]])

    def test_every_frame_keyed_is_no_runs(self):
        self.assertEqual(drift.gaps([1, 2, 3], [1, 2, 3]), [])

    def test_leading_and_trailing_runs_are_kept(self):
        # Keys need not bracket the range: a shape keyed at 10 and 20 inside a
        # range of 1 to 30 has drift to measure on both outsides.
        self.assertEqual(drift.gaps([1, 2, 3, 4], [3]), [[1, 2], [4]])


class TestDriftCorrect(unittest.TestCase):

    def setUp(self):
        self.frames = list(range(1, 42))
        self.host = FakeHost(parabola)

    def run_correct(self, keys, tolerance, max_passes=8):
        return drift.correct(self.frames, keys, self.host.apply_keys,
                             self.host.measure, tolerance, max_passes)

    def test_it_converges_within_tolerance(self):
        keys, worst, _ = self.run_correct([1, 41], 0.5)
        self.assertLessEqual(worst, 0.5)
        for frame in self.frames:
            if frame not in keys:
                self.assertLessEqual(self.host.measure(frame), 0.5)

    def test_authored_keys_always_survive(self):
        authored = [1, 12, 41]
        keys, _, _ = self.run_correct(authored, 0.5)
        for frame in authored:
            self.assertIn(frame, keys)

    def test_it_lands_far_short_of_dense(self):
        # The point of the tier: bounded error without keying every frame.
        keys, _, _ = self.run_correct([1, 41], 0.5)
        self.assertLess(len(keys), len(self.frames))

    def test_a_tighter_tolerance_costs_more_keys(self):
        loose, _, _ = self.run_correct([1, 41], 2.0)
        self.host = FakeHost(parabola)
        tight, _, _ = self.run_correct([1, 41], 0.1)
        self.assertGreater(len(tight), len(loose))

    def test_the_host_holds_exactly_what_is_returned(self):
        keys, _, _ = self.run_correct([1, 41], 0.5)
        self.assertEqual(self.host.applied, keys)

    def test_the_host_holds_the_returned_keys_when_passes_run_out(self):
        # The invariant that matters most: a caller never has to guess whether
        # the destination is one pass behind the list it was handed.
        keys, worst, _ = self.run_correct([1, 41], 0.001, max_passes=1)
        self.assertEqual(self.host.applied, keys)
        self.assertGreater(worst, 0.001, "one pass cannot reach this tolerance")

    def test_an_exhausted_run_still_reports_the_truth(self):
        keys, worst, at = self.run_correct([1, 41], 0.001, max_passes=2)
        residual = max(self.host.measure(f) for f in self.frames
                       if f not in keys)
        self.assertAlmostEqual(worst, residual, places=9)
        self.assertAlmostEqual(self.host.measure(at), worst, places=9)
        self.assertNotIn(at, keys)

    def test_infinite_tolerance_adds_nothing(self):
        # prd.md section 8's "authored keys only" mode.
        keys, _, _ = self.run_correct([1, 12, 41], float("inf"))
        self.assertEqual(keys, [1, 12, 41])
        self.assertEqual(self.host.applications, 1)

    def test_zero_tolerance_is_the_dense_path(self):
        keys, worst, at = self.run_correct([1, 41], 0.0)
        self.assertEqual(keys, self.frames)
        self.assertEqual(worst, 0.0)
        self.assertIsNone(at, "no frame is unkeyed in dense mode")
        self.assertEqual(self.host.applied, self.frames)
        self.assertEqual(self.host.applications, 1,
                         "dense mode must not run a measuring pass")

    def test_keys_outside_the_range_are_dropped(self):
        keys, _, _ = self.run_correct([1, 41, 500], float("inf"))
        self.assertEqual(keys, [1, 41])

    def test_no_key_inside_the_range_raises(self):
        with self.assertRaises(ValueError):
            self.run_correct([500], 0.5)

    def test_an_empty_frame_range_raises(self):
        with self.assertRaises(ValueError):
            drift.correct([], [1], self.host.apply_keys, self.host.measure, 0.5)

    def test_a_host_that_already_agrees_is_left_alone(self):
        exact = FakeHost(lambda f: 3.0 * f)
        keys, worst, _ = drift.correct(self.frames, [1, 41], exact.apply_keys,
                                       exact.measure, 0.5)
        self.assertEqual(keys, [1, 41])
        self.assertEqual(worst, 0.0)


class HoldingHost(object):
    """A destination whose outgoing side at `held` freezes the rest of its gap.

    The parabola fixture puts a gap's worst frame in its middle, which is the
    easy case. This is the hard one: past `held` the destination stops while the
    dense layer keeps moving, so the deviation climbs steadily and the worst
    frame of the gap is always its **last**. A key there shortens the run
    instead of splitting it, which is the degeneracy `drift._survey` guards.

    Not synthetic - an outgoing `hold` behaves exactly this way whenever an
    ancestor transform moves the geometry through the held interval, because
    `.rbj` keys describe canonical space with that transform already baked in
    (`HANDOFF.md`, "A `hold` can contradict its own dense layer").
    """

    def __init__(self, truth, held):
        self.truth = truth
        self.held = held
        self.applied = None

    def apply_keys(self, key_frames):
        self.applied = list(key_frames)

    def evaluate(self, frame):
        keys = self.applied
        if frame <= keys[0]:
            return self.truth(keys[0])
        if frame >= keys[-1]:
            return self.truth(keys[-1])
        for a, b in zip(keys, keys[1:]):
            if a <= frame <= b:
                if a == self.held:
                    return self.truth(a)
                t = (frame - a) / float(b - a)
                return self.truth(a) + t * (self.truth(b) - self.truth(a))
        raise AssertionError("frame %r outside the key span" % frame)

    def measure(self, frame):
        return abs(self.evaluate(frame) - self.truth(frame))


class TestDriftOverAMonotoneGap(unittest.TestCase):
    """The gap whose worst frame is its own end, which bisection has to notice.

    Before `_survey` added the midpoint this walked backwards one frame per
    pass and ran out of them: against `test/golden/held_over_moving_layer.rbj`
    it landed corrective keys on 16 through 23 and left 60.0000 px at frame 15,
    which is the failure the After Effects import reported in the host.
    """

    def setUp(self):
        self.frames = list(range(0, 25))
        # Steady motion, so the deviation inside the held gap is proportional to
        # the distance from the hold and its maximum is always the gap's end.
        self.host = HoldingHost(lambda f: 20.0 * f, held=12)

    def run_correct(self, tolerance=0.5, max_passes=8):
        return drift.correct(self.frames, [0, 12, 24], self.host.apply_keys,
                             self.host.measure, tolerance, max_passes)

    def test_it_converges_instead_of_running_out_of_passes(self):
        _, worst, _ = self.run_correct()
        self.assertLessEqual(worst, 0.5)

    def test_it_does_not_walk_backwards_from_the_end_of_the_gap(self):
        keys, _, _ = self.run_correct()
        corrective = [f for f in keys if f not in (0, 12, 24)]
        self.assertLess(len(corrective), 8,
                        "one key per pass is the degenerate walk, not a split")
        # The midpoint that splits the gap is `_survey`'s doing and is asserted
        # against `_survey` directly below. It is deliberately not asserted
        # here: splitting the run is how the pass converges, but once it has,
        # `_sweep` hands back whatever the split turned out not to need, and on
        # this gap a single key does the whole job.
        self.assertLessEqual(len(corrective), 3,
                             "the split converges, then the sweep gives back")

    def test_every_unkeyed_frame_really_is_within_tolerance(self):
        keys, _, _ = self.run_correct()
        for frame in self.frames:
            if frame not in keys:
                self.assertLessEqual(self.host.measure(frame), 0.5)

    def test_the_worst_frame_is_still_pinned(self):
        # The midpoint is added as well as the worst frame, never instead of
        # it, so this can only cost passes that the old behaviour also paid.
        self.host.apply_keys([0, 12, 24])
        additions, _, _ = drift._survey(self.frames, [0, 12, 24],
                                        self.host.measure, 0.5)
        self.assertIn(23, additions, "the worst frame of the held gap")
        self.assertIn(18, additions, "and the midpoint that splits it")

    def test_an_interior_worst_frame_is_left_alone(self):
        # The parabola case must not start paying for the degenerate one.
        host = FakeHost(parabola)
        frames = list(range(1, 42))
        host.apply_keys([1, 41])
        additions, _, at = drift._survey(frames, [1, 41], host.measure, 0.5)
        self.assertEqual(additions, [at])


class TestSweep(unittest.TestCase):
    """`_sweep`: bisection overshoots, and this hands the overshoot back.

    The pass pins a gap's worst frame and the gap's midpoint together, and the
    midpoint is usually redundant the moment the worst frame lands beside it.
    Nothing in the loop revisits that, so the result converged above the floor
    - 9 keys where 4 held the shape on `held_over_moving_layer.rbj`, measured
    against an exact minimum in `test/probe/probe_key_minimality.py`.

    What it must never do is take back a key the caller asked for. Those are
    the artist's, and the count is not the only thing read off a curve: an
    authored key is an edit handle and a statement of intent, a corrective one
    is neither.
    """

    def straight(self, keys, authored, tolerance=0.5):
        # A straight line, so any key set at all reproduces it exactly and
        # every removal is admissible on the geometry. What survives is then
        # purely a statement about the policy.
        frames = list(range(0, 11))
        host = FakeHost(lambda f: 10.0 * f)
        got = drift._sweep(frames, keys, set(authored), host.apply_keys,
                           host.measure, tolerance)
        return got, host

    def test_it_gives_back_a_key_the_fit_does_not_need(self):
        got, _ = self.straight([0, 5, 10], authored=[0, 10])
        self.assertEqual(got, [0, 10])

    def test_it_never_removes_an_authored_key(self):
        got, _ = self.straight([0, 5, 10], authored=[0, 5, 10])
        self.assertEqual(got, [0, 5, 10])

    def test_it_keeps_an_authored_key_between_corrective_ones(self):
        got, _ = self.straight([0, 2, 5, 8, 10], authored=[0, 5, 10])
        self.assertEqual(got, [0, 5, 10])

    def test_it_keeps_an_end_the_geometry_still_needs(self):
        # Dropping an end truncates the keyed span, and both hosts hold the
        # nearest key's value beyond it. On a moving line that hold is exactly
        # the drift the window past the surviving neighbour measures, so the
        # end stays.
        got, _ = self.straight([0, 5, 10], authored=[5])
        self.assertEqual(got, [0, 5, 10])

    def flat(self, keys, authored, tolerance=0.5):
        # A constant, so the hold beyond any truncated span is exact and every
        # removal is admissible. What survives is again purely the policy.
        frames = list(range(0, 11))
        host = FakeHost(lambda f: 7.0)
        got = drift._sweep(frames, keys, set(authored), host.apply_keys,
                           host.measure, tolerance)
        return got, host

    def test_it_gives_back_an_end_nothing_needs(self):
        got, _ = self.flat([0, 5, 10], authored=[5])
        self.assertEqual(got, [5])

    def test_one_key_always_survives(self):
        # A destination cannot hold a shape with no keys at all; saying which
        # one key means is the adapter's call, not this function's.
        got, _ = self.flat([0, 5, 10], authored=[])
        self.assertEqual(len(got), 1)

    def test_an_authored_end_survives_even_when_nothing_needs_it(self):
        got, _ = self.flat([0, 5, 10], authored=[0, 10])
        self.assertEqual(got, [0, 10])

    def test_it_keeps_an_end_that_pins_a_flat_tail(self):
        # Flat up to 5, then a ramp the keys cannot see: the far end holds the
        # ramp's last value, so the near end of the flat stretch still matters.
        frames = list(range(0, 11))
        host = FakeHost(lambda f: 10.0 * max(f - 5, 0))
        got = drift._sweep(frames, [0, 5, 10], set(), host.apply_keys,
                           host.measure, 0.5)
        self.assertEqual(got, [5, 10])

    def test_correct_passes_authored_through_to_the_sweep(self):
        # The importer's case: the file names the artist's own frames, and the
        # seeds it does not name - an exporter's pinned endpoints - come home
        # only if the geometry needs them.
        frames = list(range(0, 11))
        host = FakeHost(lambda f: 7.0)
        keys, worst, _ = drift.correct(frames, [0, 5, 10], host.apply_keys,
                                       host.measure, 0.5, authored=[5])
        self.assertEqual(keys, [5])
        self.assertEqual(worst, 0.0)
        self.assertEqual(host.applied, keys)

    def test_the_destination_holds_exactly_what_is_returned(self):
        # The sweep applies each trial in order to measure it, so the last
        # thing it touched is not necessarily what it kept. `correct` promises
        # the host holds the keys it returns.
        frames = list(range(0, 25))
        host = HoldingHost(lambda f: 20.0 * f, held=12)
        keys, _, _ = drift.correct(frames, [0, 12, 24], host.apply_keys,
                                   host.measure, 0.5)
        self.assertEqual(host.applied, keys)

    def test_it_re_applies_after_a_rejected_last_trial(self):
        # The case the sweep gets wrong if it only re-applies when it changed
        # something: every candidate can be refused, and the host is then left
        # holding the last refusal - one key short of the answer, silently.
        # A parabola at 0.3 px lands enough neighbouring keys for the last one
        # tried to be one that has to stay.
        frames = list(range(1, 22))
        host = FakeHost(parabola)
        keys, _, _ = drift.correct(frames, [1, 21], host.apply_keys,
                                   host.measure, 0.3)
        self.assertEqual(host.applied, keys)

    def test_what_it_keeps_still_holds_every_frame(self):
        frames = list(range(0, 25))
        host = HoldingHost(lambda f: 20.0 * f, held=12)
        keys, worst, _ = drift.correct(frames, [0, 12, 24], host.apply_keys,
                                       host.measure, 0.5)
        self.assertLessEqual(worst, 0.5)
        for frame in frames:
            if frame not in keys:
                self.assertLessEqual(host.measure(frame), 0.5, "frame %d" % frame)

    def test_a_pass_that_ran_out_is_not_swept(self):
        # A `worst` above tolerance means the fit is still short of keys.
        # Giving any back there would make it worse, and would report a state
        # the host does not hold.
        frames = list(range(1, 42))
        host = FakeHost(parabola)
        keys, worst, _ = drift.correct(frames, [1, 41], host.apply_keys,
                                       host.measure, 0.5, max_passes=1)
        self.assertGreater(worst, 0.5)
        self.assertEqual(host.applied, keys)


class TestGoldenStaticEase(unittest.TestCase):
    """The run that answered whether `.rbj` ease reproduces AE's own curve.

    Two masks on a solid that does not move, exported and reimported in After
    Effects on 2026-08-21. The reimport returned **0 corrective keys and
    0.0000 px** on both, which is the measurement: an `ease` key with real
    parameters rebuilds its dense layer exactly.

    Every other AE fixture in this project sits on a scaled, rotating layer
    whose transform is baked into the points, so its corrective-key counts
    measure the rotation rather than the interpolation - `eased` in
    `ae_scene.rbj` needed 20 keys and that said nothing about ease at all. This
    file exists to have no transform to argue about.

    What the tests below protect is the part that makes the host result
    meaningful. A 0.0000 px reimport is only evidence if the dense layer was
    genuinely curved and the ease genuinely non-default; a fixture flattened by
    some later edit would still report 0.0000 px and prove nothing.
    """

    def setUp(self):
        handle = open(GOLDEN_STATIC_EASE)
        try:
            self.doc = json.loads(handle.read())
        finally:
            handle.close()
        self.shapes = dict((s["name"], s) for s in self.doc["shapes"])

    def test_it_validates(self):
        self.assertEqual(rbj.validate(self.doc), [])

    def test_it_is_a_version_1_file(self):
        # Nothing here is open, and the writer emits the lowest version that
        # expresses the file (spec/rbj-v2-draft.md section 2). A v2-capable
        # exporter stamping 2 on everything would fail this.
        self.assertEqual(self.doc["version"], 1)

    def test_the_eased_shape_carries_real_parameters(self):
        # Not AE's 16.667 default in disguise, which is what a bare `ease`
        # picks up when it crosses applications.
        for key in self.shapes["eased_static"]["keys"]:
            self.assertEqual(key["interp"], {"in": "ease", "out": "ease"})
            self.assertAlmostEqual(key["ease"]["in"][0], 0.91176, places=5)
            self.assertAlmostEqual(key["ease"]["out"][0], 0.33333, places=5)

    def test_the_linear_shape_claims_no_ease_parameters(self):
        for key in self.shapes["linear_static"]["keys"]:
            self.assertEqual(key["interp"], {"in": "linear", "out": "linear"})
            self.assertNotIn("ease", key)

    def bow_off_the_chord(self, name):
        """How far the dense layer departs a straight line between its keys."""
        shape = self.shapes[name]
        frames = shape["frames"]
        keys = [k["frame"] for k in shape["keys"]]
        worst = 0.0
        for a, b in zip(keys, keys[1:]):
            first = [p["c"] for p in frames[str(a)]["points"]]
            last = [p["c"] for p in frames[str(b)]["points"]]
            for frame in range(a + 1, b):
                t = (frame - a) / float(b - a)
                here = [p["c"] for p in frames[str(frame)]["points"]]
                for ca, cb, cf in zip(first, last, here):
                    for axis in (0, 1):
                        straight = ca[axis] + (cb[axis] - ca[axis]) * t
                        worst = max(worst, abs(straight - cf[axis]))
        return worst

    def test_the_eased_dense_layer_is_genuinely_curved(self):
        # 135 px of signal against a 0.5 px tolerance. Without this the host's
        # 0.0000 px reimport would be consistent with the ease being ignored.
        self.assertGreater(self.bow_off_the_chord("eased_static"), 100.0)

    def test_the_linear_dense_layer_is_genuinely_straight(self):
        # The calibration, and the guard on the fixture: it reimported with
        # zero corrective keys, which only means anything because a straight
        # line is what it should be. If a later edit puts these masks back on
        # the rotating solid, this fails rather than quietly lying.
        self.assertLess(self.bow_off_the_chord("linear_static"), 0.001)


class TestGoldenAeScene(unittest.TestCase):
    """The six-shape After Effects export, validated with no host present.

    Nothing read this file until 2026-08-22. It is the largest host artefact in
    the project and the only v2 one - an anchored feather and an open spline in
    the same document - and every reference to it anywhere in the tree was a
    comment. Acceptance criterion 12 says a golden validates without the other
    application present; this one never had.

    What it pins is what a bad re-export produces, because re-exporting it is a
    by-hand run on another machine (`test/probe/README.md`, "Re-exporting the
    scene golden"): the wrong layer selected, a stale deployment, a fixture
    that moved. All three write a plausible file.
    """

    def setUp(self):
        with io.open(GOLDEN_SCENE, encoding="utf-8") as handle:
            self.doc = rbj.loads(handle.read())

    def test_it_validates(self):
        self.assertEqual(rbj.validate(self.doc), [])

    def test_it_is_the_six_shape_fixture(self):
        # `setup_ae_scene.jsx` builds two solids and the export takes whichever
        # layers are selected, so the commonest bad re-export is the OTHER
        # solid: two shapes called eased_static and linear_static, which is a
        # legal file and not this one. It has happened.
        self.assertEqual([s["name"] for s in self.doc["shapes"]],
                         ["linear", "eased", "mixed", "feathered", "offgrid",
                          "opened"])
        self.assertEqual(self.doc["source"]["app"], "After Effects")
        self.assertEqual(self.doc["range"], [0, 24])

    def test_the_declared_version_is_the_one_its_shapes_force(self):
        # Asked of `version_for` rather than hardcoded. Two writers decide the
        # version by one shared rule, and a file whose declared version
        # disagrees with its own contents is exactly what that rule exists to
        # prevent - a v1 reader either refusing a file it could open or
        # accepting one it cannot.
        self.assertEqual(self.doc["version"],
                         rbj.version_for(self.doc["shapes"]))
        self.assertEqual(self.doc["version"], rbj.VERSION_ANCHORED_FEATHER)

    def test_one_shape_is_open_and_one_is_anchored(self):
        # The two features that put this file past v1, and the reason it is
        # worth having at all. Either one silently reverting leaves a legal
        # file that no longer exercises what it was committed for.
        self.assertEqual([s["name"] for s in self.doc["shapes"]
                          if not s["closed"]], ["opened"])
        self.assertEqual([s["name"] for s in self.doc["shapes"]
                          if s["feather_model"] == "anchored"], ["feathered"])

    def test_the_conform_left_no_ease_anywhere(self):
        # The exporter rewrites every eased side as linear before it writes
        # (prd.md section 9.1 step 6a), so an `ease` block in an After Effects
        # file means the conform did not run. That is what a deployment one
        # commit behind looks like from here, and it needs no host to see.
        for shape in self.doc["shapes"]:
            for key in shape["keys"]:
                self.assertNotIn("ease", key,
                                 "%s frame %s" % (shape["name"], key["frame"]))

    def test_the_dense_layer_covers_every_frame_of_every_shape(self):
        first, last = self.doc["range"]
        for shape in self.doc["shapes"]:
            self.assertEqual(sorted(int(f) for f in shape["frames"]),
                             list(range(first, last + 1)), shape["name"])

    def test_the_feather_anchors_are_where_the_fixture_put_them(self):
        # `setup_ae_scene.jsx` authors featherSegLocs [0, 0, 2, 3] against
        # featherRelSegLocs [0.25, 0.75, 0.5, 0], which is `seg + rel` of 0.25,
        # 0.75, 2.5 and 3.0, with radii [30, -15, 12, 0]. Checked on every
        # frame: the anchors hold still relative to the path here, and a set
        # that starts sliding is a different fixture with different costs
        # downstream (spec/rbj-v2-draft.md section 6.5).
        shape = [s for s in self.doc["shapes"]
                 if s["name"] == "feathered"][0]
        for key, record in shape["frames"].items():
            anchors = sorted(record["feather_points"], key=lambda a: a["t"])
            self.assertEqual([a["t"] for a in anchors],
                             [0.25, 0.75, 2.5, 3.0], "frame %s" % key)
            self.assertEqual([a["feather"] for a in anchors],
                             [30.0, -15.0, 12.0, 0.0], "frame %s" % key)


class TestGoldenAeSceneViaNuke(unittest.TestCase):
    """What Nuke writes after reading an After Effects file, with no host.

    `test/test_ae_crossapp.js` covers Nuke -> AE at the document level. This is
    the other direction's artefact: `ae_scene.rbj` imported into Nuke at
    tolerance inf and exported straight back out, by `test_ae_to_nuke.py`. Held
    against its own source, so the questions it answers are about the crossing
    rather than about a number someone wrote down.

    It sat in `golden/` from 2026-08-21 to 2026-08-22 referenced by nothing and
    regenerated by nothing, by which point it was 286 px of geometry away from
    what the same pipeline produced - the conform, the anchored re-export and
    the step-key fix had all landed under it. A derived file nobody reads is
    not evidence, it is a claim with no date on it.
    """

    def setUp(self):
        with io.open(GOLDEN_VIA_NUKE, encoding="utf-8") as handle:
            self.doc = rbj.loads(handle.read())
        with io.open(GOLDEN_SCENE, encoding="utf-8") as handle:
            self.source = rbj.loads(handle.read())

    def test_it_validates(self):
        self.assertEqual(rbj.validate(self.doc), [])

    def test_nothing_was_lost_crossing(self):
        self.assertEqual(self.doc["source"]["app"], "Nuke")
        self.assertEqual([s["name"] for s in self.doc["shapes"]],
                         [s["name"] for s in self.source["shapes"]])
        self.assertEqual(self.doc["range"], self.source["range"])

    def test_every_authored_key_survived(self):
        # Acceptance criterion 3, which until now could only be read off a
        # Nuke report. The import that produced this ran at tolerance inf, so
        # the drift pass added nothing and the key list is the sparse layer
        # itself - a corrective key here would be a key the file did not have.
        for after, before in zip(self.doc["shapes"], self.source["shapes"]):
            self.assertEqual([k["frame"] for k in after["keys"]],
                             [k["frame"] for k in before["keys"]],
                             after["name"])

    def test_the_open_spline_came_back_open(self):
        opened = [s for s in self.doc["shapes"] if s["name"] == "opened"][0]
        self.assertFalse(opened["closed"])
        self.assertEqual(self.doc["version"], rbj.VERSION_OPEN_SPLINES)

    def test_the_anchored_feather_arrived_as_vertices(self):
        # spec/rbj-v2-draft.md section 6.5: Nuke can only anchor feather at a
        # vertex, so the importer splits the segment and the shape comes back
        # with more points than the artist drew. Counted from the source
        # rather than hardcoded - one per anchor that is genuinely
        # mid-segment, and the two sitting on a vertex cost nothing.
        before = [s for s in self.source["shapes"]
                  if s["name"] == "feathered"][0]
        after = [s for s in self.doc["shapes"]
                 if s["name"] == "feathered"][0]
        self.assertEqual(before["feather_model"], "anchored")
        self.assertEqual(after["feather_model"], "per_point")
        anchors = before["frames"]["0"]["feather_points"]
        mid = [a for a in anchors if a["t"] != int(a["t"])]
        self.assertEqual(len(after["frames"]["0"]["points"]),
                         len(before["frames"]["0"]["points"]) + len(mid))

    def test_nuke_writes_no_ease_parameters_but_does_spell_a_step_key(self):
        # The Phase 3 decision: nothing on the Nuke side calibrates influence
        # and speed, so a Nuke source never writes an `ease` block. It does
        # write the *word*, on one side of one key - a step key flattens its
        # own incoming tangent, so `mixed`'s hold arrives as {ease, hold} and
        # not the {linear, hold} this project claimed until 2026-08-22.
        asymmetric = []
        for shape in self.doc["shapes"]:
            for key in shape["keys"]:
                self.assertNotIn("ease", key, shape["name"])
                if key["interp"]["in"] != key["interp"]["out"]:
                    asymmetric.append((shape["name"], key["frame"],
                                       key["interp"]))
        self.assertEqual(asymmetric,
                         [("mixed", 18, {"in": "ease", "out": "hold"})])


class TestUiEntryPoints(unittest.TestCase):
    """The menu item and the panel name code that exists.

    Both entry points are strings pointing at functions: `nuke/menu.py` names
    its commands as source to exec, and `ae/rotobridge_panel.jsx` names the two
    adapter files to evaluate. Neither is reachable by the suites - `nuke.menu`
    raises "not in GUI mode" under `--nc -t` (measured 2026-08-22), and nothing
    here models ScriptUI - so a renamed function or file breaks the UI silently
    and only on an artist's machine.

    What is checkable with no host is the wiring, and that is the half that
    rots. The behaviour behind it is the adapters', which are tested.
    """

    def commands(self):
        """The script string of every `addCommand` in `nuke/menu.py`."""
        with io.open(os.path.join(NUKE_DIR, "menu.py"),
                     encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), "menu.py")
        out = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) \
                    and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "addCommand":
                # (label, source-to-exec)
                out.append(node.args[1].value)
        return out

    def test_the_menu_registers_both_directions(self):
        found = self.commands()
        self.assertTrue(any("export" in c for c in found), found)
        self.assertTrue(any("import" in c for c in found), found)

    def test_the_menu_offers_an_about_entry(self):
        # Load-bearing, not decoration. Every dialog RotoBridge raises names
        # the build, but a tester asked which build they are on has nowhere to
        # look when no dialog is open: After Effects has the panel footer and
        # Nuke has nothing else.
        self.assertTrue(any("about" in c for c in self.commands()),
                        self.commands())

    def test_every_menu_command_names_a_function_that_exists(self):
        for source in self.commands():
            # "import rotobridge_export; rotobridge_export.main()"
            match = re.match(r"^import (\w+); \1\.(\w+)\(\)$", source)
            self.assertTrue(match, "unrecognised command form: %r" % source)
            module, function = match.group(1), match.group(2)
            path = os.path.join(NUKE_DIR, module + ".py")
            self.assertTrue(os.path.exists(path), path)
            with io.open(path, encoding="utf-8") as handle:
                names = [n.name for n in ast.walk(ast.parse(handle.read(), path))
                         if isinstance(n, ast.FunctionDef)]
            self.assertIn(function, names, "%s.%s" % (module, function))

    def test_the_panel_names_adapters_that_exist(self):
        with io.open(os.path.join(AE, "rotobridge_panel.jsx"),
                     encoding="utf-8") as handle:
            text = handle.read()
        named = re.findall(r'"(rotobridge_\w+\.jsx)"', text)
        self.assertEqual(sorted(set(named)),
                         ["rotobridge_export.jsx", "rotobridge_import.jsx"])
        for name in named:
            self.assertTrue(os.path.exists(os.path.join(AE_LIB, name)), name)

    def test_the_panel_looks_where_the_drop_puts_the_adapters(self):
        # Three places name the same subfolder and none of them can see the
        # others: the repo has `ae/lib`, `tools/package.sh` stages
        # `after_effects/lib`, and the panel searches `LIB`. Disagreement
        # between them is invisible until an artist clicks a button and
        # nothing happens, which is the least debuggable bug report this
        # project can receive from someone else's machine.
        with io.open(os.path.join(AE, "rotobridge_panel.jsx"),
                     encoding="utf-8") as handle:
            found = re.search(r'var LIB = "([^"]+)";', handle.read())
        self.assertIsNotNone(found, "the panel has no LIB constant")
        self.assertEqual(found.group(1), os.path.basename(AE_LIB))

        with io.open(os.path.join(REPO, "tools", "package.sh"),
                     encoding="utf-8") as handle:
            packager = handle.read()
        self.assertIn('after_effects/%s' % found.group(1), packager)


    def test_the_installer_carries_the_whole_payload(self):
        # `ae/install.jsx` lists what it copies; an adapter added to `ae/lib`
        # without touching that list would fail as a missing file on the
        # artist's machine only, after the download.
        with io.open(os.path.join(AE, "install.jsx"),
                     encoding="utf-8") as handle:
            text = handle.read()
        listed = set(re.findall(r'"(rotobridge_\w+\.jsx)"', text))
        on_disk = set(name for name in os.listdir(AE_LIB)
                      if name.endswith(".jsx"))
        on_disk.add("rotobridge_panel.jsx")
        self.assertEqual(listed, on_disk)

        found = re.search(r'var LIB = "([^"]+)";', text)
        self.assertIsNotNone(found, "the installer has no LIB constant")
        self.assertEqual(found.group(1), os.path.basename(AE_LIB))

    def test_the_installer_can_read_the_version_it_reports(self):
        # The installer greps `var VERSION = "..."` out of the panel instead
        # of carrying a fourth copy for `tools/bump_version.py` to rewrite.
        # This is the same expression it uses, applied to the same file.
        with io.open(os.path.join(AE, "install.jsx"),
                     encoding="utf-8") as handle:
            self.assertIn('match(/var VERSION = "([0-9.]+)"/)', handle.read())
        with io.open(os.path.join(AE, "rotobridge_panel.jsx"),
                     encoding="utf-8") as handle:
            found = re.search(r'var VERSION = "([0-9.]+)"', handle.read())
        self.assertIsNotNone(found, "the panel has no VERSION the installer"
                             " could read")
        self.assertEqual(found.group(1), version.VERSION)

    def test_the_drop_stages_the_installer_beside_its_payload(self):
        # The installer copies whatever sits next to it, so the stage must
        # put it at the top of `after_effects/`, not in a subfolder.
        with io.open(os.path.join(REPO, "tools", "package.sh"),
                     encoding="utf-8") as handle:
            packager = handle.read()
        self.assertIn(
            'cp ae/install.jsx "${STAGE}/after_effects/'
            'Install for After Effects.jsx"', packager)


class TestGoldenSparseExport(unittest.TestCase):
    """A real Nuke export of a shape keyed on five frames out of forty-one.

    The point of committing it: the sparse layer is the part of the format that
    exists for the artist rather than for the geometry, and it can be checked
    with no host present. If the exporter ever starts writing a key per frame
    again, this fails without needing a licence to notice.
    """

    def setUp(self):
        with io.open(GOLDEN_SPARSE, encoding="utf-8") as handle:
            self.doc = rbj.loads(handle.read())

    def test_it_validates(self):
        self.assertEqual(rbj.validate(self.doc), [])

    def test_the_sparse_layer_is_actually_sparse(self):
        shape = self.doc["shapes"][0]
        first, last = self.doc["range"]
        self.assertEqual(len(shape["frames"]), last - first + 1)
        self.assertEqual([k["frame"] for k in shape["keys"]],
                         [1, 11, 21, 31, 41])

    def test_explicitly_linear_nuke_keys_stay_linear(self):
        # Tier 1. Anything else here means the key type read back wrong, and
        # the whole sparse path degrades to ease plus corrective keys.
        for key in self.doc["shapes"][0]["keys"]:
            self.assertEqual(key["interp"], {"in": "linear", "out": "linear"})

    def test_no_key_claims_ease_parameters(self):
        # The Phase 3 decision: a Nuke source never writes `ease`, because
        # nothing on that side calibrates influence and speed against AE.
        for key in self.doc["shapes"][0]["keys"]:
            self.assertNotIn("ease", key)

    def test_the_dense_layer_moves_between_the_keys(self):
        # If it did not, the fixture would prove nothing about interpolation.
        shape = self.doc["shapes"][0]
        at_one = shape["frames"]["1"]["points"][0]["c"]
        at_six = shape["frames"]["6"]["points"][0]["c"]
        self.assertNotEqual(at_one, at_six)


class TestInterpAe(unittest.TestCase):
    """After Effects key types and ease parameters, spec section 10.1 and 10.3.

    One type per side on both sides of this mapping, so every case here is
    exact. That is the whole reason the AE direction has no tiers.
    """

    def test_the_three_types_map_one_to_one(self):
        self.assertEqual(interp.side_from_ae(interp.AE_HOLD), "hold")
        self.assertEqual(interp.side_from_ae(interp.AE_LINEAR), "linear")
        self.assertEqual(interp.side_from_ae(interp.AE_BEZIER), "ease")

    def test_linear_is_the_lowest_constant(self):
        # Read off the host in probe runs 2 and 4. The menu presents them in
        # the other order, so this is the easy one to invert from memory.
        self.assertEqual((interp.AE_LINEAR, interp.AE_BEZIER, interp.AE_HOLD),
                         (6612, 6613, 6614))

    def test_an_unknown_type_degrades_to_ease(self):
        # Not an error: bare `ease` means "smooth, parameters unknown, rely on
        # the drift pass", which is true of a type we cannot name.
        self.assertEqual(interp.side_from_ae(9999), "ease")

    def test_every_side_round_trips(self):
        for side in ("hold", "linear", "ease"):
            self.assertEqual(interp.side_from_ae(interp.side_to_ae(side)), side)

    def test_influence_is_a_percentage_going_out(self):
        # Run 6 read the first real authored ease off a mask: 91.176 in.
        self.assertEqual(interp.ease_from_ae(91.176, 0.0), [0.91176, 0.0])

    def test_speed_is_not_scaled(self):
        # Influence normalises across control points; speed does not, because
        # each point travels a different distance between two keys.
        self.assertEqual(interp.ease_from_ae(50.0, 1.5)[1], 1.5)

    def test_the_default_influence_survives_a_round_trip(self):
        pair = interp.ease_from_ae(interp.AE_DEFAULT_INFLUENCE, 0.0)
        influence, speed = interp.ease_to_ae(pair)
        self.assertAlmostEqual(influence, interp.AE_DEFAULT_INFLUENCE, places=9)
        self.assertEqual(speed, 0.0)

    def test_zero_influence_clamps_rather_than_raising_in_the_host(self):
        # Spec section 10.3 allows 0.0; After Effects does not accept it.
        influence, _ = interp.ease_to_ae([0.0, 0.0])
        self.assertEqual(influence, 0.1)

    def test_influence_above_the_range_clamps_too(self):
        influence, _ = interp.ease_to_ae([2.0, 0.0])
        self.assertEqual(influence, 100.0)


class TestFeatherPointSnapping(unittest.TestCase):
    """prd.md section 9.3, driven by probe run 3's real mask.

    Four feather points on a seven-vertex shape: three mid-segment, two on the
    same segment, one with a radius of exactly zero. Every branch of the rule
    is in that one reading, which is why it is the fixture.
    """

    RUN3 = dict(seg_locs=[3, 6, 1, 3],
                rel_locs=[0.9029, 0.9715, 0.0975, 1.0],
                radii=[89.5565, 0.0, -46.6171, -1e-8],
                vertex_count=7)

    def snap(self, **over):
        args = dict(self.RUN3)
        args.update(over)
        return geom.snap_feather_points(args["seg_locs"], args["rel_locs"],
                                        args["radii"], args["vertex_count"])

    def test_it_returns_one_scalar_per_vertex(self):
        self.assertEqual(len(self.snap()["feather"]), 7)

    def test_run_three_lands_where_it_should(self):
        self.assertEqual(self.snap()["feather"],
                         [0.0, -46.6171, 0.0, 0.0, 89.5565, 0.0, 0.0])

    def test_a_late_point_snaps_forward(self):
        # rel 0.9029 on segment 3 is nearer vertex 4 than vertex 3.
        got = geom.snap_feather_points([3], [0.9029], [5.0], 7)
        self.assertEqual(got["feather"][4], 5.0)

    def test_an_early_point_snaps_back(self):
        got = geom.snap_feather_points([3], [0.0975], [5.0], 7)
        self.assertEqual(got["feather"][3], 5.0)

    def test_the_last_segment_wraps_to_the_first_vertex(self):
        # Segment 6 of a seven-vertex closed shape ends at vertex 0, not 7.
        got = geom.snap_feather_points([6], [0.9715], [5.0], 7)
        self.assertEqual(got["feather"][0], 5.0)

    def test_a_point_already_on_a_vertex_is_not_reported_as_snapped(self):
        # rel 0.0 is the segment's start vertex exactly, and 1.0 its end.
        self.assertEqual(geom.snap_feather_points([2], [0.0], [1.0], 7)["snapped"], [])
        self.assertEqual(geom.snap_feather_points([2], [1.0], [1.0], 7)["snapped"], [])

    def test_mid_segment_points_are_reported(self):
        self.assertEqual(self.snap()["snapped"], [0, 1, 2])

    def test_a_collision_keeps_the_larger_magnitude(self):
        dropped = self.snap()["dropped"]
        self.assertEqual(len(dropped), 1)
        self.assertEqual(dropped[0]["index"], 3)
        self.assertEqual(dropped[0]["vertex"], 4)
        self.assertEqual(dropped[0]["kept"], 89.5565)

    def test_magnitude_decides_regardless_of_sign(self):
        # A large inward point beats a small outward one.
        got = geom.snap_feather_points([0, 0], [0.0, 0.0], [3.0, -9.0], 4)
        self.assertEqual(got["feather"][0], -9.0)

    def test_a_tie_leaves_the_first_point_holding_the_vertex(self):
        # Otherwise the result would depend on the order the host read them in.
        got = geom.snap_feather_points([0, 0], [0.0, 0.0], [4.0, -4.0], 4)
        self.assertEqual(got["feather"][0], 4.0)
        self.assertEqual(got["dropped"][0]["index"], 1)

    def test_a_zero_radius_point_competes_on_equal_terms(self):
        # It pins the feather back to zero width and is load-bearing; it is not
        # treated as an absent point.
        got = geom.snap_feather_points([0], [0.0], [0.0], 4)
        self.assertEqual(got["dropped"], [])
        self.assertEqual(got["feather"], [0.0, 0.0, 0.0, 0.0])

    def test_no_points_leaves_every_vertex_at_zero(self):
        got = geom.snap_feather_points([], [], [], 5)
        self.assertEqual(got["feather"], [0.0] * 5)
        self.assertEqual(got["snapped"], [])
        self.assertEqual(got["dropped"], [])


class TestFeatherAnchors(unittest.TestCase):
    """spec/rbj-v2-draft.md section 6.4, the lossless reading of run 3's data.

    `TestFeatherPointSnapping` covers what v1 does with the same input. These
    are the same vectors, kept side by side deliberately: the pair is the
    measurement of what section 6 is worth.
    """

    def test_the_run_3_shape_keeps_every_anchor_where_it_was(self):
        # Four points on a seven-vertex mask: three mid-segment, two on the
        # same segment, one radius of exactly zero. v1 moves the radius-12
        # anchor 150 px to reach vertex 3 and discards the authored zero.
        anchors = geom.feather_anchors([0, 0, 2, 3], [0.25, 0.75, 0.5, 0.0],
                                       [30.0, -15.0, 12.0, 0.0], 7)
        self.assertEqual(anchors, [{"t": 0.25, "feather": 30.0},
                                   {"t": 0.75, "feather": -15.0},
                                   {"t": 2.5, "feather": 12.0},
                                   {"t": 3.0, "feather": 0.0}])

    def test_two_anchors_on_one_segment_both_survive(self):
        # The pair v1 has to drop one of, because no per-point member can hold
        # two values for one point.
        anchors = geom.feather_anchors([2, 2], [0.25, 0.75], [8.0, -3.0], 5)
        self.assertEqual([a["t"] for a in anchors], [2.25, 2.75])

    def test_t_is_the_segment_plus_the_fraction(self):
        self.assertEqual(geom.feather_anchors([3], [0.5], [1.0], 8)[0]["t"],
                         3.5)

    def test_the_wraparound_spelling_of_a_vertex_is_the_same_anchor(self):
        # After Effects renames a point written at (i, 0) to (i-1, 1). Both
        # spellings must produce one t, or the same authored shape exports as
        # two different files depending on when it was read.
        at_start = geom.feather_anchors([4], [0.0], [5.0], 7)
        as_renamed = geom.feather_anchors([3], [1.0], [5.0], 7)
        self.assertEqual(at_start, as_renamed)

    def test_the_last_segment_end_wraps_to_zero_on_a_closed_shape(self):
        # Section 6.4: t = n names the same anchor as t = 0 and must be
        # written as 0, which is also what the validator enforces.
        anchors = geom.feather_anchors([6], [1.0], [5.0], 7)
        self.assertEqual(anchors[0]["t"], 0.0)

    def test_an_open_shape_does_not_wrap(self):
        # It has one segment fewer and genuinely ends on its last vertex, so
        # t = n - 1 is a real position rather than another name for 0.
        anchors = geom.feather_anchors([5], [1.0], [5.0], 7, closed=False)
        self.assertEqual(anchors[0]["t"], 6.0)

    def test_the_result_is_ordered_by_t_ascending(self):
        # The host regroups its arrays by feather type when the shape is read
        # between keyframes, so read order is not ascending and cannot be
        # relied on. Section 6.3 requires ascending.
        anchors = geom.feather_anchors([4, 0, 2], [0.5, 0.5, 0.5],
                                       [1.0, 2.0, 3.0], 6)
        self.assertEqual([a["t"] for a in anchors], [0.5, 2.5, 4.5])

    def test_read_order_does_not_change_the_file(self):
        # Same anchors, host arrays grouped the other way. Re-exporting one
        # scene must not produce a different file.
        first = geom.feather_anchors([0, 2, 4], [0.5, 0.5, 0.5],
                                     [1.0, 2.0, 3.0], 6)
        second = geom.feather_anchors([4, 2, 0], [0.5, 0.5, 0.5],
                                      [3.0, 2.0, 1.0], 6)
        self.assertEqual(first, second)

    def test_two_anchors_at_one_t_are_ordered_deterministically(self):
        first = geom.feather_anchors([1, 1], [0.0, 0.0], [12.0, 0.0], 5)
        second = geom.feather_anchors([1, 1], [0.0, 0.0], [0.0, 12.0], 5)
        self.assertEqual(first, second)
        self.assertEqual([a["feather"] for a in first], [0.0, 12.0])

    def test_a_zero_radius_anchor_is_carried(self):
        # v1's collision rule discards it; that is the defect section 6.1
        # measures. Here it is just another anchor.
        anchors = geom.feather_anchors([3], [0.0], [0.0], 7)
        self.assertEqual(anchors, [{"t": 3.0, "feather": 0.0}])

    def test_no_feather_points_is_an_empty_list(self):
        self.assertEqual(geom.feather_anchors([], [], [], 7), [])

    def test_every_t_is_inside_the_range_the_validator_enforces(self):
        # The two halves of section 6 have to agree, or the exporter writes
        # files its own validator rejects.
        n = 7
        for seg in range(n):
            for rel in (0.0, 0.25, 0.5, 0.75, 1.0):
                t = geom.feather_anchors([seg], [rel], [1.0], n)[0]["t"]
                self.assertTrue(0.0 <= t < float(n),
                                "seg %d rel %s gave t %r" % (seg, rel, t))


def _eval_cubic(points, i, j, u):
    """One .rbj segment evaluated at parameter u, straight from the formula.

    Deliberately not built out of anything the code under test uses: a split
    that is wrong in the same way as its own evaluator would look right.
    """
    b0 = points[i]["c"]
    b1 = [points[i]["c"][0] + points[i]["out"][0],
          points[i]["c"][1] + points[i]["out"][1]]
    b2 = [points[j]["c"][0] + points[j]["in"][0],
          points[j]["c"][1] + points[j]["in"][1]]
    b3 = points[j]["c"]
    v = 1.0 - u
    return [v * v * v * b0[k] + 3 * v * v * u * b1[k]
            + 3 * v * u * u * b2[k] + u * u * u * b3[k] for k in (0, 1)]


class TestSplitCubic(unittest.TestCase):
    """spec/rbj-v2-draft.md section 6.5. The claim is that nothing moves."""

    CURVE = [[0.0, 0.0], [30.0, 100.0], [120.0, -40.0], [150.0, 60.0]]

    def test_the_halves_share_the_split_point(self):
        left, right = geom.split_cubic(self.CURVE, 0.4)
        self.assertEqual(left[3], right[0])

    def test_the_ends_are_untouched(self):
        left, right = geom.split_cubic(self.CURVE, 0.4)
        self.assertEqual(left[0], self.CURVE[0])
        self.assertEqual(right[3], self.CURVE[3])

    def test_the_split_point_is_on_the_original_curve(self):
        def bezier(control, u):
            v = 1.0 - u
            return [v ** 3 * control[0][k] + 3 * v * v * u * control[1][k]
                    + 3 * v * u * u * control[2][k] + u ** 3 * control[3][k]
                    for k in (0, 1)]

        for u in (0.1, 0.25, 0.5, 0.75, 0.9):
            left, _ = geom.split_cubic(self.CURVE, u)
            want = bezier(self.CURVE, u)
            for k in (0, 1):
                self.assertAlmostEqual(left[3][k], want[k], places=12)

    def test_the_two_halves_retrace_the_whole_curve(self):
        # The claim section 6.5 rests on: subdivision reproduces the curve
        # exactly, so a vertex inserted to hold a feather anchor does not move
        # the shape. Sampled densely rather than at the split point alone.
        def bezier(control, u):
            v = 1.0 - u
            return [v ** 3 * control[0][k] + 3 * v * v * u * control[1][k]
                    + 3 * v * u * u * control[2][k] + u ** 3 * control[3][k]
                    for k in (0, 1)]

        split = 0.37
        left, right = geom.split_cubic(self.CURVE, split)
        for i in range(101):
            u = i / 100.0
            want = bezier(self.CURVE, u)
            if u <= split:
                got = bezier(left, u / split)
            else:
                got = bezier(right, (u - split) / (1.0 - split))
            for k in (0, 1):
                self.assertAlmostEqual(got[k], want[k], places=9,
                                       msg="at u=%g" % u)


class TestInsertAnchorVertices(unittest.TestCase):
    """spec/rbj-v2-draft.md section 6.5, into a host that anchors at vertices.

    The price is vertices; the guarantee is that the shape does not move.
    """

    def square(self):
        # Curved sides, so a split that ignored the tangents would show.
        return [{"c": [0.0, 0.0], "in": [-20.0, 0.0], "out": [20.0, 30.0]},
                {"c": [100.0, 0.0], "in": [-20.0, 30.0], "out": [20.0, 0.0]},
                {"c": [100.0, 100.0], "in": [20.0, 0.0], "out": [-20.0, 0.0]},
                {"c": [0.0, 100.0], "in": [20.0, 0.0], "out": [-20.0, 0.0]}]

    def test_an_anchor_on_a_vertex_inserts_nothing(self):
        got = geom.insert_anchor_vertices(self.square(),
                                          [{"t": 2.0, "feather": 9.0}])
        self.assertEqual(got["inserted"], 0)
        self.assertEqual(len(got["points"]), 4)
        self.assertEqual(got["feather"], [0.0, 0.0, 9.0, 0.0])

    def test_a_mid_segment_anchor_inserts_one_vertex(self):
        got = geom.insert_anchor_vertices(self.square(),
                                          [{"t": 0.5, "feather": 9.0}])
        self.assertEqual(got["inserted"], 1)
        self.assertEqual(len(got["points"]), 5)
        self.assertEqual(got["feather"], [0.0, 9.0, 0.0, 0.0, 0.0])

    def test_the_inserted_vertex_sits_on_the_original_curve(self):
        base = self.square()
        for t in (0.25, 0.5, 0.75, 1.5, 3.5):
            got = geom.insert_anchor_vertices(base, [{"t": t, "feather": 1.0}])
            segment = int(t)
            want = _eval_cubic(base, segment, (segment + 1) % 4, t - segment)
            new = got["points"][segment + 1]["c"]
            for k in (0, 1):
                self.assertAlmostEqual(new[k], want[k], places=9,
                                       msg="t=%g axis %d" % (t, k))

    def test_the_shape_does_not_move(self):
        # The whole promise. Sample the original curve and the split one and
        # require them to agree everywhere, not only at the inserted vertex.
        base = self.square()
        got = geom.insert_anchor_vertices(base, [{"t": 0.4, "feather": 1.0}])
        after = got["points"]
        for i in range(101):
            u = i / 100.0
            want = _eval_cubic(base, 0, 1, u)
            if u <= 0.4:
                have = _eval_cubic(after, 0, 1, u / 0.4)
            else:
                have = _eval_cubic(after, 1, 2, (u - 0.4) / 0.6)
            for k in (0, 1):
                self.assertAlmostEqual(have[k], want[k], places=9,
                                       msg="at u=%g" % u)

    def test_two_anchors_on_one_segment_both_get_a_vertex(self):
        # The case v1 could not carry at all, and the reason the whole model
        # is a list rather than a wider point field.
        base = self.square()
        got = geom.insert_anchor_vertices(base, [{"t": 0.25, "feather": 5.0},
                                                 {"t": 0.75, "feather": -7.0}])
        self.assertEqual(got["inserted"], 2)
        self.assertEqual(got["feather"], [0.0, 5.0, -7.0, 0.0, 0.0, 0.0])
        for k, t in ((1, 0.25), (2, 0.75)):
            want = _eval_cubic(base, 0, 1, t)
            for axis in (0, 1):
                self.assertAlmostEqual(got["points"][k]["c"][axis], want[axis],
                                       places=9, msg="t=%g" % t)

    def test_the_shape_does_not_move_after_two_cuts_on_one_segment(self):
        # The parameter remap is the part that is easy to get wrong: the
        # second cut is taken on what is left of the segment, not on the whole.
        base = self.square()
        got = geom.insert_anchor_vertices(base, [{"t": 0.25, "feather": 1.0},
                                                 {"t": 0.75, "feather": 2.0}])
        after = got["points"]
        spans = ((0, 1, 0.0, 0.25), (1, 2, 0.25, 0.75), (2, 3, 0.75, 1.0))
        for i in range(101):
            u = i / 100.0
            want = _eval_cubic(base, 0, 1, u)
            for a, b, lo, hi in spans:
                if lo <= u <= hi:
                    have = _eval_cubic(after, a, b, (u - lo) / (hi - lo))
                    break
            for k in (0, 1):
                self.assertAlmostEqual(have[k], want[k], places=9,
                                       msg="at u=%g" % u)

    def test_cuts_on_different_segments_do_not_disturb_each_other(self):
        base = self.square()
        got = geom.insert_anchor_vertices(base, [{"t": 0.5, "feather": 1.0},
                                                 {"t": 2.5, "feather": 2.0}])
        self.assertEqual(got["inserted"], 2)
        self.assertEqual(got["feather"], [0.0, 1.0, 0.0, 0.0, 2.0, 0.0])
        for index, t in ((1, 0.5), (4, 2.5)):
            segment = int(t)
            want = _eval_cubic(base, segment, segment + 1, t - segment)
            for k in (0, 1):
                self.assertAlmostEqual(got["points"][index]["c"][k], want[k],
                                       places=9)

    def test_a_cut_on_the_wrapping_segment_fixes_the_first_vertex(self):
        # The segment leaving the last vertex arrives at vertex 0, which the
        # emitting loop has already passed. Its incoming tangent still has to
        # be the rewritten one.
        base = self.square()
        got = geom.insert_anchor_vertices(base, [{"t": 3.5, "feather": 1.0}])
        self.assertEqual(got["inserted"], 1)
        self.assertNotEqual(got["points"][0]["in"], base[0]["in"])
        want = _eval_cubic(base, 3, 0, 0.5)
        for k in (0, 1):
            self.assertAlmostEqual(got["points"][4]["c"][k], want[k], places=9)

    def test_the_input_is_not_modified(self):
        base = self.square()
        before = json.dumps(base)
        geom.insert_anchor_vertices(base, [{"t": 3.5, "feather": 1.0},
                                           {"t": 0.5, "feather": 2.0}])
        self.assertEqual(json.dumps(base), before)

    def test_two_anchors_at_one_t_collide(self):
        # Nuke's featherCenter is one offset per control point, so two anchors
        # at one position have one vertex between them however the segment is
        # cut. This is the loss section 6 cannot remove, and it is reported.
        got = geom.insert_anchor_vertices(self.square(),
                                          [{"t": 2.0, "feather": 3.0},
                                           {"t": 2.0, "feather": -9.0}])
        self.assertEqual(got["feather"][2], -9.0)
        self.assertEqual(got["collided"],
                         [{"t": 2.0, "radius": 3.0, "kept": -9.0}])

    def test_two_anchors_at_one_mid_segment_t_collide(self):
        got = geom.insert_anchor_vertices(self.square(),
                                          [{"t": 1.5, "feather": 3.0},
                                           {"t": 1.5, "feather": 1.0}])
        self.assertEqual(got["inserted"], 1)
        self.assertEqual(got["feather"][2], 3.0)
        self.assertEqual(len(got["collided"]), 1)

    def test_the_earlier_anchor_holds_on_a_tie(self):
        # snap_feather_points' rule, kept so the two paths do not disagree
        # about the same input.
        got = geom.insert_anchor_vertices(self.square(),
                                          [{"t": 1.0, "feather": 4.0},
                                           {"t": 1.0, "feather": -4.0}])
        self.assertEqual(got["feather"][1], 4.0)

    def test_no_anchors_leaves_the_shape_alone(self):
        base = self.square()
        got = geom.insert_anchor_vertices(base, [])
        self.assertEqual(got["inserted"], 0)
        self.assertEqual(got["points"], base)
        self.assertEqual(got["feather"], [0.0] * 4)

    def test_an_open_shape_keeps_its_last_vertex_free(self):
        base = self.square()
        got = geom.insert_anchor_vertices(base, [{"t": 3.0, "feather": 6.0}],
                                          closed=False)
        self.assertEqual(got["inserted"], 0)
        self.assertEqual(got["feather"], [0.0, 0.0, 0.0, 6.0])
        self.assertEqual(got["points"][0]["in"], base[0]["in"])


class TestFeatherPointsFromAnchors(unittest.TestCase):
    """spec/rbj-v2-draft.md section 6, back into After Effects.

    The easy direction: the host anchors feather anywhere along a segment, so
    every entry lands exactly where the file says. Nuke's direction is 6.5 and
    has to insert vertices to manage the same thing.
    """

    def test_t_splits_into_the_segment_and_the_fraction(self):
        segs, rels, radii, types = geom.feather_points_from_anchors(
            [{"t": 2.5, "feather": 12.0}])
        self.assertEqual((segs, rels, radii), ([2], [0.5], [12.0]))
        self.assertEqual(types, [0])

    def test_an_integral_t_pins_to_the_start_of_its_own_segment(self):
        segs, rels, _, _ = geom.feather_points_from_anchors(
            [{"t": 3.0, "feather": 1.0}])
        self.assertEqual((segs, rels), ([3], [0.0]))

    def test_the_type_follows_the_sign(self):
        # A point's direction cannot be changed after creation, so the host has
        # to be handed the right one up front.
        _, _, _, types = geom.feather_points_from_anchors(
            [{"t": 0.0, "feather": 5.0}, {"t": 1.0, "feather": -5.0},
             {"t": 2.0, "feather": 0.0}])
        self.assertEqual(types, [0, 1, 0])

    def test_two_anchors_at_one_t_both_survive(self):
        segs, rels, radii, _ = geom.feather_points_from_anchors(
            [{"t": 3.0, "feather": 0.0}, {"t": 3.0, "feather": 12.0}])
        self.assertEqual((segs, rels, radii), ([3, 3], [0.0, 0.0],
                                               [0.0, 12.0]))

    def test_it_round_trips_with_feather_anchors(self):
        # The two halves of section 6 in the same process. Run 3's shape, out
        # to the host's four arrays and back.
        anchors = [{"t": 0.25, "feather": 30.0},
                   {"t": 0.75, "feather": -15.0},
                   {"t": 2.5, "feather": 12.0},
                   {"t": 3.0, "feather": 0.0}]
        segs, rels, radii, _ = geom.feather_points_from_anchors(anchors)
        self.assertEqual(geom.feather_anchors(segs, rels, radii, 7), anchors)

    def test_the_hosts_rename_survives_the_round_trip(self):
        # After Effects hands (i, 0) back as (i-1, 1). Reading that must give
        # the t that was written, or a re-export moves every vertex anchor.
        anchors = [{"t": 4.0, "feather": 5.0}]
        segs, rels, radii, _ = geom.feather_points_from_anchors(anchors)
        renamed_segs = [s - 1 for s in segs]
        renamed_rels = [1.0 for _ in rels]
        self.assertEqual(geom.feather_anchors(renamed_segs, renamed_rels,
                                              radii, 7), anchors)

    def test_no_anchors_gives_four_empty_arrays(self):
        self.assertEqual(geom.feather_points_from_anchors([]),
                         ([], [], [], []))


class TestFeatherPointsFromVertices(unittest.TestCase):
    """The way back: one scalar per vertex to After Effects' four arrays."""

    def test_each_vertex_pins_to_the_start_of_its_own_segment(self):
        segs, rels, radii, types = geom.feather_points_from_vertices([1.0, -2.0])
        self.assertEqual(segs, [0, 1])
        self.assertEqual(rels, [0.0, 0.0])
        self.assertEqual(radii, [1.0, -2.0])

    def test_the_type_agrees_with_the_sign(self):
        # Run 3 read type 0 back non-negative and type 1 non-positive, and a
        # point's direction cannot be changed after it is created.
        _, _, _, types = geom.feather_points_from_vertices([5.0, -5.0, 0.0])
        self.assertEqual(types, [0, 1, 0])

    def test_zeros_are_emitted_rather_than_skipped(self):
        segs, _, radii, _ = geom.feather_points_from_vertices([0.0, 3.0, 0.0])
        self.assertEqual(segs, [0, 1, 2])
        self.assertEqual(radii, [0.0, 3.0, 0.0])

    def test_it_round_trips_through_the_snapper(self):
        want = [1.5, 0.0, -3.25, 7.0]
        segs, rels, radii, _ = geom.feather_points_from_vertices(want)
        got = geom.snap_feather_points(segs, rels, radii, len(want))
        self.assertEqual(got["feather"], want)
        self.assertEqual(got["snapped"], [])
        self.assertEqual(got["dropped"], [])


@unittest.skipUnless(NODE, "node is not installed; the ExtendScript port is "
                           "still covered by test/test_ae_core.js")
class TestImportRecord(unittest.TestCase):
    """The durable import record (`core/report.py`).

    Rendering is the whole of it: an adapter hands over what it measured and
    gets back the document it writes next to the host project. The mirror in
    `ae/lib/rotobridge_core.jsx` is held to the same output byte for byte by
    `TestEs3CrossCheck`.
    """

    def record(self, **changes):
        base = {
            "written": "2026-08-22 09:14:03",
            "tool": "RotoBridge 0.9.0",
            "host": "Nuke 17.1v1",
            "target": "Roto1",
            "source_file": "/shots/ab_010/roto/ab_010.rbj",
            "source": {"app": "After Effects", "app_version": "25.6x101",
                       "tool_version": "0.9.0",
                       "width": 1920, "height": 1080, "fps": 24.0,
                       "pixel_aspect": 1.0},
            "version": 2,
            "range": [1, 25],
            "offset": 0,
            "tolerance": 0.5,
            "shapes": [{"name": "feathered", "feather_model": "anchored",
                        "points": 7, "authored": 25, "corrective": 0,
                        "residual": 0.0, "worst_frame": 12}],
            "file_warnings": [],
            "import_warnings": [],
        }
        base.update(changes)
        return base

    def test_it_names_the_file_the_application_and_the_shape(self):
        text = report.render(self.record())
        for wanted in ("/shots/ab_010/roto/ab_010.rbj", "After Effects 25.6x101",
                       "Nuke 17.1v1", "feathered", ".rbj version 2",
                       "1920 x 1080 at 24 fps"):
            self.assertIn(wanted, text)

    def test_it_names_the_build_on_both_sides(self):
        # The record is the one artifact a non-technical tester can send that
        # answers every question at once, and "which build" is two questions:
        # the one that wrote the file and the one that read it. They are
        # routinely different machines and routinely different versions.
        text = report.render(self.record())
        self.assertIn("RotoBridge 0.9.0", text)
        self.assertIn("exported with", text)

    def test_a_file_older_than_the_member_says_so(self):
        # Every .rbj written before source.tool_version existed. Silence in a
        # document written to settle an argument is worse than a plain "not
        # recorded" - a missing row reads as the record having forgotten.
        source = dict(self.record()["source"])
        source.pop("tool_version")
        text = report.render(self.record(source=source))
        self.assertIn("not recorded", text)

    def test_whole_numbers_lose_the_trailing_zero(self):
        # The one accepted divergence between the two writers is how they
        # spell 1.0, and a record is a document both hosts must produce
        # identically. So neither spells it the JSON way.
        text = report.render(self.record())
        self.assertIn("at 24 fps, pixel aspect 1\n", text)
        self.assertNotIn("24.0", text)

    def test_the_offset_is_shown_as_the_frames_it_lands_on(self):
        text = report.render(self.record(offset=100))
        self.assertIn("source frames  1 to 25", text)
        self.assertIn("placed at      101 to 125 (offset 100)", text)

    def test_each_import_mode_is_named_rather_than_printed(self):
        # `inf` is a legal tolerance and the two languages spell it
        # differently, so no record carries either spelling.
        self.assertIn("unbounded (authored keys only)",
                      report.render(self.record(tolerance=float("inf"))))
        self.assertIn("0 px (every frame keyed)",
                      report.render(self.record(tolerance=0.0)))
        self.assertIn("tolerance      0.5 px",
                      report.render(self.record(tolerance=0.5)))

    def test_a_shape_says_what_arrived_and_how_far_it_sits_from_the_file(self):
        line = report.render(self.record(shapes=[
            {"name": "plain", "feather_model": "per_point", "points": 4,
             "authored": 5, "corrective": 3, "residual": 0.42105,
             "worst_frame": 9}]))
        self.assertIn("  plain: feather per_point, 4 point(s), 5 authored "
                      "key(s), 3 corrective; worst drift 0.4211 px at frame 9",
                      line)

    def test_a_pixel_measurement_rounds_half_away_from_zero(self):
        # `%.4f` rounds half to even and JavaScript's `toFixed` rounds half
        # away from zero. 0.15625 is exactly representable, so it lands on the
        # tie every time and the two would disagree if either language's
        # default were used.
        self.assertIn("worst drift 0.1563 px", report.render(self.record(
            shapes=[{"name": "tie", "feather_model": "none", "points": 4,
                     "authored": 5, "corrective": 1, "residual": 0.15625,
                     "worst_frame": 9}])))

    def test_a_shape_that_never_drifted_says_so(self):
        # `worst_frame` is None when every frame is a key and also when no
        # frame between the keys moved. A bare "0.0000 px at frame None" would
        # read as a measurement that was taken at a frame that does not exist.
        text = report.render(self.record(shapes=[
            {"name": "dense", "feather_model": "none", "points": 4,
             "authored": 25, "corrective": 0, "residual": 0.0,
             "worst_frame": None}]))
        self.assertIn("nothing drifted from the file", text)
        self.assertNotIn("worst drift", text)

    def test_the_two_warning_sets_stay_apart(self):
        text = report.render(self.record(
            file_warnings=["shape 'x': ease was dropped"],
            import_warnings=["shape 'x': 3 vertices were inserted"]))
        self.assertIn("1 warning recorded when the file was written:", text)
        self.assertIn("  - shape 'x': ease was dropped", text)
        self.assertIn("1 warning from this import:", text)
        self.assertIn("  - shape 'x': 3 vertices were inserted", text)

    def test_silence_is_stated_rather_than_omitted(self):
        # An absent section makes no claim. "Nothing was lost" is the claim
        # this document exists to support.
        text = report.render(self.record())
        self.assertIn("no warnings recorded when the file was written", text)
        self.assertIn("no warnings from this import", text)

    def test_a_record_appends_cleanly_to_another(self):
        # A comp is imported into more than once, and the second import must
        # not erase the evidence of the first. The rule is the writer's, but it
        # only works if the text carries its own separator.
        twice = report.render(self.record()) + report.render(self.record())
        self.assertEqual(twice.count("RotoBridge import record"), 2)
        self.assertEqual(twice.count(report.RULE), 2)
        self.assertTrue(twice.endswith("\n"))

    def test_the_record_sits_beside_whatever_anchors_it(self):
        self.assertEqual(report.path_for("/shots/ab_010/comp/ab_010_v012.nk"),
                         "/shots/ab_010/comp/ab_010_v012.rotobridge.txt")
        self.assertEqual(report.path_for("/shots/ab_010/roto/ab_010.rbj"),
                         "/shots/ab_010/roto/ab_010.rotobridge.txt")

    def test_only_a_dot_in_the_last_component_is_an_extension(self):
        # `os.path.splitext`'s rule, written out in `core/report.py` so the
        # ExtendScript mirror can say the same thing. A version folder called
        # `v2.1` must not eat the file name.
        self.assertEqual(report.path_for("/shots/v2.1/ab_010"),
                         "/shots/v2.1/ab_010.rotobridge.txt")
        self.assertEqual(report.path_for("/shots/.rbj"),
                         "/shots/.rbj.rotobridge.txt")


class _WithoutNuke(unittest.TestCase):
    """Imports `nuke/rotobridge_import.py` with the host modules stubbed out.

    The importer cannot be imported without Nuke, and some of what it decides
    does not need Nuke at all: which reading an anchored shape gets, and what
    goes into the import record. Both are worth testing here rather than only
    in the host, because both have a branch nobody will reach by hand, and an
    untested fallback is a fallback that does not work.

    `cls.nuke` is the stub, so a subclass can give it whatever the function
    under test asks the host for.
    """

    @classmethod
    def setUpClass(cls):
        import types
        stubs = {}
        nuke_stub = types.ModuleType("nuke")
        rp_stub = types.ModuleType("nuke.rotopaint")
        nuke_stub.rotopaint = rp_stub
        shared = types.ModuleType("rotobridge_nuke")
        for name in ("ATTR_FEATHER_FALLOFF", "ATTR_FEATHER_X", "ATTR_FEATHER_Y",
                     "ATTR_OPACITY", "INTERP_LINEAR", "blend_from_rbj",
                     "bridge_folder", "falloff_from_rbj", "point_members",
                     "roto_knob", "set_curve_linear", "set_curve_types",
                     "write_attr_curve", "write_attr_static"):
            setattr(shared, name, None)
        shared.drift, shared.geom = drift, geom
        shared.interp, shared.rbj, shared.report = interp, rbj, report
        shared.messages, shared.version = messages, version
        stubs["nuke"] = nuke_stub
        stubs["nuke.rotopaint"] = rp_stub
        stubs["rotobridge_nuke"] = shared

        cls.nuke = nuke_stub
        cls._saved = dict((k, sys.modules.get(k)) for k in stubs)
        sys.modules.update(stubs)
        sys.path.insert(0, os.path.join(REPO, "nuke"))
        try:
            import rotobridge_import
            cls.rbi = rotobridge_import
        finally:
            sys.path.pop(0)

    @classmethod
    def tearDownClass(cls):
        for key, was in cls._saved.items():
            if was is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = was
        sys.modules.pop("rotobridge_import", None)


class TestNukeImportSeed(_WithoutNuke):
    """`_default_input` - what the input box is seeded with, without Nuke."""

    def seeded(self, folder):
        saved = self.rbi.bridge_folder
        self.rbi.bridge_folder = lambda: folder
        try:
            return self.rbi._default_input()
        finally:
            self.rbi.bridge_folder = saved

    def test_an_unsaved_script_seeds_nothing(self):
        self.assertEqual(self.seeded(None), "")

    def test_a_missing_bridge_folder_seeds_nothing(self):
        holder = tempfile.mkdtemp()
        try:
            self.assertEqual(self.seeded(holder + "/rotobridge"), "")
        finally:
            shutil.rmtree(holder)

    def test_the_newest_rbj_wins_and_bystanders_do_not_count(self):
        holder = tempfile.mkdtemp()
        try:
            for name, age in (("old.rbj", 100), ("new.rbj", 50),
                              ("newest.txt", 0)):
                path = os.path.join(holder, name)
                with open(path, "w") as fh:
                    fh.write("x")
                stamp = time.time() - age
                os.utime(path, (stamp, stamp))
            self.assertEqual(self.seeded(holder),
                             os.path.join(holder, "new.rbj").replace(
                                 "\\", "/"))
        finally:
            shutil.rmtree(holder)

    def test_an_empty_bridge_folder_seeds_nothing(self):
        holder = tempfile.mkdtemp()
        try:
            self.assertEqual(self.seeded(holder), "")
        finally:
            shutil.rmtree(holder)


class TestNukeAnchoredFeather(_WithoutNuke):
    """The Nuke importer's section 6.5 policy, without Nuke."""

    def spec(self, anchors_at, frames=(0, 1, 2)):
        """A four-point square whose anchors are `anchors_at(frame)`."""
        square = [{"c": [0.0, 0.0], "in": [-20.0, 0.0], "out": [20.0, 30.0]},
                  {"c": [100.0, 0.0], "in": [-20.0, 30.0], "out": [20.0, 0.0]},
                  {"c": [100.0, 100.0], "in": [20.0, 0.0], "out": [-20.0, 0.0]},
                  {"c": [0.0, 100.0], "in": [20.0, 0.0], "out": [-20.0, 0.0]}]
        return {
            "name": "feathered", "closed": True,
            "feather_model": "anchored",
            "frames": dict(
                (str(f), {"opacity": 1.0, "feather_uniform": [0.0, 0.0],
                          "points": copy.deepcopy(square),
                          "feather_points": anchors_at(f)})
                for f in frames),
        }

    def run_anchored(self, anchors_at, frames=(0, 1, 2)):
        said = []
        got = self.rbi._anchored_dense(self.spec(anchors_at, frames),
                                       list(frames), said.append)
        return got, said

    def test_a_mid_segment_anchor_becomes_a_vertex_on_every_frame(self):
        got, said = self.run_anchored(
            lambda f: [{"t": 0.5, "feather": 9.0}])
        self.assertIsNotNone(got)
        for frame in ("0", "1", "2"):
            points = got[frame]["points"]
            self.assertEqual(len(points), 5, frame)
            self.assertEqual(points[1]["feather"], 9.0, frame)
        self.assertTrue(any("1 vertex was inserted" in w for w in said), said)

    def test_every_point_carries_feather_so_it_reads_as_per_point(self):
        # The whole reason for the transformation: downstream is Nuke's own
        # model and needs no further special case.
        got, _ = self.run_anchored(lambda f: [{"t": 1.5, "feather": 4.0}])
        for point in got["0"]["points"]:
            self.assertIn("feather", point)

    def test_the_insertion_count_is_written_in_words_that_read(self):
        # It goes in front of a compositor wondering why the shape has more
        # points than the artist drew, so "2 vertex/vertices" will not do.
        _, one = self.run_anchored(lambda f: [{"t": 0.5, "feather": 1.0}])
        _, two = self.run_anchored(lambda f: [{"t": 0.5, "feather": 1.0},
                                              {"t": 2.5, "feather": 2.0}])
        self.assertIn("1 vertex was inserted", " ".join(one))
        self.assertIn("2 vertices were inserted", " ".join(two))

    def test_a_moving_anchor_keeps_one_vertex_count(self):
        # Section 6.5: an anchor that slides costs keys, not accuracy. The
        # count is what the format requires to stay fixed, and it does.
        got, said = self.run_anchored(
            lambda f: [{"t": 0.2 + 0.1 * f, "feather": 9.0}])
        self.assertIsNotNone(got)
        self.assertEqual(set(len(got[k]["points"]) for k in got), set([5]))
        self.assertNotEqual(got["0"]["points"][1]["c"],
                            got["2"]["points"][1]["c"])

    def test_an_anchor_sliding_onto_a_vertex_falls_back_to_the_snap(self):
        # The crossing case. At frame 2 the anchor is exactly on vertex 1, so
        # no vertex is inserted and the count drops - which is a topology
        # change, and the shape takes the v1 reading instead.
        got, said = self.run_anchored(
            lambda f: [{"t": 0.5 + 0.25 * f, "feather": 9.0}])
        self.assertIsNone(got)
        self.assertTrue(any("cross each other between frames" in w
                            for w in said), said)

    def test_the_fallback_places_feather_as_version_1_did(self):
        spec = self.spec(lambda f: [{"t": 0.75, "feather": 9.0}])
        got = self.rbi._snapped_dense(spec, [0, 1, 2])
        points = got["0"]["points"]
        self.assertEqual(len(points), 4, "the snap inserts nothing")
        self.assertEqual([p["feather"] for p in points],
                         [0.0, 9.0, 0.0, 0.0])

    def test_a_vertex_anchor_inserts_nothing_and_says_nothing(self):
        got, said = self.run_anchored(lambda f: [{"t": 2.0, "feather": 5.0}])
        self.assertEqual(len(got["0"]["points"]), 4)
        self.assertEqual([p["feather"] for p in got["0"]["points"]],
                         [0.0, 0.0, 5.0, 0.0])
        self.assertEqual(said, [])

    def test_colliding_anchors_are_reported_once_not_once_per_frame(self):
        got, said = self.run_anchored(
            lambda f: [{"t": 2.0, "feather": 3.0},
                       {"t": 2.0, "feather": -9.0}])
        clashes = [w for w in said if "share a position" in w]
        self.assertEqual(len(clashes), 1, said)
        self.assertIn("1 feather anchor(s)", clashes[0])
        self.assertEqual(got["0"]["points"][2]["feather"], -9.0)


class TestNukeFeatherOffsets(_WithoutNuke):
    """The per-frame offset rebuild, and what it says when it cannot."""

    def degenerate(self):
        # Every point at one position: no polygon, no defined normals, so a
        # non-zero feather has nowhere to point.
        point = {"c": [10.0, 10.0], "feather": 5.0}
        return {"points": [dict(point), dict(point), dict(point)]}

    def test_a_degenerate_vertex_is_reported_once_not_once_per_frame(self):
        # The same rule colliding anchors already follow: the loop is per
        # frame, the fact is per shape, and 150 copies of one sentence bury
        # every other warning in the record.
        dense = {"0": self.degenerate(), "1": self.degenerate(),
                 "2": self.degenerate()}
        said = []
        got = self.rbi._frame_offsets(dense, [0, 1, 2], said.append,
                                      "flat", "per_point", True)
        self.assertEqual(len(got), 3)
        self.assertEqual(len(said), 1, said)
        self.assertIn("[feather-degenerate-vertex]", said[0])


class TestNukeImportRecord(_WithoutNuke):
    """What the Nuke importer puts in the record, and where it puts it.

    The host run proves the record is written; this proves what is in it. The
    interesting part is not the formatting - `TestImportRecord` has that - but
    the two decisions the adapter makes: which file the record sits beside, and
    which warnings belong to which application.
    """

    class Node(object):
        def __init__(self, name):
            self._name = name

        def name(self):
            return self._name

    def setUp(self):
        self.nuke.NUKE_VERSION_STRING = "17.1v1"
        self.nuke.root = lambda: self.Node("Root")

    def doc(self, warnings):
        got = valid_doc()
        got["warnings"] = list(warnings)
        return got

    def test_the_record_sits_beside_the_script_when_there_is_one(self):
        self.nuke.root = lambda: self.Node("/shots/ab_010/comp/ab_010_v012.nk")
        self.assertEqual(self.rbi.record_path("/roto/ab_010.rbj"),
                         "/shots/ab_010/comp/ab_010_v012.rotobridge.txt")

    def test_an_unsaved_script_puts_the_record_beside_the_rbj(self):
        # `nuke.root().name()` is the literal string "Root" until the script is
        # saved, which is also what a headless `-t` run reports.
        self.assertEqual(self.rbi.record_path("/roto/ab_010.rbj"),
                         "/roto/ab_010.rotobridge.txt")

    def test_the_exporters_warnings_stay_the_exporters(self):
        # `import_document` seeds its warning list with the file's own, in
        # order and first. A record that ran them together would answer "which
        # application dropped it?" with "one of them did".
        doc = self.doc(["the exporter lost the ease"])
        warnings = list(doc["warnings"]) + ["this import inserted a vertex"]
        got = self.rbi.build_record(doc, "/roto/ab_010.rbj", self.Node("Roto1"),
                                    warnings, [], 0, 0.5)
        self.assertEqual(got["file_warnings"], ["the exporter lost the ease"])
        self.assertEqual(got["import_warnings"],
                         ["this import inserted a vertex"])

    def test_it_carries_the_host_the_target_and_the_settings(self):
        doc = self.doc([])
        got = self.rbi.build_record(doc, "/roto/ab_010.rbj", self.Node("Roto3"),
                                    [], [], -1000, float("inf"))
        self.assertEqual(got["host"], "Nuke 17.1v1")
        self.assertEqual(got["target"], "Roto3")
        self.assertEqual(got["source_file"], "/roto/ab_010.rbj")
        self.assertEqual(got["offset"], -1000)
        self.assertEqual(got["tolerance"], float("inf"))
        self.assertEqual(got["range"], doc["range"])
        self.assertEqual(got["version"], doc["version"])
        # Rendering it is the check that every field an adapter must supply is
        # supplied: `render` reads them all and raises on a missing one.
        self.assertIn("Nuke 17.1v1", report.render(got))

    def test_a_second_import_does_not_erase_the_first(self):
        doc = self.doc([])
        record = self.rbi.build_record(doc, "/roto/ab_010.rbj",
                                       self.Node("Roto1"), [], [], 0, 0.5)
        holder = tempfile.mkdtemp()
        try:
            path = os.path.join(holder, "shot.rotobridge.txt")
            said = []
            self.assertEqual(self.rbi.write_record(record, path, said.append),
                             path)
            self.assertEqual(self.rbi.write_record(record, path, said.append),
                             path)
            with open(path) as fh:
                text = fh.read()
        finally:
            shutil.rmtree(holder)
        self.assertEqual(text.count("RotoBridge import record"), 2)
        self.assertEqual(said, [])

    def test_an_unwritable_record_is_a_warning_and_not_a_failure(self):
        # The shapes are in the script by the time this runs. Losing an import
        # over a read-only folder would be a worse failure than the one being
        # reported.
        record = self.rbi.build_record(self.doc([]), "/roto/ab_010.rbj",
                                       self.Node("Roto1"), [], [], 0, 0.5)
        said = []
        got = self.rbi.write_record(record, os.path.join(REPO, "does", "not",
                                                         "exist.txt"),
                                    said.append)
        self.assertIsNone(got)
        self.assertEqual(len(said), 1)
        self.assertIn("could not be written", said[0])


class TestMessages(unittest.TestCase):
    """The warning registry: one table, codes in front, strict rendering."""

    # One value per placeholder name, shared with the ES3 cross-check so both
    # implementations render the same bytes from the same inputs. Numbers are
    # deliberately mixed in to exercise the whole-value rule.
    SAMPLES = {
        "subject": "mask 'Roto A'", "name": "Roto A", "first": "Solid 1",
        "second": "Solid 2", "px": 2.5, "mode": "Lighten",
        "members": "tension, corner angle", "count": 3, "vertex": 2,
        "kept": 9.5, "dropped": -4, "offset": "0.125", "frame": -988,
        "added": 22, "tolerance": 0.5, "layer": "Solid 1",
        "src": "1920x1080", "dst": "1280x720", "residual": "0.4211",
        "path": "/shots/x.txt", "reason": "Permission denied",
        "detail": "4 at frame 2, 5 at frame 3", "noun": "vertices were",
        "app": "After Effects", "blend": "difference", "type": "Stroke",
        "attr": "the inverted flag",
    }

    @classmethod
    def params_for(cls, code):
        holders = re.findall(r"\{([a-z0-9_]+)\}", messages.TEMPLATES[code])
        missing = [h for h in holders if h not in cls.SAMPLES]
        assert not missing, "add SAMPLES for %s: %s" % (code, missing)
        return dict((h, cls.SAMPLES[h]) for h in holders)

    def test_every_code_renders_and_leads_with_its_code(self):
        # `render` raises on an unfilled placeholder, so surviving this loop
        # also proves SAMPLES covers every parameter every template names.
        for code in messages.codes():
            text = messages.render(code, self.params_for(code))
            self.assertTrue(text.startswith("[%s] " % code), text)

    def test_an_unknown_code_is_a_bug_not_a_warning(self):
        self.assertRaises(ValueError, messages.render, "no-such-code", {})

    def test_a_missing_parameter_is_a_bug_not_a_warning(self):
        self.assertRaises(ValueError, messages.render, "feather-snapped",
                          {"subject": "mask 'M'"})

    def test_whole_numbers_lose_the_trailing_zero(self):
        # JavaScript has one number type, so this is the report rule applied
        # to warnings: 3.0 and 3 are the same value and get the same spelling.
        got = messages.render("feather-snapped",
                              {"subject": "mask 'M'", "count": 3.0})
        self.assertIn(" 3 feather point(s)", got)

    def test_px_rounds_half_away_from_zero(self):
        self.assertEqual(messages.px(0.00005, 4), "0.0001")
        self.assertEqual(messages.px(-0.00005, 4), "-0.0001")
        self.assertEqual(messages.px(2.5, 3), "2.500")


class TestNukeSubset(_WithoutNuke):
    """The import's shape selection, by id first and name second."""

    SHAPES = [{"name": "roof", "id": "Roto1/roof"},
              {"name": "door"}]

    def run_subset(self, wanted):
        said = []
        got = self.rbi._subset(list(self.SHAPES), wanted, said.append)
        return got, said

    def test_a_name_still_selects(self):
        got, said = self.run_subset(["door"])
        self.assertEqual([s["name"] for s in got], ["door"])
        self.assertEqual(said, [])

    def test_an_id_selects_too(self):
        got, said = self.run_subset(["Roto1/roof"])
        self.assertEqual([s["name"] for s in got], ["roof"])
        self.assertEqual(said, [])

    def test_a_miss_is_named_and_an_empty_match_raises(self):
        got, said = self.run_subset(["roof", "chimney"])
        self.assertEqual(len(got), 1)
        self.assertEqual(len(said), 1)
        self.assertIn("[subset-missing] shape 'chimney'", said[0])
        self.assertRaises(ValueError, self.rbi._subset,
                          list(self.SHAPES), ["chimney"], said.append)


class TestNukeToleranceParser(_WithoutNuke):
    """The one free-text control the import panel has (prd.md section 8)."""

    def test_blank_and_inf_mean_unbounded(self):
        for raw in ("", "  ", "inf", "Infinity"):
            self.assertEqual(self.rbi._parse_tolerance(raw), float("inf"), raw)

    def test_a_number_is_a_number(self):
        self.assertEqual(self.rbi._parse_tolerance(" 0.5 "), 0.5)
        self.assertEqual(self.rbi._parse_tolerance("0"), 0.0)

    def test_negative_is_refused(self):
        with self.assertRaises(ValueError):
            self.rbi._parse_tolerance("-1")

    def test_nan_is_refused_not_silently_unbounded(self):
        # `float("nan") < 0.0` is False, so without its own check nan slips
        # through, the drift pass behaves as tolerance inf, and the record
        # prints "nan px". The AE side already throws on it (via isNaN);
        # accepting it here would be a divergence between the two importers.
        with self.assertRaises(ValueError):
            self.rbi._parse_tolerance("nan")

    def test_garbage_is_refused(self):
        with self.assertRaises(ValueError):
            self.rbi._parse_tolerance("five")


class TestNukeAttributeWrite(_WithoutNuke):
    """What `_write_attributes` keys and what it leaves as a plain value."""

    def test_an_unkeyed_falloff_arrives_keyless(self):
        # `ff` is static per shape. It used to arrive as a one-key curve,
        # written before probe_nuke_static.py showed a keyless attribute
        # holds `add`'s value everywhere; one key is still a key nobody
        # authored.
        rbi = self.rbi
        saved = dict((name, getattr(rbi, name))
                     for name in ("write_attr_static", "write_attr_curve",
                                  "set_curve_linear", "blend_from_rbj",
                                  "falloff_from_rbj", "ATTR_FEATHER_FALLOFF",
                                  "ATTR_OPACITY", "ATTR_FEATHER_X",
                                  "ATTR_FEATHER_Y"))
        calls = []
        try:
            rbi.write_attr_static = \
                lambda attrs, name, value: calls.append(("static", name, value))
            rbi.write_attr_curve = \
                lambda attrs, name, samples: calls.append(("curve", name))
            rbi.set_curve_linear = lambda curve: None
            rbi.blend_from_rbj = lambda blend, warn, name: 0.0
            rbi.falloff_from_rbj = lambda falloff: 1.0
            rbi.ATTR_FEATHER_FALLOFF = "ff"
            rbi.ATTR_OPACITY, rbi.ATTR_FEATHER_X = "opc", "fx"
            rbi.ATTR_FEATHER_Y = "fy"

            class Shape(object):
                def getAttributes(self):
                    return object()

            record = {"opacity": 1.0, "feather_uniform": [0.0, 0.0]}
            spec = {"name": "s", "blend": "union",
                    "feather_falloff": "smooth",
                    "frames": {"0": dict(record), "1": dict(record)}}
            rbi._write_attributes(Shape(), spec, [0, 1], 0, 0.5,
                                  lambda m: None)
        finally:
            for name, value in saved.items():
                setattr(rbi, name, value)
        self.assertIn(("static", "ff", 1.0), calls)
        self.assertEqual([c for c in calls if c[0] == "curve"], [])


class _WithoutNukeExport(unittest.TestCase):
    """Imports `nuke/rotobridge_export.py` with the host modules stubbed out.

    The exporter cannot be imported without the host modules, so this stubs
    them the way `_WithoutNuke` does for the importer. The fakes carry only
    what the functions under test actually read; the attribute names and the
    view are the real ones, because tests reach the code through them.
    """

    @classmethod
    def setUpClass(cls):
        import types
        stubs = {}
        nuke_stub = types.ModuleType("nuke")
        rp_stub = types.ModuleType("nuke.rotopaint")
        nuke_stub.rotopaint = rp_stub
        shared = types.ModuleType("rotobridge_nuke")
        for name in ("attr_value", "blend_to_rbj", "bridge_folder",
                     "falloff_to_rbj", "is_closed", "iter_shapes", "roto_knob",
                     "script_range", "selected_roto_node", "vec2"):
            setattr(shared, name, None)
        shared.ATTR_OPACITY, shared.ATTR_BLEND = "opc", "bm"
        shared.ATTR_INVERTED, shared.ATTR_FEATHER_FALLOFF = "inv", "ff"
        shared.ATTR_FEATHER_X, shared.ATTR_FEATHER_Y = "fx", "fy"
        shared.VIEW = "main"
        shared.point_members = lambda cp: (cp.center, cp.leftTangent,
                                           cp.rightTangent, cp.featherCenter)
        shared.drift, shared.geom = drift, geom
        shared.interp, shared.rbj, shared.report = interp, rbj, report
        shared.messages, shared.timing = messages, timing
        shared.version = version
        stubs["nuke"] = nuke_stub
        stubs["nuke.rotopaint"] = rp_stub
        stubs["rotobridge_nuke"] = shared

        cls._saved = dict((k, sys.modules.get(k)) for k in stubs)
        sys.modules.update(stubs)
        sys.path.insert(0, os.path.join(REPO, "nuke"))
        try:
            import rotobridge_export
            cls.rbe = rotobridge_export
        finally:
            sys.path.pop(0)

    @classmethod
    def tearDownClass(cls):
        for key, was in cls._saved.items():
            if was is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = was
        sys.modules.pop("rotobridge_export", None)


class TestNukeExportSeed(_WithoutNukeExport):
    """`_default_output` - what the output box is seeded with, without Nuke."""

    class Node:
        def name(self):
            return "Roto1"

    def seeded(self, folder):
        saved = self.rbe.bridge_folder
        self.rbe.bridge_folder = lambda: folder
        try:
            return self.rbe._default_output(self.Node())
        finally:
            self.rbe.bridge_folder = saved

    def test_an_unsaved_script_seeds_nothing(self):
        self.assertEqual(self.seeded(None), "")

    def test_a_saved_script_seeds_folder_and_node_name(self):
        # The folder is made before the panel shows, so the seed names a
        # place that exists by the time the artist sees it.
        holder = tempfile.mkdtemp()
        try:
            folder = holder + "/rotobridge"
            self.assertEqual(self.seeded(folder), folder + "/Roto1.rbj")
            self.assertTrue(os.path.isdir(folder))
        finally:
            shutil.rmtree(holder)


class TestNukeSparseKeys(_WithoutNukeExport):
    """`_sparse_keys` without Nuke: the union, the vote, and the provenance."""

    class Curve(object):
        def __init__(self, times):
            self.times = list(times)

        def getNumberOfKeys(self):
            return len(self.times)

        def getKey(self, k):
            class Key(object):
                pass
            key = Key()
            key.time = self.times[k]
            # Never read for a single-key curve: it abstains from the vote.
            key.interpolationType = None
            return key

    class Member(object):
        def __init__(self, curves):
            self.curves = list(curves)
            self.dim = len(self.curves)

        def getPositionAnimCurve(self, d):
            return self.curves[d]

    class Transform(object):
        def getTransformKeyTimes(self):
            return (1.0,)
        getTranslationKeyTimes = getTransformKeyTimes
        getRotationKeyTimes = getTransformKeyTimes
        getScaleKeyTimes = getTransformKeyTimes
        getSkewXKeyTimes = getTransformKeyTimes
        getPivotPointKeyTimes = getTransformKeyTimes

    def shape(self, times_per_curve):
        """One control point whose four members each carry one curve."""
        Curve, Member = self.Curve, self.Member

        class Point(object):
            def __init__(self):
                members = [Member([Curve(times)])
                           for times in times_per_curve]
                (self.center, self.leftTangent,
                 self.rightTangent, self.featherCenter) = members

        transform = self.Transform()

        class Shape(object):
            def __len__(self):
                return 1

            def __getitem__(self, i):
                return Point()

            def getTransform(self):
                return transform

        return Shape()

    def test_one_authored_key_is_still_authored(self):
        # A shape the artist keyed exactly once used to export as never
        # keyed: every curve held one key, every curve abstained, and
        # `authored_frames` said []. The default import then deleted the
        # artist's key - 1 authored arrived as 0.
        shape = self.shape([(50.0,), (50.0,), (50.0,), (50.0,)])
        said = []
        keys, authored = self.rbe._sparse_keys(shape, (), list(range(0, 101)),
                                               said.append, "once")
        self.assertEqual(authored, [50])
        self.assertEqual([k["frame"] for k in keys], [0, 50, 100])
        # No two-key curve voted, so the side is unknown, which is `ease`.
        self.assertEqual(keys[1]["interp"], {"in": "ease", "out": "ease"})
        self.assertEqual(said, [])

    def test_a_subframe_key_is_snapped_and_said(self):
        # The AE exporter has warned about off-grid keys since Phase 4; a
        # Nuke curve keyed at 10.4 was snapped just as silently. Warned once
        # per distinct time, not per axis carrying it.
        shape = self.shape([(10.4, 20.0), (10.4, 20.0), (), ()])
        said = []
        keys, authored = self.rbe._sparse_keys(shape, (), list(range(0, 31)),
                                               said.append, "sub")
        self.assertEqual(authored, [10, 20])
        self.assertEqual([k["frame"] for k in keys], [0, 10, 20, 30])
        self.assertEqual(len(said), 1)
        self.assertIn("[key-off-grid]", said[0])
        self.assertIn("0.400 of a frame", said[0])
        self.assertIn("snapped to frame 10", said[0])

    def test_a_keyless_curve_still_abstains_from_everything(self):
        shape = self.shape([(), (), (), ()])
        keys, authored = self.rbe._sparse_keys(shape, (), list(range(0, 11)),
                                               lambda m: None, "static")
        self.assertEqual(authored, [])
        self.assertEqual([k["frame"] for k in keys], [0, 10])


class TestNukeExportWarnings(_WithoutNukeExport):
    """Per-shape attributes that animate must say so when they cross."""

    class Attrs(object):
        def __init__(self, counts):
            self.counts = counts

        def getCurve(self, name, view):
            assert view == "main"
            counts = self.counts

            class Curve(object):
                def getNumberOfKeys(_self):
                    return counts.get(name, 0)
            return Curve()

    def test_an_animated_per_shape_attribute_is_warned_about(self):
        # `inv`, `bm` and `ff` cross as their value at the first exported
        # frame; a curve keyed on more than one frame used to lose its
        # animation with no warning at all.
        said = []
        self.rbe._warn_attr_animation(self.Attrs({"inv": 2, "bm": 3}),
                                      said.append, "s")
        self.assertEqual(len(said), 2)
        self.assertIn("[attr-animation-dropped]", said[0])
        self.assertIn("the inverted flag", said[0])
        self.assertIn("the blending mode", said[1])

    def test_one_key_or_none_is_a_value_not_animation(self):
        said = []
        self.rbe._warn_attr_animation(self.Attrs({"inv": 1, "bm": 1, "ff": 0}),
                                      said.append, "s")
        self.assertEqual(said, [])


class TestLinearFit(unittest.TestCase):
    """The export-side pass: what a LINEAR sparse layer costs.

    Same search as `correct`, and the vectors below are the ones the ES3 mirror
    is checked against in `TestEs3CrossCheck`.
    """

    def bow(self, peak, count=25):
        """A parabola `peak` px off the chord between its ends."""
        frames = list(range(count))
        middle = (count - 1) / 2.0
        return frames, {f: [f * 10.0,
                            peak * (1.0 - ((f - middle) / middle) ** 2)]
                        for f in frames}

    def test_a_straight_line_needs_no_keys_beyond_its_ends(self):
        frames = list(range(0, 25))
        dense = {f: [f * 10.0, 0.0] for f in frames}
        keys, worst, at = drift.linear_fit(frames, dense, [0, 24], 0.5)
        self.assertEqual(keys, [0, 24])
        self.assertEqual(worst, 0.0)
        self.assertIsNone(at)

    def test_a_bow_inside_tolerance_costs_nothing_either(self):
        frames, dense = self.bow(0.4)
        keys, worst, _ = drift.linear_fit(frames, dense, [0, 24], 0.5)
        self.assertEqual(keys, [0, 24])
        self.assertAlmostEqual(worst, 0.4)

    def test_the_key_count_scales_with_the_bow_not_with_the_range(self):
        # The number that answers "what does an ease cost": it is a property of
        # how far the curve leaves its own chord, not of the interpolation
        # having a name. A 144 px bow needs every frame; a 10 px bow needs nine.
        counts = []
        for peak in (2.0, 10.0, 144.0):
            frames, dense = self.bow(peak)
            counts.append(len(drift.linear_fit(frames, dense, [0, 24], 0.5)[0]))
        self.assertEqual(counts, [3, 9, 25])

    def test_it_converges_under_the_tolerance_it_was_given(self):
        for peak in (2.0, 10.0, 144.0):
            frames, dense = self.bow(peak)
            _, worst, _ = drift.linear_fit(frames, dense, [0, 24], 0.5)
            self.assertLessEqual(worst, 0.5, "peak %g" % peak)

    def test_it_measures_every_component_not_only_the_first(self):
        # Tangents and feather ride in the same flat vector as the vertex and
        # are held to the same tolerance, which is the rule the Nuke importer's
        # _deviation already applies.
        frames = list(range(0, 5))
        dense = {f: [0.0, 0.0, 0.0, 0.0, 0.0, float(f == 2) * 10.0]
                 for f in frames}
        keys, _, _ = drift.linear_fit(frames, dense, [0, 4], 0.5)
        self.assertIn(2, keys)

    def test_a_held_segment_is_flat_and_costs_nothing(self):
        # The bug this pins: without `holds` the fit prices a held segment as a
        # straight line to the next key, reports the whole jump as drift, and
        # buys keys to flatten something already flat. A conform meant to
        # preserve holds would destroy them.
        frames = list(range(0, 5))
        dense = {0: [0.0], 1: [0.0], 2: [0.0], 3: [0.0], 4: [100.0]}
        # One key, not three: bisection reaches [0, 2, 3, 4] and the sweep
        # gives 2 back, because the line from 0 to 3 already lands on 1 and 2.
        self.assertEqual(drift.linear_fit(frames, dense, [0, 4], 0.5)[0],
                         [0, 3, 4])
        self.assertEqual(
            drift.linear_fit(frames, dense, [0, 4], 0.5, holds=[0])[0], [0, 4])

    def test_a_hold_the_bake_contradicts_is_still_measured(self):
        # The other half: `holds` is a claim about the segment, and where the
        # bake disagrees the fit must not take the claim's word for it.
        frames = list(range(0, 5))
        dense = {f: [f * 25.0] for f in frames}
        keys, worst, _ = drift.linear_fit(frames, dense, [0, 4], 0.5,
                                          holds=[0])
        self.assertGreater(len(keys), 2)
        self.assertLessEqual(worst, 0.5)

    def test_tolerance_zero_keys_every_frame(self):
        frames, dense = self.bow(144.0)
        keys, worst, at = drift.linear_fit(frames, dense, [0, 24], 0.0)
        self.assertEqual(keys, frames)
        self.assertIsNone(at)


def dense_vectors(shape):
    """The flat per-frame vectors the exporter builds, same order.

    `ae/lib/rotobridge_export.jsx` `denseVectors`, in Python: every scalar a
    destination will interpolate, laid end to end, one list per frame.
    """
    out = {}
    for name, frame in shape["frames"].items():
        flat = []
        for point in frame["points"]:
            flat += [point["c"][0], point["c"][1],
                     point["in"][0], point["in"][1],
                     point["out"][0], point["out"][1]]
            if "feather" in point:
                flat.append(point["feather"])
        if "feather_points" in frame:
            # The anchored model keeps its radii here, not on the points -
            # same rule as the jsx, or the mirror stops being one.
            for anchor in frame["feather_points"]:
                flat += [anchor["t"], anchor["feather"]]
        out[int(name)] = flat
    return out


class TestConformOverRealHostData(unittest.TestCase):
    """The conform, over an After Effects ease that After Effects really wrote.

    `test/ae_mock.js` refuses to bake a bezier segment - nothing had measured
    what AE's temporal ease does to a mask path when that refusal was written -
    so the mock cannot produce a genuinely eased dense layer and the export
    suite's conform tests all run over keys on every frame. This is the other
    half: `ae_static_ease.rbj` is a real export of a mask on a solid that does
    not move, carrying influence 91.176 in / 33.333 out over 25 frames of
    sampled geometry.

    What it pins is the claim the exporter makes: that after conforming, a
    straight line between the chosen keys reproduces the source on every frame.
    Measured here independently rather than by trusting the number `linear_fit`
    returns, for the same reason `test_ae_to_nuke_render.py` checks its
    measuring chain against arithmetic before it believes it.
    """

    def setUp(self):
        handle = open(GOLDEN_STATIC_EASE)
        try:
            self.doc = json.loads(handle.read())
        finally:
            handle.close()
        self.shapes = dict((s["name"], s) for s in self.doc["shapes"])

    def walk(self, shape):
        frames = sorted(int(f) for f in shape["frames"])
        keys = sorted(int(k["frame"]) for k in shape["keys"])
        return frames, dense_vectors(shape), keys

    def worst_line_error(self, dense, keys):
        """Independent arithmetic: a straight line between keys against truth.

        Deliberately not `drift._linear_error`. A fit that agreed with its own
        measure would pass this whatever either of them did.
        """
        worst = 0.0
        for frame in sorted(dense):
            if frame in keys:
                continue
            before = max(k for k in keys if k <= frame)
            after = min(k for k in keys if k >= frame)
            ratio = (frame - before) / float(after - before)
            for i, truth in enumerate(dense[frame]):
                drawn = (dense[before][i]
                         + (dense[after][i] - dense[before][i]) * ratio)
                worst = max(worst, abs(drawn - truth))
        return worst

    def test_the_fixture_still_has_an_ease_worth_conforming(self):
        # The control, and it comes first: every assertion below is vacuous if
        # this file were ever flattened or re-exported through the conform.
        eased = self.shapes["eased_static"]
        self.assertEqual(len(eased["keys"]), 3)
        for key in eased["keys"]:
            self.assertEqual(key["interp"], {"in": "ease", "out": "ease"})
        frames, dense, keys = self.walk(eased)
        self.assertGreater(self.worst_line_error(dense, keys), 100.0,
                           "three straight keys must miss this curve badly")

    def test_conforming_it_reproduces_the_source_on_every_frame(self):
        frames, dense, keys = self.walk(self.shapes["eased_static"])
        chosen, worst, _ = drift.linear_fit(frames, dense, keys, 0.5)
        # 135 px of bow rebuilt to under half a pixel, checked by arithmetic
        # that never touched the fit.
        self.assertLessEqual(self.worst_line_error(dense, chosen), 0.5)
        self.assertLessEqual(worst, 0.5)

    def test_it_costs_this_curve_every_frame_and_says_so(self):
        # The honest number, and the one that makes the trade visible: a 700 px
        # travel under influence 91/33 needs all 25 frames at 0.5 px. The
        # conform does not make an ease cheaper - it moves who pays. Measured
        # in Nuke 17.1v1: conformed, this shape imports with 0 corrective keys
        # against 22 before.
        frames, dense, keys = self.walk(self.shapes["eased_static"])
        chosen, _, _ = drift.linear_fit(frames, dense, keys, 0.5)
        self.assertEqual(chosen, frames)

    def test_the_linear_shape_beside_it_costs_nothing(self):
        # The calibration. If linear ever started buying keys, the number above
        # would stop being readable as the price of the ease.
        frames, dense, keys = self.walk(self.shapes["linear_static"])
        chosen, worst, _ = drift.linear_fit(frames, dense, keys, 0.5)
        self.assertEqual(chosen, keys)
        self.assertLess(worst, 0.5)


class TestConformAsAfterEffectsWroteIt(unittest.TestCase):
    """The exporter's own conform, read back out of a real host export.

    `ae_static_conformed.rbj` is `ae_static_ease.rbj`'s comp exported again
    with the conform in place, After Effects 25.6x101, 2026-08-22. The pair is
    the same two masks on the same solid, so everything that differs between
    the files is the conform and nothing else.

    `TestConformOverRealHostData` above pins the *rule* - that a straight line
    between the chosen keys reproduces a real AE ease. This pins the *wiring*:
    that `ae/lib/rotobridge_export.jsx` running under ExtendScript reaches the same
    keys as `core.drift.linear_fit` does here, over the same bake. Those are
    two implementations of one fit in two languages, and only a host run can
    put them side by side - `test/ae_mock.js` refuses to bake a bezier segment,
    so under the mock there is no eased dense layer for either to fit.
    """

    def setUp(self):
        self.before = self.read(GOLDEN_STATIC_EASE)
        self.after = self.read(GOLDEN_STATIC_CONFORMED)
        self.pairs = []
        for name in ("eased_static", "linear_static"):
            self.pairs.append((
                name,
                dict((s["name"], s) for s in self.before["shapes"])[name],
                dict((s["name"], s) for s in self.after["shapes"])[name]))

    def read(self, path):
        handle = open(path)
        try:
            return json.loads(handle.read())
        finally:
            handle.close()

    def test_the_two_files_are_the_same_fixture(self):
        # The control. Exported by hand from a comp built by hand, so the first
        # thing to establish is that a difference below is the conform rather
        # than a different scene, a different build or the wrong layer selected
        # - which is the mistake this file's own procedure warns about.
        self.assertEqual(self.before["source"], self.after["source"])
        self.assertEqual(self.before["range"], self.after["range"])
        self.assertEqual([s["name"] for s in self.before["shapes"]],
                         [s["name"] for s in self.after["shapes"]])

    def test_the_conform_never_writes_to_the_dense_layer(self):
        # It reads the bake, fits a sparse layer to it and rewrites the keys.
        # Bit-identical, not near: these are two exports of one comp, and the
        # bake does not go through the fit at all. A float away would mean the
        # fixture moved between the runs.
        for name, before, after in self.pairs:
            for frame in before["frames"]:
                for i, point in enumerate(before["frames"][frame]["points"]):
                    self.assertEqual(point,
                                     after["frames"][frame]["points"][i],
                                     "%s frame %s point %d" % (name, frame, i))

    def test_the_host_chose_the_keys_this_fit_chooses(self):
        # The point of the fixture. ExtendScript's `RB.drift.linearFit` against
        # Python's, over a dense layer After Effects baked, compared as the
        # frame list each one landed on rather than as a count.
        for name, before, after in self.pairs:
            frames = sorted(int(f) for f in before["frames"])
            keys = sorted(int(k["frame"]) for k in before["keys"])
            holds = [int(k["frame"]) for k in before["keys"]
                     if k["interp"].get("out") == "hold"]
            chosen, _, _ = drift.linear_fit(frames, dense_vectors(before),
                                            keys, 0.5, holds)
            self.assertEqual([int(k["frame"]) for k in after["keys"]], chosen,
                             name)

    def test_an_after_effects_file_no_longer_carries_ease_at_all(self):
        # The cost, stated in the file. Pinned endpoints are spelled `ease`
        # too, so the conform fires on a shape with nothing authored - which is
        # why `linear_static` is in here rather than only the eased one.
        for name, _, after in self.pairs:
            for key in after["keys"]:
                self.assertNotIn("ease", key, name)
                for side in ("in", "out"):
                    self.assertNotEqual(key["interp"].get(side), "ease", name)

    def test_only_the_authored_ease_is_warned_about(self):
        # A curve the artist drew is lost and says so; a parameterless side the
        # exporter invented is conformed silently, because nothing anyone made
        # went with it. One warning in the file, and it names the eased shape.
        self.assertEqual(len(self.after["warnings"]), 1)
        self.assertIn("eased_static", self.after["warnings"][0])
        self.assertIn("6 key side(s) carried temporal ease",
                      self.after["warnings"][0])

    def test_the_price_of_the_ease_is_in_the_file(self):
        # 3 authored keys to 25, against a linear shape beside it that still
        # costs 2. The same numbers `TestConformOverRealHostData` derives, now
        # as what the host actually wrote.
        keys = dict((name, (len(before["keys"]), len(after["keys"])))
                    for name, before, after in self.pairs)
        self.assertEqual(keys["eased_static"], (3, 25))
        self.assertEqual(keys["linear_static"], (2, 2))


class TestEs3CrossCheck(unittest.TestCase):
    """What the ExtendScript writer produces, the Python reader must accept.

    `test/test_ae_core.js` proves the port reads what Python writes. This is the
    other direction, and it is the one that decides whether an After Effects
    export can be opened in Nuke at all. Neither suite can establish it alone.

    The port is loaded exactly as an adapter loads it, `core` then `rbj`, so a
    dependency the second file has on the first cannot pass here and fail in
    the host.
    """

    def test_the_two_message_tables_are_the_same_table(self):
        # Every warning either application raises is spelled once here and once
        # in the port, because a bug report from someone else's machine arrives
        # as a screenshot and two hosts describing one loss in two ways is a
        # question nobody can answer. Nothing else checks the pair, so a typo in
        # either was invisible until an artist read it.
        script = (
            "global.RB = require(%s);"
            "process.stdout.write(JSON.stringify(RB.messages.TEMPLATES));"
        ) % json.dumps(os.path.join(AE_LIB, "rotobridge_core.jsx"))
        proc = subprocess.run([NODE, "-e", script],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            self.fail("node failed:\n" + proc.stderr.decode("utf-8", "replace"))
        theirs = json.loads(proc.stdout.decode("utf-8"))

        self.assertEqual(sorted(theirs), sorted(messages.TEMPLATES),
                         "the two tables do not carry the same codes")
        for code in sorted(messages.TEMPLATES):
            self.assertEqual(theirs[code], messages.TEMPLATES[code], code)

    def es3_rewrite(self, doc):
        """Round trip `doc` through the ExtendScript writer, via node."""
        script = (
            "global.RB = require(%s);"
            "require(%s);"
            "var chunks = [];"
            "process.stdin.on('data', function (c) { chunks.push(c); });"
            "process.stdin.on('end', function () {"
            "  var doc = RB.rbj.parse(chunks.join(''));"
            "  process.stdout.write(RB.rbj.stringify(doc));"
            "});"
        ) % (json.dumps(os.path.join(AE_LIB, "rotobridge_core.jsx")),
             json.dumps(os.path.join(AE_LIB, "rotobridge_rbj.jsx")))
        proc = subprocess.run([NODE, "-e", script],
                              input=rbj.dumps(doc).encode("utf-8"),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            self.fail("node failed:\n" + proc.stderr.decode("utf-8", "replace"))
        return proc.stdout.decode("utf-8")

    def es3_render(self, record):
        """Render an import record through the ExtendScript mirror."""
        script = (
            "global.RB = require(%s);"
            "var chunks = [];"
            "process.stdin.on('data', function (c) { chunks.push(c); });"
            "process.stdin.on('end', function () {"
            "  var rec = JSON.parse(chunks.join(''));"
            "  if (rec.tolerance === 'inf') { rec.tolerance = Infinity; }"
            "  process.stdout.write(RB.report.render(rec));"
            "});"
        ) % (json.dumps(os.path.join(AE_LIB, "rotobridge_core.jsx")),)
        # JSON has no infinity, and an unbounded tolerance is exactly one of
        # the values the two languages spell differently. It crosses as a
        # string and the script above turns it back.
        payload = dict(record)
        if payload["tolerance"] == float("inf"):
            payload["tolerance"] = "inf"
        proc = subprocess.run([NODE, "-e", script],
                              input=json.dumps(payload).encode("utf-8"),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            self.fail("node failed:\n" + proc.stderr.decode("utf-8", "replace"))
        return proc.stdout.decode("utf-8")

    def test_both_implementations_write_the_same_import_record(self):
        # Byte for byte, unlike the .rbj writers: a record is one document
        # about one import, and two hosts producing different ones would make
        # the record an argument rather than settle one. Every field that could
        # be spelled two ways is here - a whole float, a fractional one, an
        # infinity, a null worst frame and a negative offset.
        record = TestImportRecord().record(
            offset=-1000, tolerance=float("inf"),
            shapes=[{"name": "feathered", "feather_model": "anchored",
                     "points": 7, "authored": 25, "corrective": 0,
                     "residual": 0.0, "worst_frame": None},
                    {"name": "plain", "feather_model": "per_point",
                     "points": 4, "authored": 5, "corrective": 3,
                     "residual": 0.42105, "worst_frame": -988}],
            file_warnings=["shape 'plain': ease was dropped"],
            import_warnings=["shape 'feathered': 3 vertices were inserted"])
        self.assertEqual(self.es3_render(record), report.render(record))

        # And the branch an older file takes. A document held to byte
        # identity must not have a path only one implementation has run.
        source = dict(record["source"])
        source.pop("tool_version")
        older = dict(record, source=source)
        self.assertEqual(self.es3_render(older), report.render(older))

    def test_both_implementations_render_the_same_warnings(self):
        # The registry is the fence against the two hosts' prose for the same
        # loss drifting apart, which the inline sentences had already done
        # (the inverted flag was announced two different ways). Same samples
        # as TestMessages, rendered on both sides, compared byte for byte -
        # and the code LISTS are compared first, so a code added to one table
        # only fails here rather than surfacing in a host.
        script = (
            "global.RB = require(%s);"
            "var chunks = [];"
            "process.stdin.on('data', function (c) { chunks.push(c); });"
            "process.stdin.on('end', function () {"
            "  var params = JSON.parse(chunks.join(''));"
            "  var codes = RB.messages.codes();"
            "  var out = { codes: codes, rendered: {} };"
            "  for (var i = 0; i < codes.length; i++) {"
            "    if (params[codes[i]] !== undefined) {"
            "      out.rendered[codes[i]] ="
            "          RB.messages.render(codes[i], params[codes[i]]);"
            "    }"
            "  }"
            "  process.stdout.write(JSON.stringify(out));"
            "});"
        ) % (json.dumps(os.path.join(AE_LIB, "rotobridge_core.jsx")),)
        params = dict((code, TestMessages.params_for(code))
                      for code in messages.codes())
        proc = subprocess.run([NODE, "-e", script],
                              input=json.dumps(params).encode("utf-8"),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            self.fail("node failed:\n" + proc.stderr.decode("utf-8", "replace"))
        got = json.loads(proc.stdout.decode("utf-8"))
        self.assertEqual(got["codes"], messages.codes())
        for code in messages.codes():
            self.assertEqual(got["rendered"][code],
                             messages.render(code, params[code]), code)

    def test_both_implementations_fold_the_same_frames(self):
        # Same doc, folded on each side; the fold decisions must agree, or a
        # file one application wrote compact would re-export fat from the
        # other. Compared as data (json.loads both ways) because the number
        # spelling divergence (1 vs 1.0) is accepted; the SHAPE of the fold -
        # which frames are references, and to where - is not allowed to
        # differ.
        doc = TestFrameRefs().held()
        script = (
            "global.RB = require(%s);"
            "require(%s);"
            "var chunks = [];"
            "process.stdin.on('data', function (c) { chunks.push(c); });"
            "process.stdin.on('end', function () {"
            "  var doc = JSON.parse(chunks.join(''));"
            "  process.stdout.write(RB.rbj.stringify(RB.rbj.foldFrames(doc)));"
            "});"
        ) % (json.dumps(os.path.join(AE_LIB, "rotobridge_core.jsx")),
             json.dumps(os.path.join(AE_LIB, "rotobridge_rbj.jsx")))
        proc = subprocess.run([NODE, "-e", script],
                              input=json.dumps(doc).encode("utf-8"),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            self.fail("node failed:\n" + proc.stderr.decode("utf-8", "replace"))
        theirs = json.loads(proc.stdout.decode("utf-8"))
        ours = json.loads(rbj.dumps(rbj.fold_frames(doc)))
        self.assertEqual(theirs, ours)

    def test_every_copy_of_the_build_version_agrees(self):
        # The build version is what a tester reads off a screenshot and quotes
        # back, so a stale copy of it is worse than none: it names a build that
        # was never shipped. Three files hold it - the panel includes nothing
        # by design, so it cannot share the port's constant - and this is the
        # fence that keeps them equal. `tools/bump_version.py` rewrites all
        # three at once, and this fails if one is edited by hand.
        script = ("global.RB = require(%s);"
                  "process.stdout.write(RB.VERSION);"
                  ) % (json.dumps(os.path.join(AE_LIB, "rotobridge_core.jsx")),)
        proc = subprocess.run([NODE, "-e", script],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            self.fail("node failed:\n" + proc.stderr.decode("utf-8", "replace"))
        self.assertEqual(proc.stdout.decode("utf-8"), version.VERSION)

        with open(os.path.join(AE, "rotobridge_panel.jsx")) as fh:
            panel = fh.read()
        found = re.search(r'var VERSION = "([^"]+)";', panel)
        self.assertIsNotNone(found, "the panel has no VERSION constant")
        self.assertEqual(found.group(1), version.VERSION)

    def test_it_accepts_what_extendscript_writes(self):
        text = self.es3_rewrite(valid_doc())
        self.assertEqual(rbj.loads(text), valid_doc())

    def test_the_golden_files_survive_the_round_trip(self):
        for path in (GOLDEN_SQUARE, GOLDEN_ROUNDTRIP, GOLDEN_SPARSE,
                     GOLDEN_SCENE):
            with open(path) as fh:
                original = rbj.loads(fh.read())
            self.assertEqual(rbj.loads(self.es3_rewrite(original)), original,
                             os.path.basename(path))

    def test_the_writing_build_survives_the_other_implementation(self):
        # Both validators have to agree the member is legal, or a file After
        # Effects writes is one Nuke refuses to open - which for a member that
        # exists to make bug reports self-identifying would be a fine irony.
        doc = valid_doc()
        doc["source"]["tool_version"] = "0.0.1-probe"
        self.assertEqual(rbj.loads(self.es3_rewrite(doc)), doc)

    def test_an_open_spline_survives_the_other_implementation(self):
        # Both readers gate `closed: false` on the version, and both writers
        # decide the version the same way. A disagreement here is a file one
        # application writes and the other refuses to open.
        doc = valid_doc()
        doc["version"] = rbj.VERSION_OPEN_SPLINES
        doc["shapes"][0]["closed"] = False
        self.assertEqual(rbj.loads(self.es3_rewrite(doc)), doc)

    def test_anchored_feather_survives_the_other_implementation(self):
        # Both readers gate `anchored` on the version and both writers decide
        # the version the same way, so a disagreement here is a file After
        # Effects writes and Nuke refuses to open. The mid-segment t and the
        # two-on-one-segment pair are the cases v1 could not carry at all.
        doc = valid_doc()
        doc["version"] = rbj.VERSION_ANCHORED_FEATHER
        doc["shapes"][0]["feather_model"] = "anchored"
        anchors = [{"t": 0.25, "feather": 30.0},
                   {"t": 1.25, "feather": -15.0},
                   {"t": 1.75, "feather": 0.0},
                   {"t": 2.5, "feather": 12.0, "feather_offset": [1.0, -2.0]}]
        for frame in doc["shapes"][0]["frames"].values():
            frame["feather_points"] = [dict(a) for a in anchors]
        self.assertEqual(rbj.loads(self.es3_rewrite(doc)), doc)

    def test_field_order_is_preserved(self):
        # The format is meant to be diffable (spec section 2.1). Both writers
        # emit members in insertion order, so a file rewritten by the other
        # implementation should not reorder into a useless diff.
        doc = valid_doc()
        rewritten = json.loads(self.es3_rewrite(doc))
        self.assertEqual(list(rewritten.keys()), list(doc.keys()))
        self.assertEqual(list(rewritten["shapes"][0].keys()),
                         list(doc["shapes"][0].keys()))

    def test_it_accepts_a_file_the_after_effects_exporter_actually_wrote(self):
        # The rewrite tests above prove the ES3 *writer* agrees with this
        # reader. This runs the export adapter itself, against the mock host,
        # over a mask with real keyframes and a real temporal ease - so the
        # `keys` block that only the adapter ever produces is validated by the
        # implementation that has to open it in Nuke.
        script = r"""
        var fs = require('fs'), path = require('path'), vm = require('vm');
        var mock = require(%s);
        var seen = {};
        function source(file) {
            var full = path.join(%s, file);
            if (seen[full]) { return ''; }
            seen[full] = true;
            return fs.readFileSync(full, 'utf8').replace(
                /^#include\s+"([^"]+)"\s*$/gm,
                function (_, inc) { return source(inc); });
        }
        function square(dx) {
            return mock.makeShape({
                vertices: [[100 + dx, 100], [300 + dx, 100], [300 + dx, 250]],
                inTangents: [[-10, 0], [-10, 0], [10, 0]],
                outTangents: [[10, 0], [10, 0], [-10, 0]]
            });
        }
        var host = mock.install({
            frameRate: 24, workAreaStart: 0, workAreaDuration: 3 / 24,
            layers: [{ name: 'Solid 1', masks: [{
                name: 'Mask 1',
                pathKeys: [
                    { t: 0, value: square(0) },
                    { t: 1 / 24, value: square(20), inType: 6613,
                      outType: 6613, inEase: new mock.KeyframeEase(0, 91.176),
                      outEase: new mock.KeyframeEase(1, 100) },
                    { t: 2 / 24, value: square(40), inType: 6612,
                      outType: 6614 }
                ]
            }] }]
        });
        vm.runInThisContext(source('rotobridge_export.jsx'),
                            { filename: 'rotobridge_export.jsx' });
        if (host.written === null) {
            throw new Error('nothing written: ' + host.alerts.join(' | '));
        }
        process.stdout.write(host.written);
        """ % (json.dumps(os.path.join(os.path.dirname(
                   os.path.abspath(__file__)), "ae_mock.js")),
               json.dumps(AE_LIB))
        proc = subprocess.run([NODE, "-e", script],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            self.fail("node failed:\n" + proc.stderr.decode("utf-8", "replace"))

        doc = rbj.loads(proc.stdout.decode("utf-8"))
        keys = doc["shapes"][0]["keys"]
        self.assertEqual([k["frame"] for k in keys], [0, 1, 2])
        # The bezier key arrives conformed. After Effects' temporal ease has no
        # equivalent in a Nuke roto curve at all, so the exporter rewrites it as
        # linear and buys back the shape with keys rather than writing
        # parameters the destination cannot read. Nothing carries an `ease`
        # block any more, which is why this asserts its absence.
        self.assertEqual(keys[1]["interp"], {"in": "linear", "out": "linear"})
        self.assertNotIn("ease", keys[1])
        # `hold` is untouched, because Nuke's step holds it exactly.
        self.assertEqual(keys[2]["interp"], {"in": "linear", "out": "hold"})

    def test_feather_snapping_agrees_between_the_two_implementations(self):
        # The one rule with real branching in it - nearer-vertex snapping,
        # collision by magnitude, ties, wrap-around - and the one where a
        # divergence would show up as feather in the wrong place rather than as
        # a file neither reader accepts.
        cases = [
            # Probe run 3's mask, which hits every branch at once.
            ([3, 6, 1, 3], [0.9029, 0.9715, 0.0975, 1.0],
             [89.5565, 0.0, -46.6171, -1e-8], 7),
            ([], [], [], 5),                       # no points
            ([0, 0], [0.0, 0.0], [4.0, -4.0], 4),  # a tie
            ([0, 0], [0.0, 0.0], [3.0, -9.0], 4),  # sign must not decide
            ([2], [0.5], [1.0], 4),                # exactly on the boundary
            ([3], [1.0], [-2.5], 4),               # last segment, wraps
        ]
        script = (
            "global.RB = require(%s);"
            "var cases = JSON.parse(process.argv[1]);"
            "var out = [];"
            "for (var i = 0; i < cases.length; i++) {"
            "  var c = cases[i];"
            "  out.push(RB.geom.snapFeatherPoints(c[0], c[1], c[2], c[3]));"
            "}"
            "process.stdout.write(JSON.stringify(out));"
        ) % json.dumps(os.path.join(AE_LIB, "rotobridge_core.jsx"))
        proc = subprocess.run([NODE, "-e", script, json.dumps(cases)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            self.fail("node failed:\n" + proc.stderr.decode("utf-8", "replace"))
        theirs = json.loads(proc.stdout.decode("utf-8"))

        for case, got in zip(cases, theirs):
            mine = geom.snap_feather_points(*case)
            self.assertEqual(got["feather"], mine["feather"], case)
            self.assertEqual(got["snapped"], mine["snapped"], case)
            self.assertEqual(got["dropped"], mine["dropped"], case)

    def test_the_only_divergence_is_how_whole_numbers_are_spelled(self):
        # JavaScript has one number type, so its writer emits 1 where Python
        # emits 1.0. Both are the same JSON value and both readers accept
        # either, so this is not a defect - but it is the *only* difference
        # there should be, and this pins that. A second divergence appearing
        # later shows up here rather than in a host.
        doc = valid_doc()
        mine = rbj.dumps(doc)
        theirs = self.es3_rewrite(doc)
        self.assertNotEqual(theirs, mine, "the divergence is expected to exist")
        drop_trailing_zero = lambda t: re.sub(r"(\d)\.0\b", r"\1", t)
        self.assertEqual(drop_trailing_zero(theirs).splitlines(),
                         drop_trailing_zero(mine).splitlines())


if __name__ == "__main__":
    unittest.main()
