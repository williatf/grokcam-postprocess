"""Golden full-resolution sprocket-pair detector and batch validation."""

from __future__ import annotations

import numpy as np
from PIL import Image

from .config import DetectorCalibration
from .models import SprocketDetection


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
    raw = np.array([(d.cx, d.cy) if d else (np.nan, np.nan) for d in detections], dtype=float)
    detected = np.array([d is not None for d in detections], dtype=bool)
    accepted = detected.copy()
    for axis, limit in ((0, calibration.horizontal_outlier_limit), (1, calibration.vertical_outlier_limit)):
        series = raw[:, axis]
        safe = np.where(np.isfinite(series), series, np.nanmedian(series))
        padded = np.pad(safe, 2, mode="edge")
        local = np.array([np.median(padded[i:i + 5]) for i in range(len(series))])
        accepted &= np.isfinite(series) & (np.abs(series - local) < limit)
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
