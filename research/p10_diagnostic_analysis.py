#!/usr/bin/env python3
"""P10: Analyze diagnostic data on fallback-frame failures."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np


def analyze_diagnostics(csv_path: Path, output_dir: Path) -> None:
    """Analyze diagnostic data by registration source and failure reason."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    rows = []
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    # Group by source
    by_source = defaultdict(list)
    for row in rows:
        by_source[row["source"]].append(row)
    
    # Detailed analysis
    print("\n=== P10 DIAGNOSTIC ANALYSIS ===\n")
    
    for source in sorted(by_source.keys()):
        frames = by_source[source]
        print(f"\n{source.upper()} ({len(frames)} frames)")
        print("-" * 70)
        
        # Analyze lower_top
        print("\nLOWER_TOP:")
        top_valid = [r for r in frames if r.get("lower_top_valid") == "True"]
        print(f"  Measurable: {len(top_valid)}/{len(frames)} ({100.0*len(top_valid)/len(frames):.1f}%)")
        
        if top_valid:
            # Analyze when top is measurable
            peaks = [float(r["lower_top_peak"]) for r in top_valid if r.get("lower_top_peak")]
            prominences = [float(r["lower_top_prominence"]) for r in top_valid if r.get("lower_top_prominence")]
            snrs = [float(r["lower_top_snr"]) for r in top_valid if r.get("lower_top_snr")]
            print(f"    Peak: median={np.median(peaks):.1f}, mean={np.mean(peaks):.1f}")
            print(f"    Prominence: median={np.median(prominences):.1f}, mean={np.mean(prominences):.1f}")
            print(f"    SNR: median={np.median(snrs):.2f}, mean={np.mean(snrs):.2f}")
        
        # Analyze why top fails
        top_failed = [r for r in frames if r.get("lower_top_valid") != "True"]
        if top_failed:
            print(f"  Failures: {len(top_failed)}")
            
            # Analyze diagnostic reasons
            at_boundary = sum(1 for r in top_failed if r.get("lower_top_diag_peak_at_boundary") == "True")
            print(f"    Peak at boundary: {at_boundary}/{len(top_failed)}")
            
            weak_prominences = [float(r["lower_top_prominence"]) for r in top_failed 
                              if r.get("lower_top_prominence") and float(r["lower_top_prominence"]) < 8]
            print(f"    Weak prominence (<8): {len(weak_prominences)}/{len(top_failed)}")
            if weak_prominences:
                print(f"      Median: {np.median(weak_prominences):.1f}, Max: {np.max(weak_prominences):.1f}")
            
            weak_snrs = [float(r["lower_top_snr"]) for r in top_failed 
                        if r.get("lower_top_snr") and float(r["lower_top_snr"]) < 2.5]
            print(f"    Weak SNR (<2.5): {len(weak_snrs)}/{len(top_failed)}")
            if weak_snrs:
                print(f"      Median: {np.median(weak_snrs):.2f}, Max: {np.max(weak_snrs):.2f}")
            
            weak_peaks = [float(r["lower_top_peak"]) for r in top_failed 
                         if r.get("lower_top_peak") and float(r["lower_top_peak"]) < 20]
            print(f"    Weak peak (<20): {len(weak_peaks)}/{len(top_failed)}")
            if weak_peaks:
                print(f"      Median: {np.median(weak_peaks):.1f}, Max: {np.max(weak_peaks):.1f}")
        
        # Analyze lower_bottom  
        print("\nLOWER_BOTTOM:")
        bottom_valid = [r for r in frames if r.get("lower_bottom_valid") == "True"]
        print(f"  Measurable: {len(bottom_valid)}/{len(frames)} ({100.0*len(bottom_valid)/len(frames):.1f}%)")
        
        if bottom_valid:
            peaks = [float(r["lower_bottom_peak"]) for r in bottom_valid if r.get("lower_bottom_peak")]
            prominences = [float(r["lower_bottom_prominence"]) for r in bottom_valid if r.get("lower_bottom_prominence")]
            snrs = [float(r["lower_bottom_snr"]) for r in bottom_valid if r.get("lower_bottom_snr")]
            print(f"    Peak: median={np.median(peaks):.1f}, mean={np.mean(peaks):.1f}")
            print(f"    Prominence: median={np.median(prominences):.1f}, mean={np.mean(prominences):.1f}")
            print(f"    SNR: median={np.median(snrs):.2f}, mean={np.mean(snrs):.2f}")
        
        bottom_failed = [r for r in frames if r.get("lower_bottom_valid") != "True"]
        if bottom_failed:
            print(f"  Failures: {len(bottom_failed)}")
            
            at_boundary = sum(1 for r in bottom_failed if r.get("lower_bottom_diag_peak_at_boundary") == "True")
            print(f"    Peak at boundary: {at_boundary}/{len(bottom_failed)}")
            
            weak_prominences = [float(r["lower_bottom_prominence"]) for r in bottom_failed 
                              if r.get("lower_bottom_prominence") and float(r["lower_bottom_prominence"]) < 8]
            print(f"    Weak prominence (<8): {len(weak_prominences)}/{len(bottom_failed)}")
            if weak_prominences:
                print(f"      Median: {np.median(weak_prominences):.1f}, Max: {np.max(weak_prominences):.1f}")
            
            weak_snrs = [float(r["lower_bottom_snr"]) for r in bottom_failed 
                        if r.get("lower_bottom_snr") and float(r["lower_bottom_snr"]) < 2.5]
            print(f"    Weak SNR (<2.5): {len(weak_snrs)}/{len(bottom_failed)}")
            if weak_snrs:
                print(f"      Median: {np.median(weak_snrs):.2f}, Max: {np.max(weak_snrs):.2f}")
            
            weak_peaks = [float(r["lower_bottom_peak"]) for r in bottom_failed 
                         if r.get("lower_bottom_peak") and float(r["lower_bottom_peak"]) < 20]
            print(f"    Weak peak (<20): {len(weak_peaks)}/{len(bottom_failed)}")
            if weak_peaks:
                print(f"      Median: {np.median(weak_peaks):.1f}, Max: {np.max(weak_peaks):.1f}")
        
        # Summary: both measurable
        both = [r for r in frames if r.get("lower_top_valid") == "True" and r.get("lower_bottom_valid") == "True"]
        print(f"\nBoth measurable: {len(both)}/{len(frames)}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--diagnostics-csv", required=True)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    
    analyze_diagnostics(Path(args.diagnostics_csv), Path(args.output_dir))


if __name__ == "__main__":
    main()
