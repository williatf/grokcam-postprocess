#!/usr/bin/env python3
"""P12: Prepare source-transition outlier analysis."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def load_transitions(jsonl_path: Path) -> list[dict]:
    """Load transitions from JSONL."""
    transitions = []
    with jsonl_path.open() as f:
        for line in f:
            if line.strip():
                transitions.append(json.loads(line))
    return transitions


def prepare_analysis(transitions: list[dict], output_dir: Path) -> None:
    """Prepare outlier and control selection."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Sort by absolute delta_difference
    sorted_trans = sorted(
        transitions,
        key=lambda t: abs(t["delta_difference"]),
        reverse=True
    )
    
    print("=== TRANSITION RANKING BY ABS(DELTA_DIFFERENCE) ===\n")
    for i, t in enumerate(sorted_trans[:15]):
        print(
            f"{i+1:2d}. Frames {t['frame_a']:4d}-{t['frame_b']:4d} "
            f"({t['source_a']} → {t['source_b']}): "
            f"abs_diff = {abs(t['delta_difference']):.2f} px "
            f"(anchor={t['trusted_anchor_delta']:+.2f}, "
            f"edge={t['lower_top_delta']:+.2f})"
        )
    
    # Select 10 largest outliers
    outliers = sorted_trans[:10]
    
    # Select control set: small differences
    small_diff = [t for t in sorted_trans if abs(t["delta_difference"]) < 1.0][:6]
    
    print(f"\n=== SELECTED FOR INSPECTION ===\n")
    print(f"Largest outliers (n={len(outliers)}):")
    for t in outliers:
        print(f"  {t['frame_a']}-{t['frame_b']}: {abs(t['delta_difference']):.2f} px")
    
    print(f"\nControl set: small difference (n={len(small_diff)}):")
    for t in small_diff:
        print(f"  {t['frame_a']}-{t['frame_b']}: {abs(t['delta_difference']):.2f} px")
    
    # Prepare inspection manifest
    inspect_set = {
        "outliers": outliers,
        "control": small_diff,
        "all_transitions": sorted_trans,
    }
    
    manifest_path = output_dir / "inspect_manifest.json"
    with manifest_path.open("w") as f:
        json.dump(inspect_set, f, indent=2)
    
    print(f"\nManifest saved to {manifest_path}")
    
    # Save frame list to inspect
    frames_to_inspect = set()
    for t in outliers + small_diff:
        frames_to_inspect.add(t["frame_a"])
        frames_to_inspect.add(t["frame_b"])
    
    frames_sorted = sorted(frames_to_inspect)
    print(f"\nUnique frames to inspect: {len(frames_sorted)}")
    print(f"Range: {min(frames_sorted)}-{max(frames_sorted)}")
    
    # Save frame list
    frame_list_path = output_dir / "frames_to_inspect.txt"
    with frame_list_path.open("w") as f:
        for frame in frames_sorted:
            f.write(f"{frame}\n")
    
    print(f"Frame list saved to {frame_list_path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--transitions-jsonl", required=True)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    
    transitions = load_transitions(Path(args.transitions_jsonl))
    print(f"Loaded {len(transitions)} transitions\n")
    
    prepare_analysis(transitions, Path(args.output_dir))


if __name__ == "__main__":
    main()
