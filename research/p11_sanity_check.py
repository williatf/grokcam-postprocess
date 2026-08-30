#!/usr/bin/env python3
"""P11: Sanity check - compare lower-top to lower-midpoint where both available."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np


def sanity_check_midpoint_vs_top(csv_path: Path, output_dir: Path) -> None:
    """Compare lower-top against lower-midpoint for frames where both are valid."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    rows = []
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    print("\n=== SANITY CHECK: Lower-top vs Lower-midpoint ===\n")
    
    # Find frames where we have both lower-top and both lower boundaries
    both_available = []
    
    for row in rows:
        if (row.get("lower_top_valid") == "True" and 
            row.get("lower_bottom_valid") == "True" and
            row.get("lower_top_valid") == "True"):
            try:
                lower_top_y = float(row["lower_top_y"])
                lower_bottom_y = float(row["lower_bottom_y"])
                lower_top_offset = float(row["lower_top_offset"])
                lower_bottom_offset = float(row["lower_bottom_offset"])
                
                # Compute midpoint
                lower_midpoint_y = (lower_top_y + lower_bottom_y) / 2.0
                
                both_available.append({
                    "frame": int(row["frame"]),
                    "source": row["source"],
                    "lower_top_y": lower_top_y,
                    "lower_top_offset": lower_top_offset,
                    "lower_midpoint_y": lower_midpoint_y,
                    "lower_top_to_midpoint_distance": lower_midpoint_y - lower_top_y,
                })
            except (ValueError, TypeError):
                pass
    
    print(f"Frames with both boundaries (for sanity check): {len(both_available)}\n")
    
    if not both_available:
        print("No frames available for comparison.")
        return
    
    # Group by source
    by_source = {}
    for item in both_available:
        src = item["source"]
        if src not in by_source:
            by_source[src] = []
        by_source[src].append(item)
    
    # Analyze distances
    for source in sorted(by_source.keys()):
        items = by_source[source]
        distances = [item["lower_top_to_midpoint_distance"] for item in items]
        
        print(f"{source.upper()} ({len(items)} frames):")
        print(f"  Lower-top to midpoint distance:")
        print(f"    Median: {np.median(distances):.2f} px")
        print(f"    Mean: {np.mean(distances):.2f} px")
        print(f"    Std: {np.std(distances):.2f} px")
        print(f"    Range: [{min(distances):.2f}, {max(distances):.2f}]")
    
    print("\nNote: These distances should be consistent (~136 px = HEIGHT/2)")
    print("  as this is the physical distance from top to midpoint.")
    print("  Consistency here validates that lower-top is measuring the same edge")
    print("  and that the measurement technique is coherent.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--p09-csv", required=True)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    
    sanity_check_midpoint_vs_top(Path(args.p09_csv), Path(args.output_dir))


if __name__ == "__main__":
    main()
