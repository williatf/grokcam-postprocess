from __future__ import annotations

import importlib.util
import sys
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image

from grokcam.config import load_calibration
from grokcam.detectors import (create_detector, detector_checkpoint,
                               restore_detector_checkpoint)
from grokcam.manifest import load_or_create
from grokcam.detectors.rolling_geometry import band_edges, pair_bands


REPOSITORY = Path(__file__).resolve().parents[1]
REFERENCE_HELPER = (REPOSITORY / "work/registration-walkthrough/Reel_46335_REDO1"
                    / "first_frames/annotate_primary_strip.py")


def reference_functions():
    spec = importlib.util.spec_from_file_location("reference_annotate_primary_strip",
                                                  REFERENCE_HELPER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sample_frame() -> Image.Image:
    pixels = np.zeros((1520, 2028, 3), dtype=np.uint8)
    pixels[220:460, 275:620] = 245
    pixels[951:1191, 275:620] = 245
    return Image.fromarray(pixels)


class RollingGeometryDetectorTests(unittest.TestCase):
    def test_original_pair_and_edge_helpers_are_preserved(self):
        source = reference_functions()
        calibration = replace(load_calibration().detector, search_x0=240,
                              search_x1=660, threshold_scale=0.96)
        bright = np.zeros((1520, 420), dtype=bool)
        bright[220:460, 35:380] = True
        bright[951:1191, 35:380] = True

        expected = source.pair_bands(bright, calibration)
        actual = pair_bands(bright, calibration)
        self.assertTrue(np.array_equal(expected[0], actual[0]))
        self.assertEqual(expected[1:], actual[1:])
        band = expected[1][0]
        self.assertEqual(source.band_edges(bright, band, calibration),
                         band_edges(bright, band, calibration))

    def test_detector_is_selectable_but_adaptive_remains_default(self):
        calibration = load_calibration()
        self.assertEqual(calibration.sprocket_detector_id, "adaptive-v1")
        detector = create_detector("rolling-geometry-v1", calibration.detector)
        self.assertEqual(detector.name, "rolling-geometry-v1")
        self.assertTrue(detector.stateful)
        with self.assertRaisesRegex(ValueError, "does not accept options"):
            create_detector("rolling-geometry-v1", calibration.detector,
                            {"threshold_scale": 0.97})

    def test_state_checkpoint_reproduces_next_detection(self):
        calibration = load_calibration().detector
        uninterrupted = create_detector("rolling-geometry-v1", calibration)
        frame = sample_frame()
        for _ in range(7):
            uninterrupted.detect(frame)
        checkpoint = detector_checkpoint(uninterrupted)

        resumed = create_detector("rolling-geometry-v1", calibration)
        restore_detector_checkpoint(resumed, checkpoint)
        self.assertEqual(resumed.get_state(), uninterrupted.get_state())
        self.assertEqual(resumed.detect(frame), uninterrupted.detect(frame))
        self.assertEqual(resumed.get_state(), uninterrupted.get_state())

    def test_checkpoint_rejects_detector_version_and_configuration_changes(self):
        calibration = load_calibration().detector
        detector = create_detector("rolling-geometry-v1", calibration)
        checkpoint = detector_checkpoint(detector)

        older = dict(checkpoint)
        older["version"] = "0"
        with self.assertRaisesRegex(RuntimeError, "different version"):
            restore_detector_checkpoint(detector, older)

        changed_calibration = replace(calibration, expected_pitch=calibration.expected_pitch + 1)
        changed = create_detector("rolling-geometry-v1", changed_calibration)
        with self.assertRaisesRegex(RuntimeError, "configuration_sha256"):
            restore_detector_checkpoint(changed, checkpoint)

    def test_resume_rejects_switching_away_from_rolling_detector(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "processing_manifest.json"
            rolling = replace(load_calibration(),
                              sprocket_detector_id="rolling-geometry-v1")
            load_or_create(manifest_path, Path("/archive/raw"), [1], 16, 1,
                           rolling, Path("ffmpeg"))
            with self.assertRaisesRegex(RuntimeError, "different sprocket detector"):
                load_or_create(manifest_path, Path("/archive/raw"), [1], 16, 1,
                               load_calibration(), Path("ffmpeg"))


if __name__ == "__main__":
    unittest.main()
