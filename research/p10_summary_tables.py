#!/usr/bin/env python3
"""P10: Generate summary statistics by source and failure pattern."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np


def generate_summary_tables(csv_path: Path, output_dir: Path) -> None:
    """Generate detailed summary tables for P10 findings."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    rows = []
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    # Group by source
    by_source = defaultdict(list)
    for row in rows:
        by_source[row["source"]].append(row)
    
    # Generate CSV with detailed statistics per source
    summary_csv_path = output_dir / "p10_summary_statistics.csv"
    with summary_csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "source", "total_frames",
            "lower_top_measurable", "lower_top_pct",
            "lower_bottom_measurable", "lower_bottom_pct",
            "both_measurable", "both_pct",
            "only_top", "only_bottom", "neither",
            "top_peak_at_boundary_count",
            "bottom_peak_at_boundary_count",
            "bottom_weak_snr_count",
            "bottom_weak_prominence_count"
        ])
        writer.writeheader()
        
        for source in sorted(by_source.keys()):
            frames = by_source[source]
            n = len(frames)
            
            top_valid = sum(1 for r in frames if r.get("lower_top_valid") == "True")
            bottom_valid = sum(1 for r in frames if r.get("lower_bottom_valid") == "True")
            both_valid = sum(1 for r in frames if r.get("lower_top_valid") == "True" and r.get("lower_bottom_valid") == "True")
            only_top = top_valid - both_valid
            only_bottom = bottom_valid - both_valid
            neither = n - top_valid - bottom_valid + both_valid
            
            top_boundary_count = sum(1 for r in frames if r.get("lower_top_diag_peak_at_boundary") == "True")
            bottom_boundary_count = sum(1 for r in frames if r.get("lower_bottom_diag_peak_at_boundary") == "True")
            
            bottom_weak_snr = sum(1 for r in frames 
                                 if r.get("lower_bottom_valid") != "True"
                                 and r.get("lower_bottom_snr") 
                                 and float(r["lower_bottom_snr"]) < 2.5)
            
            bottom_weak_prom = sum(1 for r in frames 
                                  if r.get("lower_bottom_valid") != "True"
                                  and r.get("lower_bottom_prominence")
                                  and float(r["lower_bottom_prominence"]) < 8)
            
            writer.writerow({
                "source": source,
                "total_frames": n,
                "lower_top_measurable": top_valid,
                "lower_top_pct": f"{100.0*top_valid/n:.1f}%",
                "lower_bottom_measurable": bottom_valid,
                "lower_bottom_pct": f"{100.0*bottom_valid/n:.1f}%",
                "both_measurable": both_valid,
                "both_pct": f"{100.0*both_valid/n:.1f}%",
                "only_top": only_top,
                "only_bottom": only_bottom,
                "neither": neither,
                "top_peak_at_boundary_count": top_boundary_count,
                "bottom_peak_at_boundary_count": bottom_boundary_count,
                "bottom_weak_snr_count": bottom_weak_snr,
                "bottom_weak_prominence_count": bottom_weak_prom,
            })
    
    print(f"Summary statistics: {summary_csv_path}")
    
    # Generate comparison vs primary
    print("\n=== FALLBACK vs PRIMARY COVERAGE COMPARISON ===\n")
    
    primary_frames = by_source.get("primary", [])
    both_primary = 0
    n_primary = 0
    if primary_frames:
        n_primary = len(primary_frames)
        both_primary = sum(1 for r in primary_frames 
                          if r.get("lower_top_valid") == "True" and r.get("lower_bottom_valid") == "True")
        print(f"PRIMARY (control): {both_primary}/{n_primary} ({100.0*both_primary/n_primary:.1f}%) both measurable")
    
    fallback_combined = []
    for src in ["physical_p06", "physical_p07", "physical_pair"]:
        if src in by_source:
            fallback_combined.extend(by_source[src])
    
    if fallback_combined and n_primary > 0:
        n_fallback = len(fallback_combined)
        both_fallback = sum(1 for r in fallback_combined 
                           if r.get("lower_top_valid") == "True" and r.get("lower_bottom_valid") == "True")
        print(f"FALLBACK combined: {both_fallback}/{n_fallback} ({100.0*both_fallback/n_fallback:.1f}%) both measurable")
        if both_primary > 0:
            coverage_ratio = (1 - both_fallback/n_fallback) / (1 - both_primary/n_primary)
            print(f"Coverage reduction factor: {coverage_ratio:.1f}x worse")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--diagnostics-csv", required=True)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    
    generate_summary_tables(Path(args.diagnostics_csv), Path(args.output_dir))


if __name__ == "__main__":
    main()
