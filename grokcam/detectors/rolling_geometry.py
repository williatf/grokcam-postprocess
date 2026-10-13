"""The experimentally evaluated sequential rolling-geometry detector.

The pair and edge helpers below intentionally preserve the research-study
implementation.  They are copied verbatim from the tracked reference script's
``annotate_primary_strip.py`` dependency; the trial used these helpers rather
than ``grokcam.sprocket_detection.detect`` to enumerate and score candidates.
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import asdict
from itertools import product
from typing import Any

import numpy as np
from PIL import Image

from ..config import DetectorCalibration
from ..models import SprocketDetection
from ..sprocket_detection import runs
from .base import DetectorDiagnostics, DetectorResult


X0, X1 = 240, 660
SCALE = 0.96
ALPHA = 0.65
WINDOW = 25
BOOTSTRAP_GOAL = 12
SEED_MIN = 5
SMOOTH_HALF = 5
STATE_SCHEMA = 1


def pair_bands(bright: np.ndarray, cal):
    row_counts = bright.sum(axis=1)
    bands = [(top, bottom) for top, bottom in runs(
        row_counts > cal.minimum_bright_row_pixels)
        if cal.band_height_min <= bottom - top <= cal.band_height_max]
    candidates = []
    for upper, lower in zip(bands, bands[1:]):
        uy, ly = sum(upper) / 2.0, sum(lower) / 2.0
        pitch_error = abs((ly - uy) - cal.expected_pitch)
        if pitch_error > cal.pitch_tolerance:
            continue
        centers, widths = [], []
        for top, bottom in (upper, lower):
            columns = np.flatnonzero(
                bright[top:bottom].sum(axis=0) > (bottom - top) * cal.column_fill)
            if len(columns) < cal.minimum_bright_columns:
                break
            left, right = int(columns[0]), int(columns[-1])
            centers.append((left + right) / 2.0 + cal.search_x0)
            widths.append(right - left + 1)
        if len(centers) == 2:
            score = (pitch_error + abs(centers[0] - centers[1]) * 2
                     + abs(np.mean(widths) - cal.expected_width) * 0.2)
            candidates.append((score, upper, lower))
    return row_counts, bands, min(candidates, default=None, key=lambda item: item[0])


def band_edges(bright: np.ndarray, band: tuple[int, int], cal):
    """Return global X bounds using the detector's column-fill rule."""
    top, bottom = band
    columns = np.flatnonzero(
        bright[top:bottom].sum(axis=0) > (bottom - top) * cal.column_fill
    )
    if len(columns) < cal.minimum_bright_columns:
        return None
    return int(columns[0]) + cal.search_x0, int(columns[-1]) + cal.search_x0


def _median(values):
    return float(np.median(values)) if values else None


def _model(history: deque[dict[str, Any]]) -> dict[str, float | None]:
    return {
        "height": _median([band["height"] for row in history for band in row["features"]]),
        "width": _median([band["width"] for row in history for band in row["features"]]),
        "aspect": _median([band["aspect"] for row in history for band in row["features"]]),
        "pitch": _median([row["pitch"] for row in history]),
        "center": _median([row["center"] for row in history]),
        "row_count": _median([row["row_plateau"] for row in history]),
    }


def _broad_valid(features: dict[str, Any]) -> bool:
    return (all(205 <= band["height"] <= 275 and 250 <= band["width"] <= 430
                and 1.0 <= band["aspect"] <= 1.85 for band in features["features"])
            and 680 <= features["pitch"] <= 790
            and abs(features["features"][0]["cx"] - features["features"][1]["cx"]) <= 65)


def _geometry_ok(features: dict[str, Any], model: dict[str, float | None],
                 bootstrap: bool = False, relaxed: bool = False) -> tuple[bool, str]:
    if not _broad_valid(features):
        return False, "broad_geometry"
    if bootstrap or model["pitch"] is None:
        return True, "bootstrap_geometry"
    if abs(features["pitch"] - model["pitch"]) > (25 if relaxed else 12):
        return False, "pitch"
    if any(abs(band["height"] - model["height"]) > (30 if relaxed else 12)
           for band in features["features"]):
        return False, "height"
    if any(abs(band["width"] - model["width"]) > (75 if relaxed else 30)
           for band in features["features"]):
        return False, "width"
    if any(abs(band["aspect"] - model["aspect"]) > (.35 if relaxed else .18)
           for band in features["features"]):
        return False, "aspect"
    if abs(features["center"] - model["center"]) > (80 if relaxed else 45):
        return False, "center"
    return True, "rolling_geometry"


