"""Frozen P15-first / forced-P07 + P22 production crop registration."""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from .models import CropGeometry, SprocketDetection
from .physical_sprocket import (FROZEN_CONFIG, PhysicalPairResult, _p06_fit,
                                _pair_candidate, _physical_hole, capture_boxes,
                                detect_pair)

P15_IMPLEMENTATION_SHA256 = "2584c0cc8cf742b598bd4893be8a8442c78fc39dbeff6dbfb769db2b2c89d839"
P15_CONFIGURATION_SHA256 = "80ff1afc96a5d7ce904dc0d1f0b0baf3bd88176fe8e79aa546f10c2f399642ba"
P22_IMPLEMENTATION_SHA256 = "b828812ebdd52059d71a0ce9210bbc7d71eac01bb9b550b6eb8dd041cee45529"
P22_CONFIGURATION_SHA256 = "753a2cbb85b4a67d4cbe9c5475c8cb9d156b0076dfaf38baa5b2a45ee1f0caac"
MODEL_TO_OPTICAL_OFFSET_Y = 4.178787846871160
OPTICAL_LOWER_TOP_TO_CROP_TOP = -673.5297914597816
P22_RADIUS = 3.0
P22_STEP = 0.25
P22_SHALLOW_MARGIN = 0.01
P24_CAPTURE_Y_BIAS = 14.5
P24_PHYSICAL_Y_BIAS = 23.0
P24_PITCH_RANGE = (740.0, 835.0)
P24_WIDTH_MIN = 350.0
P24_HEIGHT_RANGE = (250.0, 340.0)
P24_HEIGHT_DIFFERENCE_MIN = 20.0
P24_X_DISPLACEMENT_MAX = 30.0
P24_Y_AGREEMENT_MAX = 8.0
P24_PHYSICAL_SCORE_MAX = 0.30
P25_CAPTURE_X_BIAS = 1.3344210526315692
P24_FREEZE_SHA256 = "11634baefcb94c4cbb76d586eb19fa338fe857e7d3dd35ecdc95433ce7c507af"
P24_GATE_SHA256 = "8e1abe38860f230db39683c9c341798758813d7d21609ecf5208db00c1d34a92"
P25_FREEZE_SHA256 = "be28b659636b8ea9a49cc35535b411464b5fe77894907628617262e837767587"
P25_CALIBRATION_SHA256 = "bcdbd2838e950b8fb55eb8e8525da3d6b540c2123c31c5814cc198fadfe951d3"
WIDTH = 381.5842105263158
HEIGHT = 272.0
PITCH = 785.0
LOWER_X = 18.678947368421063
P15_CONFIG = {
    "search_radius_px": 8, "horizontal_half_fraction": .30, "column_step": 2,
    "minimum_peak": 20, "minimum_prominence": 8, "minimum_noise": 2,
    "minimum_snr": 2.5, "subpixel_min_curvature": 1.0,
    "subpixel_max_fraction": .75, "minimum_inlier_columns": 24,
    "minimum_inlier_fraction": .20, "minimum_outlier_limit_px": 1.0,
    "outlier_mad_multiplier": 3.0,
}


@dataclass(frozen=True)
class RegistrationResult:
    crop: CropGeometry | None
    source: str | None
    anchor_x: float | None
    optical_lower_top_y: float | None
    diagnostics: dict


def _subpixel(values, index):
    if not 0 < index < len(values) - 1:
        return float(index), False
    left, center, right = map(float, values[index - 1:index + 2])
    denominator = left - 2 * center + right
    if denominator >= -P15_CONFIG["subpixel_min_curvature"]:
        return float(index), False
    fraction = .5 * (left - right) / denominator
    if abs(fraction) <= P15_CONFIG["subpixel_max_fraction"]:
        return float(index + fraction), True
    return float(index), False


