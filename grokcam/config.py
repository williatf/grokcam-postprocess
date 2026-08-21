"""Authoritative production calibration and per-run configuration."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path


@dataclass(frozen=True)
class DetectorCalibration:
    search_x0: int = 100
    search_x1: int = 570
    bright_percentile: float = 99.0
    threshold_scale: float = 0.90
    minimum_bright_row_pixels: int = 130
    band_height_min: int = 180
    band_height_max: int = 330
    expected_pitch: float = 785.0
    pitch_tolerance: float = 100.0
    minimum_bright_columns: int = 200
    column_fill: float = 0.55
    expected_width: float = 365.0
    horizontal_outlier_limit: float = 12.0
    vertical_outlier_limit: float = 45.0


@dataclass(frozen=True)
class CropCalibration:
    x_offset: float = 159.0
    y_offset: float = -413.0
    width: int = 1133
    height: int = 900


@dataclass(frozen=True)
class MatchCalibration:
    report: Path = Path("/mnt/GrokCam/projects/RAW_Test/outputs/rawpy-darktable-match-poc/poc-report.json")


@dataclass(frozen=True)
class ProductionCalibration:
    detector: DetectorCalibration = field(default_factory=DetectorCalibration)
    crop: CropCalibration = field(default_factory=CropCalibration)
    match: MatchCalibration = field(default_factory=MatchCalibration)
    contrast: float = 1.04
    picture_aperture_x: tuple[float, float] = (0.15, 0.92)
    picture_aperture_y: tuple[float, float] = (0.12, 0.88)
    exposure_limit_stops: float = 0.65
    white_balance_blend: float = 0.25

    def to_dict(self) -> dict:
        value = asdict(self)
        value["match"]["report"] = str(self.match.report)
        return value


def load_calibration(path: Path | None = None, match_report: Path | None = None) -> ProductionCalibration:
    """Load optional JSON overrides without changing golden defaults."""
    calibration = ProductionCalibration()
    if path is not None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        allowed = {"detector", "crop", "match", "contrast", "picture_aperture_x",
                   "picture_aperture_y", "exposure_limit_stops", "white_balance_blend"}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"unknown calibration keys: {', '.join(sorted(unknown))}")
        detector = replace(calibration.detector, **raw.get("detector", {}))
        crop = replace(calibration.crop, **raw.get("crop", {}))
        match_values = raw.get("match", {})
        match = replace(calibration.match, **({"report": Path(match_values["report"])} if "report" in match_values else {}))
        scalar = {k: v for k, v in raw.items() if k not in {"detector", "crop", "match"}}
        calibration = replace(calibration, detector=detector, crop=crop, match=match, **scalar)
    if match_report is not None:
        calibration = replace(calibration, match=MatchCalibration(match_report))
    return calibration
