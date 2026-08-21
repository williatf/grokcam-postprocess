from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from grokcam.config import DEFAULT_MATCH_REPORT, DetectorCalibration, load_calibration
from grokcam.batch import RunOptions, finalize_if_complete, remaining_batches
from grokcam.manifest import load_or_create
from grokcam.models import SprocketDetection
from grokcam.raw_development import apply_match, load_match_report
from grokcam.registration import crop_for_detection
from grokcam.regression import compare_manifests
from grokcam.regression import frame_records
from grokcam.resume import contiguous_batches
from grokcam.sprocket_detection import detect, validate_batch


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

    def test_detector_on_synthetic_pair(self):
        image = np.zeros((1520, 2028, 3), dtype=np.uint8)
        image[100:300, 140:505] = 255
        image[885:1085, 140:505] = 255
        result = detect(Image.fromarray(image), DetectorCalibration())
        self.assertEqual(result.cx, 322.0)
        self.assertEqual(result.cy, 592.5)
        self.assertEqual(result.score, 0.0)

    def test_batch_validation_interpolates_failed_detection(self):
        values = [SprocketDetection(300, 700, 1), None, SprocketDetection(302, 704, 2)]
        result = validate_batch(values, DetectorCalibration())
        self.assertEqual((result[1].cx, result[1].cy), (301.0, 702.0))
        self.assertTrue(result[1].interpolated)
        self.assertFalse(result[1].detected)

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
            self.assertEqual(manifest["frame_range"], [10, 11])
            self.assertEqual(manifest["crop"]["width"], 1133)
            self.assertEqual(manifest["raw_development_calibration"]["sha256"],
                             "d5a4526b6b5e38fd9d7b37876b0ec39cb37a370d066419433db38f978cb3dc96")
            self.assertTrue(path.exists())

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