def _measure_edge(gray, expected_y):
    cfg = P15_CONFIG
    ys = np.arange(math.floor(expected_y - cfg["search_radius_px"]),
                   math.ceil(expected_y + cfg["search_radius_px"]) + 1, dtype=float)
    sy = cv2.Sobel(cv2.GaussianBlur(gray, (1, 5), 0), cv2.CV_32F, 0, 1, ksize=3)
    columns = []
    for x in range(0, gray.shape[1], cfg["column_step"]):
        yi = np.clip(np.rint(ys).astype(int), 0, gray.shape[0] - 1)
        profile = sy[yi, x]
        index = int(np.argmax(profile))
        outside = np.delete(profile, np.arange(max(0, index - 1), min(len(profile), index + 2)))
        base = float(np.median(outside))
        noise = max(float(1.4826 * np.median(np.abs(outside - base))), cfg["minimum_noise"])
        peak = float(profile[index]); prominence = peak - base
        position, stable = _subpixel(profile, index)
        if (index in (0, len(profile) - 1) or peak < cfg["minimum_peak"] or
                prominence < cfg["minimum_prominence"] or prominence / noise < cfg["minimum_snr"]):
            continue
        columns.append({"y": float(np.interp(position, np.arange(len(ys)), ys)),
                        "peak": peak, "prominence": prominence,
                        "snr": prominence / noise, "subpixel": stable})
    total = math.ceil(gray.shape[1] / cfg["column_step"])
    if not columns:
        return {"valid": False, "y": None, "reason": "no_valid_columns",
                "valid_columns": 0, "total_columns": total}
    positions = np.array([column["y"] for column in columns])
    median = float(np.median(positions)); mad = float(np.median(np.abs(positions - median)))
    limit = max(cfg["minimum_outlier_limit_px"], cfg["outlier_mad_multiplier"] * mad)
    inliers = [column for column in columns if abs(column["y"] - median) <= limit]
    positions = np.array([column["y"] for column in inliers]); fraction = len(inliers) / total
    valid = len(inliers) >= cfg["minimum_inlier_columns"] and fraction >= cfg["minimum_inlier_fraction"]
    return {"valid": valid, "y": float(np.median(positions)),
            "reason": None if valid else "insufficient_column_consensus",
            "valid_columns": len(inliers), "total_columns": total,
            "valid_fraction": fraction,
            "column_mad": float(np.median(np.abs(positions - np.median(positions)))),
            "median_snr": float(np.median([column["snr"] for column in inliers])),
            "subpixel_fraction": sum(column["subpixel"] for column in inliers) / len(inliers)}


def measure_p15_lower_top(image: Image.Image, anchor_x: float, anchor_y: float) -> dict:
    """Exact frozen P15 lower-top measurement; the primary anchor only places its ROI."""
    upper_x = anchor_x + 17.125 - LOWER_X / 2
    lower_x = upper_x + LOWER_X
    lower_y = anchor_y - PITCH / 2 + PITCH
    expected = lower_y - HEIGHT / 2
    x0 = max(0, int(lower_x - WIDTH * P15_CONFIG["horizontal_half_fraction"]))
    x1 = min(image.width, int(lower_x + WIDTH * P15_CONFIG["horizontal_half_fraction"]))
    y0 = max(0, int(expected - P15_CONFIG["search_radius_px"] - 5))
    y1 = min(image.height, int(expected + P15_CONFIG["search_radius_px"] + 6))
    gray = cv2.cvtColor(np.asarray(image.crop((x0, y0, x1, y1)).convert("RGB")),
                        cv2.COLOR_RGB2GRAY).astype(np.float32)
    result = _measure_edge(gray, expected - y0)
    if result["y"] is not None:
        result["y"] += y0
    result["expected_y"] = expected
    result["offset"] = None if result["y"] is None else result["y"] - expected
    return result


