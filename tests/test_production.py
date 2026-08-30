from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from grokcam.config import (DEFAULT_MATCH_REPORT, DetectorCalibration,
                            VerticalStabilizationCalibration, load_calibration)
from grokcam.batch import (RunOptions, finalize_if_complete, preserve_excluded_tiff,
                           remaining_batches)
from grokcam.manifest import PIPELINE_ID, load_or_create
from grokcam.models import SprocketDetection
from grokcam.raw_development import apply_match, load_match_report
from grokcam.registration import crop_for_detection
from grokcam.regression import compare_manifests
from grokcam.regression import frame_records
from grokcam.resume import contiguous_batches
from grokcam.sprocket_detection import detect, validate_batch
from grokcam.sprocket_detection import validate_batch_with_physical
from grokcam.physical_sprocket import (DETECTOR_MODE, FROZEN_CONFIG,
                                      PhysicalPairResult, fit_pair)
from grokcam.vertical_stabilization import (FrameMeasurements, ResidualMeasurement,
                                            measure_frame, resolve_batch)


class ProductionTests(unittest.TestCase):
    def test_default_crop_geometry_is_golden(self):
        calibration = load_calibration()
        crop = crop_for_detection(SprocketDetection(300.0, 800.0, 0.0), calibration.crop)
        self.assertEqual((crop.left, crop.top, crop.width, crop.height), (459.0, 387.0, 1133, 900))

    def test_calibration_rejects_unknown_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            path.write_text('{"mystery": 2}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown calibration"):
                load_calibration(path)

    def test_vertical_stabilization_is_disabled_by_default(self):
        self.assertFalse(load_calibration().vertical_stabilization.enabled)

    def test_vertical_calibration_override_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            path.write_text('{"vertical_stabilization": {"enabled": true}}', encoding="utf-8")
            self.assertTrue(load_calibration(path).vertical_stabilization.enabled)

    def test_detector_on_synthetic_pair(self):
        image = np.zeros((1520, 2028, 3), dtype=np.uint8)
        image[100:300, 140:505] = 255
        image[885:1085, 140:505] = 255
        result = detect(Image.fromarray(image), DetectorCalibration())
        self.assertEqual(result.cx, 322.0)
        self.assertEqual(result.cy, 592.5)
        self.assertEqual(result.score, 0.0)

    def test_adaptive_top_search_only_follows_rejected_primary_failure(self):
        image = np.zeros((900, 1133, 3), dtype=np.uint8)
        image[60:142, 0:90] = 255
        image[674:900, 0:90] = 255
        rejected = SprocketDetection(300, 700, 1, accepted=False)
        measured = measure_frame(Image.fromarray(image), rejected,
                                 VerticalStabilizationCalibration(enabled=True))
        self.assertEqual(measured.search_mode, "expanded")
        self.assertAlmostEqual(measured.selected_top.y, 141.5, delta=2.0)

    def test_large_residual_correction_adjusts_crop_without_cap(self):
        config = VerticalStabilizationCalibration(enabled=True)
        top = ResidualMeasurement(128.1190476191, 1.0, .1, .2, 0.0)
        bottom = ResidualMeasurement(666.0, 1.0, .1, .2, .5)
        measured = FrameMeasurements(top, None, top, "normal", bottom)
        crop = crop_for_detection(SprocketDetection(300, 800, 1), load_calibration().crop)
        result = resolve_batch([measured], [crop], [1520], config)[0]
        self.assertEqual(result.source, "measured")
        self.assertAlmostEqual(result.correction_y, 96.8095238095)
        self.assertAlmostEqual(result.corrected_crop.top, crop.top + 96.8095238095)

    def test_invalid_top_uses_bottom_rescue_not_dirty_large_edge(self):
        config = VerticalStabilizationCalibration(enabled=True)
        dirty = ResidualMeasurement(196.0, 1.0, .1, .2, .8)
        bottom = ResidualMeasurement(756.0, 1.0, .1, .2, .5)
        measured = FrameMeasurements(dirty, None, dirty, "normal", bottom)
        crop = crop_for_detection(SprocketDetection(300, 800, 1), load_calibration().crop)
        result = resolve_batch([measured], [crop], [1520], config)[0]
        self.assertEqual(result.source, "bottom_rescue")
        self.assertEqual(result.correction_y, 1.0)

    def test_failed_same_frame_measurements_interpolate_correction(self):
        config = VerticalStabilizationCalibration(enabled=True)
        valid_a = ResidualMeasurement(config.top_reference_y - 10, 1.0, .1, .2, 0.0)
        invalid = ResidualMeasurement(None, 0.0)
        valid_b = ResidualMeasurement(config.top_reference_y - 20, 1.0, .1, .2, 0.0)
        bad_bottom = ResidualMeasurement(None, 0.0)
        values = [FrameMeasurements(item, None, item, "normal", bad_bottom)
                  for item in (valid_a, invalid, valid_b)]
        crop = crop_for_detection(SprocketDetection(300, 700, 1), load_calibration().crop)
        results = resolve_batch(values, [crop] * 3, [1520] * 3, config)
        self.assertEqual(results[1].source, "interpolated")
        self.assertAlmostEqual(results[1].correction_y, 15.0)

    def test_bounded_corrected_crop_has_no_synthetic_black_fill(self):
        image = Image.new("RGB", (2028, 1520), "white")
        crop = crop_for_detection(SprocketDetection(300, 800, 1), load_calibration().crop)
        from grokcam.image_processing import registered_frame
        output = registered_frame(image, crop, load_calibration().contrast)
        self.assertEqual(np.asarray(output).min(), 255)

    def test_blue_reel_named_vertical_regressions(self):
        """Freeze production decisions measured on Blue Reel 3000--3999."""
        config = VerticalStabilizationCalibration(enabled=True)
        # frame: (top y, top tail, bottom y, mode, expected source, correction)
        cases = {
            3260: (211.0454545455, .2934, 756.5, "normal", "measured", 13.8831),
            3451: (178.0, .0047, 714.5, "normal", "measured", 46.9286),
            3487: (128.1190476190, .0047, 665.8333, "expanded", "expanded_residual", 96.8095),
            3615: (195.9666666667, .3578, 755.3888888889, "normal", "bottom_rescue", 1.6111),
            3676: (205.9285714286, .3047, 758.0, "normal", "bottom_rescue", -1.0),
            3754: (157.7222222222, .0060, 687.0, "normal", "measured", 67.2063),
            3846: (167.8333333333, .0023, 699.7, "normal", "measured", 57.0952),
            3882: (142.5, .0058, 673.5, "expanded", "expanded_residual", 82.4286),
        }
        crop = crop_for_detection(SprocketDetection(300, 700, 1), load_calibration().crop)
        for frame, (top_y, tail, bottom_y, mode, source, correction) in cases.items():
            with self.subTest(frame=frame):
                top = ResidualMeasurement(top_y, 1.0, .05, .20, tail)
                bottom = ResidualMeasurement(bottom_y, 1.0, .03, .10, .20)
                measured = FrameMeasurements(top, top if mode == "expanded" else None,
                                             top, mode, bottom)
                result = resolve_batch([measured], [crop], [1520], config)[0]
                self.assertEqual(result.source, source)
                self.assertAlmostEqual(result.correction_y, correction, places=3)

    def test_batch_validation_interpolates_failed_detection(self):
        values = [SprocketDetection(300, 700, 1), None, SprocketDetection(302, 704, 2)]
        result = validate_batch(values, DetectorCalibration())
        self.assertEqual((result[1].cx, result[1].cy), (301.0, 702.0))
        self.assertTrue(result[1].interpolated)
        self.assertFalse(result[1].detected)

    def test_physical_mode_does_not_invoke_p07_on_clean_frames(self):
        values = [SprocketDetection(300, 700, 1), SprocketDetection(301, 701, 1)]
        with patch("grokcam.physical_sprocket.detect_fallback") as physical:
            result, details = validate_batch_with_physical(
                lambda _index: Image.new("RGB", (2028, 1520)), values, DetectorCalibration())
        physical.assert_not_called()
        self.assertEqual([d.detector for d in result], ["primary", "primary"])
        self.assertTrue(all(d["final_registration_source"] == "primary" for d in details))

    def test_p07_same_frame_result_precedes_interpolation(self):
        values = [SprocketDetection(300, 700, 1), None, SprocketDetection(302, 704, 1)]
        recovered = PhysicalPairResult(True, "joint_pair_recovery", 410.0, 820.0,
                                       {"classification": "joint_pair_recovery"})
        with patch("grokcam.physical_sprocket.detect_fallback", return_value=recovered):
            result, details = validate_batch_with_physical(
                lambda _index: Image.new("RGB", (2028, 1520)), values, DetectorCalibration())
        self.assertEqual((result[1].cx, result[1].cy), (410.0, 820.0))
        self.assertFalse(result[1].interpolated)
        self.assertEqual(result[1].detector, "physical_p07")
        self.assertTrue(details[1]["p07_accepted"])

    def test_fallback_preserves_rejected_primary_and_capture_roi_provenance(self):
        values = [SprocketDetection(300, 700, 1), SprocketDetection(500, 900, 9),
                  SprocketDetection(302, 704, 1)]
        recovered = PhysicalPairResult(True, "joint_pair_recovery", 410.0, 820.0,
            {"classification": "joint_pair_recovery", "stage": "p07",
             "capture_roi_boxes": [[100, 200, 300, 250]], "independent_holes": [None, None]})
        with patch("grokcam.physical_sprocket.detect_fallback", return_value=recovered):
            _result, details = validate_batch_with_physical(
                lambda _index: Image.new("RGB", (2028, 1520)), values,
                DetectorCalibration(), [{}, {"capture": True}, {}])
        self.assertEqual(details[1]["primary_rejected_anchor"], {"x": 500, "y": 900, "score": 9})
        self.assertEqual(details[1]["physical_diagnostics"]["capture_roi_boxes"],
                         [[100, 200, 300, 250]])

    def test_p07_ambiguity_is_excluded_not_interpolated(self):
        values = [SprocketDetection(300, 700, 1), None, SprocketDetection(302, 704, 1)]
        rejected = PhysicalPairResult(False, "ambiguous_competing_pair_positions", None, None,
                                      {"classification": "ambiguous_competing_pair_positions"})
        with patch("grokcam.physical_sprocket.detect_fallback", return_value=rejected):
            result, details = validate_batch_with_physical(
                lambda _index: Image.new("RGB", (2028, 1520)), values, DetectorCalibration())
        self.assertIsNone(result[1])
        self.assertIsNone(details[1]["final_registration_source"])
        self.assertEqual(details[1]["output_disposition"], "excluded")
        self.assertEqual(details[1]["exclusion_reason"],
                         "ambiguous_competing_pair_positions")

    def test_p07_excludes_unresolved_batch_edge(self):
        values = [None, SprocketDetection(300, 700, 1)]
        rejected = PhysicalPairResult(False, "insufficient_joint_support", None, None, {})
        with patch("grokcam.physical_sprocket.detect_fallback", return_value=rejected):
            result, details = validate_batch_with_physical(
                lambda _index: Image.new("RGB", (2028, 1520)), values,
                DetectorCalibration())
        self.assertIsNone(result[0])
        self.assertEqual(details[0]["output_disposition"], "excluded")

    def test_p07_excludes_multi_frame_run_and_continues(self):
        values = [SprocketDetection(300, 700, 1), None, None,
                  SprocketDetection(301, 701, 1)]
        rejected = PhysicalPairResult(False, "insufficient_joint_support", None, None, {})
        with patch("grokcam.physical_sprocket.detect_fallback", return_value=rejected):
            result, details = validate_batch_with_physical(
                lambda _index: Image.new("RGB", (2028, 1520)), values,
                DetectorCalibration())
        self.assertEqual([item is None for item in result], [False, True, True, False])
        self.assertEqual([details[i]["output_disposition"] for i in (1, 2)],
                         ["excluded", "excluded"])
        self.assertEqual(result[3].cx, 301)

    def test_excluded_debug_tiff_is_exact_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "frame_002606.tif"
            source.write_bytes(b"developed-tiff-evidence")
            destination = preserve_excluded_tiff(source, root / "output")
            self.assertEqual(destination.read_bytes(), source.read_bytes())
            self.assertEqual(destination.name, "frame_002606.tif")

    def test_p07_anchor_flows_into_residual_coordinate_then_one_final_crop(self):
        p07 = SprocketDetection(410.0, 820.0, None, detector="physical_p07")
        primary_crop = crop_for_detection(p07, load_calibration().crop)
        config = VerticalStabilizationCalibration(enabled=True)
        top = ResidualMeasurement(config.top_reference_y - 12.5, 1.0, .1, .2, 0.0)
        bottom = ResidualMeasurement(config.bottom_reference_y - 12.5, 1.0, .1, .2, .2)
        measured = FrameMeasurements(top, None, top, "normal", bottom)
        resolved = resolve_batch([measured], [primary_crop], [1520], config)[0]
        self.assertEqual((primary_crop.left, primary_crop.top), (569.0, 407.0))
        self.assertEqual(resolved.source, "measured")
        self.assertEqual(resolved.corrected_crop.top, 419.5)
        source = Image.new("RGB", (2028, 1520), "white")
        with patch("PIL.Image.Image.transform", autospec=True,
                   side_effect=Image.Image.transform) as sample:
            from grokcam.image_processing import registered_frame
            output = registered_frame(source, resolved.corrected_crop, 1.0)
        self.assertEqual(output.size, (1133, 900))
        self.assertEqual(sample.call_count, 1)

    def test_production_p07_is_exact_to_cached_oracle_on_same_input(self):
        from research.p07_exact_cached_candidate_poc import fit_pair_cached
        image = np.random.default_rng(7).integers(0, 256, (1520, 2028, 3), dtype=np.uint8)
        oracle = fit_pair_cached(image, [], [], None, FROZEN_CONFIG)
        self.assertEqual(fit_pair(image), oracle)

    def test_resume_batches_do_not_bridge_gaps(self):
        paths = [Path(f"frame_{n:06d}.dng") for n in (1, 2, 4, 5, 6)]
        number = lambda p: int(p.stem.rsplit("_", 1)[1])
        batches = contiguous_batches(paths, number, 2)
        self.assertEqual([[number(p) for p in b] for b in batches], [[1, 2], [4, 5], [6]])

    def test_segment_plan_preserves_only_verified_existing_video(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kept = root / "kept.mp4"
            kept.touch()
            dngs = [root / f"frame_{n:06d}.dng" for n in range(1, 6)]
            manifest = {"segments": [
                {"first": 1, "last": 2, "video": str(kept), "verified": True},
                {"first": 3, "last": 3, "video": str(root / "missing.mp4"), "verified": True},
            ]}
            completed, batches = remaining_batches(dngs, manifest, 2)
            self.assertEqual([(item["first"], item["last"]) for item in completed], [(1, 2)])
            self.assertEqual([[int(p.stem[-6:]) for p in batch] for batch in batches], [[3, 4], [5]])

    def test_manifest_creation_records_read_only_source_and_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "processing_manifest.json"
            with patch("grokcam.manifest.tool_version", return_value="ffmpeg test"):
                manifest = load_or_create(path, Path("/archive/raw"), [10, 11], 16, 2,
                                          load_calibration(), Path("ffmpeg"))
            self.assertEqual(manifest["source_policy"], "read_only")
            self.assertEqual(PIPELINE_ID, "grokcam_postprocess")
            self.assertEqual(manifest["pipeline"], PIPELINE_ID)
            self.assertEqual(manifest["frame_range"], [10, 11])
            self.assertEqual(manifest["crop"]["width"], 1133)
            self.assertEqual(manifest["raw_development_calibration"]["sha256"],
                             "d5a4526b6b5e38fd9d7b37876b0ec39cb37a370d066419433db38f978cb3dc96")
            self.assertTrue(path.exists())

    def test_manifest_records_physical_mode_and_rejects_mixed_resume(self):
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "processing_manifest.json"
            physical = replace(load_calibration(), sprocket_detector_mode=DETECTOR_MODE)
            with patch("grokcam.manifest.tool_version", return_value="ffmpeg test"):
                manifest = load_or_create(path, Path("/archive/raw"), [1], 16, 1,
                                          physical, Path("ffmpeg"))
                self.assertEqual(manifest["sprocket_registration"]["mode"], DETECTOR_MODE)
                with self.assertRaisesRegex(RuntimeError, "different sprocket detector"):
                    load_or_create(path, Path("/archive/raw"), [1], 16, 1,
                                   load_calibration(), Path("ffmpeg"))
                manifest["sprocket_registration"]["production_module_sha256"] = "wrong"
                path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "production module hash"):
                    load_or_create(path, Path("/archive/raw"), [1], 16, 1,
                                   physical, Path("ffmpeg"))
                manifest["sprocket_registration"]["production_module_sha256"] = \
                    __import__("grokcam.manifest", fromlist=["physical_module_sha256"]).physical_module_sha256()
                manifest["sprocket_registration"]["failure_policy"] = "legacy_interpolation"
                path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "failure policy"):
                    load_or_create(path, Path("/archive/raw"), [1], 16, 1,
                                   physical, Path("ffmpeg"))

    def test_finalization_records_verified_movie_and_removes_segments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            segments = root / "segments"
            segments.mkdir()
            video = segments / "frames_000001_000002_16fps.mp4"
            video.write_bytes(b"segment")
            dngs = [root / "frame_000001.dng", root / "frame_000002.dng"]
            manifest = {"segments": [{"first": 1, "last": 2, "video": str(video), "verified": True}]}
            manifest_path = root / "processing_manifest.json"
            options = RunOptions(root, root, fps=16)

            def fake_concat(_ffmpeg, _concat, _paths, temporary):
                temporary.write_bytes(b"joined")

            with patch("grokcam.batch.concatenate_segments", side_effect=fake_concat), \
                 patch("grokcam.batch.verify_video", return_value={"streams": [{"nb_frames": "2"}]}):
                final = finalize_if_complete(options, dngs, manifest, manifest_path, segments)
            self.assertEqual(final.read_bytes(), b"joined")
            self.assertTrue(manifest["final"]["verified"])
            self.assertFalse(video.exists())
            self.assertTrue(manifest_path.exists())

    def test_finalization_records_source_to_encoded_mapping_and_exclusion_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); segments = root / "segments"; segments.mkdir()
            video = segments / "frames_000001_000004_16fps.mp4"; video.write_bytes(b"segment")
            debug = root / "debug" / "excluded_frames" / "frame_000002.tif"
            records = [
                {"frame": 1, "output_disposition": "included", "encoded_output_frame": 1},
                {"frame": 2, "output_disposition": "excluded", "encoded_output_frame": None,
                 "exclusion_reason": "insufficient_joint_support", "debug_developed_image": str(debug)},
                {"frame": 3, "output_disposition": "excluded", "encoded_output_frame": None,
                 "exclusion_reason": "insufficient_joint_support", "debug_developed_image": str(debug)},
                {"frame": 4, "output_disposition": "included", "encoded_output_frame": 2},
            ]
            manifest = {"segments": [{"first": 1, "last": 4, "frames": 2,
                                       "video": str(video), "verified": True,
                                       "frame_records": records}]}
            dngs = [root / f"frame_{n:06d}.dng" for n in range(1, 5)]
            options = RunOptions(root, root, fps=16)
            def fake_concat(_ffmpeg, _concat, _paths, temporary): temporary.write_bytes(b"joined")
            with patch("grokcam.batch.concatenate_segments", side_effect=fake_concat), \
                 patch("grokcam.batch.verify_video", return_value={"streams": [{"nb_frames": "2"}]}):
                finalize_if_complete(options, dngs, manifest, root / "manifest.json", segments)
            self.assertEqual(manifest["frame_mapping"], {
                "source_frames": 4, "included_frames": 2, "excluded_frames": 2,
                "encoded_frames": 2, "invariants_valid": True})
            run = manifest["exclusion_runs"][0]
            self.assertEqual((run["first"], run["last"], run["length"]), (2, 3, 2))
            self.assertEqual(run["duration_seconds"], .125)
            self.assertEqual((run["preceding_trusted_frame"], run["following_trusted_frame"]), (1, 4))

    def test_match_report_and_transform(self):
        report_path = DEFAULT_MATCH_REPORT
        report = load_match_report(report_path)
        sample = np.full((2, 2, 3), 0.25, dtype=np.float32)
        transformed = apply_match(sample, report["fit"])
        self.assertEqual(transformed.shape, sample.shape)
        self.assertTrue(np.all(np.isfinite(transformed)))

    def test_golden_calibration_identity_is_frozen(self):
        self.assertEqual(hashlib.sha256(DEFAULT_MATCH_REPORT.read_bytes()).hexdigest(),
                         "d5a4526b6b5e38fd9d7b37876b0ec39cb37a370d066419433db38f978cb3dc96")
        report = load_match_report(DEFAULT_MATCH_REPORT)
        self.assertEqual(np.asarray(report["fit"]["coefficients"]).shape, (13, 3))
        self.assertEqual(np.asarray(report["fit"]["luts"]).shape, (3, 256))
        self.assertEqual(report["fit"]["white_balance_correction"],
                         [1.06982421875, 1.0, 1.0991804599761963, 1.0])

    def test_golden_manifest_comparison(self):
        reference = Path("work/matched-timed-proof/processing_manifest.json")
        if not reference.exists():
            self.skipTest("checked proof manifest is unavailable")
        data = json.loads(reference.read_text(encoding="utf-8"))
        records = frame_records(data)
        expected = {
            120: (406.0, 777.0, 565.0, 364.0),
            121: (405.25, 782.5, 564.25, 369.5),
            122: (407.5, 775.5, 566.5, 362.5),
            123: (405.5, 762.25, 564.5, 349.25),
        }
        actual = {number: tuple(records[number][field] for field in
                  ("anchor_x", "anchor_y", "crop_left", "crop_top")) for number in records}
        self.assertEqual(actual, expected)
        self.assertEqual(data["final"]["video_sha256"],
                         "bc13e671530a3483dce0f510c1420ad32cf481c942956a8221197297541c5f76")
        result = compare_manifests(reference, reference)
        self.assertEqual(result["compared_frames"], 4)
        self.assertEqual(max(result["maximum_geometry_difference"].values()), 0.0)
        self.assertEqual(result["detector_mismatches"], 0)


if __name__ == "__main__":
    unittest.main()
