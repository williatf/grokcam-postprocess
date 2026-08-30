#!/usr/bin/env python3
"""P12: Visual inspection of critical frames (2143-2144 focus)."""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from grokcam.config import load_calibration
from grokcam.raw_development import DarktableMatchedDeveloper

PITCH = 785.0
HEIGHT = 272.0
LOWER_X = 18.678947368421063


def load_p09_csv(csv_path: Path) -> dict[int, dict[str, str]]:
    """Load P09 measurements."""
    measurements = {}
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            measurements[int(row["frame"])] = row
    return measurements


def develop_and_save_crop(
    frame: int,
    raw_dir: Path,
    developer: DarktableMatchedDeveloper,
    measurements: dict,
    output_dir: Path,
) -> Path:
    """
    Develop a frame and save a diagnostic crop of the lower sprocket.
    """
    
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"frame_{frame:06d}_sprocket_crop.png"
    
    # Skip if already exists
    if output_path.exists():
        print(f"  Frame {frame}: crop already exists")
        return output_path
    
    # Develop frame
    dng_path = raw_dir / f"frame_{frame:06d}.dng"
    tiff_path = output_dir / f"frame_{frame:06d}_temp.tif"
    
    print(f"  Developing frame {frame}...")
    developer.develop(dng_path, tiff_path)
    
    # Load image
    image = Image.open(tiff_path)
    
    # Get measurements
    meas = measurements.get(frame, {})
    anchor_y = float(meas.get("trusted_anchor_y", 0))
    lower_top_y = float(meas.get("lower_top_y", 0))
    lower_center_y = float(meas.get("lower_center", 0))
    
    # Extract sprocket crop (large area around lower hole)
    # Lower hole center is roughly at anchor_y + PITCH/2
    lower_est_y = anchor_y + PITCH / 2
    
    crop_top = max(0, int(lower_est_y - 150))
    crop_bottom = min(image.height, int(lower_est_y + 150))
    crop_left = max(0, int(405 - 200))
    crop_right = min(image.width, int(405 + 200))
    
    crop_img = image.crop((crop_left, crop_top, crop_right, crop_bottom))
    
    # Convert to RGB for drawing
    if crop_img.mode == 'L':
        crop_rgb = Image.new('RGB', crop_img.size)
        crop_rgb.paste(crop_img)
    else:
        crop_rgb = crop_img.convert('RGB')
    
    # Draw reference lines on the crop
    draw = ImageDraw.Draw(crop_rgb)
    
    # Line for anchor-estimated lower-top
    anchor_est_y = lower_est_y - HEIGHT / 2
    y_anchor_rel = anchor_est_y - crop_top
    if 0 <= y_anchor_rel < crop_rgb.height:
        draw.line([(0, y_anchor_rel), (crop_rgb.width, y_anchor_rel)], fill=(0, 0, 255), width=1)
    
    # Line for measured lower-top
    y_meas_rel = lower_top_y - crop_top
    if 0 <= y_meas_rel < crop_rgb.height:
        draw.line([(0, y_meas_rel), (crop_rgb.width, y_meas_rel)], fill=(255, 0, 0), width=1)
    
    # Line for lower center
    y_center_rel = lower_center_y - crop_top
    if 0 <= y_center_rel < crop_rgb.height:
        draw.line([(0, y_center_rel), (crop_rgb.width, y_center_rel)], fill=(0, 255, 0), width=1)
    
    # Add legend
    draw.text((5, 5), f"Blue=anchor-est, Red=measured-top, Green=measured-center", fill=(255, 255, 255))
    draw.text((5, 20), f"Frame {frame} ({meas.get('source', '?')})", fill=(255, 255, 255))
    
    # Save
    crop_rgb.save(output_path)
    print(f"  Saved crop to {output_path}")
    
    # Cleanup
    tiff_path.unlink(missing_ok=True)
    
    return output_path


def analyze_frame_pair(
    frame_a: int,
    frame_b: int,
    raw_dir: Path,
    developer: DarktableMatchedDeveloper,
    measurements: dict,
    output_dir: Path,
) -> dict:
    """Analyze a frame pair with visual inspection."""
    
    print(f"\n=== ANALYZING FRAMES {frame_a}-{frame_b} ===\n")
    
    # Develop crops
    crop_a_path = develop_and_save_crop(frame_a, raw_dir, developer, measurements, output_dir / "crops")
    crop_b_path = develop_and_save_crop(frame_b, raw_dir, developer, measurements, output_dir / "crops")
    
    # Get measurements
    meas_a = measurements.get(frame_a, {})
    meas_b = measurements.get(frame_b, {})
    
    anchor_a = float(meas_a.get("trusted_anchor_y", 0))
    anchor_b = float(meas_b.get("trusted_anchor_y", 0))
    lower_top_a = float(meas_a.get("lower_top_y", 0))
    lower_top_b = float(meas_b.get("lower_top_y", 0))
    
    # Calculate deltas
    anchor_delta = anchor_b - anchor_a
    lower_top_delta = lower_top_b - lower_top_a
    
    print(f"Frame {frame_a} ({meas_a.get('source', '?')}): anchor={anchor_a:.1f}, lower-top={lower_top_a:.1f}")
    print(f"Frame {frame_b} ({meas_b.get('source', '?')}): anchor={anchor_b:.1f}, lower-top={lower_top_b:.1f}")
    print()
    print(f"Anchor moves: {anchor_delta:+.2f} px")
    print(f"Lower-top moves: {lower_top_delta:+.2f} px")
    print(f"Disagreement: {anchor_delta - lower_top_delta:+.2f} px")
    print()
    print(f"Crops saved:")
    print(f"  {crop_a_path}")
    print(f"  {crop_b_path}")
    
    return {
        "frame_a": frame_a,
        "frame_b": frame_b,
        "source_a": meas_a.get("source", "?"),
        "source_b": meas_b.get("source", "?"),
        "anchor_delta": anchor_delta,
        "lower_top_delta": lower_top_delta,
        "crop_a": str(crop_a_path),
        "crop_b": str(crop_b_path),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--frame-a", type=int, required=True)
    p.add_argument("--frame-b", type=int, required=True)
    p.add_argument("--p09-csv", required=True)
    p.add_argument("--raw-dir", required=True)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    
    # Load measurements
    measurements = load_p09_csv(Path(args.p09_csv))
    
    # Setup developer
    calibration = load_calibration()
    developer = DarktableMatchedDeveloper(calibration.match.report)
    
    # Analyze
    result = analyze_frame_pair(
        args.frame_a,
        args.frame_b,
        Path(args.raw_dir),
        developer,
        measurements,
        Path(args.output_dir),
    )
    
    print(f"\n\nDone. Crops available for visual inspection.")


if __name__ == "__main__":
    main()