def evaluate_p24_guide(image: Image.Image, capture_item, timings: dict,
                       counters: dict) -> tuple[tuple[float, float] | None, dict]:
    """Apply the exact frozen P24 gate and P25 X calibration; never register directly."""
    counters["p24_attempts"] += 1
    started = time.perf_counter()
    boxes = capture_boxes(capture_item)
    pair_present = len(boxes) == 2
    detail = {"attempted": True, "capture_pair_available": pair_present,
              "capture_y_bias": P24_CAPTURE_Y_BIAS,
              "physical_y_bias": P24_PHYSICAL_Y_BIAS,
              "capture_x_bias": P25_CAPTURE_X_BIAS}
    if pair_present:
        counters["p24_capture_pairs_available"] += 1
        upper, lower = sorted(boxes, key=lambda box: box[1])
        pitch = lower[1] - upper[1]; x_displacement = lower[0] - upper[0]
        height_difference = abs(lower[3] - upper[3])
        raw_y = (upper[1] + lower[1]) / 2 + PITCH / 2 - HEIGHT / 2
        raw_x = (upper[0] + lower[0]) / 2 - 17.125
        predicates = {
            "pair_present": True,
            "pitch": P24_PITCH_RANGE[0] <= pitch <= P24_PITCH_RANGE[1],
            "widths": upper[2] >= P24_WIDTH_MIN and lower[2] >= P24_WIDTH_MIN,
            "heights": all(P24_HEIGHT_RANGE[0] <= box[3] <= P24_HEIGHT_RANGE[1]
                           for box in (upper, lower)),
            "height_difference": height_difference >= P24_HEIGHT_DIFFERENCE_MIN,
            "x_displacement": abs(x_displacement) <= P24_X_DISPLACEMENT_MAX,
        }
        detail.update({"capture_upper": list(upper), "capture_lower": list(lower),
                       "capture_pitch": pitch, "capture_x_displacement": x_displacement,
                       "capture_height_difference": height_difference,
                       "raw_capture_anchor_x": raw_x,
                       "calibrated_capture_anchor_x": raw_x - P25_CAPTURE_X_BIAS,
                       "raw_capture_lower_top_y": raw_y,
                       "calibrated_capture_lower_top_y": raw_y - P24_CAPTURE_Y_BIAS,
                       "capture_predicates": predicates})
    else:
        predicates = {"pair_present": False, "pitch": False, "widths": False,
                      "heights": False, "height_difference": False,
                      "x_displacement": False}
        detail["capture_predicates"] = predicates
    capture_pass = all(predicates.values())
    detail["capture_geometry_pass"] = capture_pass
    if capture_pass: counters["p24_capture_geometry_passes"] += 1
    timings["p24_capture_transform_gate"] += time.perf_counter() - started
    if not capture_pass:
        detail["disposition"] = ("no_capture_pair" if not pair_present else
                                 "capture_geometry_gate_rejected")
        return None, detail

    started = time.perf_counter(); rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    holes=[]; reasons=[]
    for box in boxes:
        hole, reason = _physical_hole(rgb, box); holes.append(hole); reasons.append(reason)
    pair_available = len(holes) == 2 and all(hole is not None for hole in holes)
    detail.update({"physical_pair_available": pair_available,
                   "physical_holes": [vars(hole) if hole else None for hole in holes],
                   "physical_hole_reasons": reasons})
    if pair_available:
        counters["p24_physical_corroborator_available"] += 1
        upper_hole, lower_hole = sorted(holes, key=lambda hole: hole.cy)
        raw_physical_y = (upper_hole.cy + lower_hole.cy) / 2 + PITCH / 2 - HEIGHT / 2
        physical_y = raw_physical_y - P24_PHYSICAL_Y_BIAS
        disagreement = abs(detail["calibrated_capture_lower_top_y"] - physical_y)
        corroboration = {
            "upper_fit_score": upper_hole.score <= P24_PHYSICAL_SCORE_MAX,
            "lower_fit_score": lower_hole.score <= P24_PHYSICAL_SCORE_MAX,
            "y_agreement": disagreement <= P24_Y_AGREEMENT_MAX,
        }
        detail.update({"raw_physical_lower_top_y": raw_physical_y,
                       "calibrated_physical_lower_top_y": physical_y,
                       "capture_physical_y_disagreement": disagreement,
                       "corroboration_predicates": corroboration})
    else:
        corroboration = {"upper_fit_score": False, "lower_fit_score": False,
                         "y_agreement": False}
        detail["corroboration_predicates"] = corroboration
    corroborated = pair_available and all(corroboration.values())
    detail["corroboration_pass"] = corroborated
    if corroborated: counters["p24_corroborated_gate_passes"] += 1
    timings["p24_physical_hole_corroboration"] += time.perf_counter() - started
    if not corroborated:
        if not pair_available: detail["disposition"] = "no_physical_pair"
        elif not corroboration["upper_fit_score"] or not corroboration["lower_fit_score"]:
            detail["disposition"] = "physical_fit_rejected"
        else: detail["disposition"] = "capture_physical_disagreement"
        return None, detail
    detail["disposition"] = "p24_admitted"
    anchor_x = detail["calibrated_capture_anchor_x"]
    anchor_y = detail["calibrated_capture_lower_top_y"] - (PITCH / 2 - HEIGHT / 2)
    return (anchor_x, anchor_y), detail


