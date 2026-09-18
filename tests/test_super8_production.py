from __future__ import annotations

import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from dataclasses import replace
from unittest.mock import patch

import numpy as np
from PIL import Image

from grokcam.config import load_calibration
from grokcam.batch import RunOptions
from grokcam.image_processing import registered_frame
from grokcam.models import CropGeometry
from grokcam.super8_audit import (
    _boundary_requires_one_future_frame,
    _resolve_batch,
    _worker,
    run_super8_batch_production,
)


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
        scheduler = summary["scheduler"]
        self.assertEqual(scheduler["queue_capacity"], 1)
        self.assertLessEqual(scheduler["maximum_observed_queue_depth"], 1)
        self.assertGreaterEqual(scheduler["producer_consumer_overlap_wall_seconds"], 0.0)
        self.assertEqual(len(summary["batch_timings"]), 2)
        for batch in summary["batch_timings"]:
            for event in (
                "producer_start", "producer_finished", "batch_boundary_closed",
                "enqueue_start", "enqueue_finished", "consumer_start",
                "crop_render_finished", "normalization_finished",
                "encoding_verification_finished", "consumer_finished",
            ):
                self.assertIn(event, batch["scheduler"])

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

    def test_boundary_lookahead_is_only_used_for_one_directly_bracketed_gap(self):
        direct = lambda frame, y: {
            "frame": frame, "accepted": True, "detector_provenance": "PRIMARY",
            "final_registration_y": y, "raw_candidate_x": 270.0,
        }
        failed = lambda frame: {
            "frame": frame, "accepted": False, "detector_provenance": "UNTRUSTED",
            "final_registration_y": None, "raw_candidate_x": None,
        }

        self.assertFalse(_boundary_requires_one_future_frame([direct(1, 800.0)]))
        self.assertTrue(_boundary_requires_one_future_frame([direct(1, 800.0), failed(2)]))
        self.assertFalse(_boundary_requires_one_future_frame(
            [direct(1, 800.0), failed(2), failed(3)]))

        one_gap = [direct(1, 800.0), failed(2)]
        _resolve_batch(one_gap, right=direct(3, 820.0))
        self.assertEqual(one_gap[1]["detector_provenance"], "INTERPOLATED")

        non_direct_following = [direct(1, 800.0), failed(2)]
        _resolve_batch(non_direct_following, right=failed(3))
        self.assertEqual(non_direct_following[1]["detector_provenance"], "UNTRUSTED")

        unresolved_suffix = [direct(1, 800.0), failed(2), failed(3)]
        _resolve_batch(unresolved_suffix)
        self.assertEqual([record["detector_provenance"] for record in unresolved_suffix[1:]],
                         ["UNTRUSTED", "UNTRUSTED"])

    def test_producer_and_consumer_overlap_without_changing_frame_order(self):
        calls = []
        consumer_started = threading.Event()
        second_development_started = threading.Event()
        native = np.zeros((10, 10, 3), dtype=np.uint8)

        class FakeDeveloper:
            def __init__(self, _report):
                pass

            def develop(self, dng, tiff):
                if dng.name.endswith("000002.dng"):
                    second_development_started.set()
                    if not consumer_started.wait(5):
                        raise RuntimeError("consumer did not start while producer was active")
                Image.fromarray(native, "RGB").save(tiff)

        class FakeRegistration:
            def __init__(self, _calibration):
                pass

            def register(self, _image):
                frame = len(calls) + 1
                calls.append(frame)
                return SimpleNamespace(
                    diagnostics={}, provenance="PRIMARY", fallback_level="P03_PRIMARY",
                    accepted=True, raw_candidate_y=5.0, anchor_x=5.0,
                    registration_y=5.0 + frame, score=1.0, rejection_reasons=(),
                )

        def fake_render(*args, **kwargs):
            consumer_started.set()
            return original_render(*args, **kwargs)

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
            import grokcam.super8_audit as audit
            original_render = audit._render_staged_batch
            root = Path(directory)
            dngs = []
            for frame in (1, 2):
                path = root / f"frame_{frame:06d}.dng"
                path.write_bytes(b"source")
                dngs.append(path)
            calibration = load_calibration(Path("calibrations/super8_redo5.json"))
            calibration = replace(
                calibration,
                super8_registration=replace(
                    calibration.super8_registration,
                    crop_validated=True, crop_x_offset=0.0, crop_y_offset=0.0,
                    crop_width=4, crop_height=4),
            )
            with patch("grokcam.super8_audit._render_staged_batch", fake_render):
                summary = run_super8_batch_production(
                    dngs, root / "output", calibration,
                    RunOptions(root, root / "output", batch_frames=1, jobs=1,
                               minimum_free_gib=0.0))

        self.assertTrue(second_development_started.is_set())
        self.assertEqual(calls, [1, 2])
        self.assertGreater(summary["scheduler"]["producer_consumer_overlap_wall_seconds"], 0.0)

    def test_producer_failure_does_not_deadlock_or_clean_staging(self):
        class FailingDeveloper:
            def __init__(self, _report):
                pass

            def develop(self, _dng, _tiff):
                raise RuntimeError("synthetic producer failure")

        with tempfile.TemporaryDirectory() as directory, \
                patch("grokcam.super8_audit.DarktableMatchedDeveloper", FailingDeveloper):
            root = Path(directory)
            dng = root / "frame_000001.dng"
            dng.write_bytes(b"source")
            calibration = load_calibration(Path("calibrations/super8_redo5.json"))
            with self.assertRaisesRegex(RuntimeError, "synthetic producer failure"):
                run_super8_batch_production(
                    [dng], root / "output", calibration,
                    RunOptions(root, root / "output", batch_frames=1,
                               minimum_free_gib=0.0))
            self.assertTrue((root / "output" / ".super8-staging").is_dir())

    def test_consumer_failure_stops_producer_and_preserves_staging(self):
        native = np.zeros((10, 10, 3), dtype=np.uint8)

        class FakeDeveloper:
            def __init__(self, _report):
                pass

            def develop(self, _dng, tiff):
                Image.fromarray(native, "RGB").save(tiff)

        class FakeRegistration:
            def __init__(self, _calibration):
                pass

            def register(self, _image):
                return SimpleNamespace(
                    diagnostics={}, provenance="PRIMARY", fallback_level="P03_PRIMARY",
                    accepted=True, raw_candidate_y=5.0, anchor_x=5.0,
                    registration_y=5.0, score=1.0, rejection_reasons=(),
                )

        with tempfile.TemporaryDirectory() as directory, \
                patch("grokcam.super8_audit.DarktableMatchedDeveloper", FakeDeveloper), \
                patch("grokcam.super8_audit.Super8Registration", FakeRegistration), \
                patch("grokcam.super8_audit._render_staged_batch",
                      side_effect=RuntimeError("synthetic consumer failure")):
            root = Path(directory)
            dngs = []
            for frame in (1, 2):
                path = root / f"frame_{frame:06d}.dng"
                path.write_bytes(b"source")
                dngs.append(path)
            calibration = load_calibration(Path("calibrations/super8_redo5.json"))
            with self.assertRaisesRegex(RuntimeError, "synthetic consumer failure"):
                run_super8_batch_production(
                    dngs, root / "output", calibration,
                    RunOptions(root, root / "output", batch_frames=1,
                               minimum_free_gib=0.0))
            self.assertTrue((root / "output" / ".super8-staging").is_dir())
            self.assertFalse((root / "output" / "Super8_REDO5_000001_000002_16fps.mp4").exists())


if __name__ == "__main__":
    unittest.main()
