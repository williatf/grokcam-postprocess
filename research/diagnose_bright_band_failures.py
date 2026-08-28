#!/usr/bin/env python3
"""Classify the previous hybrid bright-band failures without changing it."""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grokcam.config import load_calibration
from grokcam.raw_development import DarktableMatchedDeveloper
from research.p01_hybrid_capture_prior_poc import contiguous_runs, load_capture, transform_boxes


def diagnose_hole(bright: np.ndarray, luminance: np.ndarray, prediction: tuple[float, float, float, float], calibration):
    px, py, pw, ph = prediction
    height, width = bright.shape
    x0 = max(calibration.search_x0, int(math.floor(px - 0.85 * pw)))
    x1 = min(calibration.search_x1, int(math.ceil(px + 0.85 * pw)))
    y0 = max(0, int(math.floor(py - 0.85 * ph)))
    y1 = min(height, int(math.ceil(py + 0.85 * ph)))
    roi = bright[y0:y1, x0:x1]
    lum = luminance[y0:y1, x0:x1]
    if roi.size == 0:
        return "other", {"reason": "empty_roi"}
    p40, p995 = float(np.percentile(lum, 40)), float(np.percentile(lum, 99.5))
    if p995 - p40 < 0.04 * 255 or roi.mean() < 0.02:
        return "threshold/brightness", {"p40": p40, "p995": p995, "bright_fraction": float(roi.mean())}
    row_minimum = min(calibration.minimum_bright_row_pixels, max(40, int(round(pw * 0.32))))
    raw_runs = contiguous_runs(roi.sum(axis=1) > row_minimum)
    bands = [(a, b) for a, b in raw_runs if calibration.band_height_min <= b - a <= calibration.band_height_max]
    if not bands:
        longest = max((b - a for a, b in raw_runs), default=0)
        if len(raw_runs) >= 2 and longest < calibration.band_height_min:
            return "fragmented region", {"row_runs": len(raw_runs), "longest_row_run": longest}
        return "size/shape", {"row_runs": len(raw_runs), "longest_row_run": longest}
    had_columns = False
    had_width = False
    had_fill = False
    candidates = []
    for top, bottom in bands:
        column_mask = roi[top:bottom].sum(axis=0) > (bottom - top) * calibration.column_fill
        column_runs = contiguous_runs(column_mask)
        if column_runs:
            had_columns = True
        for left, right in column_runs:
            if right - left < calibration.minimum_bright_columns:
                continue
            had_width = True
            measured_width = right - left
            if not 0.40 * calibration.expected_width <= measured_width <= 1.60 * calibration.expected_width:
                continue
            region = roi[top:bottom, left:right]
            fill = float(np.mean(region))
            if fill < 0.45:
                continue
            had_fill = True
            cx, cy = x0 + (left + right) / 2, y0 + (top + bottom) / 2
            distance = math.hypot((cx - px) / max(pw, 1), (cy - py) / max(ph, 1))
            if distance <= 0.75:
                candidates.append((cx, cy, measured_width, bottom - top, fill, distance))
    if len(candidates) > 1:
        return "ambiguous structure", {"candidates": len(candidates)}
    if candidates:
        return "success", {"candidate": candidates[0]}
    if not had_columns or not had_width:
        return "fill", {"had_columns": had_columns, "had_width": had_width}
    if not had_fill:
        return "fill", {"had_fill": False}
    return "size/shape", {"reason": "candidate_too_far_or_width"}


def diagnose_pair(image: Image.Image, capture: dict, calibration):
    boxes = transform_boxes(capture)
    if boxes is None:
        return "other", {"reason": "ineligible"}
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    full_lum = rgb.mean(axis=2)
    strip = full_lum[:, calibration.search_x0:calibration.search_x1]
    threshold = float(np.percentile(strip, calibration.bright_percentile) * calibration.threshold_scale)
    bright = full_lum > threshold
    results = [diagnose_hole(bright, full_lum, box, calibration) for box in boxes]
    if any(category != "success" for category, _ in results):
        # Report the first failed physical hole; both details remain in JSON.
        category = next(category for category, _ in results if category != "success")
        return category, {"holes": [{"category": c, **d} for c, d in results], "threshold": threshold}
    upper, lower = [detail["candidate"] for _, detail in results]
    pitch = lower[1] - upper[1]
    x_agreement = abs(lower[0] - upper[0])
    if abs(pitch - calibration.expected_pitch) > calibration.pitch_tolerance:
        return "pitch", {"pitch": pitch, "x_agreement": x_agreement}
    if x_agreement > 100:
        return "X agreement", {"pitch": pitch, "x_agreement": x_agreement}
    return "success", {"pitch": pitch, "x_agreement": x_agreement}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "research/output/sprocket_xy/physical_hole_capture_prior_poc/phase1")
    parser.add_argument("--jobs", type=int, default=3)
    args = parser.parse_args()
    previous = ROOT / "research/output/sprocket_xy/hybrid_capture_prior_poc/Reel_46335/diagnostics.csv"
    rows = list(csv.DictReader(previous.open()))
    targets = [int(r["frame"]) for r in rows
               if r["production_accepted"] == "False"
               and r["capture_pair_seed_eligible"] == "True"
               and r["hybrid_seed_evidence"] == "False"]
    if len(targets) != 1153:
        raise RuntimeError(f"expected 1153 prior eligible failures, found {len(targets)}")
    project = Path("/mnt/GrokCam/projects/Reel_46335")
    capture = load_capture(project)
    calibration = load_calibration()
    developer = DarktableMatchedDeveloper(calibration.match.report)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    work = ROOT / "work"
    output = []
    for start in range(0, len(targets), 24):
        batch = targets[start:start + 24]
        temporary = Path(tempfile.mkdtemp(prefix="bright_failure_", dir=work))
        try:
            with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                futures = {}
                for frame in batch:
                    target = temporary / f"frame_{frame:06d}.tif"
                    futures[pool.submit(developer.develop, project / "raw" / f"frame_{frame:06d}.dng", target)] = target
                for future in as_completed(futures):
                    future.result()
            for frame in batch:
                with Image.open(temporary / f"frame_{frame:06d}.tif") as image:
                    category, detail = diagnose_pair(image, capture[frame], calibration.detector)
                output.append({"frame": frame, "classification": category,
                               "details": json.dumps(detail, sort_keys=True,
                                                     default=lambda value: value.item())})
        finally:
            shutil.rmtree(temporary)
        print(f"classified {min(start + len(batch), len(targets))}/{len(targets)}", flush=True)
    counts = Counter(r["classification"] for r in output)
    with (args.output_dir / "failure_classification.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["frame", "classification", "details"])
        writer.writeheader(); writer.writerows(output)
    (args.output_dir / "summary.json").write_text(json.dumps({"frames": len(output), "counts": counts}, indent=2) + "\n")


if __name__ == "__main__":
    main()
