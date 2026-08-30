#!/usr/bin/env python3
"""P18: evaluate/refine the trusted detector's rigid-pair Y register.

Research only. P15 lower-top measurements are evaluation truth and are never
used by the estimator. The alternative holds X and rigid geometry fixed and
maximizes the frozen P07 pair evidence over a fine one-dimensional Y search.
"""
from __future__ import annotations

import argparse
import csv
import json
import tempfile
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from grokcam.config import load_calibration
from grokcam.physical_sprocket import FROZEN_CONFIG, _line_strength, _pair_candidate
from grokcam.raw_development import DarktableMatchedDeveloper

ROOT = Path(__file__).resolve().parents[1]
KNOWN = {2003, 2082, 2093, 2097, 2144, 2240, 2242, 2161, 2162, 2146, 2147}
SOURCE_LABELS = {
    "primary": "Primary", "physical_pair": "physical-pair",
    "physical_p06": "P06", "physical_p07": "P07",
}


def metrics(errors):
    values = np.asarray(list(errors), dtype=float)
    absolute = np.abs(values)
    center = float(np.median(values))
    return {
        "count": int(len(values)), "median_bias_px": center,
        "mad_px": float(np.median(np.abs(values - center))),
        "median_absolute_error_px": float(np.median(absolute)),
        "p95_absolute_error_px": float(np.percentile(absolute, 95)),
        "max_absolute_error_px": float(np.max(absolute)),
        "over_2_px": int(np.sum(absolute > 2)),
        "over_3_px": int(np.sum(absolute > 3)),
        "over_5_px": int(np.sum(absolute > 5)),
    }


def evidence_refined_anchor_y(image, anchor_x, anchor_y, radius, step):
    """Fine Y translation of the frozen pair using its existing evidence."""
    rgb = np.asarray(image.convert("RGB"))
    cfg = FROZEN_CONFIG
    h, w = rgb.shape[:2]
    hole_w, hole_h = cfg["hole_width"], cfg["hole_height"]
    xmin, xmax = cfg["sprocket_x_domain"]
    ymin, ymax = cfg["upper_y_domain"]
    x0 = max(0, int(xmin-hole_w/2-40)); x1 = min(w, int(xmax+hole_w/2+40))
    y0 = max(0, int(ymin-hole_h/2-40)); y1 = min(h, int(ymax+cfg["pitch"]+hole_h/2+40))
    gray = cv2.cvtColor(rgb[y0:y1, x0:x1], cv2.COLOR_RGB2GRAY).astype(np.float32)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    sx0 = cv2.Sobel(blur, cv2.CV_32F, 1, 0, ksize=3)
    sy0 = cv2.Sobel(blur, cv2.CV_32F, 0, 1, ksize=3)
    norm = max(float(np.percentile(cv2.magnitude(sx0, sy0), 92)), 12)
    sx, sy = np.clip(sx0/norm, -1, 1), np.clip(sy0/norm, -1, 1)
    upper_x = anchor_x + 17.125 - cfg["lower_minus_upper_x"]/2
    upper_y = anchor_y - cfg["pitch"]/2
    candidates = []
    for delta in np.arange(-radius, radius + step/2, step):
        candidate = _pair_candidate(gray, sx, sy, upper_x-x0, upper_y+delta-y0, cfg)
        uy = upper_y + delta - y0
        ly = uy + cfg["pitch"]
        ux = upper_x - x0
        lx = ux + cfg["lower_minus_upper_x"]
        # Only the four already-modelled horizontal boundaries carry Y
        # translation information. Keep their frozen signed line response.
        y_score = sum(_line_strength(sx, sy, cx, cy, hole_w, hole_h, edge)[0]
                      for cx, cy in ((ux, uy), (lx, ly))
                      for edge in ("top_edge", "bottom_edge"))
        candidates.append((y_score, -abs(float(delta)), float(delta), candidate["raw_score"]))
    score, _, delta, pair_score = max(candidates)
    return anchor_y + delta, delta, score, pair_score


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--p15", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--radius", type=float, default=12.0)
    parser.add_argument("--step", type=float, default=0.25)
    args = parser.parse_args()

    truth = {int(r["frame"]): r for r in csv.DictReader(args.p15.open())
             if r["lower_top_valid"] == "True"}
    manifest = json.loads(args.manifest.read_text())
    records = {int(r["frame"]): r for s in manifest["segments"] for r in s["frame_records"]}
    developer = DarktableMatchedDeveloper(load_calibration().match.report)
    output = args.output_dir; output.mkdir(parents=True, exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory(prefix="p18_", dir=ROOT/"work") as temp:
        tif = Path(temp)/"developed.tif"
        for index, frame in enumerate(sorted(truth), 1):
            record, p15 = records[frame], truth[frame]
            developer.develop(args.raw_dir/f"frame_{frame:06d}.dng", tif)
            with Image.open(tif) as image:
                refined_y, delta, score, pair_score = evidence_refined_anchor_y(
                    image, float(record["anchor_x"]), float(record["anchor_y"]),
                    args.radius, args.step)
            rows.append({
                "frame": frame, "source": SOURCE_LABELS[record["final_registration_source"]],
                "trusted_anchor_y": float(record["anchor_y"]),
                "refined_anchor_y": refined_y, "refinement_delta_y": delta,
                "refined_y_evidence_score": score, "refined_pair_evidence_score": pair_score,
                "true_registration_y": float(p15["lower_top_y"]),
            })
            if index == 1 or index % 25 == 0 or index == len(truth):
                print(f"P18 {index}/{len(truth)}", flush=True)

    # Fixed offset calibration is trained on even frames; odd frames are held out.
    train = [r for r in rows if r["frame"] % 2 == 0]
    held = [r for r in rows if r["frame"] % 2 == 1]
    offsets = {}
    for name, field in (("existing", "trusted_anchor_y"), ("refined", "refined_anchor_y")):
        offset = float(np.median([r["true_registration_y"]-r[field] for r in train]))
        offsets[name] = offset
        for r in rows:
            r[f"{name}_error_px"] = r[field] + offset - r["true_registration_y"]

    fields = list(rows[0])
    with (output/"measurements.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    report = {"scope": {"valid": len(rows), "sources": dict(Counter(r["source"] for r in rows))},
              "estimator": {"description": "fixed-X fine 1-D rigid-pair Y translation maximizing the four frozen P07 horizontal-edge responses",
                            "radius_px": args.radius, "step_px": args.step, "uses_p15_as_input": False},
              "split": {"calibration": "even frame numbers", "held_out": "odd frame numbers",
                        "calibration_count": len(train), "held_out_count": len(held)}, "results": {}}
    for name in ("existing", "refined"):
        key = f"{name}_error_px"
        report["results"][name] = {
            "calibrated_offset_px": offsets[name],
            "overall": metrics(r[key] for r in rows),
            "calibration": metrics(r[key] for r in train),
            "held_out": metrics(r[key] for r in held),
            "by_source": {source: metrics(r[key] for r in rows if r["source"] == source)
                          for source in ("Primary", "physical-pair", "P06", "P07")},
        }
    report["known_and_controls"] = {str(r["frame"]): r for r in rows if r["frame"] in KNOWN}
    (output/"summary.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
