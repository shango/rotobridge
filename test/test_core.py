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
import os
import re
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import drift, geom, interp, rbj, timing

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")
GOLDEN_SQUARE = os.path.join(GOLDEN, "square.rbj")
GOLDEN_ROUNDTRIP = os.path.join(GOLDEN, "roundtrip.rbj")
GOLDEN_SPARSE = os.path.join(GOLDEN, "sparse.rbj")

COMP_HEIGHT = 1080

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AE = os.path.join(REPO, "ae")
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
        self.reject(lambda d: d.update(version=2), "newer than this reader")

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

    def test_open_spline(self):
        self.reject(lambda d: d["shapes"][0].update(closed=False),
                    "open splines are out of scope")

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

    def test_an_invalid_document_names_the_shape(self):
        doc = valid_doc()
        doc["shapes"][0]["frames"]["11"]["points"].pop()
        errs = rbj.validate(doc)
        self.assertIn("'tri'", " | ".join(errs))


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

    def test_step_is_outgoing_only(self):
        # Case 63: a step key moved eval(75) to the key value and left eval(25)
        # at the cubic default, so it governs the leaving segment alone.
        self.assertEqual(interp.sides_from_nuke(interp.NUKE_STEP),
                         {"in": "linear", "out": "hold"})

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
        self.assertEqual(interp.to_nuke({"in": "linear", "out": "hold"}),
                         (interp.NUKE_STEP, True))

    def test_hold_out_is_exact_whatever_arrives(self):
        # Nuke's step governs the leaving segment only, so there is no
        # incoming side to lose and no warning to raise.
        self.assertEqual(interp.to_nuke({"in": "ease", "out": "hold"}),
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
class TestEs3CrossCheck(unittest.TestCase):
    """What the ExtendScript writer produces, the Python reader must accept.

    `test/test_ae_core.js` proves the port reads what Python writes. This is the
    other direction, and it is the one that decides whether an After Effects
    export can be opened in Nuke at all. Neither suite can establish it alone.

    The port is loaded exactly as an adapter loads it, `core` then `rbj`, so a
    dependency the second file has on the first cannot pass here and fail in
    the host.
    """

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
        ) % (json.dumps(os.path.join(AE, "rotobridge_core.jsx")),
             json.dumps(os.path.join(AE, "rotobridge_rbj.jsx")))
        proc = subprocess.run([NODE, "-e", script],
                              input=rbj.dumps(doc).encode("utf-8"),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            self.fail("node failed:\n" + proc.stderr.decode("utf-8", "replace"))
        return proc.stdout.decode("utf-8")

    def test_it_accepts_what_extendscript_writes(self):
        text = self.es3_rewrite(valid_doc())
        self.assertEqual(rbj.loads(text), valid_doc())

    def test_the_golden_files_survive_the_round_trip(self):
        for path in (GOLDEN_SQUARE, GOLDEN_ROUNDTRIP, GOLDEN_SPARSE):
            with open(path) as fh:
                original = rbj.loads(fh.read())
            self.assertEqual(rbj.loads(self.es3_rewrite(original)), original,
                             os.path.basename(path))

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
               json.dumps(AE))
        proc = subprocess.run([NODE, "-e", script],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            self.fail("node failed:\n" + proc.stderr.decode("utf-8", "replace"))

        doc = rbj.loads(proc.stdout.decode("utf-8"))
        keys = doc["shapes"][0]["keys"]
        self.assertEqual([k["frame"] for k in keys], [0, 1, 2])
        self.assertEqual(keys[1]["interp"], {"in": "ease", "out": "ease"})
        self.assertAlmostEqual(keys[1]["ease"]["in"][0], 0.91176)
        self.assertEqual(keys[1]["ease"]["out"], [1.0, 1.0])
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
        ) % json.dumps(os.path.join(AE, "rotobridge_core.jsx"))
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
