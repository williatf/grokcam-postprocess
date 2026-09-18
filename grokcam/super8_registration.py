"""Production Super 8 P03/P06 same-frame registration.

This module is deliberately independent of the capture repository and of
neighboring-frame position.  P03 supplies validated edge/component evidence;
P06 is an image-only fallback used only after P03 has failed.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .config import Super8RegistrationCalibration


P03_GATES = {
    "edge_height_min": 180.0,
    "edge_height_max": 320.0,
    "minimum_edge_quality": 4.5,
    "maximum_scanline_center_spread": 8.0,
    "minimum_strip_brightness_contrast": 0.0,
}


@dataclass(frozen=True)
class Super8RegistrationResult:
    registration_y: float | None
    anchor_x: float | None
    provenance: str
    accepted: bool
    raw_candidate_y: float | None
    score: float | None
    fallback_level: str
    rejection_reasons: tuple[str, ...]
    diagnostics: dict


def _gray(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)


def _local_extrema(values: np.ndarray, positive: bool) -> list[int]:
    if positive:
        return [int(i) for i in np.flatnonzero((values[1:-1] >= values[:-2]) &
                                                (values[1:-1] >= values[2:])) + 1]
    return [int(i) for i in np.flatnonzero((values[1:-1] <= values[:-2]) &
                                            (values[1:-1] <= values[2:])) + 1]


def _edge_evidence(profile: np.ndarray, y: int, rising: bool) -> dict:
    radius, plateau = 24, 6
    before = profile[max(0, y - radius):max(0, y - plateau)]
    after = profile[min(len(profile), y + plateau):min(len(profile), y + radius)]
    if before.size < 4 or after.size < 4:
        return {"valid": False, "contrast": 0.0, "strength": 0.0, "quality": 0.0}
    contrast = float(np.median(after) - np.median(before))
    if not rising:
        contrast = -contrast
    joined = np.r_[before, after]
    noise = float(1.4826 * np.median(np.abs(joined - np.median(joined))))
    strength = abs(float(np.gradient(profile)[y]))
    quality = float(max(0.0, contrast) * strength / (noise + 1.0))
    return {"valid": contrast > 2.0 and strength > 0.12,
            "contrast": max(0.0, contrast), "strength": strength, "quality": quality}


def _strip_pairs(gray: np.ndarray, x0: int, x1: int, relaxed: bool) -> list[dict]:
    pairs = []
    for left in np.linspace(x0, x1 - 8, 9, dtype=int):
        right = min(gray.shape[1], int(left + 8))
        profile = np.mean(gray[:, left:right].astype(np.float32), axis=1)
        smooth = cv2.GaussianBlur(profile.reshape(-1, 1), (1, 7), 0).ravel()
        gradient = np.gradient(smooth)
        positive = [i for i in _local_extrema(gradient, True) if 8 < i < len(gradient) - 8]
        negative = [i for i in _local_extrema(gradient, False) if 8 < i < len(gradient) - 8]
        positive.sort(key=lambda i: float(gradient[i]), reverse=True)
        negative.sort(key=lambda i: float(gradient[i]))
        limit = 20 if relaxed else 12
        for top in positive[:limit]:
            top_ev = _edge_evidence(smooth, top, True)
            for bottom in negative[:limit]:
                height = bottom - top
                if not 130.0 <= height <= (480.0 if relaxed else 400.0):
                    continue
                bottom_ev = _edge_evidence(smooth, bottom, False)
                if not top_ev["valid"] or not bottom_ev["valid"]:
                    continue
                center = (top + bottom) / 2.0
                inside = smooth[top + 8:bottom - 8]
                outside = np.r_[smooth[max(0, top - 28):top - 8],
                                smooth[bottom + 8:min(len(smooth), bottom + 28)]]
                contrast = float(np.median(inside) - np.median(outside)) if inside.size and outside.size else 0.0
                score = (math.log1p(top_ev["quality"]) + math.log1p(bottom_ev["quality"])
                         + max(0.0, contrast) / 40.0 - abs(height - 235.0) / 500.0)
                pairs.append({"strip_left": int(left), "strip_right": right,
                              "top_y": float(top), "bottom_y": float(bottom),
                              "center_y": center, "height": float(height),
                              "top": top_ev, "bottom": bottom_ev,
                              "brightness_contrast": contrast, "score": score})
    return pairs


def _cluster_pairs(pairs: list[dict], relaxed: bool) -> list[dict]:
    clusters: list[list[dict]] = []
    for pair in sorted(pairs, key=lambda item: item["center_y"]):
        target = next((cluster for cluster in clusters
                       if abs(pair["center_y"] - statistics.median(item["center_y"] for item in cluster))
                       <= (24.0 if relaxed else 16.0)), None)
        (target if target is not None else clusters.append([]) or clusters[-1]).append(pair)
    results = []
    for cluster in clusters:
        center_guess = statistics.median(item["center_y"] for item in cluster)
        by_strip = {}
        for item in cluster:
            key = (item["strip_left"], item["strip_right"])
            if key not in by_strip or abs(item["center_y"] - center_guess) < abs(by_strip[key]["center_y"] - center_guess):
                by_strip[key] = item
        cluster = list(by_strip.values())
        if len(by_strip) < (2 if relaxed else 3):
            continue
        top = [item["top_y"] for item in cluster]
        bottom = [item["bottom_y"] for item in cluster]
        heights = [item["height"] for item in cluster]
        top_median, bottom_median = statistics.median(top), statistics.median(bottom)
        edge_quality = float(statistics.median(min(item["top"]["quality"], item["bottom"]["quality"]) for item in cluster))
        results.append({"top_y": float(top_median), "bottom_y": float(bottom_median),
                       "center_y": float((top_median + bottom_median) / 2.0),
                       "height": float(statistics.median(heights)), "strip_count": len(by_strip),
                       "pair_count": len(cluster),
                       "top_spread": float(np.median(np.abs(np.asarray(top) - top_median))),
                       "bottom_spread": float(np.median(np.abs(np.asarray(bottom) - bottom_median))),
                       "center_spread": float(np.std([(item["top_y"] + item["bottom_y"]) / 2 for item in cluster])),
                       "edge_quality": edge_quality,
                       "brightness_contrast": float(statistics.median(item["brightness_contrast"] for item in cluster)),
                       "score": float(len(by_strip) / 9.0 * 4.0 + math.log1p(edge_quality)
                                      - float(np.median(np.abs(np.asarray(top) - top_median))) / 8.0
                                      - float(np.median(np.abs(np.asarray(bottom) - bottom_median))) / 8.0
                                      - abs(statistics.median(heights) - 235.0) / 180.0)})
    return sorted(results, key=lambda item: item["score"], reverse=True)


def _strip_detector(gray: np.ndarray, relaxed: bool) -> dict | None:
    x0, x1 = (145, 405) if relaxed else (165, 375)
    clusters = _cluster_pairs(_strip_pairs(gray, x0, x1, relaxed), relaxed)
    if not clusters:
        return None
    best = clusters[0]
    max_spread = 12.0 if relaxed else 7.0
    if best["strip_count"] < (2 if relaxed else 3):
        return None
    if best["top_spread"] > max_spread or best["bottom_spread"] > max_spread:
        return None
    if not 130.0 <= best["height"] <= (480.0 if relaxed else 400.0):
        return None
    return {**best, "center_x": float((x0 + x1) / 2.0), "width": float(x1 - x0),
            "classification": "P03_SECONDARY" if relaxed else "P03_PRIMARY"}


def _edge_peak(profile: np.ndarray, expected: float, half_window: float, rising: bool) -> dict | None:
    smooth = cv2.GaussianBlur(profile.astype(np.float32).reshape(-1, 1), (1, 7), 0).ravel()
    gradient = np.gradient(smooth)
    start = max(1, int(math.floor(expected - half_window)))
    stop = min(len(profile) - 2, int(math.ceil(expected + half_window)))
    if stop <= start:
        return None
    index = start + (int(np.argmax(gradient[start:stop + 1])) if rising else int(np.argmin(gradient[start:stop + 1])))
    y0, y1, y2 = map(float, gradient[index - 1:index + 2])
    denominator = y0 - 2.0 * y1 + y2
    offset = 0.0 if abs(denominator) < 1e-9 else 0.5 * (y0 - y2) / denominator
    position = float(index + max(-0.5, min(0.5, offset)))
    y = int(round(position)); radius, plateau = 18, 5
    before = profile[max(0, y - radius):max(0, y - plateau)]
    after = profile[min(len(profile), y + plateau):min(len(profile), y + radius)]
    if before.size == 0 or after.size == 0:
        return {"subpixel_y": position, "gradient_abs": abs(float(gradient[index])),
                "contrast": 0.0, "fit_rmse": 0.0, "quality": 0.0}
    low, high = float(np.median(before)), float(np.median(after))
    contrast = abs(high - low)
    left_rmse = float(np.sqrt(np.mean((before - low) ** 2)))
    right_rmse = float(np.sqrt(np.mean((after - high) ** 2)))
    fit_rmse = float(math.sqrt((left_rmse * left_rmse + right_rmse * right_rmse) / 2.0))
    return {"subpixel_y": position, "gradient_abs": abs(float(gradient[index])),
            "contrast": contrast, "fit_rmse": fit_rmse,
            "quality": float(contrast / (fit_rmse + 1.0))}


def _localize(gray: np.ndarray, candidate: dict) -> dict:
    cx, cy = float(candidate["center_x"]), float(candidate["center_y"])
    width, height = float(candidate["width"]), float(candidate["height"])
    left = int(round(cx - width / 2.0)); right = int(round(cx + width / 2.0))
    profile = np.mean(gray[:, max(0, left + int(.2 * width)):min(gray.shape[1], left + int(.8 * width))].astype(np.float32), axis=1)
    top = _edge_peak(profile, cy - height / 2.0, max(28.0, height * .30), True)
    bottom = _edge_peak(profile, cy + height / 2.0, max(28.0, height * .30), False)
    top_y = None if top is None else top["subpixel_y"]
    bottom_y = None if bottom is None else bottom["subpixel_y"]
    edge_height = None if top_y is None or bottom_y is None else bottom_y - top_y
    center = None if edge_height is None else (top_y + bottom_y) / 2.0
    qualities = [item["quality"] for item in (top, bottom) if item is not None]
    band_centers = []
    for fraction_left, fraction_right in ((0.15, 0.38), (0.39, 0.61), (0.62, 0.85)):
        band_left = int(round(left + fraction_left * width))
        band_right = int(round(left + fraction_right * width))
        band_profile = np.mean(gray[:, band_left:band_right].astype(np.float32), axis=1)
        band_top = _edge_peak(band_profile, cy - height / 2.0, max(28.0, height * .30), True)
        band_bottom = _edge_peak(band_profile, cy + height / 2.0, max(28.0, height * .30), False)
        if band_top is not None and band_bottom is not None:
            band_centers.append((band_top["subpixel_y"], band_bottom["subpixel_y"]))
    center_spread = (float(np.std([(item[0] + item[1]) / 2.0 for item in band_centers]))
                     if band_centers else None)
    return {"component_centroid_x": cx, "component_centroid_y": cy,
            "component_top_y": cy - height / 2.0, "component_bottom_y": cy + height / 2.0,
            "component_width": width, "component_height": height,
            "edge_top_y": top_y, "edge_bottom_y": bottom_y, "edge_center_y": center,
            "edge_height": edge_height,
            "edge_quality": {"top": None if top is None else {key: top[key] for key in ("gradient_abs", "contrast", "fit_rmse", "quality")},
                             "bottom": None if bottom is None else {key: bottom[key] for key in ("gradient_abs", "contrast", "fit_rmse", "quality")},
                             "minimum_quality": float(min(qualities)) if qualities else 0.0},
            "scanline_band_count": len(band_centers), "scanline_center_spread": center_spread}


def _measurement(candidate: dict, gray: np.ndarray) -> dict:
    value = _localize(gray, candidate)
    value.update({"p03_top_y": candidate["top_y"], "p03_bottom_y": candidate["bottom_y"],
                  "p03_center_y": candidate["center_y"], "p03_strip_count": candidate["strip_count"],
                  "p03_top_spread": candidate["top_spread"], "p03_bottom_spread": candidate["bottom_spread"],
                  "p03_center_spread": candidate["center_spread"],
                  "p03_edge_quality": candidate["edge_quality"],
                  "p03_brightness_contrast": candidate["brightness_contrast"]})
    return value


def _quality_rejections(measurement: dict | None, require_contrast: bool) -> list[str]:
    if measurement is None:
        return ["no_precision_measurement"]
    reasons = []
    if measurement.get("edge_center_y") is None:
        reasons.append("missing_top_or_bottom_precision_edge")
    height = measurement.get("edge_height")
    if height is None or not P03_GATES["edge_height_min"] <= height <= P03_GATES["edge_height_max"]:
        reasons.append("refined_edge_height_out_of_range")
    if measurement.get("edge_quality", {}).get("minimum_quality", 0.0) < P03_GATES["minimum_edge_quality"]:
        reasons.append("minimum_edge_quality_below_gate")
    spread = measurement.get("scanline_center_spread")
    if spread is None or spread > P03_GATES["maximum_scanline_center_spread"]:
        reasons.append("three_band_center_spread_above_gate")
    if require_contrast and measurement.get("p03_brightness_contrast", 0.0) <= P03_GATES["minimum_strip_brightness_contrast"]:
        reasons.append("strip_brightness_contrast_not_positive")
    return reasons


def _component_candidates(gray: np.ndarray) -> list[dict]:
    x0, x1 = 100, min(450, gray.shape[1])
    crop = cv2.GaussianBlur(gray[:, x0:x1], (5, 5), 0)
    otsu, _ = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    threshold = max(float(otsu), float(np.percentile(crop, 88.0)), 150.0)
    mask = np.uint8(crop >= threshold) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    result = []
    for label in range(1, count):
        x, y, width, height, area = map(int, stats[label])
        cx, cy = x0 + float(centroids[label][0]), float(centroids[label][1]) + y
        if area < 100 or not 120 <= height <= 500 or not 150 <= cx <= 400:
            continue
        classification = "COMPLETE" if y > 10 and y + height < gray.shape[0] - 10 else "PARTIAL"
        result.append({"center_x": cx, "center_y": cy, "width": float(width), "height": float(height),
                       "area": float(area), "classification": classification,
                       "score": float(area / max(1.0, width * height))})
    return sorted(result, key=lambda item: item["score"], reverse=True)


def _component_fallback(gray: np.ndarray, candidates: list[dict]) -> tuple[dict | None, list[dict]]:
    attempts = []
    for candidate in candidates:
        if candidate["classification"] not in {"COMPLETE", "PARTIAL"}:
            continue
        measurement = _localize(gray, candidate)
        reasons = _quality_rejections(measurement, False)
        attempts.append({"candidate": candidate, "rejection_reasons": reasons})
        if not reasons:
            measurement = {**measurement, "center_x": candidate["center_x"], "width": candidate["width"],
                           "height": candidate["height"], "classification": "P03_COMPONENT_FALLBACK",
                           "fallback_candidate": candidate}
            return measurement, attempts
    return None, attempts


def _normalize(image: np.ndarray) -> np.ndarray:
    low, high = np.percentile(image.astype(np.float32), (1.0, 99.0))
    return np.clip((image.astype(np.float32) - low) * 255.0 / max(high - low, 1e-6), 0, 255).astype(np.uint8)


def _representation(gray: np.ndarray, variant: str) -> np.ndarray:
    if variant == "gray":
        return _normalize(gray)
    gx = cv2.Sobel(gray.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)
    magnitude = cv2.magnitude(gx, gy)
    return np.clip(magnitude * 255.0 / max(float(np.percentile(magnitude, 99.0)), 1e-6), 0, 255).astype(np.uint8)


def _geometry(image: np.ndarray, x: float, y: float, scale: float) -> dict:
    cx, cy = int(round(x)), int(round(y)); half_w, half_h = int(round(96 * scale)), int(round(117 * scale))
    outer_w, outer_h = int(round(125 * scale)), int(round(146 * scale))
    if cx - outer_w < 1 or cx + outer_w >= image.shape[1] or cy - outer_h < 1 or cy + outer_h >= image.shape[0]:
        return {"score": 0.0, "valid": False}
    interior = image[cy - half_h:cy + half_h, cx - half_w:cx + half_w].astype(np.float32)
    ring = np.concatenate((image[cy - outer_h:cy - half_h, cx - outer_w:cx + outer_w].ravel(),
                           image[cy + half_h:cy + outer_h, cx - outer_w:cx + outer_w].ravel(),
                           image[cy - half_h:cy + half_h, cx - outer_w:cx - half_w].ravel(),
                           image[cy - half_h:cy + half_h, cx + half_w:cx + outer_w].ravel())).astype(np.float32)
    contrast = abs(float(np.median(interior) - np.median(ring))) / 255.0
    gx = cv2.Sobel(image.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(image.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)
    magnitude = cv2.magnitude(gx, gy)
    bands = [magnitude[cy - half_h - 5:cy - half_h + 6, cx - half_w:cx + half_w],
             magnitude[cy + half_h - 5:cy + half_h + 6, cx - half_w:cx + half_w],
             magnitude[cy - half_h:cy + half_h, cx - half_w - 5:cx - half_w + 6],
             magnitude[cy - half_h:cy + half_h, cx + half_w - 5:cx + half_w + 6]]
    support = min(float(np.percentile(b, 75)) / 255.0 for b in bands if b.size)
    return {"score": float(min(1.0, .55 * min(1.0, contrast * 3.0) + .45 * min(1.0, support))),
            "valid": True, "interior_contrast": contrast, "edge_support": support}


def _quadratic(values: np.ndarray, index: int) -> float:
    if index <= 0 or index >= len(values) - 1:
        return float(index)
    left, center, right = map(float, values[index - 1:index + 2])
    denominator = left - 2 * center + right
    offset = 0.0 if abs(denominator) < 1e-9 else .5 * (left - right) / denominator
    return float(index + max(-.5, min(.5, offset)))


class Super8TemplateMatcher:
    def __init__(self, calibration: Super8RegistrationCalibration):
        self.calibration = calibration
        metadata = json.loads(calibration.template_metadata.read_text(encoding="utf-8"))
        actual_hash = hashlib.sha256(calibration.template_bank.read_bytes()).hexdigest()
        if actual_hash != metadata["resource_sha256"]:
            raise ValueError("Super 8 template bank checksum does not match its metadata")
        bank = np.load(calibration.template_bank)
        self.templates = {"gray": bank["gray"], "edge": bank["edge"]}

    def match(self, gray: np.ndarray) -> dict:
        candidates = []
        x0, x1 = self.calibration.x_search
        for variant, template in self.templates.items():
            source = _representation(gray, variant)
            for scale in self.calibration.scales:
                width = int(round(self.calibration.template_patch_width * scale))
                height = int(round(self.calibration.template_patch_height * scale))
                resized = cv2.resize(template, (width, height), interpolation=cv2.INTER_LINEAR)
                score_map = cv2.matchTemplate(source[:, x0:x1], resized, cv2.TM_CCOEFF_NORMED)
                for _ in range(8):
                    iy, ix = np.unravel_index(int(np.argmax(score_map)), score_map.shape)
                    score = float(score_map[iy, ix])
                    if not math.isfinite(score):
                        break
                    candidates.append({"score": score, "x": x0 + ix + width / 2.0,
                                       "y": _quadratic(score_map[:, ix], iy) + height / 2.0,
                                       "scale": scale, "variant": variant})
                    cv2.rectangle(score_map, (max(0, ix - 30), max(0, iy - 40)),
                                  (min(score_map.shape[1] - 1, ix + 30), min(score_map.shape[0] - 1, iy + 40)), -1.0, -1)
        candidates.sort(key=lambda item: item["score"], reverse=True)
        if not candidates:
            return {"accepted": False, "rejection_reasons": ["no_candidate"]}
        best = candidates[0]
        physical = []
        for candidate in candidates:
            if candidate["score"] < self.calibration.p06_score_min:
                continue
            geometry = _geometry(gray, candidate["x"], candidate["y"], candidate["scale"])
            if geometry["score"] < self.calibration.p06_geometry_min:
                continue
            if any(abs(candidate["x"] - old["x"]) < self.calibration.p06_physical_cluster_x_px
                   and abs(candidate["y"] - old["y"]) < self.calibration.p06_physical_cluster_y_px for old in physical):
                continue
            physical.append({**candidate, "geometry": geometry})
            if len(physical) >= 8:
                break
        competitor = next((item for item in candidates[1:]
                           if abs(item["x"] - best["x"]) >= self.calibration.p06_competitor_x_separation_px
                           or abs(item["y"] - best["y"]) >= self.calibration.p06_competitor_y_separation_px), None)
        margin = None if competitor is None else best["score"] - competitor["score"]
        agreement = next((item for item in candidates[1:]
                          if item["variant"] != best["variant"]
                          and abs(item["x"] - best["x"]) <= self.calibration.p06_representation_agreement_px
                          and abs(item["y"] - best["y"]) <= self.calibration.p06_representation_agreement_px), None)
        reasons = []
        if best["score"] < self.calibration.p06_score_min:
            reasons.append("score_below_gate")
        if agreement is None:
            reasons.append("gray_gradient_disagreement")
        geometry = _geometry(gray, best["x"], best["y"], best["scale"])
        if geometry["score"] < self.calibration.p06_geometry_min:
            reasons.append("physical_geometry_below_gate")
        if margin is None or margin < self.calibration.p06_competitor_margin_min:
            reasons.append("competitor_margin_below_gate")
        if len(physical) > 1:
            reasons.append("multiple_distinct_physical_candidates")
        return {"accepted": not reasons, "rejection_reasons": reasons,
                "best": best, "subpixel_y": best["y"], "competitor": competitor,
                "margin": margin, "representation_agreement": agreement,
                "geometry": geometry, "physical_candidates": physical,
                "candidate_count": len(candidates)}


class Super8Registration:
    def __init__(self, calibration: Super8RegistrationCalibration):
        self.matcher = Super8TemplateMatcher(calibration)

    def register(self, image: Image.Image) -> Super8RegistrationResult:
        gray = _gray(image)
        attempts = []
        primary = _strip_detector(gray, False)
        measurement = None if primary is None else _measurement(primary, gray)
        reasons = _quality_rejections(measurement, True)
        attempts.append({"stage": "P03_PRIMARY", "candidate": primary, "measurement": measurement,
                         "rejection_reasons": reasons})
        if primary is not None and not reasons:
            return Super8RegistrationResult(measurement["edge_center_y"], measurement["component_centroid_x"],
                                            "PRIMARY", True, primary["center_y"], primary["score"],
                                            "P03_PRIMARY", (), {"p03_attempts": attempts})

        secondary = _strip_detector(gray, True)
        measurement = None if secondary is None else _measurement(secondary, gray)
        reasons = _quality_rejections(measurement, True)
        attempts.append({"stage": "P03_SECONDARY", "candidate": secondary, "measurement": measurement,
                         "rejection_reasons": reasons})
        if secondary is not None and not reasons:
            return Super8RegistrationResult(measurement["edge_center_y"], measurement["component_centroid_x"],
                                            "SECONDARY", True, secondary["center_y"], secondary["score"],
                                            "P03_SECONDARY", (), {"p03_attempts": attempts})

        components = _component_candidates(gray)
        fallback, fallback_attempts = _component_fallback(gray, components)
        if fallback is not None:
            return Super8RegistrationResult(fallback["edge_center_y"], fallback["component_centroid_x"],
                                            "FALLBACK", True, fallback["component_centroid_y"],
                                            fallback["fallback_candidate"].get("score"), "P03_COMPONENT_FALLBACK", (),
                                            {"p03_attempts": attempts, "component_candidates": components,
                                             "component_attempts": fallback_attempts})

        p06 = self.matcher.match(gray)
        if p06["accepted"]:
            return Super8RegistrationResult(p06["subpixel_y"], p06["best"]["x"], "TEMPLATE_FALLBACK", True,
                                            p06["subpixel_y"], p06["best"]["score"], "P06_TEMPLATE_FALLBACK", (),
                                            {"p03_attempts": attempts, "component_candidates": components,
                                             "component_attempts": fallback_attempts, "p06": p06})
        return Super8RegistrationResult(None, None, "UNTRUSTED", False, None,
                                        p06.get("best", {}).get("score"), "UNTRUSTED",
                                        tuple(p06.get("rejection_reasons", [])),
                                        {"p03_attempts": attempts, "component_candidates": components,
                                         "component_attempts": fallback_attempts, "p06": p06})
