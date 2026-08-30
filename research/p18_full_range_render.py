#!/usr/bin/env python3
"""Run the frozen P18 register on every frame and render a continuous movie."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grokcam.config import load_calibration
from grokcam.encoding import encode_segment, file_sha256, verify_video
from grokcam.image_processing import registered_frame
from grokcam.models import CropGeometry
from grokcam.normalization import normalize_frames
from grokcam.raw_development import DarktableMatchedDeveloper
from research.p18_sprocket_detector_register_poc import evidence_refined_anchor_y
ANCHOR_TO_LOWER_TOP_PX = 260.53905176455373
LOWER_TOP_TO_CROP_TOP_PX = -673.5297914597816
CROP_TOP_FROM_REFINED_ANCHOR_PX = ANCHOR_TO_LOWER_TOP_PX + LOWER_TOP_TO_CROP_TOP_PX


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--p15", type=Path, required=True)
    p.add_argument("--raw-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--first", type=int, default=2000)
    p.add_argument("--last", type=int, default=2350)
    p.add_argument("--fps", type=int, default=16)
    p.add_argument("--ffmpeg", type=Path, default=Path("/usr/bin/ffmpeg"))
    p.add_argument("--ffprobe", type=Path, default=Path("/usr/bin/ffprobe"))
    args = p.parse_args()

    manifest = json.loads(args.manifest.read_text())
    records = sorted((r for s in manifest["segments"] for r in s["frame_records"]
                      if args.first <= int(r["frame"]) <= args.last), key=lambda r: int(r["frame"]))
    expected = list(range(args.first, args.last + 1))
    if [int(r["frame"]) for r in records] != expected:
        raise RuntimeError("Manifest does not contain the exact continuous requested range")
    p15_valid = {int(r["frame"]): float(r["lower_top_y"])
                 for r in csv.DictReader(args.p15.open()) if r["lower_top_valid"] == "True"}

    output = args.output_dir
    staging = output/"staging"
    registered = staging/"registered"
    normalized = staging/"normalized"
    registered.mkdir(parents=True, exist_ok=True)
    calibration = load_calibration()
    developer = DarktableMatchedDeveloper(calibration.match.report)
    developed = staging/"developed.tif"
    rows = []
    for index, record in enumerate(records, 1):
        frame = int(record["frame"])
        developer.develop(args.raw_dir/f"frame_{frame:06d}.dng", developed)
        with Image.open(developed) as image:
            refined_y, delta, y_score, pair_score = evidence_refined_anchor_y(
                image, float(record["anchor_x"]), float(record["anchor_y"]), 12.0, 0.25)
            crop_top = refined_y + CROP_TOP_FROM_REFINED_ANCHOR_PX
            crop = CropGeometry(float(record["crop_left"]), crop_top,
                                calibration.crop.width, calibration.crop.height)
            registered_frame(image, crop, calibration.contrast).save(
                registered/f"frame_{frame:06d}.jpg", quality=95, subsampling=0)
        truth = p15_valid.get(frame)
        rows.append({
            "frame": frame, "source": record["final_registration_source"],
            "p15_valid": truth is not None, "p15_lower_top_y": truth,
            "trusted_anchor_x": float(record["anchor_x"]),
            "trusted_anchor_y": float(record["anchor_y"]),
            "refined_anchor_y": refined_y, "refinement_delta_y": delta,
            "refined_y_evidence_score": y_score,
            "refined_pair_evidence_score": pair_score,
            "crop_left": float(record["crop_left"]), "crop_top": crop_top,
            "p15_error_px": None if truth is None else refined_y + ANCHOR_TO_LOWER_TOP_PX - truth,
        })
        developed.unlink(missing_ok=True)
        if index == 1 or index % 25 == 0 or index == len(records):
            print(f"P18 full range {index}/{len(records)}", flush=True)

    normalization, target = normalize_frames(
        sorted(registered.glob("frame_*.jpg")), normalized, None)
    movie = output/f"Reel_46335_{args.first:06d}_{args.last:06d}_p18_register_{args.fps}fps.mp4"
    temporary = movie.with_suffix(".tmp.mp4")
    encode_segment(args.ffmpeg, normalized, temporary, args.first, len(records), args.fps)
    verification = verify_video(args.ffmpeg, args.ffprobe, temporary, len(records))
    temporary.replace(movie)

    with (output/"measurements.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    missing = [r for r in rows if not r["p15_valid"]]
    summary = {
        "scope": {"first": args.first, "last": args.last, "frames": len(rows),
                  "p15_valid": len(rows)-len(missing), "p15_missing": len(missing)},
        "frozen_p18": {"search_radius_px": 12.0, "search_step_px": 0.25,
                       "score": "sum of four frozen P07 signed horizontal-edge responses",
                       "anchor_to_lower_top_px": ANCHOR_TO_LOWER_TOP_PX,
                       "lower_top_to_crop_top_px": LOWER_TOP_TO_CROP_TOP_PX,
                       "crop_top_from_refined_anchor_px": CROP_TOP_FROM_REFINED_ANCHOR_PX,
                       "p18_implementation": str((ROOT/"research/p18_sprocket_detector_register_poc.py").resolve()),
                       "p18_implementation_sha256": sha256(ROOT/"research/p18_sprocket_detector_register_poc.py")},
        "provenance": {"manifest": str(args.manifest.resolve()), "manifest_sha256": sha256(args.manifest),
                       "p15": str(args.p15.resolve()), "p15_sha256": sha256(args.p15),
                       "raw_dir": str(args.raw_dir.resolve()), "source_policy": "read_only"},
        "p15_missing_frames": [r["frame"] for r in missing],
        "p15_missing_refinement_delta": {
            "min": min(r["refinement_delta_y"] for r in missing),
            "median": sorted(r["refinement_delta_y"] for r in missing)[len(missing)//2],
            "max": max(r["refinement_delta_y"] for r in missing),
            "at_search_boundary": sum(abs(r["refinement_delta_y"]) == 12.0 for r in missing)},
        "normalization_target_luma": target,
        "movie": {"path": str(movie.resolve()), "bytes": movie.stat().st_size,
                  "sha256": file_sha256(movie), "verification": verification},
    }
    (output/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    shutil.rmtree(staging)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
