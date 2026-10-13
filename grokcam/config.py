"""Authoritative production calibration and per-run configuration."""

from __future__ import annotations

import json
import math
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
class Regular8CaptureGeometry:
    """Validated, optional per-capture Regular 8 pixel geometry.

    These values describe the optical mapping for one capture session. They
    do not redefine the Regular 8 film format and are intentionally absent by
    default for backward compatibility.
    """

    schema_version: int
    film_format: str
    source: str
    calibration_frames: tuple[int, ...]
    sprocket_pitch_px: float
    sprocket_pitch_mad_px: float
    sprocket_width_px: float
    sprocket_width_mad_px: float
    sprocket_height_px: float
    sprocket_height_mad_px: float
    sprocket_x_px: float
    sprocket_x_mad_px: float
    lower_x_minus_midpoint_px: float
    lower_top_minus_midpoint_px: float
    lower_top_residual_mad_px: float
    p24_capture_pitch_px: float
    p24_capture_pitch_mad_px: float
    p24_capture_width_px: float
    p24_capture_width_mad_px: float
    p24_capture_height_px: float
    p24_capture_height_mad_px: float
    p24_capture_x_displacement_px: float
    p24_capture_x_displacement_mad_px: float
    quality: dict = field(default_factory=dict)
    sanity_bounds: dict = field(default_factory=dict)
    calibration_method: str = "legacy_manual"
    calibration_timestamp: str | None = None
    frozen: bool = True
    p15_image_support_width_px: float | None = None
    p15_image_support_height_px: float | None = None

    _BOUNDS = {
        "sprocket_pitch_px": (500.0, 1000.0),
        "sprocket_width_px": (100.0, 500.0),
        "sprocket_height_px": (100.0, 400.0),
        "sprocket_x_px": (100.0, 700.0),
        "p24_capture_pitch_px": (500.0, 1000.0),
        "p24_capture_width_px": (200.0, 500.0),
        "p24_capture_height_px": (150.0, 400.0),
        "p24_capture_x_displacement_px": (-100.0, 100.0),
    }

    @classmethod
    def from_dict(cls, raw: dict) -> "Regular8CaptureGeometry":
        if not isinstance(raw, dict):
            raise ValueError("capture geometry must be a JSON object")
        required = {
            "schema_version", "film_format", "source", "calibration_frames",
            "sprocket_pitch_px", "sprocket_pitch_mad_px", "sprocket_width_px",
            "sprocket_width_mad_px", "sprocket_height_px", "sprocket_height_mad_px",
            "sprocket_x_px", "sprocket_x_mad_px", "lower_x_minus_midpoint_px",
            "lower_top_minus_midpoint_px", "lower_top_residual_mad_px",
            "p24_capture_pitch_px", "p24_capture_pitch_mad_px",
            "p24_capture_width_px", "p24_capture_width_mad_px",
            "p24_capture_height_px", "p24_capture_height_mad_px",
            "p24_capture_x_displacement_px", "p24_capture_x_displacement_mad_px",
        }
        missing = sorted(required - set(raw))
        if missing:
            raise ValueError("capture geometry missing required fields: " + ", ".join(missing))
        if raw["schema_version"] != 1:
            raise ValueError(f"unsupported capture geometry schema_version: {raw['schema_version']}")
        if raw["film_format"] != "regular8":
            raise ValueError("capture geometry film_format must be regular8")
        if raw.get("frozen", True) is not True:
            raise ValueError("capture geometry must be frozen before processing")
        frames = raw["calibration_frames"]
        if (not isinstance(frames, list) or not frames or
                any(isinstance(value, bool) or not isinstance(value, int) or value < 1
                    for value in frames)):
            raise ValueError("capture geometry calibration_frames must be non-empty positive integers")
        values = {key: raw[key] for key in required
                  if key not in {"schema_version", "film_format", "source", "calibration_frames"}}
        for key, value in values.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError(f"capture geometry {key} must be a finite number")
        for key in ("p15_image_support_width_px", "p15_image_support_height_px"):
            if key in raw:
                value = raw[key]
                if (not isinstance(value, (int, float)) or isinstance(value, bool) or
                        not math.isfinite(float(value))):
                    raise ValueError(f"capture geometry {key} must be a finite number")
        for key in (key for key in values if key.endswith("_mad_px")):
            if float(values[key]) < 0:
                raise ValueError(f"capture geometry {key} must not be negative")
        for key, (low, high) in cls._BOUNDS.items():
            value = float(raw[key])
            if not low <= value <= high:
                raise ValueError(f"capture geometry {key}={value} is outside sanity bounds [{low}, {high}]")
        for key, fallback in (("p15_image_support_width_px", "sprocket_width_px"),
                              ("p15_image_support_height_px", "sprocket_height_px")):
            value = float(raw.get(key, raw[fallback]))
            low, high = cls._BOUNDS[fallback]
            if not low <= value <= high:
                raise ValueError(f"capture geometry {key}={value} is outside sanity bounds [{low}, {high}]")
        quality = raw.get("quality", {})
        if not isinstance(quality, dict):
            raise ValueError("capture geometry quality must be an object")
        quality = dict(quality)
        quality.setdefault(
            "capture_lower_top_minus_midpoint",
            quality.get("p24_capture_lower_top_minus_midpoint"),
        )
        quality.setdefault(
            "capture_lower_x_minus_midpoint",
            quality.get("p24_capture_lower_x_minus_midpoint"),
        )
        capture_quality = {
            "capture_lower_top_minus_midpoint",
            "capture_lower_x_minus_midpoint",
        }
        if not all(isinstance(quality.get(key), dict) and
                   isinstance(quality[key].get("median"), (int, float)) and
                   math.isfinite(float(quality[key]["median"]))
                   for key in capture_quality):
            raise ValueError("capture geometry quality lacks P24 lower-edge medians")
        return cls(
            schema_version=1, film_format="regular8", source=str(raw["source"]),
            calibration_frames=tuple(frames),
            **{key: float(raw[key]) for key in values},
            quality=quality, sanity_bounds=raw.get("sanity_bounds", {}),
            calibration_method=str(raw.get("calibration_method", "legacy_manual")),
            calibration_timestamp=raw.get("calibration_timestamp"),
            frozen=bool(raw.get("frozen", True)),
            p15_image_support_width_px=(
                float(raw["p15_image_support_width_px"])
                if raw.get("p15_image_support_width_px") is not None
                else float(raw["sprocket_width_px"])
            ),
            p15_image_support_height_px=(
                float(raw["p15_image_support_height_px"])
                if raw.get("p15_image_support_height_px") is not None
                else float(raw["sprocket_height_px"])
            ),
        )

    @property
    def p24_capture_lower_top_minus_midpoint_px(self) -> float:
        return float(self.quality["capture_lower_top_minus_midpoint"]["median"])

    @property
    def p24_capture_lower_x_minus_midpoint_px(self) -> float:
        return float(self.quality["capture_lower_x_minus_midpoint"]["median"])

    def to_dict(self) -> dict:
        return asdict(self)


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
    capture_geometry: Regular8CaptureGeometry | None = None
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
    # Primary detector and registration policy are independent choices. The
    # legacy attribute below remains the Python attribute and legacy JSON
    # input alias for registration selection.
    sprocket_detector_id: str = "adaptive-v1"
    sprocket_detector_options: dict = field(default_factory=dict)
    sprocket_detector_mode: str = "physical-p07-v1"
    contrast: float = 1.04
    picture_aperture_x: tuple[float, float] = (0.15, 0.92)
    picture_aperture_y: tuple[float, float] = (0.12, 0.88)
    exposure_limit_stops: float = 0.65
    white_balance_blend: float = 0.25

    def to_dict(self) -> dict:
        value = asdict(self)
        value["match"]["report"] = str(self.match.report)
        detector_id = value.pop("sprocket_detector_id")
        detector_options = value.pop("sprocket_detector_options")
        registration = value.pop("sprocket_detector_mode")
        value["sprocket"] = {"detector": detector_id, "registration": registration}
        if detector_options:
            value["sprocket"]["options"] = detector_options
        return value


