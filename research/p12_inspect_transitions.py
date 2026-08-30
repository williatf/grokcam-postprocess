#!/usr/bin/env python3
"""P12: Inspect source-transition outliers and classify."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from grokcam.config import load_calibration
from grokcam.raw_development import DarktableMatchedDeveloper

# P09 constants
PITCH = 785.0
HEIGHT = 272.0
LOWER_X = 18.678947368421063
WIDTH = 381.5842105263158


def load_manifest(manifest_path: Path) -> dict[int, dict[str, Any]]:
    """Load transitions to inspect."""
    with manifest_path.open() as f:
        data = json.load(f)
    return data


def load_p09_csv(csv_path: Path) -> dict[int, dict[str, Any]]:
    """Load P09 measurements indexed by frame."""
    measurements = {}
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            frame = int(row["frame"])
            measurements[frame] = row
    return measurements


def develop_frame(frame_num: int, raw_dir: Path, developer: DarktableMatchedDeveloper, cache_dir: Path) -> Image.Image:
    """Develop frame to TIFF, using cache if available."""
    cache_path = cache_dir / f"frame_{frame_num:06d}.tif"
    
    if not cache_path.exists():
        dng_path = raw_dir / f"frame_{frame_num:06d}.dng"
        if not dng_path.exists():
            raise FileNotFoundError(f"DNG not found: {dng_path}")
        developer.develop(dng_path, cache_path)
    
    return Image.open(cache_path)


def get_anchor_y_estimate(anchor_y: float) -> float:
    """Estimate where the lower-top boundary should be if anchor is at anchor_y."""
    # From P09: lower sprocket is PITCH pixels below upper
    # anchor_y is typically near the upper hole center
    # lower-top should be at approximately: anchor_y + PITCH/2 - HEIGHT/2
    # But this varies by source, so we'll use the anchor as a relative reference
    return anchor_y + PITCH / 2 - HEIGHT / 2


def extract_lower_sprocket_crop(image: Image.Image, anchor_x: float, lower_center_y: float, crop_height: int = 150, crop_width: int = 200) -> tuple[Image.Image, float, float]:
    """
    Extract a crop showing the lower sprocket area.
    
    Returns:
        (cropped_image, offset_x, offset_y) where offset_* is the top-left corner of crop in original coords
    """
    left = max(0, int(anchor_x - crop_width / 2))
    top = max(0, int(lower_center_y - crop_height / 2))
    right = min(image.width, left + crop_width)
    bottom = min(image.height, top + crop_height)
    
    crop = image.crop((left, top, right, bottom))
    return crop, float(left), float(top)


def draw_diagnostic_overlay(
    crop: Image.Image,
    crop_offset_x: float,
    crop_offset_y: float,
    anchor_y_estimate: float,
    measured_lower_top_y: float,
    actual_lower_center_y: float,
) -> Image.Image:
    """
    Draw overlay on crop showing three candidate positions:
    - anchor-derived estimate (blue)
    - measured lower-top (red)
    - actual visual lower center (green)
    """
    # Convert to PIL Image if needed
    if not isinstance(crop, Image.Image):
        crop = Image.fromarray(np.uint8(crop))
    
    overlay = crop.copy()
    draw = ImageDraw.Draw(overlay, 'RGBA')
    
    # Draw horizontal lines at each position
    # Anchor estimate (blue)
    y_anchor_rel = anchor_y_estimate - crop_offset_y
    if 0 <= y_anchor_rel < crop.height:
        draw.line([(0, y_anchor_rel), (crop.width, y_anchor_rel)], fill=(0, 0, 255, 180), width=2)
    
    # Measured lower-top (red)
    y_measured_rel = measured_lower_top_y - crop_offset_y
    if 0 <= y_measured_rel < crop.height:
        draw.line([(0, y_measured_rel), (crop.width, y_measured_rel)], fill=(255, 0, 0, 180), width=2)
    
    # Actual visual lower center (green) - if available
    y_actual_rel = actual_lower_center_y - crop_offset_y
    if 0 <= y_actual_rel < crop.height:
        draw.line([(0, y_actual_rel), (crop.width, y_actual_rel)], fill=(0, 255, 0, 180), width=2)
    
    return overlay


def classify_transition(
    frame_a: int,
    frame_b: int,
    source_a: str,
    source_b: str,
    anchor_delta: float,
    lower_top_delta: float,
    delta_difference: float,
    measurement_a: dict[str, Any],
    measurement_b: dict[str, Any],
    image_a: Optional[Image.Image] = None,
    image_b: Optional[Image.Image] = None,
) -> dict[str, Any]:
    """
    Classify a transition based on available evidence.
    
    Returns a classification dict with:
    - classification: A/B/C/D
    - suspected_bad_frame: frame number if identifiable, else None
    - estimated_error_px: estimated error magnitude if identifiable
    - evidence: description of visual evidence
    """
    
    result = {
        "frame_a": frame_a,
        "frame_b": frame_b,
        "source_a": source_a,
        "source_b": source_b,
        "trusted_anchor_delta": anchor_delta,
        "lower_top_delta": lower_top_delta,
        "delta_difference": delta_difference,
        "abs_diff": abs(delta_difference),
        "classification": "D",
        "suspected_bad_frame": None,
        "estimated_error_px": None,
        "evidence": "",
    }
    
    # Check if both measurements are valid
    lt_valid_a = measurement_a.get("lower_top_valid") == "True"
    lt_valid_b = measurement_b.get("lower_top_valid") == "True"
    
    if not (lt_valid_a and lt_valid_b):
        result["evidence"] = "One or both lower-top measurements not valid"
        result["classification"] = "D"
        return result
    
    # Extract measurements
    anchor_a = float(measurement_a.get("trusted_anchor_y", 0))
    anchor_b = float(measurement_b.get("trusted_anchor_y", 0))
    lower_top_a = float(measurement_a.get("lower_top_y", 0))
    lower_top_b = float(measurement_b.get("lower_top_y", 0))
    
    # Estimate where anchor places the lower-top
    anchor_est_a = get_anchor_y_estimate(anchor_a)
    anchor_est_b = get_anchor_y_estimate(anchor_b)
    anchor_est_delta = anchor_est_b - anchor_est_a
    
    # The actual delta difference between anchor estimate and measured
    measured_vs_anchor_diff_a = lower_top_a - anchor_est_a
    measured_vs_anchor_diff_b = lower_top_b - anchor_est_b
    
    # Signal quality
    lower_top_snr_a = float(measurement_a.get("lower_top_snr", 0))
    lower_top_snr_b = float(measurement_b.get("lower_top_snr", 0))
    lower_top_peak_a = float(measurement_a.get("lower_top_peak", 0))
    lower_top_peak_b = float(measurement_b.get("lower_top_peak", 0))
    
    # High SNR suggests high confidence
    high_snr_a = lower_top_snr_a > 3.0
    high_snr_b = lower_top_snr_b > 3.0
    
    # If one source transition is to/from physical_pair, be cautious
    # Physical_pair has only 2.8% coverage, high uncertainty
    is_pair_transition = (source_a == "physical_pair") or (source_b == "physical_pair")
    
    # Decision logic based on visible disagreement and signal quality
    # Case 1: Both measurements have high SNR and show opposite-sign movement
    # This could indicate one anchor is definitely wrong
    if abs(anchor_delta) > 2 and abs(lower_top_delta) > 2:
        if (anchor_delta > 0 and lower_top_delta < 0) or (anchor_delta < 0 and lower_top_delta > 0):
            # Opposite signs - one is likely wrong
            if high_snr_b:
                result["classification"] = "A"
                result["suspected_bad_frame"] = frame_a
                result["estimated_error_px"] = abs(anchor_est_delta - lower_top_delta)
                result["evidence"] = f"High-SNR measurement ({lower_top_snr_b:.1f}) shows opposite-sign motion to anchor"
            elif high_snr_a:
                result["classification"] = "A"
                result["suspected_bad_frame"] = frame_b
                result["estimated_error_px"] = abs(anchor_est_delta - lower_top_delta)
                result["evidence"] = f"High-SNR measurement ({lower_top_snr_a:.1f}) shows opposite-sign motion to anchor"
            else:
                result["classification"] = "B"
                result["evidence"] = "Opposite-sign motion but SNR not high; ambiguous"
        else:
            # Same sign, but large disagreement
            if is_pair_transition:
                result["classification"] = "B"
                result["evidence"] = "Large disagreement involving physical_pair; low coverage makes this unreliable"
            elif max(high_snr_a, high_snr_b):
                result["classification"] = "B"
                result["evidence"] = f"Same-sign large disagreement ({abs(delta_difference):.2f} px) with at least one high-SNR measurement"
            else:
                result["classification"] = "C"
                result["evidence"] = "Same-sign large disagreement but both SNRs modest; likely physical deformation"
    elif abs(delta_difference) < 1.5:
        # Good agreement
        result["classification"] = "C"
        result["evidence"] = "Good agreement; physical movement appears tracked correctly"
    else:
        # Moderate disagreement
        if is_pair_transition:
            result["classification"] = "B"
            result["evidence"] = f"Moderate disagreement ({abs(delta_difference):.2f} px) involving physical_pair (low coverage)"
        elif max(high_snr_a, high_snr_b):
            result["classification"] = "B"
            result["evidence"] = f"Moderate disagreement ({abs(delta_difference):.2f} px) with high-SNR measurement"
        else:
            result["classification"] = "C"
            result["evidence"] = "Moderate disagreement but modest SNR; likely physical deformation or noise"
    
    return result


def run_analysis(
    manifest_path: Path,
    p09_csv_path: Path,
    raw_dir: Path,
    cache_dir: Path,
    output_dir: Path,
) -> list[dict[str, Any]]:
    """Run P12 analysis."""
    
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    # Load data
    manifest = load_manifest(manifest_path)
    p09_data = load_p09_csv(p09_csv_path)
    
    # Setup developer
    calibration = load_calibration()
    developer = DarktableMatchedDeveloper(calibration.match.report)
    
    # Analyze outliers
    results = []
    
    for transition_set_name in ["outliers", "control"]:
        transitions = manifest[transition_set_name]
        
        print(f"\n=== CLASSIFYING {transition_set_name.upper()} ({len(transitions)} transitions) ===\n")
        
        for trans in transitions:
            frame_a = trans["frame_a"]
            frame_b = trans["frame_b"]
            source_a = trans["source_a"]
            source_b = trans["source_b"]
            anchor_delta = trans["trusted_anchor_delta"]
            lower_top_delta = trans["lower_top_delta"]
            delta_diff = trans["delta_difference"]
            
            # Get measurements
            meas_a = p09_data.get(frame_a)
            meas_b = p09_data.get(frame_b)
            
            if not (meas_a and meas_b):
                print(f"SKIP {frame_a}-{frame_b}: missing measurements")
                continue
            
            # Classify
            classification = classify_transition(
                frame_a, frame_b, source_a, source_b,
                anchor_delta, lower_top_delta, delta_diff,
                meas_a, meas_b,
                image_a=None, image_b=None,  # For now, no image-based analysis
            )
            
            results.append(classification)
            
            print(
                f"{frame_a:4d}-{frame_b:4d} ({source_a:14s} → {source_b:14s}): "
                f"diff={abs(delta_diff):5.2f}px → "
                f"CLASS {classification['classification']}: {classification['evidence'][:60]}"
            )
    
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest-json", required=True)
    p.add_argument("--p09-csv", required=True)
    p.add_argument("--raw-dir", required=True)
    p.add_argument("--cache-dir", required=True)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    
    results = run_analysis(
        Path(args.manifest_json),
        Path(args.p09_csv),
        Path(args.raw_dir),
        Path(args.cache_dir),
        Path(args.output_dir),
    )
    
    # Save results
    output_path = Path(args.output_dir) / "p12_classifications.jsonl"
    with output_path.open("w") as f:
        for result in results:
            f.write(json.dumps(result) + "\n")
    
    print(f"\n\nSaved {len(results)} classifications to {output_path}")
    
    # Summary
    by_class = {}
    for r in results:
        c = r["classification"]
        by_class.setdefault(c, []).append(r)
    
    print("\nSummary:")
    for c in "ABCD":
        count = len(by_class.get(c, []))
        print(f"  {c}: {count}")


if __name__ == "__main__":
    main()