def _rank(features: dict[str, Any], model: dict[str, float | None]) -> float:
    strength = sum(band.get("rise", 0) + band.get("fall", 0)
                   for band in features["features"])
    return (abs(features["pitch"] - (model["pitch"] or 732))
            + sum(abs(band["height"] - (model["height"] or 240))
                  for band in features["features"])
            + .45 * sum(abs(band["width"] - (model["width"] or 343))
                        for band in features["features"])
            - .012 * strength)


def _feature(bright: np.ndarray, band: tuple[int, int], cal,
             permissive: bool = False) -> dict[str, Any] | None:
    if permissive:
        top, bottom = band
        height = bottom - top
        columns = np.flatnonzero(bright[top:bottom].sum(axis=0) > height * .35)
        if len(columns) < 120:
            return None
        edges = (int(columns[0]) + cal.search_x0, int(columns[-1]) + cal.search_x0)
    else:
        edges = band_edges(bright, band, cal)
        if edges is None:
            return None
    left, right = edges
    height = band[1] - band[0]
    return {"top": int(band[0]), "bottom": int(band[1]), "height": int(height),
            "left": left, "right": right, "width": int(right - left + 1),
            "cx": (left + right) / 2, "aspect": (right - left + 1) / height,
            "cy": (band[0] + band[1]) / 2}


def _pair_features(bright: np.ndarray, pair, cal) -> dict[str, Any] | None:
    upper, lower = pair
    upper_feature = _feature(bright, upper, cal)
    lower_feature = _feature(bright, lower, cal)
    if not upper_feature or not lower_feature:
        return None
    return {"bands": [[int(upper[0]), int(upper[1])], [int(lower[0]), int(lower[1])]],
            "features": [upper_feature, lower_feature],
            "pitch": lower_feature["cy"] - upper_feature["cy"],
            "center": (upper_feature["cx"] + lower_feature["cx"]) / 2,
            "width": (upper_feature["width"] + lower_feature["width"]) / 2,
            "aspect": (upper_feature["aspect"] + lower_feature["aspect"]) / 2,
            "heights": [upper_feature["height"], lower_feature["height"]]}


def _profile_events(counts: np.ndarray):
    smoothed = np.convolve(
        np.pad(counts.astype(float), (SMOOTH_HALF, SMOOTH_HALF), mode="edge"),
        np.ones(11) / 11, mode="valid")
    slope = np.zeros_like(smoothed)
    slope[SMOOTH_HALF:-SMOOTH_HALF] = (
        smoothed[2 * SMOOTH_HALF:] - smoothed[:-2 * SMOOTH_HALF])
    ups, downs = [], []
    for y in range(SMOOTH_HALF + 2, len(slope) - SMOOTH_HALF - 2):
        if slope[y] >= 25 and slope[y] >= slope[y - 1] and slope[y] > slope[y + 1]:
            ups.append((y, float(slope[y])))
        if slope[y] <= -25 and slope[y] <= slope[y - 1] and slope[y] < slope[y + 1]:
            downs.append((y, float(-slope[y])))
    return smoothed, ups, downs


def _profile_bands(ups, downs, expected_heights):
    output = []
    expected_height = float(np.mean(expected_heights))
    for (top, rise), (bottom, fall) in product(ups, downs):
        height = bottom - top
        if bottom <= top or abs(height - expected_height) > 38 or rise < 25 or fall < 20:
            continue
        output.append((top, bottom, rise, fall))
    return output


