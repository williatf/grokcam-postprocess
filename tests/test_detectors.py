from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from PIL import Image

from grokcam.config import load_calibration
from grokcam.detectors import (DetectorDiagnostics, DetectorResult,
                               create_detector, detector_checkpoint,
                               register_detector, registered_detectors,
                               restore_state_before_frame, unregister_detector)
from grokcam.manifest import load_or_create
from grokcam.models import SprocketDetection


class MockStatefulDetector:
    name = "mock-stateful-test"
    version = "1"
    stateful = True

    def __init__(self, calibration, options=None):
        self.count = 0
        self.configuration_value = {"threshold_scale": calibration.threshold_scale}

    def detect(self, image):
        self.count += 1
        return DetectorResult(
            SprocketDetection(float(self.count), float(image.width), 1.0),
            DetectorDiagnostics(self.name, self.version, True,
                                confidence=0.9, fallback_used=self.count > 1),
        )

    def configuration(self):
        return self.configuration_value

    def get_state(self):
        return {"count": self.count}

    def restore_state(self, state):
        self.count = int(state["count"])


class DetectorArchitectureTests(unittest.TestCase):
    def test_only_existing_production_detector_is_registered_by_default(self):
        self.assertEqual(registered_detectors(),
                         ("adaptive-v1", "rolling-geometry-v1"))
        self.assertEqual(load_calibration().sprocket_detector_id, "rolling-geometry-v1")
        with self.assertRaisesRegex(ValueError, "unknown sprocket detector"):
            create_detector("not-registered", load_calibration().detector)

    def test_configuration_accepts_new_pair_and_legacy_registration_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            path.write_text(json.dumps({"sprocket": {
                "detector": "adaptive-v1", "registration": "legacy"}}))
            nested = load_calibration(path)
            self.assertEqual(nested.sprocket_detector_id, "adaptive-v1")
            self.assertEqual(nested.sprocket_detector_mode, "legacy")
            self.assertEqual(nested.to_dict()["sprocket"], {
                "detector": "adaptive-v1", "registration": "legacy"})
            self.assertNotIn("sprocket_detector_id", nested.to_dict())
            self.assertNotIn("sprocket_detector_options", nested.to_dict())
            self.assertNotIn("sprocket_detector_mode", nested.to_dict())

            path.write_text('{"sprocket_detector_mode": "legacy"}')
            old = load_calibration(path)
            self.assertEqual(old.sprocket_detector_id, "rolling-geometry-v1")
            self.assertEqual(old.sprocket_detector_mode, "legacy")

            path.write_text('{"sprocket": {"registration": "legacy"}, '
                            '"sprocket_detector_mode": "physical-p07-v1"}')
            with self.assertRaisesRegex(ValueError, "conflicts"):
                load_calibration(path)

            path.write_text(json.dumps({"sprocket": {"detector": "adaptive-v1",
                                                       "options": {"rolling": True}}}))
            calibration = load_calibration(path)
            with self.assertRaisesRegex(ValueError, "does not accept"):
                create_detector(calibration.sprocket_detector_id,
                                calibration.detector,
                                calibration.sprocket_detector_options)

    def test_adaptive_adapter_preserves_existing_detector_result(self):
        import numpy as np
        from grokcam.sprocket_detection import detect

        image = np.zeros((1520, 2028, 3), dtype=np.uint8)
        image[100:300, 140:505] = 255
        image[885:1085, 140:505] = 255
        pil_image = Image.fromarray(image)
        calibration = load_calibration().detector
        expected = detect(pil_image, calibration)
        result = create_detector("adaptive-v1", calibration).detect(pil_image)
        self.assertEqual(result.detection, expected)
        self.assertEqual(result.diagnostics.detector, "adaptive-v1")
        self.assertEqual(result.diagnostics.version, "1")
        self.assertTrue(result.diagnostics.success)

    def test_state_restores_across_a_completed_batch_boundary(self):
        register_detector("mock-stateful-test", MockStatefulDetector)
        try:
            calibration = load_calibration().detector
            uninterrupted = create_detector("mock-stateful-test", calibration)
            image = Image.new("RGB", (40, 20))
            uninterrupted.detect(image)
            uninterrupted.detect(image)
            checkpoint = detector_checkpoint(uninterrupted)
            manifest = {"segments": [{"first": 1, "last": 2, "verified": True,
                                      "sprocket_detector_checkpoint": checkpoint}]}

            resumed = create_detector("mock-stateful-test", calibration)
            restored_after = restore_state_before_frame(
                resumed, manifest, 3, initial_state={"count": 0})
            resumed_result = resumed.detect(image)
            uninterrupted_result = uninterrupted.detect(image)
            self.assertEqual(restored_after, 2)
            self.assertEqual(resumed_result, uninterrupted_result)
            self.assertEqual(resumed.get_state(), {"count": 3})
        finally:
            unregister_detector("mock-stateful-test")

    def test_stateful_resume_rejects_prior_segment_without_checkpoint(self):
        register_detector("mock-stateful-test", MockStatefulDetector)
        try:
            detector = create_detector("mock-stateful-test", load_calibration().detector)
            manifest = {"segments": [{"first": 1, "last": 2, "verified": True}]}
            with self.assertRaisesRegex(RuntimeError, "has no detector checkpoint"):
                restore_state_before_frame(detector, manifest, 3, initial_state={"count": 0})
        finally:
            unregister_detector("mock-stateful-test")

    def test_checkpoint_rejects_detector_version_mismatch(self):
        from grokcam.detectors import restore_detector_checkpoint

        register_detector("mock-stateful-test", MockStatefulDetector)
        try:
            detector = create_detector("mock-stateful-test", load_calibration().detector)
            checkpoint = detector_checkpoint(detector)
            checkpoint["version"] = "older"
            with self.assertRaisesRegex(RuntimeError, "different version"):
                restore_detector_checkpoint(detector, checkpoint)
        finally:
            unregister_detector("mock-stateful-test")

    def test_manifest_rejects_detector_configuration_change_on_resume(self):
        register_detector("mock-stateful-test", MockStatefulDetector)
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "processing_manifest.json"
                calibration = replace(load_calibration(),
                                      sprocket_detector_id="mock-stateful-test")
                load_or_create(path, Path("/archive/raw"), [1], 16, 1,
                               calibration, Path("ffmpeg"))
                changed = replace(
                    calibration,
                    detector=replace(calibration.detector, threshold_scale=0.91),
                )
                with self.assertRaisesRegex(RuntimeError, "different sprocket detector"):
                    load_or_create(path, Path("/archive/raw"), [1], 16, 1,
                                   changed, Path("ffmpeg"))
        finally:
            unregister_detector("mock-stateful-test")

    def test_legacy_manifest_without_detector_identity_resumes_with_adaptive_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "processing_manifest.json"
            # Historical manifests without detector metadata were produced by
            # adaptive-v1. Resume them only when that detector is selected.
            calibration = replace(load_calibration(),
                                  sprocket_detector_id="adaptive-v1")
            load_or_create(path, Path("/archive/raw"), [1], 16, 1,
                           calibration, Path("ffmpeg"))
            manifest = json.loads(path.read_text())
            manifest.pop("sprocket_detection")
            path.write_text(json.dumps(manifest))
            resumed = load_or_create(path, Path("/archive/raw"), [1], 16, 1,
                                     calibration, Path("ffmpeg"))
            self.assertEqual(resumed["sprocket_detection"]["name"], "adaptive-v1")


if __name__ == "__main__":
    unittest.main()
