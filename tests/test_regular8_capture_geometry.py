from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from grokcam.batch import RunOptions, _run_reel_core
from grokcam.api import ProcessingConfig
from grokcam.config import (Regular8CaptureGeometry, load_calibration,
                            load_capture_geometry)
from grokcam.events import EventEmitter
from grokcam.manifest import load_or_create
from grokcam.models import CropGeometry, SprocketDetection
from grokcam.physical_sprocket import PhysicalPairResult
from grokcam.precision_registration import (P15_CONFIG, RegistrationResult,
                                            register_precisely)


def valid_geometry() -> dict:
    return {
        "schema_version": 1,
        "film_format": "regular8",
        "source": "capture",
        "calibration_frames": [1, 2, 3],
        "sprocket_pitch_px": 732.0,
        "sprocket_pitch_mad_px": 0.2,
        "sprocket_width_px": 257.0,
        "sprocket_width_mad_px": 0.2,
        "sprocket_height_px": 242.0,
        "sprocket_height_mad_px": 0.2,
        "sprocket_x_px": 438.0,
        "sprocket_x_mad_px": 0.2,
        "lower_x_minus_midpoint_px": 2.75,
        "lower_top_minus_midpoint_px": 245.0,
        "lower_top_residual_mad_px": 0.3,
        "p24_capture_pitch_px": 733.333,
        "p24_capture_pitch_mad_px": 0.2,
        "p24_capture_width_px": 353.566,
        "p24_capture_width_mad_px": 0.3,
        "p24_capture_height_px": 249.333,
        "p24_capture_height_mad_px": 0.3,
        "p24_capture_x_displacement_px": 9.339,
        "p24_capture_x_displacement_mad_px": 0.3,
        "quality": {
            "capture_lower_top_minus_midpoint": {"median": 242.0},
            "capture_lower_x_minus_midpoint": {"median": 4.67},
        },
        "sanity_bounds": {},
    }