def _fallback(bright, counts, model, cal):
    smoothed, ups, downs = _profile_events(counts)
    bands = _profile_bands(ups, downs, [model["height"] or 242] * 2)
    pairs = []
    for upper, lower in product(bands, bands):
        if lower[0] <= upper[0]:
            continue
        features = []
        for band in (upper, lower):
            feature = _feature(bright, (band[0], band[1]), cal, permissive=True)
            if feature is None:
                break
            feature["rise"], feature["fall"] = band[2], band[3]
            features.append(feature)
        if len(features) != 2:
            continue
        pitch = features[1]["cy"] - features[0]["cy"]
        candidate = {
            "bands": [[upper[0], upper[1]], [lower[0], lower[1]]],
            "features": features, "pitch": pitch,
            "center": (features[0]["cx"] + features[1]["cx"]) / 2,
            "width": (features[0]["width"] + features[1]["width"]) / 2,
            "aspect": (features[0]["aspect"] + features[1]["aspect"]) / 2,
            "heights": [features[0]["height"], features[1]["height"]],
            "profile_edges": [upper[2:], lower[2:]],
        }
        good, _reason = _geometry_ok(candidate, model,
                                     bootstrap=model["pitch"] is None, relaxed=True)
        if good:
            pairs.append((_rank(candidate, model), candidate))
    selected = min(pairs, key=lambda item: item[0])[1] if pairs else None
    return selected, smoothed, ups, downs


