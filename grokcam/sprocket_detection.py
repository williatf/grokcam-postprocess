"""Golden full-resolution sprocket-pair detector and batch validation."""

from __future__ import annotations

import numpy as np
from PIL import Image

from .config import DetectorCalibration
from .models import SprocketDetection


def _batch_acceptance(detections, calibration):
    raw = np.array([(d.cx, d.cy) if d else (np.nan, np.nan) for d in detections], dtype=float)
    detected = np.array([d is not None for d in detections], dtype=bool)
    accepted = detected.copy()
    for axis, limit in ((0, calibration.horizontal_outlier_limit), (1, calibration.vertical_outlier_limit)):
        series = raw[:, axis]
        safe = np.where(np.isfinite(series), series, np.nanmedian(series))
        padded = np.pad(safe, 2, mode="edge")
        local = np.array([np.median(padded[i:i + 5]) for i in range(len(series))])
        accepted &= np.isfinite(series) & (np.abs(series - local) < limit)
    return raw, detected, accepted


def runs(mask: np.ndarray) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    start = None
    for index, value in enumerate(mask):
        if value and start is None:
            start = index
        if start is not None and (not value or index == len(mask) - 1):
            result.append((start, index if not value else index + 1))
            start = None
    return result


def detect(image: Image.Image, calibration: DetectorCalibration) -> SprocketDetection:
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    x0, x1 = calibration.search_x0, calibration.search_x1
    luminance = rgb[:, x0:x1].mean(axis=2)
    threshold = float(np.percentile(luminance, calibration.bright_percentile) * calibration.threshold_scale)
    bright = luminance > threshold
    bands = [(a, b) for a, b in runs(bright.sum(axis=1) > calibration.minimum_bright_row_pixels)
             if calibration.band_height_min <= b - a <= calibration.band_height_max]
    candidates: list[tuple[float, float, float]] = []
    for upper, lower in zip(bands, bands[1:]):
        uy, ly = sum(upper) / 2.0, sum(lower) / 2.0
        pitch_error = abs((ly - uy) - calibration.expected_pitch)
        if pitch_error > calibration.pitch_tolerance:
            continue
        centers, widths = [], []
        for top, bottom in (upper, lower):
            columns = np.flatnonzero(bright[top:bottom].sum(axis=0) > (bottom - top) * calibration.column_fill)
            if len(columns) < calibration.minimum_bright_columns:
                break
            left, right = int(columns[0]), int(columns[-1])
            centers.append((left + right) / 2.0 + x0)
            widths.append(right - left + 1)
        if len(centers) == 2:
            score = (pitch_error + abs(centers[0] - centers[1]) * 2
                     + abs(np.mean(widths) - calibration.expected_width) * 0.2)
            candidates.append((score, float(np.mean(centers)), (uy + ly) / 2.0))
    if not candidates:
        raise ValueError("no reliable sprocket pair")
    score, cx, cy = min(candidates)
    return SprocketDetection(cx=cx, cy=cy, score=score)


def validate_batch(detections: list[SprocketDetection | None], calibration: DetectorCalibration) -> list[SprocketDetection]:
    raw, detected, accepted = _batch_acceptance(detections, calibration)
    positions = np.arange(len(raw))
    output = raw.copy()
    for axis in range(2):
        good = accepted & np.isfinite(output[:, axis])
        if not good.any():
            raise RuntimeError("No usable sprocket measurements in batch")
        output[:, axis] = np.interp(positions, positions[good], output[good, axis])
    return [SprocketDetection(float(x), float(y), detections[i].score if detections[i] else None,
                              detected=bool(detected[i]), accepted=bool(accepted[i]),
                              interpolated=not bool(accepted[i]))
            for i, (x, y) in enumerate(output)]


def validate_batch_with_physical(image_loader, detections, calibration, capture_items=None):
    """Resolve from same-frame evidence; leave unresolved frames excluded."""
    from .physical_sprocket import detect_fallback
    capture_items = capture_items or [None] * len(detections)
    raw, detected, accepted = _batch_acceptance(detections, calibration)
    details = []
    for index, _prior in enumerate(detections):
        detail = {"physical_fallback_stage": None, "p06_attempted": False,
                  "p06_accepted": False, "p07_attempted": False, "p07_accepted": False,
                  "primary_detected": bool(detected[index]),
                  "primary_accepted": bool(accepted[index]),
                  "primary_rejected_anchor": (None if accepted[index] or detections[index] is None else
                      {"x": detections[index].cx, "y": detections[index].cy,
                       "score": detections[index].score})}
        if accepted[index]:
            detail["final_registration_source"] = "primary"
        else:
            # Capture boxes only define search ROIs. The accepted anchor always
            # comes from full-resolution same-frame image evidence.
            with image_loader(index) as image:
                result = detect_fallback(image, capture_items[index])
            stage=result.diagnostics.get("stage","p07")
            detail.update({"physical_fallback_stage": stage,
                           "p06_attempted": stage in {"p06","p07"} and result.diagnostics.get("p06") is not None,
                           "p06_accepted": stage == "p06",
                           "p07_attempted": stage == "p07", "p07_accepted": stage == "p07" and result.accepted,
                           "physical_diagnostics": result.diagnostics,
                           "physical_rejection_reason": None if result.accepted else result.classification})
            if result.accepted:
                raw[index] = (result.anchor_x, result.anchor_y)
                accepted[index] = True
                detail["final_registration_source"] = {"physical_pair":"physical_pair","p06":"physical_p06","p07":"physical_p07"}[stage]
            else:
                detail.update({"final_registration_source": None,
                               "output_disposition": "excluded",
                               "exclusion_reason": result.classification})
        details.append(detail)
    resolved=[]
    for i,(x,y) in enumerate(raw):
        if not accepted[i]:
            resolved.append(None)
            continue
        score=detections[i].score if detections[i] else None
        resolved.append(SprocketDetection(float(x),float(y),score,
                        detector=details[i]["final_registration_source"],
                        detected=bool(detected[i]),accepted=True,interpolated=False))
        details[i].setdefault("output_disposition", "included")
    return resolved, details
