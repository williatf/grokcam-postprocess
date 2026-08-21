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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_or_create(path: Path, raw_dir: Path, numbers: list[int], fps: int, batch_frames: int,
                   calibration: ProductionCalibration, ffmpeg: Path) -> dict:
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest.setdefault("batch_history", []).append({"started": utc_now(), "batch_frames": batch_frames})
        return manifest
    match_path = calibration.match.report.expanduser().resolve()
    match_bytes = match_path.read_bytes()
    match_report = json.loads(match_bytes)
    manifest = {
        "pipeline": "grokcam_raw_production_darktable_matched", "version": __version__,
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