class RollingGeometryV1Detector:
    """Past-only geometry calibration with the study's fast and fallback paths."""

    name = "rolling-geometry-v1"
    version = "1"
    stateful = True

    def __init__(self, calibration: DetectorCalibration, options: dict[str, Any] | None = None):
        if options:
            raise ValueError("rolling-geometry-v1 does not accept options; trial parameters are fixed")
        self._calibration = calibration
        self._history: deque[dict[str, Any]] = deque(maxlen=WINDOW)
        self._bootstrap: list[dict[str, Any]] = []

    def _effective_calibration(self, row_minimum: int) -> DetectorCalibration:
        # Match the trial's per-frame calibration replacement exactly.
        return self._calibration.__class__(**{
            **self._calibration.__dict__, "search_x0": X0, "search_x1": X1,
            "threshold_scale": SCALE, "minimum_bright_row_pixels": row_minimum,
        })

    def detect(self, image: Image.Image) -> DetectorResult:
        rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
        if rgb.shape[1] < X1 or rgb.shape[0] == 0:
            return self._unresolved("image_smaller_than_experimental_search_strip")
        luminance = rgb[:, X0:X1].mean(2)
        p99 = float(np.percentile(luminance, 99))
        threshold = p99 * SCALE
        bright = luminance > threshold
        counts = bright.sum(1).astype(np.uint16)
        model_before = _model(self._history)
        initialized = len(self._history) >= SEED_MIN
        row_minimum = (max(130, int(round(ALPHA * (model_before["row_count"] or 0))))
                       if initialized else 130)
        calibration = self._effective_calibration(row_minimum)

        _row_counts, bands, _selected = pair_bands(bright, calibration)
        fast_candidates = []
        for upper, lower in zip(bands, bands[1:]):
            features = _pair_features(bright, (upper, lower), calibration)
            if features and _broad_valid(features):
                accepted, reason = _geometry_ok(features, model_before,
                                                 bootstrap=not initialized)
                fast_candidates.append((features, accepted, reason))
        chosen = min((candidate for candidate in fast_candidates if candidate[1]),
                     key=lambda item: _rank(item[0], model_before), default=None)
        fallback_attempted = False
        ups, downs = [], []
        reason = ("no_fast_candidate" if not fast_candidates else
                  ";".join(sorted({item[2] for item in fast_candidates if not item[1]})))
        method, status = "fast", "accepted"
        if chosen is None:
            fallback_attempted = True
            method = "profile_fallback"
            fallback_pair, _smoothed, ups, downs = _fallback(
                bright, counts, model_before, calibration)
            if fallback_pair:
                chosen = (fallback_pair, True, "profile_geometry")
                status = "recovered" if fast_candidates or not bands else "fallback_only"
            else:
                status = "unresolved"

        pair = chosen[0] if chosen else None
        if pair:
            plateau = float(np.median(np.concatenate(
                [counts[top:bottom] for top, bottom in pair["bands"]])))
            pair["row_plateau"] = plateau
            record = {**pair, "row_plateau": plateau}
            if len(self._history) < BOOTSTRAP_GOAL:
                self._bootstrap.append(record)
            self._history.append(record)
        model_after = _model(self._history)

        detection = None
        score = None
        if pair:
            score = float(_rank(pair, model_before))
            center_y = (pair["features"][0]["cy"] + pair["features"][1]["cy"]) / 2
            detection = SprocketDetection(
                cx=float(pair["center"]), cy=float(center_y), score=score,
                detector=self.name, detected=True, accepted=True, interpolated=False,
            )
        details = {
            "method": method, "status": status,
            "fallback_attempted": fallback_attempted,
            "fallback_recovery_success": bool(fallback_attempted and pair),
            "geometry_gate_rejection_reason": reason,
            "rolling_geometry_before": model_before,
            "rolling_geometry_after": model_after,
            "rolling_pitch_px": model_before["pitch"],
            "rolling_height_px": model_before["height"],
            "rolling_width_px": model_before["width"],
            "rolling_aspect_ratio": model_before["aspect"],
            "rolling_center_x_px": model_before["center"],
            "dynamic_row_minimum": row_minimum,
            "bootstrap_progress": {"accepted_pairs": len(self._bootstrap),
                                   "goal": BOOTSTRAP_GOAL},
            "history_size": len(self._history),
            "candidate_count": len(fast_candidates),
            "fallback_rise_events": len(ups), "fallback_fall_events": len(downs),
            "p99_luminance": p99, "threshold": threshold,
            "pair": deepcopy(pair),
        }
        return DetectorResult(
            detection,
            DetectorDiagnostics(self.name, self.version, detection is not None,
                                confidence=score, fallback_used=fallback_attempted,
                                details=details),
        )

    def _unresolved(self, reason: str) -> DetectorResult:
        return DetectorResult(None, DetectorDiagnostics(
            self.name, self.version, False,
            details={"method": "none", "status": "unresolved", "reason": reason,
                     "fallback_attempted": False,
                     "fallback_recovery_success": False,
                     "bootstrap_progress": {"accepted_pairs": len(self._bootstrap),
                                            "goal": BOOTSTRAP_GOAL}},
        ))

    def configuration(self) -> dict[str, Any]:
        return {
            "calibration": asdict(self._calibration),
            "options": {},
            "fixed_parameters": {
                "search_x": [X0, X1], "threshold_percentile": 99.0,
                "threshold_scale": SCALE, "initial_row_minimum": 130,
                "dynamic_row_minimum_factor": ALPHA,
                "rolling_history_size": WINDOW, "bootstrap_goal": BOOTSTRAP_GOAL,
                "seed_minimum": SEED_MIN, "fallback_smoothing_half_width": SMOOTH_HALF,
            },
        }

    def get_state(self) -> dict[str, Any]:
        return {"schema": STATE_SCHEMA,
                "history": deepcopy(list(self._history)),
                "bootstrap": deepcopy(self._bootstrap)}

    def restore_state(self, state: dict[str, Any]) -> None:
        if not isinstance(state, dict) or set(state) != {"schema", "history", "bootstrap"}:
            raise ValueError("invalid rolling-geometry-v1 state")
        if state["schema"] != STATE_SCHEMA:
            raise ValueError("incompatible rolling-geometry-v1 state schema")
        history, bootstrap = state["history"], state["bootstrap"]
        if (not isinstance(history, list) or len(history) > WINDOW or
                not isinstance(bootstrap, list) or len(bootstrap) > BOOTSTRAP_GOAL):
            raise ValueError("invalid rolling-geometry-v1 state history")
        # Ensure checkpoints remain JSON-safe and reject corrupt/non-finite state.
        import json
        json.dumps(state, allow_nan=False)
        self._history = deque(deepcopy(history), maxlen=WINDOW)
        self._bootstrap = deepcopy(bootstrap)


def _factory(calibration: DetectorCalibration,
             options: dict[str, Any] | None = None) -> RollingGeometryV1Detector:
    return RollingGeometryV1Detector(calibration, options)
