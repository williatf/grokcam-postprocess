#!/usr/bin/env python3
"""P11: Analyze lower-top Y coordinate consistency across registration sources."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np


def analyze_lower_top(csv_path: Path, output_dir: Path) -> dict:
    """Analyze lower-top offset consistency by registration source."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load P09 measurements
    rows = []
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    # Group by source and check lower-top validity
    by_source = defaultdict(list)
    for row in rows:
        by_source[row["source"]].append(row)
    
    results = {}
    
    print("\n=== P11: LOWER-TOP CONSISTENCY ANALYSIS ===\n")
    
    for source in sorted(by_source.keys()):
        frames = by_source[source]
        
        # Filter to valid measurements
        valid_frames = [r for r in frames if r.get("lower_top_valid") == "True"]
        
        if not valid_frames:
            print(f"\n{source.upper()}: No valid lower-top measurements")
            continue
        
        # Collect offsets
        offsets = []
        for r in valid_frames:
            try:
                offset = float(r.get("lower_top_offset", "nan"))
                if np.isfinite(offset):
                    offsets.append(offset)
            except (ValueError, TypeError):
                pass
        
        if not offsets:
            print(f"\n{source.upper()}: No valid offsets")
            continue
        
        offsets = np.array(offsets)
        abs_offsets = np.abs(offsets)
        
        # Statistics
        stats = {
            "source": source,
            "total_frames": len(frames),
            "valid_frames": len(valid_frames),
            "valid_pct": 100.0 * len(valid_frames) / len(frames),
            "median_offset": float(np.median(offsets)),
            "median_abs_offset": float(np.median(abs_offsets)),
            "offset_mad": float(1.4826 * np.median(np.abs(offsets - np.median(offsets)))),
            "mean_offset": float(np.mean(offsets)),
            "mean_abs_offset": float(np.mean(abs_offsets)),
            "p90_abs_offset": float(np.percentile(abs_offsets, 90)),
            "p95_abs_offset": float(np.percentile(abs_offsets, 95)),
            "std_offset": float(np.std(offsets)),
            "min_offset": float(np.min(offsets)),
            "max_offset": float(np.max(offsets)),
        }
        
        results[source] = stats
        
        print(f"{source.upper()}")
        print(f"  Total frames: {stats['total_frames']}")
        print(f"  Valid lower-top: {stats['valid_frames']}/{stats['total_frames']} ({stats['valid_pct']:.1f}%)")
        print(f"  Median offset: {stats['median_offset']:+.3f} px")
        print(f"  Median abs offset: {stats['median_abs_offset']:.3f} px")
        print(f"  Offset MAD: {stats['offset_mad']:.3f} px")
        print(f"  P90 abs offset: {stats['p90_abs_offset']:.3f} px")
        print(f"  P95 abs offset: {stats['p95_abs_offset']:.3f} px")
        print(f"  Std dev: {stats['std_offset']:.3f} px")
        print(f"  Range: [{stats['min_offset']:+.3f}, {stats['max_offset']:+.3f}]")
    
    # Cross-source comparison
    print("\n=== CROSS-SOURCE COMPARISON ===\n")
    
    sources_with_data = sorted([s for s in results.keys() if results[s]["valid_frames"] > 0])
    
    if len(sources_with_data) > 1:
        # Compare median offsets
        medians = {s: results[s]["median_offset"] for s in sources_with_data}
        print("Median offsets by source:")
        for s in sources_with_data:
            print(f"  {s:15s}: {medians[s]:+.3f} px")
        
        # Check if all sources agree (within ~1-2 px)
        median_values = list(medians.values())
        median_span = max(median_values) - min(median_values)
        print(f"\nMedian span across sources: {median_span:.3f} px")
        
        if median_span < 1.0:
            print("✓ Sources have consistent median offsets (< 1 px spread)")
        elif median_span < 2.0:
            print("~ Sources have moderately consistent medians (1-2 px spread)")
        else:
            print("✗ Sources show divergent median offsets (> 2 px spread)")
    
    return results


def analyze_transitions(csv_path: Path, output_dir: Path) -> None:
    """Analyze source transitions to compare trusted vs lower-top movement."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load P09 measurements in frame order
    rows = []
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    # Sort by frame number
    rows_by_frame = {int(r["frame"]): r for r in rows}
    frames = sorted(rows_by_frame.keys())
    
    print("\n=== SOURCE TRANSITIONS ===\n")
    
    transitions = []
    
    for i in range(len(frames) - 1):
        frame_a = frames[i]
        frame_b = frames[i + 1]
        
        row_a = rows_by_frame[frame_a]
        row_b = rows_by_frame[frame_b]
        
        # Check if source changes
        src_a = row_a["source"]
        src_b = row_b["source"]
        
        if src_a == src_b:
            continue
        
        # Check if both have valid lower-top
        if row_a.get("lower_top_valid") != "True" or row_b.get("lower_top_valid") != "True":
            continue
        
        try:
            anchor_y_a = float(row_a["trusted_anchor_y"])
            anchor_y_b = float(row_b["trusted_anchor_y"])
            lower_top_y_a = float(row_a["lower_top_y"])
            lower_top_y_b = float(row_b["lower_top_y"])
            
            anchor_delta = anchor_y_b - anchor_y_a
            lower_top_delta = lower_top_y_b - lower_top_y_a
            
            transition = {
                "frame_a": frame_a,
                "frame_b": frame_b,
                "source_a": src_a,
                "source_b": src_b,
                "trusted_anchor_delta": anchor_delta,
                "lower_top_delta": lower_top_delta,
                "delta_difference": anchor_delta - lower_top_delta,
            }
            
            transitions.append(transition)
            
            print(f"Frames {frame_a} → {frame_b}  ({src_a} → {src_b})")
            print(f"  Trusted anchor ΔY: {anchor_delta:+.2f} px")
            print(f"  Lower-top ΔY: {lower_top_delta:+.2f} px")
            print(f"  Difference: {transition['delta_difference']:+.2f} px")
            print()
        
        except (ValueError, TypeError):
            pass
    
    if not transitions:
        print("No source transitions with valid lower-top measurements on both sides.")
        return
    
    print(f"Found {len(transitions)} source transitions with both sides measurable.\n")
    
    # Summary
    differences = [t["delta_difference"] for t in transitions]
    abs_differences = [abs(d) for d in differences]
    
    print("Summary of anchor vs lower-top movement at transitions:")
    print(f"  Median difference: {np.median(differences):+.2f} px")
    print(f"  Median abs difference: {np.median(abs_differences):.2f} px")
    print(f"  Std dev: {np.std(differences):.2f} px")
    print(f"  Range: [{min(differences):+.2f}, {max(differences):+.2f}]")
    
    # Write transitions to JSONL
    transitions_file = output_dir / "source_transitions.jsonl"
    with transitions_file.open("w") as f:
        for t in transitions:
            f.write(json.dumps(t) + "\n")
    
    print(f"\nTransitions saved to: {transitions_file}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--p09-csv", required=True, help="Path to P09 measurements.csv")
    p.add_argument("--output-dir", required=True, help="Output directory")
    args = p.parse_args()
    
    csv_path = Path(args.p09_csv)
    output_dir = Path(args.output_dir)
    
    results = analyze_lower_top(csv_path, output_dir)
    analyze_transitions(csv_path, output_dir)
    
    # Write summary JSON
    summary_file = output_dir / "p11_analysis_summary.json"
    summary_file.write_text(json.dumps(results, indent=2))
    print(f"\nSummary saved to: {summary_file}")


if __name__ == "__main__":
    main()
