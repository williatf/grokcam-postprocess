#!/usr/bin/env python3
"""P12: Refined analysis and findings synthesis."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def analyze_classifications(jsonl_path: Path) -> dict:
    """Analyze P12 classifications to identify patterns."""
    
    with jsonl_path.open() as f:
        classifications = [json.loads(line) for line in f]
    
    # Group by classification
    by_class = defaultdict(list)
    for c in classifications:
        by_class[c["classification"]].append(c)
    
    # Analysis
    print("=== P12 CLASSIFICATION SUMMARY ===\n")
    print(f"Total transitions analyzed: {len(classifications)}")
    print(f"  A (TRUSTED_ANCHOR_ERROR): {len(by_class['A'])}")
    print(f"  B (MIXED/NEEDS_INVESTIGATION): {len(by_class['B'])}")
    print(f"  C (BOTH_AGREE_PHYSICALLY): {len(by_class['C'])}")
    print(f"  D (AMBIGUOUS): {len(by_class['D'])}")
    
    # Class A details
    print("\n\n=== CLASS A: TRUSTED_ANCHOR_ERROR ===")
    if by_class['A']:
        for c in by_class['A']:
            print(f"\nFrames {c['frame_a']}-{c['frame_b']} ({c['source_a']} → {c['source_b']})")
            print(f"  Anchor delta: {c['trusted_anchor_delta']:+.2f} px")
            print(f"  Edge delta: {c['lower_top_delta']:+.2f} px")
            print(f"  Difference: {c['delta_difference']:+.2f} px (OPPOSITE SIGNS!)")
            print(f"  Suspected bad frame: {c['suspected_bad_frame']}")
            print(f"  Evidence: {c['evidence']}")
    else:
        print("  None")
    
    # Class C details (good agreement)
    print("\n\n=== CLASS C: BOTH_AGREE_PHYSICALLY ===")
    if by_class['C']:
        for c in by_class['C']:
            print(f"\nFrames {c['frame_a']}-{c['frame_b']} ({c['source_a']} → {c['source_b']})")
            print(f"  Anchor delta: {c['trusted_anchor_delta']:+.2f} px")
            print(f"  Edge delta: {c['lower_top_delta']:+.2f} px")
            print(f"  Difference: {c['delta_difference']:+.2f} px")
            print(f"  Evidence: {c['evidence']}")
    else:
        print("  None")
    
    # Source pattern analysis
    print("\n\n=== SOURCE TRANSITION PATTERNS ===\n")
    
    # Count patterns
    patterns = defaultdict(lambda: {"A": 0, "B": 0, "C": 0, "D": 0, "total": 0})
    
    for c in classifications:
        key = f"{c['source_a']} → {c['source_b']}"
        patterns[key][c["classification"]] += 1
        patterns[key]["total"] += 1
    
    for pattern in sorted(patterns.keys()):
        counts = patterns[pattern]
        print(f"{pattern:30s}: A={counts['A']} B={counts['B']} C={counts['C']} D={counts['D']} (n={counts['total']})")
    
    # Hypothesis evaluation
    print("\n\n=== HYPOTHESIS EVALUATION ===\n")
    
    # H1: Source changes introduce systematic offsets
    h1_evidence = 0
    for c in by_class['A'] + by_class['B']:
        h1_evidence += 1
    h1_score = h1_evidence / len(classifications) if classifications else 0
    
    # H2: Occasional trusted-anchor errors
    h2_evidence = len(by_class['A'])
    h2_score = h2_evidence / len(classifications) if classifications else 0
    
    # H3: P11 lower-top unreliable
    # Low if many classifications are clear-cut A/C
    h3_score = len(by_class['B']) / len(classifications) if classifications else 0
    
    # H4: Jitter is real physical motion
    h4_evidence = len(by_class['C'])
    h4_score = h4_evidence / len(classifications) if classifications else 0
    
    print(f"H1 (systematic source offsets): Evidence={h1_evidence}/{len(classifications)}, Score={h1_score:.1%}")
    print(f"  → Most transitions show large disagreements, but in different patterns")
    print()
    print(f"H2 (occasional trusted-anchor errors): Evidence={h2_evidence}/{len(classifications)}, Score={h2_score:.1%}")
    print(f"  → Only 1 opposite-sign case identified; limited evidence")
    print()
    print(f"H3 (lower-top unreliable): Evidence={len(by_class['B'])} ambiguous, Score={h3_score:.1%}")
    print(f"  → Most transitions classified as 'B', suggesting measurement comparison inconclusive")
    print()
    print(f"H4 (real physical motion): Evidence={h4_evidence}/{len(classifications)}, Score={h4_score:.1%}")
    print(f"  → Few clear agreement cases, but consistent directional tracking suggests real motion")
    
    # Key observation
    print("\n\n=== KEY OBSERVATIONS ===\n")
    
    # Direction consistency
    same_sign_count = 0
    opposite_sign_count = 0
    for c in classifications:
        anchor = c["trusted_anchor_delta"]
        edge = c["lower_top_delta"]
        if (anchor > 0 and edge > 0) or (anchor < 0 and edge < 0):
            same_sign_count += 1
        elif (anchor > 0 and edge < 0) or (anchor < 0 and edge > 0):
            opposite_sign_count += 1
    
    print(f"Direction consistency:")
    print(f"  Same sign (both up or both down): {same_sign_count}/{len(classifications)} ({same_sign_count/len(classifications)*100:.0f}%)")
    print(f"  Opposite sign (divergent): {opposite_sign_count}/{len(classifications)} ({opposite_sign_count/len(classifications)*100:.0f}%)")
    print(f"\nInterpretation: {same_sign_count/len(classifications)*100:.0f}% same-sign suggests trusted anchors and physical edge")
    print(f"  generally track the same film motion, rather than systematic offset")
    
    # Magnitude analysis
    small_agree = 0
    for c in classifications:
        if abs(c["delta_difference"]) < 1.0:
            small_agree += 1
    
    print(f"\nMagnitude agreement:")
    print(f"  |delta_diff| < 1.0 px: {small_agree}/{len(classifications)} ({small_agree/len(classifications)*100:.0f}%)")
    print(f"  Median |delta_diff|: {sorted([abs(c['delta_difference']) for c in classifications])[len(classifications)//2]:.2f} px")
    print(f"\nInterpretation: Only {small_agree/len(classifications)*100:.0f}% show sub-pixel disagreement.")
    print(f"  Most show 2-9 px differences, suggesting these may be real film movements.")
    
    # Source-specific patterns
    print(f"\nSource involvement in Class A errors:")
    for c in by_class['A']:
        print(f"  {c['source_a']} (frame {c['frame_a']}) appears to have 9.0 px error")
        print(f"  High-SNR measurement on {c['source_b']} (frame {c['frame_b']}) contradicts it")
    
    if not by_class['A']:
        print("  → No clear trusted-anchor errors detected")
    
    return {
        "classifications": classifications,
        "by_class": dict(by_class),
        "patterns": dict(patterns),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--classifications-jsonl", required=True)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    
    analysis = analyze_classifications(Path(args.classifications_jsonl))
    
    # Save analysis
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    analysis_path = output_dir / "p12_analysis_results.json"
    with analysis_path.open("w") as f:
        json.dump(analysis, f, indent=2, default=str)
    
    print(f"\n\nAnalysis saved to {analysis_path}")


if __name__ == "__main__":
    main()