def _p07_priors(image: Image.Image, capture_item) -> tuple[list[tuple[float, float]], dict]:
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    boxes = capture_boxes(capture_item); holes = []; reasons = []
    for box in boxes:
        hole, reason = _physical_hole(rgb, box); holes.append(hole); reasons.append(reason)
    good = [hole for hole in holes if hole is not None]; p06_model = None; p06_detail = None
    if len(good) == 1:
        seed = good[0]; upper = seed.cy < rgb.shape[0] / 2
        prediction = (seed.cx + (LOWER_X if upper else -LOWER_X),
                      seed.cy + (PITCH if upper else -PITCH))
        p06_model, p06_detail = _p06_fit(rgb, prediction)
    priors = [(box[0], box[1]) for box in boxes] + [(hole.cx, hole.cy) for hole in good]
    if p06_model is not None:
        priors.append(p06_model)
    return priors, {"capture_roi_boxes": boxes,
                    "independent_holes": [vars(hole) if hole else None for hole in holes],
                    "physical_hole_reasons": reasons, "p06_prior": p06_detail,
                    "prior_count": len(priors), "physical_hole_count": len(good)}


def run_forced_p07(image: Image.Image, capture_item=None) -> tuple[PhysicalPairResult, list, dict]:
    """Run P07 itself; physical-pair/P06 evidence supplies priors but cannot accept or veto."""
    priors, evidence = _p07_priors(image, capture_item)
    result = detect_pair(image, priors)
    diagnostics = dict(result.diagnostics); diagnostics.update(evidence); diagnostics["stage"] = "p07"
    return PhysicalPairResult(result.accepted, result.classification, result.anchor_x,
                              result.anchor_y, diagnostics), priors, diagnostics


