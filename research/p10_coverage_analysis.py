#!/usr/bin/env python3
"""P10: Analyze lower-boundary measurement failures by registration source."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np


def analyze_coverage(csv_path: Path, output_dir: Path) -> dict:
    """Analyze P09 measurements by registration source."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Read data
    rows = []
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    # Group by source
    by_source = defaultdict(list)
    for row in rows:
        by_source[row["source"]].append(row)
    
    # Analyze each source
    results = {}
    summary = {}
    
    for source in sorted(by_source.keys()):
        frames = by_source[source]
        n_total = len(frames)
        
        # Count successes
        lower_top_valid = sum(1 for r in frames if r.get("lower_top_valid") == "True")
        lower_bottom_valid = sum(1 for r in frames if r.get("lower_bottom_valid") == "True")
        both_valid = sum(1 for r in frames 
                        if r.get("lower_top_valid") == "True" and r.get("lower_bottom_valid") == "True")
        
        # Collect failure reasons
        top_failures = defaultdict(int)
        bottom_failures = defaultdict(int)
        
        for r in frames:
            if r.get("lower_top_valid") != "True":
                reason = r.get("lower_top_failure_reason", "unknown")
                top_failures[reason] += 1
            if r.get("lower_bottom_valid") != "True":
                reason = r.get("lower_bottom_failure_reason", "unknown")
                bottom_failures[reason] += 1
        
        # Collect corrections (midpoint)
        corrections = []
        PITCH = 785.0
        for r in frames:
            if r.get("lower_top_valid") == "True" and r.get("lower_bottom_valid") == "True":
                try:
                    lt_y = float(r.get("lower_top_y", "nan"))
                    lb_y = float(r.get("lower_bottom_y", "nan"))
                    anchor_y = float(r.get("trusted_anchor_y", "nan"))
                    if np.isfinite(lt_y) and np.isfinite(lb_y) and np.isfinite(anchor_y):
                        lower_center = (lt_y + lb_y) / 2.0
                        lower_equivalent_center = lower_center - PITCH
                        # Correction is the difference from the anchor
                        correction = lower_equivalent_center - anchor_y
                        corrections.append({
                            "frame": r["frame"],
                            "correction": correction,
                            "lower_height": lb_y - lt_y
                        })
                except (ValueError, TypeError):
                    pass
        
        # Statistics for corrections
        if corrections:
            abs_corrections = [abs(c["correction"]) for c in corrections]
            heights = [c["lower_height"] for c in corrections]
            correction_stats = {
                "count": len(corrections),
                "median": float(np.median(abs_corrections)),
                "mean": float(np.mean(abs_corrections)),
                "mad": float(1.4826 * np.median(np.abs(np.array(abs_corrections) - np.median(abs_corrections)))),
                "p90": float(np.percentile(abs_corrections, 90)),
                "p95": float(np.percentile(abs_corrections, 95)),
                "median_raw_correction": float(np.median([c["correction"] for c in corrections])),
                "median_height": float(np.median(heights)),
                "mean_height": float(np.mean(heights)),
            }
        else:
            correction_stats = {}
        
        results[source] = {
            "total_frames": n_total,
            "lower_top_measurable": lower_top_valid,
            "lower_bottom_measurable": lower_bottom_valid,
            "both_measurable": both_valid,
            "lower_top_failures": dict(top_failures),
            "lower_bottom_failures": dict(bottom_failures),
            "midpoint_correction_stats": correction_stats,
            "frames_with_measurements": [c["frame"] for c in corrections],
        }
        
        summary[source] = {
            "total": n_total,
            "lower_top": lower_top_valid,
            "lower_bottom": lower_bottom_valid,
            "both": both_valid,
            "coverage_both_pct": 100.0 * both_valid / n_total if n_total else 0,
        }
    
    return {"by_source": results, "summary": summary}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--p09-csv", required=True, help="Path to P09 measurements.csv")
    p.add_argument("--output-dir", required=True, help="Output directory for P10 analysis")
    args = p.parse_args()
    
    csv_path = Path(args.p09_csv)
    output_dir = Path(args.output_dir)
    
    results = analyze_coverage(csv_path, output_dir)
    
    # Write summary
    summary_file = output_dir / "coverage_summary.json"
    summary_file.write_text(json.dumps(results, indent=2))
    print(f"Coverage summary: {summary_file}")
    
    # Print text report
    print("\n=== P10 COVERAGE ANALYSIS ===\n")
    for source in sorted(results["by_source"].keys()):
        data = results["by_source"][source]
        print(f"\n{source.upper()}")
        print(f"  Total frames: {data['total_frames']}")
        print(f"  Lower-top measurable: {data['lower_top_measurable']}/{data['total_frames']} ({100.0*data['lower_top_measurable']/data['total_frames']:.1f}%)")
        print(f"  Lower-bottom measurable: {data['lower_bottom_measurable']}/{data['total_frames']} ({100.0*data['lower_bottom_measurable']/data['total_frames']:.1f}%)")
        print(f"  Both measurable: {data['both_measurable']}/{data['total_frames']} ({100.0*data['both_measurable']/data['total_frames']:.1f}%)")
        
        if data['lower_top_failures']:
            print(f"  Top failures:")
            for reason, count in sorted(data['lower_top_failures'].items(), key=lambda x: -x[1]):
                print(f"    {reason}: {count} ({100.0*count/data['total_frames']:.1f}%)")
        
        if data['lower_bottom_failures']:
            print(f"  Bottom failures:")
            for reason, count in sorted(data['lower_bottom_failures'].items(), key=lambda x: -x[1]):
                print(f"    {reason}: {count} ({100.0*count/data['total_frames']:.1f}%)")
        
        if data['midpoint_correction_stats']:
            stats = data['midpoint_correction_stats']
            print(f"  Midpoint correction (n={stats['count']}):")
            print(f"    Median abs: {stats['median']:.3f} px")
            print(f"    Mean abs: {stats['mean']:.3f} px")
            print(f"    MAD: {stats['mad']:.3f} px")
            print(f"    P90/P95 abs: {stats['p90']:.3f} / {stats['p95']:.3f} px")
            print(f"    Median lower height: {stats['median_height']:.2f} px")


if __name__ == "__main__":
    main()
