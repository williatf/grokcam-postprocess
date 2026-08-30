#!/usr/bin/env python3
"""P10: Inspect specific failed frames to understand physical reasons."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from PIL import Image
import cv2
import numpy as np

from grokcam.config import load_calibration
from grokcam.raw_development import DarktableMatchedDeveloper


WIDTH=381.5842105263158; HEIGHT=272.0; PITCH=785.0; LOWER_X=18.678947368421063


def visualize_frame_analysis(image: Image.Image, frame_num: int, anchor_x: float, anchor_y: float, 
                            cfg: dict, diagnostics: dict) -> str:
    """Create a summary of key measurements and features on a frame."""
    report = f"Frame {frame_num}\n"
    report += f"Anchor: ({anchor_x:.1f}, {anchor_y:.1f})\n"
    report += f"Geometry: holes {WIDTH:.0f}x{HEIGHT:.0f}px, pitch {PITCH:.0f}px\n\n"
    
    # Lower hole center
    ux = anchor_x + 17.125 - LOWER_X/2
    uy = anchor_y - PITCH/2
    lx = ux + LOWER_X
    ly = uy + PITCH
    
    # Extract lower hole region
    x0 = max(0, int(math.floor(lx - WIDTH*0.30)))
    x1 = min(image.width, int(math.ceil(lx + WIDTH*0.30)))
    y0 = max(0, int(math.floor(ly - HEIGHT/2 - 12)))
    y1 = min(image.height, int(math.ceil(ly + HEIGHT/2 + 12)))
    
    lower_crop = image.crop((x0, y0, x1, y1))
    gray = cv2.cvtColor(np.asarray(lower_crop.convert("RGB")), cv2.COLOR_RGB2GRAY).astype(np.float32)
    
    report += f"Lower hole region extracted: {gray.shape[0]}x{gray.shape[1]} pixels\n"
    report += f"Image stats: min={gray.min():.0f}, median={np.median(gray):.0f}, max={gray.max():.0f}\n"
    
    # Check if there's good contrast
    p10 = np.percentile(gray, 10)
    p90 = np.percentile(gray, 90)
    contrast = p90 - p10
    report += f"Contrast (P90-P10): {contrast:.0f}\n"
    
    # Check vertical profile
    vertical_profile = gray.mean(axis=1)
    vertical_gradient = np.abs(np.diff(vertical_profile))
    max_gradient_row = np.argmax(vertical_gradient)
    report += f"Vertical gradient peak at row {max_gradient_row} (max gradient: {np.max(vertical_gradient):.1f})\n"
    
    # Expected top/bottom positions (relative to crop)
    cy_top = ly - HEIGHT/2 - y0
    cy_bottom = ly + HEIGHT/2 - y0
    search_radius = 8
    
    report += f"\nExpected top boundary: {cy_top:.0f} ± {search_radius}\n"
    report += f"Expected bottom boundary: {cy_bottom:.0f} ± {search_radius}\n"
    
    # Check if boundaries are within expected range
    if 0 <= int(cy_top) < gray.shape[0]:
        top_vicinity_gradient = np.max(vertical_gradient[max(0, int(cy_top)-search_radius):min(len(vertical_gradient), int(cy_top)+search_radius+1)])
        report += f"  Vertical gradient near top: {top_vicinity_gradient:.1f}\n"
    
    if 0 <= int(cy_bottom) < gray.shape[0]:
        bottom_vicinity_gradient = np.max(vertical_gradient[max(0, int(cy_bottom)-search_radius):min(len(vertical_gradient), int(cy_bottom)+search_radius+1)])
        report += f"  Vertical gradient near bottom: {bottom_vicinity_gradient:.1f}\n"
    
    return report


def analyze_frame_samples(raw_dir: Path, manifest_path: Path, p09_csv_path: Path, 
                         diagnostic_csv_path: Path, output_dir: Path):
    """Inspect specific failed frames from each source."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load manifests and data
    manifest = json.load(open(manifest_path))
    cfg = json.loads((Path(__file__).parent / "config/p09_sprocket_y_landmark_metrology.json").read_text())
    
    # Load diagnostic data
    diagnostic_rows = []
    with open(diagnostic_csv_path) as f:
        reader = csv.DictReader(f)
        diagnostic_rows = list(reader)
    
    # Group by source
    by_source = {}
    for row in diagnostic_rows:
        src = row["source"]
        if src not in by_source:
            by_source[src] = []
        by_source[src].append(row)
    
    # Get one sample failed frame per source
    calibration = load_calibration()
    developer = DarktableMatchedDeveloper(calibration.match.report)
    tiff_path = output_dir / "inspect_working.tif"
    
    report_lines = []
    
    for source in sorted(by_source.keys()):
        frames = by_source[source]
        report_lines.append(f"\n{'='*70}")
        report_lines.append(f"SOURCE: {source.upper()}")
        report_lines.append(f"{'='*70}")
        
        # Find a frame where both boundaries failed
        both_failed = [r for r in frames if r.get("lower_top_valid") != "True" 
                      and r.get("lower_bottom_valid") != "True"]
        
        if both_failed:
            sample = both_failed[0]
            frame = int(sample["frame"])
            
            # Get manifest record for anchor
            anchor_x, anchor_y = None, None
            for segment in manifest["segments"]:
                for record in segment["frame_records"]:
                    if record["frame"] == frame:
                        anchor_x = record["anchor_x"]
                        anchor_y = record["anchor_y"]
                        break
                if anchor_x is not None:
                    break
            
            if anchor_x is not None:
                report_lines.append(f"\nSample failed frame: {frame} (both boundaries failed)")
                report_lines.append(f"Top failures: {sample.get('lower_top_failure_reason', 'unknown')}")
                report_lines.append(f"Bottom failures: {sample.get('lower_bottom_failure_reason', 'unknown')}")
                
                # Develop and analyze
                developer.develop(raw_dir / f"frame_{frame:06d}.dng", tiff_path)
                with Image.open(tiff_path) as img:
                    analysis = visualize_frame_analysis(img, frame, anchor_x, anchor_y, cfg, sample)
                    report_lines.append(analysis)
                
                tiff_path.unlink(missing_ok=True)
    
    # Write report
    report_file = output_dir / "frame_inspection_report.txt"
    report_file.write_text("\n".join(report_lines))
    print("\n".join(report_lines))
    print(f"\nReport saved to: {report_file}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--raw-dir", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--p09-csv", required=True)
    p.add_argument("--diagnostics-csv", required=True)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    
    analyze_frame_samples(Path(args.raw_dir), Path(args.manifest), Path(args.p09_csv),
                         Path(args.diagnostics_csv), Path(args.output_dir))


if __name__ == "__main__":
    main()