def refine_p22_common_y(image: Image.Image, upper_x: float, upper_y: float,
                        priors, radius=P22_RADIUS, step=P22_STEP) -> tuple[float, dict]:
    """Exact frozen P22 search; returns only a common-Y shift and diagnostics."""
    rgb = np.asarray(image.convert("RGB")); cfg = FROZEN_CONFIG; height, width = rgb.shape[:2]
    hole_w, hole_h = cfg["hole_width"], cfg["hole_height"]
    xmin, xmax = cfg["sprocket_x_domain"]; ymin, ymax = cfg["upper_y_domain"]
    x0 = max(0, int(xmin - hole_w / 2 - 40)); x1 = min(width, int(xmax + hole_w / 2 + 40))
    y0 = max(0, int(ymin - hole_h / 2 - 40)); y1 = min(height, int(ymax + cfg["pitch"] + hole_h / 2 + 40))
    gray = cv2.cvtColor(rgb[y0:y1, x0:x1], cv2.COLOR_RGB2GRAY).astype(np.float32)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    sx0 = cv2.Sobel(blur, cv2.CV_32F, 1, 0, ksize=3); sy0 = cv2.Sobel(blur, cv2.CV_32F, 0, 1, ksize=3)
    norm = max(float(np.percentile(cv2.magnitude(sx0, sy0), 92)), 12)
    sx = np.clip(sx0 / norm, -1, 1); sy = np.clip(sy0 / norm, -1, 1)
    normalized = [(px, py) if py < height / 2 else
                  (px - cfg["lower_minus_upper_x"], py - cfg["pitch"]) for px, py in priors]
    candidates = []
    for shift in np.arange(-radius, radius + step / 2, step):
        uy = upper_y + float(shift)
        candidate = _pair_candidate(gray, sx, sy, upper_x - x0, uy - y0, cfg, False)
        distance = min((math.hypot(upper_x - px, uy - py) for px, py in normalized), default=0.)
        score = candidate["raw_score"] - cfg["weak_prior_weight"] * min(distance, 200) / 200
        candidates.append({"shift": float(shift), "score": score,
                           "raw_score": candidate["raw_score"], "prior_distance": distance})
    maximum = max(candidate["score"] for candidate in candidates)
    winners = [candidate for candidate in candidates if abs(candidate["score"] - maximum) <= 1e-12]
    best = min(winners, key=lambda candidate: (abs(candidate["shift"]), candidate["shift"]))
    separated = [candidate for candidate in candidates if abs(candidate["shift"] - best["shift"]) >= 1.0]
    runner = max((candidate["score"] for candidate in separated), default=maximum)
    diagnostics = {"local_score": best["score"], "local_raw_score": best["raw_score"],
                   "local_prior_distance": best["prior_distance"],
                   "local_score_margin_1px": best["score"] - runner,
                   "maximum_tie_count": len(winners),
                   "search_boundary_hit": abs(best["shift"]) == radius,
                   "score_range": maximum - min(candidate["score"] for candidate in candidates),
                   "candidates_json": json.dumps(candidates, separators=(",", ":")),
                   "shallow_score": best["score"] - runner <= P22_SHALLOW_MARGIN}
    return best["shift"], diagnostics


