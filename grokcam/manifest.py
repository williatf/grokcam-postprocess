"""Atomic production-manifest lifecycle."""

from __future__ import annotations

import json
import hashlib
import os
import platform
from datetime import datetime, timezone
from pathlib import Path

import rawpy
from PIL import Image

from . import __version__
from .config import ProductionCalibration
from .encoding import tool_version

DETECTOR_MODE = "physical-p07-v1"
P07_IMPLEMENTATION_SHA256 = "d78bc8478308451af69d37dc7485cb5c0a15cd7a59ccdb75ec86932a498fd13d"
P07_CONFIGURATION_SHA256 = "334abf89ee43a0eb18c7f33e68eb8afb9f38556ff981136ac16f5d30b646a1c6"
EXACT_CACHE_IMPLEMENTATION_SHA256 = "459093853b1f4fb5843849ffd034d31984a89f554a0535b190ccbf4253d3899c"


def physical_module_sha256() -> str:
    return hashlib.sha256((Path(__file__).with_name("physical_sprocket.py")).read_bytes()).hexdigest()

PIPELINE_ID = "grokcam_postprocess"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_or_create(path: Path, raw_dir: Path, numbers: list[int], fps: int, batch_frames: int,
                   calibration: ProductionCalibration, ffmpeg: Path) -> dict:
    expected_failure_policy = ("exclude_unresolved" if
                               calibration.sprocket_detector_mode == DETECTOR_MODE else
                               "legacy_interpolation")
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        recorded_mode = manifest.get("sprocket_registration", {}).get("mode", "legacy")
        if recorded_mode != calibration.sprocket_detector_mode:
            raise RuntimeError("Cannot resume an output directory with a different sprocket detector mode/version")
        if recorded_mode == DETECTOR_MODE:
            recorded_hash = manifest["sprocket_registration"].get("production_module_sha256")
            if recorded_hash != physical_module_sha256():
                raise RuntimeError("Cannot resume with a different physical P07 production module hash")
        recorded_policy = manifest.get("sprocket_registration", {}).get(
            "failure_policy", "legacy_interpolation")
        if recorded_policy != expected_failure_policy:
            raise RuntimeError("Cannot resume with a different registration failure policy")
        recorded_vertical = manifest.get("vertical_stabilization", {}).get("enabled", False)
        if recorded_vertical != calibration.vertical_stabilization.enabled:
            raise RuntimeError(
                "Cannot resume an output directory with a different vertical-stabilization mode"
            )
        manifest.setdefault("batch_history", []).append({"started": utc_now(), "batch_frames": batch_frames})
        return manifest
    match_path = calibration.match.report.expanduser().resolve()
    match_bytes = match_path.read_bytes()
    match_report = json.loads(match_bytes)
    manifest = {
        "pipeline": PIPELINE_ID, "version": __version__,
        "created": utc_now(), "raw_dir": str(raw_dir), "source_policy": "read_only",
        "frame_range": [numbers[0], numbers[-1]], "frame_count": len(numbers),
        "fps": fps, "batch_frames": batch_frames,
        "raw_development_calibration": {
            "path": str(match_path), "sha256": hashlib.sha256(match_bytes).hexdigest(),
            "model": match_report.get("fit", {}).get("model"),
            "created": match_report.get("created"),
            "training_frames": match_report.get("train_frames", []),
            "holdout_frames": match_report.get("holdout_frames", []),
        },
        "crop_preset": "loose", "crop": {
            "x_offset": calibration.crop.x_offset, "y_offset": calibration.crop.y_offset,
            "width": calibration.crop.width, "height": calibration.crop.height},
        "sprocket_registration": {
            "mode": calibration.sprocket_detector_mode,
            "physical_detector_version": DETECTOR_MODE if calibration.sprocket_detector_mode == DETECTOR_MODE else None,
            "p07_implementation_sha256": P07_IMPLEMENTATION_SHA256 if calibration.sprocket_detector_mode == DETECTOR_MODE else None,
            "p07_configuration_sha256": P07_CONFIGURATION_SHA256 if calibration.sprocket_detector_mode == DETECTOR_MODE else None,
            "exact_cache_implementation_sha256": EXACT_CACHE_IMPLEMENTATION_SHA256 if calibration.sprocket_detector_mode == DETECTOR_MODE else None,
            "production_module_sha256": physical_module_sha256() if calibration.sprocket_detector_mode == DETECTOR_MODE else None,
            "failure_policy": expected_failure_policy,
        },
        "vertical_stabilization": {
            "enabled": calibration.vertical_stabilization.enabled,
            "top_reference_y": calibration.vertical_stabilization.top_reference_y,
            "bottom_reference_y": calibration.vertical_stabilization.bottom_reference_y,
            "minimum_confidence": calibration.vertical_stabilization.minimum_confidence,
            "top_bottom_agreement_tolerance":
                calibration.vertical_stabilization.top_bottom_agreement_tolerance,
        },
        "normalization": {"picture_aperture": {"x": [.15, .92], "y": [.12, .88]},
                          "exposure_limit_stops": .65, "white_balance_blend": .25},
        "tools": {"python": platform.python_version(), "pillow": Image.__version__,
                  "rawpy": rawpy.__version__, "ffmpeg": tool_version(ffmpeg)},
        "segments": [],
    }
    atomic_json(path, manifest)
    return manifest


def record_segment(path: Path, manifest: dict, segment: dict) -> None:
    first, last = segment["first"], segment["last"]
    manifest["segments"] = [item for item in manifest["segments"]
                            if (item.get("first"), item.get("last")) != (first, last)] + [segment]
    manifest["segments"].sort(key=lambda item: item["first"])
    atomic_json(path, manifest)
