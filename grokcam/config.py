"""Authoritative production calibration and per-run configuration."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

DEFAULT_MATCH_REPORT = Path(__file__).resolve().parents[1] / "calibrations" / "darktable_match_v1.json"
DEFAULT_SUPER8_TEMPLATE_BANK = Path(__file__).resolve().parents[1] / "calibrations" / "super8_template_bank_v1.npz"
DEFAULT_SUPER8_TEMPLATE_METADATA = Path(__file__).resolve().parents[1] / "calibrations" / "super8_template_bank_v1.json"
# Shared processing-engine scratch root.  This is intentionally not part of
# either film-format calibration; both formats use the same staging policy.
DEFAULT_STAGING_DIR = Path("/mnt/grokcam-scratch")


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
    report: Path = DEFAULT_MATCH_REPORT


@dataclass(frozen=True)
class VerticalStabilizationCalibration:
    """Second-stage physical registration, disabled for backward compatibility."""

    enabled: bool = False
    top_reference_y: float = 224.9285714286
    bottom_reference_y: float = 757.0
    minimum_confidence: float = 0.20
    top_bottom_agreement_tolerance: float = 5.0


@dataclass(frozen=True)
class Super8RegistrationCalibration:
    """Versioned, image-only Super 8 P03/P06 registration resources."""

    template_bank: Path = DEFAULT_SUPER8_TEMPLATE_BANK
    template_metadata: Path = DEFAULT_SUPER8_TEMPLATE_METADATA
    template_patch_width: int = 320
    template_patch_height: int = 360
    x_search: tuple[int, int] = (100, 500)
    scales: tuple[float, ...] = (0.94, 0.97, 1.00, 1.03, 1.06, 1.09)
    p06_score_min: float = 0.56
    p06_geometry_min: float = 0.35
    p06_representation_agreement_px: float = 18.0
    p06_competitor_margin_min: float = 0.045
    p06_competitor_y_separation_px: float = 24.0
    p06_competitor_x_separation_px: float = 32.0
    p06_physical_cluster_x_px: float = 96.0
    p06_physical_cluster_y_px: float = 80.0
    crop_validated: bool = False
    crop_version: str = "unvalidated"
    crop_x_offset: float = 0.0
    crop_y_offset: float = 0.0
    crop_width: int = 0
    crop_height: int = 0

    def to_dict(self) -> dict:
        value = asdict(self)
        value["template_bank"] = str(self.template_bank)
        value["template_metadata"] = str(self.template_metadata)
        return value


@dataclass(frozen=True)
class ProductionCalibration:
    detector: DetectorCalibration = field(default_factory=DetectorCalibration)
    crop: CropCalibration = field(default_factory=CropCalibration)
    match: MatchCalibration = field(default_factory=MatchCalibration)
    vertical_stabilization: VerticalStabilizationCalibration = field(
        default_factory=VerticalStabilizationCalibration
    )
    super8_registration: Super8RegistrationCalibration = field(
        default_factory=Super8RegistrationCalibration
    )
    film_format: str = "regular8"
    # Output orientation is a rendering property.  Detection and registration
    # always operate in the native developed-image coordinate system.
    vertical_flip: bool = True
    sprocket_detector_mode: str = "physical-p07-v1"
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
        allowed = {"detector", "crop", "match", "vertical_stabilization", "super8_registration", "film_format", "vertical_flip", "sprocket_detector_mode", "contrast", "picture_aperture_x",
                   "picture_aperture_y", "exposure_limit_stops", "white_balance_blend"}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"unknown calibration keys: {', '.join(sorted(unknown))}")
        detector = replace(calibration.detector, **raw.get("detector", {}))
        crop = replace(calibration.crop, **raw.get("crop", {}))
        match_values = raw.get("match", {})
        match = replace(calibration.match, **({"report": Path(match_values["report"])} if "report" in match_values else {}))
        vertical = replace(calibration.vertical_stabilization,
                           **raw.get("vertical_stabilization", {}))
        super8_values = raw.get("super8_registration", {})
        if "template_bank" in super8_values:
            super8_values = {**super8_values, "template_bank": Path(super8_values["template_bank"])}
        if "template_metadata" in super8_values:
            super8_values = {**super8_values, "template_metadata": Path(super8_values["template_metadata"])}
        super8 = replace(calibration.super8_registration, **super8_values)
        scalar = {k: v for k, v in raw.items()
                  if k not in {"detector", "crop", "match", "vertical_stabilization", "super8_registration"}}
        calibration = replace(calibration, detector=detector, crop=crop, match=match,
                              vertical_stabilization=vertical, super8_registration=super8, **scalar)
    if calibration.film_format not in {"regular8", "super8"}:
        raise ValueError("film_format must be regular8 or super8")
    if calibration.sprocket_detector_mode not in {"legacy", "physical-p07-v1"}:
        raise ValueError("sprocket_detector_mode must be legacy or physical-p07-v1")
    if match_report is not None:
        calibration = replace(calibration, match=MatchCalibration(match_report))
    return calibration
