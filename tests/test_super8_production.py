from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

from grokcam.config import load_calibration
from grokcam.batch import RunOptions
from grokcam.image_processing import registered_frame
from grokcam.models import CropGeometry
from grokcam.super8_audit import _resolve_batch, _worker, run_super8_batch_production


class Super8ProductionTests(unittest.TestCase):
    def test_registration_receives_native_orientation_and_keeps_coordinate(self):
        native = np.arange(4 * 3 * 3, dtype=np.uint8).reshape(4, 3, 3)
        seen = {}

        class FakeDeveloper:
            def __init__(self, _report):
                pass

            def develop(self, _dng, tiff):
                Image.fromarray(native, "RGB").save(tiff)

        class FakeRegistration:
            def __init__(self, _calibration):
                pass

            def register(self, image):
                seen["image"] = np.asarray(image.convert("RGB"))
                return SimpleNamespace(
                    diagnostics={}, provenance="PRIMARY", fallback_level="P03_PRIMARY",
                    accepted=True, raw_candidate_y=11.0, anchor_x=7.0,
                    registration_y=11.5, score=1.0, rejection_reasons=(),
                )

        calibration = load_calibration(Path("calibrations/super8_redo5.json"))
        with tempfile.TemporaryDirectory() as directory, \
                patch("grokcam.super8_audit.DarktableMatchedDeveloper", FakeDeveloper), \
                patch("grokcam.super8_audit.Super8Registration", FakeRegistration):
            record = _worker((Path(directory) / "frame_000001.dng",
                              calibration.match.report, calibration))

        np.testing.assert_array_equal(seen["image"], native)
        self.assertEqual(record["registration_y"], 11.5)
        self.assertEqual(record["detector_provenance"], "PRIMARY")

    def test_super8_orientation_flips_registered_output_once_and_not_coordinates(self):
        native = np.arange(4 * 3 * 3, dtype=np.uint8).reshape(4, 3, 3)
        image = Image.fromarray(native, "RGB")
        crop = CropGeometry(0, 0, 3, 4)

        final = np.asarray(registered_frame(image, crop, contrast=1.0, vertical_flip=True))
        native_output = np.asarray(registered_frame(image, crop, contrast=1.0, vertical_flip=False))
        np.testing.assert_array_equal(final, np.flip(native_output, axis=0))
        np.testing.assert_array_equal(native_output, native)

    def test_regular8_default_orientation_remains_vertical_flip(self):
        native = np.arange(5 * 4 * 3, dtype=np.uint8).reshape(5, 4, 3)
        image = Image.fromarray(native, "RGB")
        crop = CropGeometry(0, 0, 4, 5)
        default = np.asarray(registered_frame(image, crop, contrast=1.0))
        explicit = np.asarray(registered_frame(image, crop, contrast=1.0, vertical_flip=True))
        unchanged = np.asarray(registered_frame(image, crop, contrast=1.0, vertical_flip=False))
        np.testing.assert_array_equal(default, explicit)
        np.testing.assert_array_equal(unchanged, native)

    def test_super8_batch_develops_each_dng_once_and_reuses_staging_image(self):
        calls = {"develop": 0, "register": 0}
        native = np.zeros((1520, 2028, 3), dtype=np.uint8)
        native[300:1300, 330:1650] = 128

        class FakeDeveloper:
            def __init__(self, _report):
                pass

            def develop(self, _dng, tiff):
                calls["develop"] += 1
                Image.fromarray(native, "RGB").save(tiff)

        class FakeRegistration:
            def __init__(self, _calibration):
                pass

            def register(self, _image):
                calls["register"] += 1
                return SimpleNamespace(
                    diagnostics={}, provenance="PRIMARY", fallback_level="P03_PRIMARY",
                    accepted=True, raw_candidate_y=800.0, anchor_x=270.0,
                    registration_y=800.0, score=1.0, rejection_reasons=(),
                )

        def fake_encode(_ffmpeg, _normalized, temporary, _first, _count, _fps):
            temporary.write_bytes(b"segment")

        def fake_concat(_ffmpeg, _concat, _paths, temporary):
            temporary.write_bytes(b"movie")

        with tempfile.TemporaryDirectory() as directory, \
                patch("grokcam.super8_audit.DarktableMatchedDeveloper", FakeDeveloper), \
                patch("grokcam.super8_audit.Super8Registration", FakeRegistration), \
                patch("grokcam.super8_audit.encode_segment", fake_encode), \
                patch("grokcam.super8_audit.concatenate_segments", fake_concat), \
                patch("grokcam.super8_audit.verify_video", return_value={"streams": [{"nb_frames": "2"}]}):
            root = Path(directory)
            dngs = []
            for frame in (1, 2):
                path = root / f"frame_{frame:06d}.dng"
                path.write_bytes(b"source")
                dngs.append(path)
            calibration = load_calibration(Path("calibrations/super8_redo5.json"))
            class FlushCapture(StringIO):
                def __init__(self):
                    super().__init__()
                    self.flush_count = 0

                def flush(self):
                    self.flush_count += 1
                    super().flush()

            with redirect_stdout(FlushCapture()) as captured, \
                    patch("grokcam.super8_audit.shutil.disk_usage",
                          return_value=SimpleNamespace(free=12.5 * 2**30)) as disk_usage:
                summary = run_super8_batch_production(
                    dngs, root / "output", calibration,
                    RunOptions(root, root / "output", batch_frames=1, minimum_free_gib=0.0))

        self.assertEqual(calls, {"develop": 2, "register": 2})
        self.assertEqual(summary["render"]["rendered_frames"], 2)
        self.assertEqual(summary["direct_same_frame_count"], 2)
        progress = captured.getvalue()
        self.assertIn("Remaining plan: 2 frames in 2 batches", progress)
        self.assertIn("[1/2] developing and registering 1 frames (000001-000001)", progress)
        self.assertIn("developed 1/1; free", progress)
        self.assertIn("registered 1/1", progress)
        self.assertIn("Timing breakdown for 000001-000001", progress)
        self.assertIn("Registration counts: PRIMARY=1", progress)
        self.assertIn("verified and cleaned segment 000001-000001; free", progress)
        self.assertIn("free 12.5 GiB", progress)
        self.assertGreater(captured.flush_count, 0)
        self.assertTrue(all(call.args[0] == Path(directory) / "output"
                            for call in disk_usage.call_args_list))

    def test_interpolation_resolves_failure_at_batch_boundary(self):
        direct = lambda frame, y: {
            "frame": frame, "accepted": True, "detector_provenance": "PRIMARY",
            "final_registration_y": y, "raw_candidate_x": 270.0,
        }
        failed = {"frame": 2, "accepted": False, "detector_provenance": "UNTRUSTED",
                  "final_registration_y": None, "raw_candidate_x": None}
        previous = [direct(1, 800.0), failed]
        following = [direct(3, 820.0)]
        _resolve_batch(previous, right=following[0])
        self.assertEqual(previous[1]["detector_provenance"], "INTERPOLATED")
        self.assertEqual(previous[1]["final_registration_y"], 810.0)


if __name__ == "__main__":
    unittest.main()
