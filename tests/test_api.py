from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from grokcam.api import (ProcessingConfig, ProcessingResult, StructuredProcessingError,
                         inspect_source, list_calibrations, list_projects, process_reel,
                         read_result)


class ApiTests(unittest.TestCase):
    @staticmethod
    def geometry_metadata():
        return {
            "schema_version": 1, "film_format": "regular8", "source": "capture",
            "frozen": True, "calibration_method": "regular8_capture_geometry_v1",
            "calibration_frames": [1, 2, 3],
            "sprocket_pitch_px": 732.0, "sprocket_pitch_mad_px": 0.2,
            "sprocket_width_px": 257.0, "sprocket_width_mad_px": 0.2,
            "sprocket_height_px": 242.0, "sprocket_height_mad_px": 0.2,
            "sprocket_x_px": 438.0, "sprocket_x_mad_px": 0.2,
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

    def make_project(self, root: Path, frames=(1, 2, 3), metadata=None) -> Path:
        project = root / "project"
        raw = project / "raw"
        raw.mkdir(parents=True)
        for frame in frames:
            (raw / f"frame_{frame:06d}.dng").write_bytes(b"not-a-real-dng")
        if metadata is not None:
            (project / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        return project

    def inspect(self, project: Path):
        with patch("grokcam.api._sample_dimensions", return_value=((2028, 1520), None)):
            return inspect_source(project)

    def test_source_project_and_raw_directory_inspection(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), metadata={
                "project_name": "Farmington", "film_format": "super8",
                "transport_observation": {"status": "observed"},
            })
            for source in (project, project / "raw"):
                result = self.inspect(source)
                self.assertEqual(result.source_path, project.resolve())
                self.assertEqual(result.raw_path, (project / "raw").resolve())
                self.assertEqual(result.project_name, "Farmington")
                self.assertEqual(result.declared_film_format, "super8")
                self.assertEqual((result.frame_count, result.first_frame, result.last_frame), (3, 1, 3))
                self.assertTrue(result.contiguous)
                self.assertEqual(result.sample_dimensions, (2028, 1520))

    def test_metadata_absent_and_missing_frames_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.inspect(self.make_project(Path(directory), frames=(1, 3)))
            self.assertIsNone(result.metadata)
            self.assertIsNone(result.declared_film_format)
            self.assertFalse(result.contiguous)
            self.assertEqual(result.missing_frames, (2,))
            self.assertTrue(any("missing" in warning for warning in result.warnings))

    def test_inspection_reports_frozen_capture_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.inspect(self.make_project(Path(directory), metadata={
                "project_name": "Geometry Project", "film_format": "regular8",
                "capture_geometry": self.geometry_metadata(),
            }))
            self.assertTrue(result.capture_geometry_present)
            self.assertTrue(result.capture_geometry_valid)
            self.assertTrue(result.capture_geometry_frozen)
            self.assertEqual(result.capture_geometry_summary["calibration_frames"], 3)

    def test_invalid_capture_geometry_is_structured_source_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            metadata = {"film_format": "regular8", "capture_geometry": {"frozen": False}}
            project = self.make_project(Path(directory), metadata=metadata)
            config = ProcessingConfig(project, Path(directory) / "output",
                                      "grokcam-regular8-default-v1", "regular8")
            with patch("grokcam.api._sample_dimensions", return_value=((2028, 1520), None)):
                result = process_reel(config)
            self.assertEqual(result.status, "failed")
            self.assertEqual(result.error["code"], "capture_geometry_invalid")

    def test_process_automatically_consumes_project_capture_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self.make_project(root, frames=(1, 2), metadata={
                "film_format": "regular8", "capture_geometry": self.geometry_metadata(),
            })
            output = root / "output"
            observed = {}

            def fake_process(pipeline, options):
                observed["geometry"] = pipeline.calibration.capture_geometry
                observed["source"] = options.capture_geometry_source
                output.mkdir()
                movie = output / "finished.mp4"
                movie.write_bytes(b"movie")
                (output / "processing_manifest.json").write_text(json.dumps({
                    "raw_dir": str(project / "raw"), "frame_range": [1, 2],
                    "frame_count": 2, "capture_geometry_source": "project_metadata",
                    "final": {"video": str(movie), "verified": True},
                }), encoding="utf-8")
                return {"final": {"video": str(movie)}}

            config = ProcessingConfig(project, output, "grokcam-regular8-default-v1", "regular8")
            with patch("grokcam.api._sample_dimensions", return_value=((2028, 1520), None)), \
                    patch("grokcam.api.ProductionPipeline.process_reel", fake_process):
                result = process_reel(config)
            self.assertEqual(observed["source"], "project_metadata")
            self.assertEqual(observed["geometry"].sprocket_pitch_px, 732.0)

    def test_project_discovery_uses_capture_conventions_and_is_sorted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.make_project(root, frames=(1, 2), metadata={
                "project_name": "Zulu Reel", "film_format": "regular8",
            })
            second = root / "second-folder"
            (second / "raw").mkdir(parents=True)
            for frame in (1, 3):
                (second / "raw" / f"frame_{frame:06d}.dng").write_bytes(b"not-a-real-dng")
            malformed = root / "missing-raw"
            malformed.mkdir()
            (malformed / "metadata.json").write_text("{not-json", encoding="utf-8")
            (root / "not-a-project").mkdir()
            with patch("grokcam.api._sample_dimensions", return_value=((2028, 1520), None)):
                projects = list_projects(root)
            self.assertEqual([item.project_name for item in projects], ["missing-raw", "second-folder", "Zulu Reel"])
            self.assertEqual(projects[2].source_path, first.resolve())
            self.assertFalse(projects[0].available)
            self.assertTrue(projects[0].warnings)
            self.assertTrue(projects[1].available)
            self.assertFalse(projects[1].contiguous)
            self.assertTrue(projects[2].available)
            self.assertEqual(projects[2].film_format, "regular8")

    def test_list_projects_cli_returns_json_envelope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "projects"
            self.make_project(root, frames=(1,), metadata={"project_name": "CLI Project"})
            command = [sys.executable, "-m", "grokcam.cli.gui", "list-projects", str(root)]
            environment = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1])}
            completed = subprocess.run(command, cwd=Path(__file__).parents[1], env=environment,
                                       text=True, capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            response = json.loads(completed.stdout)
            self.assertEqual(list(response), ["projects"])
            self.assertEqual(response["projects"][0]["project_name"], "CLI Project")

    def test_calibration_discovery_excludes_component_artifacts_and_reports_missing_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "production.json").write_text(json.dumps({"film_format": "super8"}), encoding="utf-8")
            (root / "component.json").write_text("{}", encoding="utf-8")
            (root / "production.metadata.json").write_text(json.dumps({
                "schema_version": 1,
                "calibration_id": "test-production",
                "display_name": "Test production",
                "config": "production.json",
                "film_formats": ["super8"],
                "requires": ["missing-resource.npz"],
            }), encoding="utf-8")
            values = list_calibrations([root])
            self.assertEqual([item.calibration_id for item in values], ["test-production"])
            self.assertFalse(values[0].available)
            self.assertIn("missing-resource.npz", values[0].unavailable_reason)

    def test_processing_config_validates_values_and_filename_traversal(self):
        with self.assertRaises(ValueError):
            ProcessingConfig("source", "output", "calibration", "super8", output_name="../movie.mp4")
        with self.assertRaises(ValueError):
            ProcessingConfig("source", "output", "calibration", "super8", fps=0)
        with self.assertRaises(ValueError):
            ProcessingConfig("source", "output", "calibration", "regular8", first_frame=4, last_frame=3)

    def test_process_result_and_events_are_structured(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self.make_project(root, frames=(1, 2))
            output = root / "output"
            movie = output / "finished.mp4"
            events = []

            def fake_process(_pipeline, options):
                output.mkdir()
                movie.write_bytes(b"movie")
                (output / "processing_manifest.json").write_text(json.dumps({
                    "raw_dir": str(project / "raw"),
                    "frame_range": [1, 2],
                    "frame_count": 2,
                    "final": {"video": str(movie), "verified": True},
                    "summary": {"processing_summary": {"included_frames": 2}},
                }), encoding="utf-8")
                return {"final": {"video": str(movie)}}

            config = ProcessingConfig(project, output, "grokcam-regular8-default-v1", "regular8",
                                      first_frame=1, last_frame=2)
            with patch("grokcam.api._sample_dimensions", return_value=((2028, 1520), None)), \
                    patch("grokcam.api.ProductionPipeline.process_reel", fake_process):
                result = process_reel(config, event_sink=events.append)
            self.assertIsInstance(result, ProcessingResult)
            self.assertEqual(result.status, "succeeded")
            self.assertEqual(result.movie_path, movie.resolve())
            self.assertEqual([event.event for event in events], ["job_started", "job_completed"])
            self.assertEqual([event.sequence for event in events], [1, 2])
            self.assertTrue(all(event.protocol == "grokcam.postprocess.events" for event in events))
            self.assertEqual(result.to_dict()["status"], "succeeded")

            recovered = read_result(output)
            self.assertEqual(recovered.status, "succeeded")
            self.assertEqual(recovered.movie_path, movie.resolve())

    def test_process_failure_returns_structured_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self.make_project(root, frames=(1, 3))
            config = ProcessingConfig(project, root / "output", "grokcam-regular8-default-v1", "regular8")
            events = []
            with patch("grokcam.api._sample_dimensions", return_value=((2028, 1520), None)):
                result = process_reel(config, event_sink=events.append)
            self.assertEqual(result.status, "failed")
            self.assertEqual(result.error["code"], "source_non_contiguous")
            self.assertEqual(events[-1].event, "job_failed")

    def test_jsonl_cli_stdout_is_json_only(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "does-not-exist"
            command = [sys.executable, "-m", "grokcam.cli.process_reel", str(source),
                       str(Path(directory) / "output"), "--event-stream", "jsonl",
                       "--calibration-id", "grokcam-regular8-default-v1"]
            environment = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1])}
            completed = subprocess.run(command, cwd=Path(__file__).parents[1], env=environment,
                                       text=True, capture_output=True)
            self.assertNotEqual(completed.returncode, 0)
            lines = [json.loads(line) for line in completed.stdout.splitlines()]
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0]["event"], "job_failed")
            self.assertEqual(lines[0]["protocol"], "grokcam.postprocess.events")

    def test_normal_cli_retains_human_readable_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.make_project(root, frames=(1,))
            staging = root / "staging"
            staging.mkdir()
            command = [sys.executable, "-m", "grokcam.cli.process_reel", str(source),
                       str(root / "output"), "--plan-only", "--minimum-free-gib", "0",
                       "--staging-dir", str(staging)]
            environment = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1])}
            completed = subprocess.run(command, cwd=Path(__file__).parents[1], env=environment,
                                       text=True, capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("Remaining plan:", completed.stdout)
            self.assertNotIn('"protocol":', completed.stdout)


if __name__ == "__main__":
    unittest.main()