def register_precisely(image: Image.Image, primary: SprocketDetection | None,
                       capture_item, timings: dict, counters: dict) -> RegistrationResult:
    """Apply primary/P15 -> frozen P24/P25/P15 -> frozen P07/P22."""
    counters["frames"] += 1; counters["p15_attempts"] += 1
    started = time.perf_counter()
    if primary is None:
        p15 = {"valid": False, "y": None, "reason": "no_primary_roi_anchor"}
    else:
        counters["primary_p15_attempts"] += 1
        p15 = measure_p15_lower_top(image, primary.cx, primary.cy)
    elapsed=time.perf_counter()-started;timings["primary_p15_measurement"]+=elapsed;timings["p15_measurement"]+=elapsed
    if p15["valid"]:
        counters["p15_successes"] += 1; counters["primary_p15_successes"] += 1
        optical_y = float(p15["y"])
        crop = CropGeometry(primary.cx + 159.0, optical_y + OPTICAL_LOWER_TOP_TO_CROP_TOP,
                            1133, 900)
        return RegistrationResult(crop, "primary_p15", primary.cx, optical_y,
                                  {"primary_detected": True,
                                   "primary_roi_anchor": primary.to_dict(),
                                   "p15": p15, "primary_p15": p15,
                                   "p24": {"attempted": False},
                                   "registration_x_source": "primary",
                                   "registration_y_source": "p15",
                                   "p07_attempted": False,
                                   "p22_attempted": False})

    guide, p24 = evaluate_p24_guide(image, capture_item, timings, counters)
    if guide is not None:
        counters["p24_guided_p15_attempts"] += 1; started=time.perf_counter()
        p24_p15=measure_p15_lower_top(image, *guide)
        elapsed=time.perf_counter()-started;timings["p24_guided_p15_measurement"]+=elapsed;timings["p15_measurement"]+=elapsed
        p24["p15"] = p24_p15; p24["guide_anchor_x"],p24["guide_anchor_y"]=guide
        p24["guide_expected_lower_top_y"]=p24_p15.get("expected_y")
        if p24_p15["valid"]:
            counters["p15_successes"]+=1;counters["p24_guided_p15_successes"]+=1
            optical_y=float(p24_p15["y"]);anchor_x=float(guide[0])
            crop=CropGeometry(anchor_x+159.0,optical_y+OPTICAL_LOWER_TOP_TO_CROP_TOP,1133,900)
            p24["disposition"]="p24_admitted_p15_accepted"
            return RegistrationResult(crop,"p24_capture_p15",anchor_x,optical_y,
                {"primary_detected":primary is not None,
                 "primary_roi_anchor":None if primary is None else primary.to_dict(),
                 "p15":p15,"primary_p15":p15,"p24":p24,
                 "registration_x_source":"capture_p25","registration_y_source":"p15",
                 "p07_attempted":False,"p22_attempted":False})
        counters["p24_guided_p15_failures"]+=1;p24["disposition"]="p24_admitted_p15_rejected"

    counters["p07_attempts"] += 1; started = time.perf_counter()
    p07, priors, p07_diagnostics = run_forced_p07(image, capture_item)
    timings["p07_fallback_detection"] += time.perf_counter() - started
    diagnostics = {"primary_detected": primary is not None,
                   "primary_roi_anchor": None if primary is None else primary.to_dict(),
                   "p15": p15, "primary_p15":p15,"p24":p24,"p07_attempted": True,
                   "p07_accepted": p07.accepted, "p07": p07_diagnostics,
                   "registration_x_source":None,"registration_y_source":None,
                   "p22_attempted": False}
    if not p07.accepted:
        counters["p07_failures"] += 1;counters["excluded_frames"]+=1
        p24["final_disposition"]="fell_through_p07_rejected"
        return RegistrationResult(None, None, None, None, diagnostics)

    counters["p07_successes"] += 1; counters["p22_invocations"] += 1
    started = time.perf_counter()
    upper_x, upper_y = p07_diagnostics["upper_center"]
    shift, p22 = refine_p22_common_y(image, upper_x, upper_y, priors)
    timings["p22_refinement"] += time.perf_counter() - started
    refined_lower_y = float(p07_diagnostics["lower_center"][1]) + shift
    model_lower_top_y = refined_lower_y - 136.0
    optical_y = model_lower_top_y + MODEL_TO_OPTICAL_OFFSET_Y
    diagnostics.update({"p22_attempted": True, "p22": p22,
                        "p22_shift_y": shift, "refined_lower_center_y": refined_lower_y,
                        "refined_model_lower_top_y": model_lower_top_y,
                        "optical_lower_top_y": optical_y,
                        "registration_x_source":"p07",
                        "registration_y_source":"p22_refined_p07"})
    p24["final_disposition"]="fell_through_p07_accepted"
    if p24.get("calibrated_capture_anchor_x") is not None:
        p24["retrospective_p07_reference_anchor_x"]=float(p07.anchor_x)
        p24["retrospective_capture_x_error"]=p24["calibrated_capture_anchor_x"]-float(p07.anchor_x)
        p24["retrospective_p07_model_lower_top_y"]=float(p07_diagnostics["lower_center"][1])-136.0
        p24["retrospective_capture_y_error"]=p24["calibrated_capture_lower_top_y"]-p24["retrospective_p07_model_lower_top_y"]
    crop = CropGeometry(float(p07.anchor_x) + 159.0,
                        optical_y + OPTICAL_LOWER_TOP_TO_CROP_TOP, 1133, 900)
    return RegistrationResult(crop, "p07_p22", p07.anchor_x, optical_y, diagnostics)
