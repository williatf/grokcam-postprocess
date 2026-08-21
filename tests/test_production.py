from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from grokcam.config import DetectorCalibration, load_calibration
from grokcam.models import SprocketDetection
from grokcam.raw_development import apply_match, load_match_report
from grokcam.registration import crop_for_detection
from grokcam.regression import compare_manifests
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

    def test_match_report_and_transform(self):
        report_path = Path("/mnt/GrokCam/projects/RAW_Test/outputs/rawpy-darktable-match-poc/poc-report.json")
        if not report_path.exists():
            self.skipTest("production match report is not mounted")
        report = load_match_report(report_path)
        sample = np.full((2, 2, 3), 0.25, dtype=np.float32)
        transformed = apply_match(sample, report["fit"])
        self.assertEqual(transformed.shape, sample.shape)
        self.assertTrue(np.all(np.isfinite(transformed)))

    def test_golden_manifest_comparison(self):
        reference = Path("work/matched-timed-proof/processing_manifest.json")
        if not reference.exists():
            self.skipTest("checked proof manifest is unavailable")
        result = compare_manifests(reference, reference)
        self.assertEqual(result["compared_frames"], 4)
        self.assertEqual(max(result["maximum_geometry_difference"].values()), 0.0)
        self.assertEqual(result["detector_mismatches"], 0)


if __name__ == "__main__":
    unittest.main()