class CaptureGeometryTests(unittest.TestCase):
    def setUp(self):
        self.geometry = Regular8CaptureGeometry.from_dict(valid_geometry())

    def test_default_calibration_has_no_capture_specific_geometry(self):
        self.assertIsNone(load_calibration().capture_geometry)

    def test_tracked_jan_wendy_artifact_is_loadable(self):
        path = Path(__file__).parents[1] / "calibrations" / \
            "jan_and_wendy_hintze_regular8_geometry_v1.json"
        loaded = load_capture_geometry(path)
        self.assertEqual(loaded.source, "/mnt/SG1TB/GrokCam/projects/Jan_and_Wendy_Hintze")
        self.assertEqual(len(loaded.calibration_frames), 478)

    def test_geometry_artifact_round_trips_and_is_strictly_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "geometry.json"
            path.write_text(json.dumps(valid_geometry()), encoding="utf-8")
            loaded = load_capture_geometry(path)
            self.assertEqual(loaded, self.geometry)
            self.assertEqual(loaded.to_dict()["film_format"], "regular8")

            malformed = valid_geometry()
            malformed.pop("p24_capture_width_px")
            path.write_text(json.dumps(malformed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing required fields"):
                load_capture_geometry(path)

            incompatible = valid_geometry()
            incompatible["film_format"] = "super8"
            path.write_text(json.dumps(incompatible), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "film_format"):
                load_capture_geometry(path)

            out_of_range = valid_geometry()
            out_of_range["sprocket_pitch_px"] = 1200
            path.write_text(json.dumps(out_of_range), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "sanity bounds"):
                load_capture_geometry(path)

    def test_regular8_geometry_preserves_p15_quality_gate_constants(self):
        self.assertEqual(P15_CONFIG["minimum_inlier_columns"], 24)
        self.assertEqual(P15_CONFIG["minimum_inlier_fraction"], .20)
        self.assertEqual(P15_CONFIG["minimum_snr"], 2.5)

    def test_capture_geometry_cannot_change_super8_behavior(self):
        with self.assertRaisesRegex(ValueError, "only supported for regular8"):
            ProcessingConfig("source", "output", "super8-calibration", "super8",
                             capture_geometry_path="capture-geometry.json")

    def _register(self, primary):
        return register_precisely(
            Image.new("RGB", (2028, 1520)), primary, None,
            defaultdict(float), defaultdict(int), self.geometry,
        )

    def test_accepted_primary_never_invokes_physical_fallback(self):
        p15 = {"valid": True, "y": 1065.0, "expected_y": 1065.0}
        primary = SprocketDetection(438.0, 820.0, 1.0, accepted=True)
        with patch("grokcam.precision_registration.measure_p15_lower_top",
                   return_value=p15) as measured, \
                patch("grokcam.precision_registration.evaluate_p24_guide") as p24, \
                patch("grokcam.precision_registration.run_forced_p07") as p07:
            result = self._register(primary)
        measured.assert_called_once()
        p24.assert_not_called()
        p07.assert_not_called()
        self.assertEqual(result.source, "primary_p15")

    def test_rejected_primary_invokes_physical_recovery(self):
        rejected = SprocketDetection(438.0, 820.0, 1.0, accepted=False)
        p07 = PhysicalPairResult(False, "rejected", None, None,
                                 {"classification": "rejected"})
        with patch("grokcam.precision_registration.measure_p15_lower_top") as measured, \
                patch("grokcam.precision_registration.evaluate_p24_guide",
                      return_value=(None, {"attempted": True})) as p24, \
                patch("grokcam.precision_registration.run_forced_p07",
                      return_value=(p07, [], {"classification": "rejected"})) as fallback:
            result = self._register(rejected)
        measured.assert_not_called()
        p24.assert_called_once()
        fallback.assert_called_once()
        self.assertIsNone(result.source)

    def test_missing_primary_invokes_physical_recovery(self):
        p07 = PhysicalPairResult(False, "rejected", None, None,
                                 {"classification": "rejected"})
        with patch("grokcam.precision_registration.evaluate_p24_guide",
                   return_value=(None, {"attempted": True})) as p24, \
                patch("grokcam.precision_registration.run_forced_p07",
                      return_value=(p07, [], {"classification": "rejected"})) as fallback:
            result = self._register(None)
        p24.assert_called_once()
        fallback.assert_called_once()
        self.assertIsNone(result.source)

    def test_manifest_resume_rejects_changed_capture_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "processing_manifest.json"
            with patch("grokcam.manifest.tool_version", return_value="ffmpeg test"):
                load_or_create(path, Path("/archive/raw"), [1], 16, 1,
                               load_calibration(), Path("ffmpeg"))
                with self.assertRaisesRegex(RuntimeError, "different capture geometry"):
                    load_or_create(
                        path, Path("/archive/raw"), [1], 16, 1,
                        replace(load_calibration(), capture_geometry=self.geometry),
                        Path("ffmpeg"),
                    )

    def test_regular8_registration_progress_is_emitted_inside_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw"
            output = root / "output"
            raw.mkdir()
            for number in (1, 2):
                (raw / f"frame_{number:06d}.dng").write_bytes(b"source")
            events = []
            options = RunOptions(
                raw_dir=raw, output_dir=output, batch_frames=2,
                minimum_free_gib=0, ffmpeg=Path("ffmpeg"), ffprobe=Path("ffprobe"),
                event_emitter=EventEmitter("test-job", events.append),
            )

            class FakeDeveloper:
                def __init__(self, _report):
                    pass

                def develop(self, _source, target):
                    Image.new("RGB", (2028, 1520), "gray").save(target)

            def fake_normalize(paths, destination, _target):
                destination.mkdir(parents=True, exist_ok=True)
                for source in paths:
                    shutil.copy2(source, destination / source.name)
                return ([{} for _ in paths], 0.5)

            def fake_encode(_ffmpeg, _normalized, temporary, _first, _count, _fps):
                temporary.write_bytes(b"video")

            def fake_concat(_ffmpeg, _concat, _paths, temporary):
                temporary.write_bytes(b"joined")

            registration = RegistrationResult(
                CropGeometry(100.0, 100.0, 1133, 900), "primary_p15",
                438.0, 1065.0, {},
            )
            with patch("grokcam.batch.DarktableMatchedDeveloper", FakeDeveloper), \
                    patch("grokcam.detectors.adaptive.detect_luminance_pair",
                          return_value=SprocketDetection(438.0, 820.0, 1.0)), \
                    patch("grokcam.batch.register_precisely", return_value=registration), \
                    patch("grokcam.batch.normalize_frames", side_effect=fake_normalize), \
                    patch("grokcam.batch.encode_segment", side_effect=fake_encode), \
                    patch("grokcam.batch.verify_video",
                          return_value={"streams": [{"nb_frames": "2"}]}), \
                    patch("grokcam.batch.concatenate_segments", side_effect=fake_concat), \
                    patch("grokcam.physical_sprocket.load_capture_metadata", return_value={}):
                _run_reel_core(options, load_calibration())

            manifest = json.loads((output / "processing_manifest.json").read_text())
            segment = manifest["segments"][0]
            self.assertEqual(segment["sprocket_detector_checkpoint"]["name"], "adaptive-v1")
            self.assertEqual(segment["sprocket_detector_checkpoint"]["state"], {})
            self.assertEqual(segment["frame_records"][0]["sprocket_detector_diagnostics"]["detector"],
                             "adaptive-v1")

            progress = [event for event in events if event.event == "registration_progress"]
            self.assertEqual(len(progress), 2)
            self.assertEqual([event.payload["completed"] for event in progress], [1, 2])
            stages = [event.payload["stage"] for event in events
                      if event.event == "stage_progress"]
            for stage in ("raw_development", "registration", "crop_render",
                          "normalization", "encoding", "verification"):
                self.assertIn(stage, stages)
            self.assertEqual(progress[-1].payload["counts"]["p15_direct"], 2)


if __name__ == "__main__":
    unittest.main()