def load_calibration(path: Path | None = None, match_report: Path | None = None) -> ProductionCalibration:
    """Load optional JSON overrides without changing golden defaults."""
    calibration = ProductionCalibration()
    if path is not None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        allowed = {"detector", "crop", "match", "capture_geometry", "vertical_stabilization", "super8_registration", "film_format", "vertical_flip", "sprocket_detector_mode", "sprocket", "contrast", "picture_aperture_x",
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
        geometry_value = raw.get("capture_geometry")
        geometry = (None if geometry_value is None else
                    Regular8CaptureGeometry.from_dict(geometry_value))
        if geometry is not None and raw.get("film_format", calibration.film_format) != "regular8":
            raise ValueError("capture geometry is only supported for regular8")
        super8_values = raw.get("super8_registration", {})
        if "template_bank" in super8_values:
            super8_values = {**super8_values, "template_bank": Path(super8_values["template_bank"])}
        if "template_metadata" in super8_values:
            super8_values = {**super8_values, "template_metadata": Path(super8_values["template_metadata"])}
        super8 = replace(calibration.super8_registration, **super8_values)
        sprocket = raw.get("sprocket", {})
        if not isinstance(sprocket, dict):
            raise ValueError("sprocket must be a JSON object")
        unknown_sprocket = set(sprocket) - {"detector", "registration", "options"}
        if unknown_sprocket:
            raise ValueError("unknown sprocket keys: " + ", ".join(sorted(unknown_sprocket)))
        detector_id = sprocket.get("detector", calibration.sprocket_detector_id)
        detector_options = sprocket.get("options", calibration.sprocket_detector_options)
        if not isinstance(detector_options, dict):
            raise ValueError("sprocket.options must be a JSON object")
        registration = sprocket.get("registration", raw.get(
            "sprocket_detector_mode", calibration.sprocket_detector_mode))
        if ("registration" in sprocket and "sprocket_detector_mode" in raw and
                sprocket["registration"] != raw["sprocket_detector_mode"]):
            raise ValueError("sprocket.registration conflicts with sprocket_detector_mode")
        scalar = {k: v for k, v in raw.items()
                  if k not in {"detector", "crop", "match", "capture_geometry", "vertical_stabilization", "super8_registration", "sprocket", "sprocket_detector_mode"}}
        calibration = replace(calibration, detector=detector, crop=crop, match=match,
                              capture_geometry=geometry,
                              vertical_stabilization=vertical, super8_registration=super8,
                              sprocket_detector_id=detector_id,
                              sprocket_detector_options=dict(detector_options),
                              sprocket_detector_mode=registration, **scalar)
    if calibration.film_format not in {"regular8", "super8"}:
        raise ValueError("film_format must be regular8 or super8")
    if calibration.sprocket_detector_mode not in {"legacy", "physical-p07-v1"}:
        raise ValueError("sprocket_detector_mode must be legacy or physical-p07-v1")
    from .detectors.registry import detector_registered
    if not detector_registered(calibration.sprocket_detector_id):
        raise ValueError(f"unknown sprocket detector: {calibration.sprocket_detector_id}")
    if match_report is not None:
        calibration = replace(calibration, match=MatchCalibration(match_report))
    return calibration


def load_capture_geometry(path: Path | None) -> Regular8CaptureGeometry | None:
    """Load and strictly validate an optional standalone geometry artifact."""
    if path is None:
        return None
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"capture geometry file does not exist: {resolved}")
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"could not read capture geometry {resolved}: {error}") from error
    return Regular8CaptureGeometry.from_dict(raw)
