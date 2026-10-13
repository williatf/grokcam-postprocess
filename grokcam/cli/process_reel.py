"""Canonical GrokCam production command."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import threading
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path

from grokcam.api import ProcessingConfig, list_calibrations, process_reel
from grokcam.batch import RunOptions
from grokcam.config import (Regular8CaptureGeometry, load_calibration,
                            load_capture_geometry)
from grokcam.detectors.registry import registered_detectors
from grokcam.pipeline import ProductionPipeline


def parser() -> argparse.ArgumentParser:
    ffmpeg = shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg"
    ffprobe = shutil.which("ffprobe") or "/usr/local/bin/ffprobe"
    result = argparse.ArgumentParser(description="Disk-bounded, resumable GrokCam production processing")
    result.add_argument("raw_dir", type=Path)
    result.add_argument("output_dir", type=Path)
    result.add_argument("--first", type=int)
    result.add_argument("--last", type=int)
    result.add_argument("--batch-frames", type=int, default=960)
    result.add_argument("--fps", type=int, default=16)
    result.add_argument("--jobs", type=int, default=3)
    result.add_argument("--crop-preset", choices=["loose"], default="loose")
    result.add_argument("--ffmpeg", type=Path, default=Path(ffmpeg))
    result.add_argument("--ffprobe", type=Path, default=Path(ffprobe))
    result.add_argument("--minimum-free-gib", type=float, default=22.0)
    result.add_argument("--staging-dir", type=Path,
                        help="local parent directory for per-render transient staging")
    result.add_argument("--plan-only", action="store_true", help="show the restart plan without processing")
    result.add_argument("--dry-run", action="store_true", help="alias for --plan-only")
    result.add_argument("--calibration", type=Path, help="optional JSON calibration overrides")
    result.add_argument("--capture-geometry", type=Path,
                        help="optional validated Regular 8 capture geometry artifact")
    result.add_argument("--match-report", type=Path, help="override the learned color-match report")
    result.add_argument("--vertical-stabilization", action="store_true",
                        help="enable second-stage physical vertical registration")
    result.add_argument("--sprocket-detector-mode", choices=["legacy", "physical-p07-v1"],
                        help="registration algorithm (default from calibration)")
    result.add_argument("--sprocket-detector", choices=registered_detectors(),
                        help="primary detector ID (default from calibration; currently adaptive-v1)")
    result.add_argument("--film-format", choices=["regular8", "super8"],
                        help="film-format strategy (default from calibration)")
    result.add_argument("--registration-only", action="store_true",
                        help="run registration and audit manifests without crop/render/encode")
    result.add_argument("--output-name", help="final movie filename (machine/API mode or normal CLI)")
    result.add_argument("--calibration-id", help="discovered calibration ID for machine/API mode")
    result.add_argument("--event-stream", choices=["jsonl"],
                        help="emit machine-readable progress events to stdout")
    return result


def main() -> None:
    args = parser().parse_args()
    if args.output_name is not None and (
            not args.output_name.strip() or args.output_name in {".", ".."} or
            Path(args.output_name).is_absolute() or "/" in args.output_name or
            "\\" in args.output_name):
        parser().error("--output-name must be a filename, not a path")
    if args.event_stream == "jsonl":
        if not args.calibration_id:
            parser().error("--calibration-id is required with --event-stream jsonl")
        calibration_info = next((item for item in list_calibrations()
                                 if item.calibration_id == args.calibration_id), None)
        if calibration_info is None:
            parser().error(f"unknown calibration ID: {args.calibration_id}")
        if not calibration_info.available:
            parser().error(calibration_info.unavailable_reason or "calibration is unavailable")
        film_format = args.film_format or (calibration_info.film_formats[0]
                                           if calibration_info.film_formats else None)
        if film_format is None:
            parser().error("--film-format is required for a calibration without a declared format")
        config = ProcessingConfig(
            source_path=args.raw_dir,
            output_directory=args.output_dir,
            calibration_id=args.calibration_id,
            film_format=film_format,
            first_frame=args.first,
            last_frame=args.last,
            fps=args.fps,
            batch_frames=args.batch_frames,
            raw_jobs=args.jobs,
            output_name=args.output_name,
            capture_geometry_path=args.capture_geometry,
            sprocket_detector=args.sprocket_detector,
        )
        output = sys.stdout
        write_lock = threading.Lock()

        def write_event(event) -> None:
            with write_lock:
                output.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
                output.flush()

        with redirect_stdout(sys.stderr):
            result = process_reel(config, event_sink=write_event)
        if result.status != "succeeded":
            raise SystemExit(1)
        return

    calibration = load_calibration(args.calibration, args.match_report)
    capture_geometry_source = (
        "super8_default" if (args.film_format or calibration.film_format) == "super8"
        else "regular8_default"
    )
    if args.capture_geometry is not None:
        calibration = replace(calibration,
                              capture_geometry=load_capture_geometry(args.capture_geometry))
        capture_geometry_source = "explicit_override"
    elif (args.film_format or calibration.film_format) == "regular8":
        project = args.raw_dir / "raw" if (args.raw_dir / "raw").is_dir() else args.raw_dir
        metadata_path = project / "metadata.json"
        if metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                raw_geometry = metadata.get("capture_geometry")
                if raw_geometry is not None:
                    calibration = replace(
                        calibration,
                        capture_geometry=Regular8CaptureGeometry.from_dict(raw_geometry),
                    )
                    capture_geometry_source = "project_metadata"
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
                parser().error(f"invalid project capture_geometry: {error}")
    if args.vertical_stabilization:
        calibration = replace(
            calibration,
            vertical_stabilization=replace(calibration.vertical_stabilization, enabled=True),
        )
    if args.sprocket_detector_mode:
        calibration = replace(calibration, sprocket_detector_mode=args.sprocket_detector_mode)
    if args.sprocket_detector:
        calibration = replace(calibration, sprocket_detector_id=args.sprocket_detector)
    if args.film_format:
        calibration = replace(calibration, film_format=args.film_format)
    if args.capture_geometry is not None and calibration.film_format != "regular8":
        parser().error("--capture-geometry is only supported for Regular 8")
    options = RunOptions(
        raw_dir=args.raw_dir, output_dir=args.output_dir, first=args.first, last=args.last,
        batch_frames=args.batch_frames, fps=args.fps, jobs=args.jobs,
        ffmpeg=args.ffmpeg, ffprobe=args.ffprobe, minimum_free_gib=args.minimum_free_gib,
        plan_only=args.plan_only or args.dry_run, registration_only=args.registration_only,
        staging_dir=args.staging_dir, output_name=args.output_name,
        capture_geometry_source=capture_geometry_source,
    )
    ProductionPipeline(calibration).process_reel(options)


if __name__ == "__main__":
    main()
