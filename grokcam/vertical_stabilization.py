"""Residual sprocket measurement and second-stage vertical registration.

This module refines primary crop coordinates.  It never shifts an already
cropped output image and deliberately places no limit on correction magnitude.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace

import numpy as np
from PIL import Image

from .config import VerticalStabilizationCalibration
from .models import CropGeometry, SprocketDetection


@dataclass(frozen=True)
class ResidualMeasurement:
    y: float | None
    confidence: float
    edge_strength: float = 0.0
    edge_contrast: float = 0.0
    bright_tail_fraction: float = 0.0


@dataclass(frozen=True)
class FrameMeasurements:
    normal: ResidualMeasurement
    expanded: ResidualMeasurement | None
    selected_top: ResidualMeasurement
    search_mode: str
    bottom: ResidualMeasurement


@dataclass(frozen=True)
class StabilizationResult:
    correction_y: float
    source: str
    corrected_crop: CropGeometry
    diagnostics: dict


def _luminance(image: Image.Image) -> np.ndarray:
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    return rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def measure_top(
    image: Image.Image,
    roi: tuple[int, int, int, int] = (0, 150, 90, 285),
    expected_y: float | None = None,
) -> ResidualMeasurement:
    """Measure the falling lower boundary of the retained upper sprocket."""
    x0, y0, x1, y1 = roi
    lum = _luminance(image)[y0:y1, x0:x1]
    if lum.shape[0] < 7 or lum.shape[1] < 8:
        return ResidualMeasurement(None, 0.0)
    threshold = max(0.70, float(np.percentile(lum, 90)) * 0.88)
    smooth = np.convolve(np.mean(lum >= threshold, axis=1),
                         np.array([1, 2, 3, 2, 1], dtype=float) / 9.0, mode="same")
    gradient = -np.gradient(smooth)
    start, stop = 3, len(gradient) - 3
    if expected_y is not None:
        index = int(round(expected_y - y0))
        start, stop = max(start, index - 10), min(stop, index + 11)
    if start >= stop:
        return ResidualMeasurement(None, 0.0)
    index = int(np.argmax(gradient[start:stop]) + start)
    strength = float(gradient[index])
    offset = _subpixel_offset(gradient, index)
    bright_above = float(np.mean(smooth[max(0, index - 12):index]))
    dark_below = float(np.mean(smooth[index:min(len(smooth), index + 12)]))
    contrast = max(0.0, bright_above - dark_below)
    bright_tail = float(np.mean(smooth[index + 2:min(len(smooth), index + 8)]))
    confidence = float(np.clip((strength / 0.08) * (contrast / 0.18), 0.0, 1.0))
    if strength < 0.018 or contrast < 0.045:
        return ResidualMeasurement(None, confidence, strength, contrast, bright_tail)
    return ResidualMeasurement(y0 + index + offset, confidence, strength, contrast, bright_tail)


def measure_bottom(image: Image.Image,
                   roi: tuple[int, int, int, int] = (0, 550, 90, 900)) -> ResidualMeasurement:
    """Measure the rising upper boundary of the retained lower sprocket."""
    x0, y0, x1, y1 = roi
    lum = _luminance(image)[y0:y1, x0:x1]
    if lum.shape[0] < 7 or lum.shape[1] < 8:
        return ResidualMeasurement(None, 0.0)
    threshold = max(0.70, float(np.percentile(lum, 90)) * 0.88)
    smooth = np.convolve(np.mean(lum >= threshold, axis=1),
                         np.array([1, 2, 3, 2, 1], dtype=float) / 9.0, mode="same")
    gradient = np.gradient(smooth)
    index = int(np.argmax(gradient[3:-3]) + 3)
    strength = float(gradient[index])
    offset = _subpixel_offset(gradient, index)
    dark_above = float(np.mean(smooth[max(0, index - 12):index]))
    bright_below = float(np.mean(smooth[index:min(len(smooth), index + 12)]))
    contrast = max(0.0, bright_below - dark_above)
    bright_tail = float(np.mean(smooth[index + 2:min(len(smooth), index + 8)]))
    confidence = float(np.clip((strength / 0.04) * (contrast / 0.14), 0.0, 1.0))
    if strength < 0.009 or contrast < 0.055 or bright_tail < 0.05:
        return ResidualMeasurement(None, confidence, strength, contrast, bright_tail)
    return ResidualMeasurement(y0 + index + offset, confidence, strength, contrast, bright_tail)


def _subpixel_offset(gradient: np.ndarray, index: int) -> float:
    if not 0 < index < len(gradient) - 1:
        return 0.0
    left, center, right = gradient[index - 1:index + 2]
    denominator = left - 2.0 * center + right
    if abs(denominator) <= 1e-9:
        return 0.0
    return float(np.clip(0.5 * (left - right) / denominator, -0.75, 0.75))


def top_rejection(measurement: ResidualMeasurement, minimum_confidence: float) -> list[str]:
    reasons = []
    if measurement.y is None:
        reasons.append("no_residual_edge")
    elif measurement.confidence < minimum_confidence:
        reasons.append("confidence_below_minimum")
    if measurement.bright_tail_fraction > 0.30:
        reasons.append("nonterminal_bright_boundary")
    return reasons


def bottom_rejection(measurement: ResidualMeasurement) -> list[str]:
    reasons = []
    if measurement.y is None:
        reasons.append("no_bottom_edge")
    elif measurement.confidence < 0.20:
        reasons.append("bottom_confidence_below_minimum")
    if measurement.y is not None and measurement.bright_tail_fraction < 0.05:
        reasons.append("bottom_bright_region_too_weak")
    return reasons


def measure_frame(image: Image.Image, primary: SprocketDetection,
                  config: VerticalStabilizationCalibration) -> FrameMeasurements:
    normal = measure_top(image)
    selected, expanded, mode = normal, None, "normal"
    if not primary.accepted and top_rejection(normal, config.minimum_confidence):
        expanded = measure_top(image, roi=(0, 60, 90, 285))
        if not top_rejection(expanded, config.minimum_confidence):
            selected, mode = expanded, "expanded"
    return FrameMeasurements(normal, expanded, selected, mode, measure_bottom(image))


def resolve_batch(measurements: list[FrameMeasurements], primary_crops: list[CropGeometry],
                  developed_heights: list[int],
                  config: VerticalStabilizationCalibration) -> list[StabilizationResult]:
    """Validate same-frame measurements, then interpolate only unresolved gaps."""
    if not (len(measurements) == len(primary_crops) == len(developed_heights)):
        raise ValueError("stabilization batch inputs must have equal lengths")
    raw: list[float | None] = []
    sources: list[str | None] = []
    diagnostics: list[dict] = []
    for measured, crop, height in zip(measurements, primary_crops, developed_heights):
        top = measured.selected_top
        bottom = measured.bottom
        top_reasons = top_rejection(top, config.minimum_confidence)
        bottom_reasons = bottom_rejection(bottom)
        top_correction = None if top.y is None else config.top_reference_y - top.y
        bottom_correction = None if bottom.y is None else config.bottom_reference_y - bottom.y
        if top_correction is not None and not _crop_in_bounds(crop, top_correction, height):
            top_reasons.append("corrected_crop_out_of_source_bounds")
        if bottom_correction is not None and not _crop_in_bounds(crop, bottom_correction, height):
            bottom_reasons.append("bottom_corrected_crop_out_of_source_bounds")
        disagreement = (None if top_correction is None or bottom_correction is None
                        else bottom_correction - top_correction)
        agreement = (None if disagreement is None else
                     abs(disagreement) <= config.top_bottom_agreement_tolerance)
        if not top_reasons:
            correction = top_correction
            source = "expanded_residual" if measured.search_mode == "expanded" else "measured"
        elif not bottom_reasons:
            correction, source = bottom_correction, "bottom_rescue"
        else:
            correction, source = None, None
        raw.append(correction)
        sources.append(source)
        diagnostics.append({
            "residual_sprocket_y": top.y,
            "residual_confidence": top.confidence,
            "residual_search_mode": measured.search_mode,
            "residual_rejection_reason": ";".join(top_reasons),
            "bottom_sprocket_y": bottom.y,
            "bottom_confidence": bottom.confidence,
            "bottom_rejection_reason": ";".join(bottom_reasons),
            "bottom_correction_y": bottom_correction,
            "top_bottom_correction_disagreement_y": disagreement,
            "top_bottom_corrections_agree": agreement,
        })
    values = np.array([np.nan if value is None else value for value in raw], dtype=float)
    good = np.isfinite(values)
    if not good.any():
        raise RuntimeError("No trustworthy residual stabilization measurements in batch")
    positions = np.arange(len(values))
    applied = np.interp(positions, positions[good], values[good])
    first_good, last_good = positions[good][0], positions[good][-1]
    results = []
    for index, (correction, crop, detail) in enumerate(zip(applied, primary_crops, diagnostics)):
        source = sources[index]
        if source is None:
            source = "interpolated" if first_good < index < last_good else "fallback"
        corrected = replace(crop, top=crop.top + float(correction))
        detail.update({"residual_source": source, "residual_correction_y": float(correction),
                       "corrected_crop_top": corrected.top})
        results.append(StabilizationResult(float(correction), source, corrected, detail))
    return results


def verify_post_crop(image: Image.Image, config: VerticalStabilizationCalibration) -> dict:
    measured = measure_top(image, expected_y=config.top_reference_y)
    valid = not top_rejection(measured, config.minimum_confidence)
    return {"post_correction_residual_y": (
                None if measured.y is None else measured.y - config.top_reference_y),
            "post_correction_confidence": measured.confidence,
            "post_correction_measurement_valid": valid}


def measurement_details(measurement: ResidualMeasurement | None) -> dict | None:
    return None if measurement is None else asdict(measurement)


def _crop_in_bounds(crop: CropGeometry, correction: float, height: int) -> bool:
    top = crop.top + correction
    return top >= 0 and top + crop.height <= height
