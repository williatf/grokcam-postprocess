#!/usr/bin/env python3
"""Analyze an existing vertical-stabilization POC run and simulate a safety cap."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from grokcam.encoding import encode_segment, file_sha256, verify_video
from research.grokcam_vertical_stabilization_poc import residual_sprocket_y, translate_y


def distribution(values: np.ndarray) -> dict:
    absolute = np.abs(values)
    return {
        "mean_absolute": float(np.mean(absolute)),
        "median_absolute": float(np.median(absolute)),
        "rms": float(np.sqrt(np.mean(values ** 2))),
        "p95_absolute": float(np.percentile(absolute, 95)),
        "p99_absolute": float(np.percentile(absolute, 99)),
        "maximum_absolute": float(np.max(absolute)),
    }


def movement(values: np.ndarray) -> dict:
    absolute = np.abs(np.diff(values))
    return {
        "mean_absolute": float(np.mean(absolute)),
        "p95_absolute": float(np.percentile(absolute, 95)),
        "p99_absolute": float(np.percentile(absolute, 99)),
        "maximum_absolute": float(np.max(absolute)),
    }


def correction_counts(corrections: np.ndarray) -> dict:
    absolute = np.abs(corrections)
    total = len(absolute)
    result = {}
    for limit in (0.25, 0.5, 1, 2, 3, 4):
        count = int(np.sum(absolute <= limit))
        result[f"at_or_below_{limit:g}_px"] = {"count": count, "percent": 100 * count / total}
    for limit in (4, 5, 6):
        count = int(np.sum(absolute > limit))
        result[f"above_{limit:g}_px"] = {"count": count, "percent": 100 * count / total}
    return result


def encode(ffmpeg: Path, ffprobe: Path, frames: Path, destination: Path,
           first: int, count: int, fps: int) -> dict:
    temporary = destination.with_suffix(".tmp.mp4")
    encode_segment(ffmpeg, frames, temporary, first, count, fps)
    verification = verify_video(ffmpeg, ffprobe, temporary, count)
    os.replace(temporary, destination)
    return {"path": str(destination), "sha256": file_sha256(destination), "verification": verification}


def labeled_crop(path: Path, label: str, guide_y: float) -> Image.Image:
    with Image.open(path) as source:
        crop = source.crop((0, 120, 180, 310)).resize((360, 380), Image.Resampling.BICUBIC)
    canvas = Image.new("RGB", (360, 410), "black")
    canvas.paste(crop, (0, 30))
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 8), label, fill="white")
    y = int(round((guide_y - 120) * 2 + 30))
    draw.line((0, y, 359, y), fill=(0, 255, 255), width=1)
    return canvas


def contact_sheet(run: Path, frame: int, first: int, last: int,
                  correction: float, confidence: float, guide_y: float) -> Path:
    frames = list(range(max(first, frame - 2), min(last, frame + 2) + 1))
    images = [labeled_crop(run / "before_frames" / f"frame_{number:06d}.jpg",
                           f"before {number}", guide_y) for number in frames]
    sheet = Image.new("RGB", (360 * len(images), 450), (24, 24, 24))
    for index, image in enumerate(images):
        sheet.paste(image, (index * 360, 40))
    ImageDraw.Draw(sheet).text(
        (8, 10), f"frame {frame}: correction {correction:+.3f} px; confidence {confidence:.3f}", fill="white")
    destination = run / "large_correction_contact_sheets" / f"frame_{frame:06d}.jpg"
    destination.parent.mkdir(exist_ok=True)
    sheet.save(destination, quality=95, subsampling=0)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--cap", type=float, default=4.0)
    parser.add_argument("--ffmpeg", type=Path, default=Path("/usr/bin/ffmpeg"))
    parser.add_argument("--ffprobe", type=Path, default=Path("/usr/bin/ffprobe"))
    args = parser.parse_args()
    run = args.run_dir.resolve()
    records = json.loads((run / "diagnostics.json").read_text(encoding="utf-8"))
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    first, last, fps = summary["range"]["first"], summary["range"]["last"], summary["range"]["fps"]
    reference = float(summary["reference_y"])
    cap_frames = run / f"after_cap{args.cap:g}_frames"
    if cap_frames.exists() and any(cap_frames.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty cap frame directory: {cap_frames}")
    cap_frames.mkdir(parents=True, exist_ok=True)

    before = np.array([float(record["raw_residual_error_y"]) for record in records])
    unlimited = np.array([float(record["applied_correction_y"]) for record in records])
    cap_corrections = np.clip(unlimited, -args.cap, args.cap)
    cap_measurements = []
    for index, (record, correction) in enumerate(zip(records, cap_corrections), 1):
        frame = int(record["frame"])
        with Image.open(run / "before_frames" / f"frame_{frame:06d}.jpg") as image:
            corrected = translate_y(image, float(correction))
            measurement = residual_sprocket_y(corrected)
            corrected.save(cap_frames / f"frame_{frame:06d}.jpg", quality=95, subsampling=0)
        cap_measurements.append(measurement)
        record["post_correction_residual_y"] = (
            None if record["stabilized_sprocket_y"] is None
            else float(record["stabilized_sprocket_y"]) - reference
        )
        record[f"cap{args.cap:g}_correction_y"] = float(correction)
        record[f"cap{args.cap:g}_stabilized_sprocket_y"] = measurement.y
        record[f"cap{args.cap:g}_confidence"] = measurement.confidence
        record[f"cap{args.cap:g}_post_correction_residual_y"] = (
            None if measurement.y is None else measurement.y - reference
        )
        if index == 1 or index % 100 == 0 or index == len(records):
            print(f"Cap frames {index}/{len(records)}", flush=True)

    diagnostics_json = run / "validation_diagnostics.json"
    diagnostics_json.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    with (run / "validation_diagnostics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)

    cap_after = np.array([
        np.nan if measurement.y is None else measurement.y - reference
        for measurement in cap_measurements
    ])
    if not np.isfinite(cap_after).all():
        good = np.isfinite(cap_after)
        positions = np.arange(len(cap_after))
        cap_after = np.interp(positions, positions[good], cap_after[good])
    unlimited_after = np.array([
        float(record["post_correction_residual_y"])
        if record["post_correction_residual_y"] is not None else np.nan for record in records
    ])
    if not np.isfinite(unlimited_after).all():
        good = np.isfinite(unlimited_after)
        positions = np.arange(len(unlimited_after))
        unlimited_after = np.interp(positions, positions[good], unlimited_after[good])

    confidence = np.array([float(record["residual_confidence"]) for record in records])
    usable = np.array([bool(record["residual_usable"]) for record in records])
    large_events = []
    for record in records:
        correction = float(record["applied_correction_y"])
        if abs(correction) > 3:
            sheet = contact_sheet(run, int(record["frame"]), first, last, correction,
                                  float(record["residual_confidence"]), reference)
            large_events.append({
                "frame": int(record["frame"]), "correction_y": correction,
                "confidence": float(record["residual_confidence"]),
                "primary_accepted": bool(record["primary_accepted"]),
                "unlimited_post_residual_y": record["post_correction_residual_y"],
                "cap_post_residual_y": record[f"cap{args.cap:g}_post_correction_residual_y"],
                "contact_sheet": str(sheet), "classification": "pending visual inspection",
            })

    video = encode(args.ffmpeg, args.ffprobe, cap_frames, run / f"after_cap{args.cap:g}.mp4",
                   first, len(records), fps)
    clipped = np.abs(unlimited) > args.cap
    report = {
        "range": summary["range"], "reference_y": reference,
        "before_residual": distribution(before),
        "unlimited_after_residual": distribution(unlimited_after),
        f"cap{args.cap:g}_after_residual": distribution(cap_after),
        "before_frame_to_frame_movement": movement(before + reference),
        "unlimited_after_frame_to_frame_movement": movement(unlimited_after + reference),
        f"cap{args.cap:g}_after_frame_to_frame_movement": movement(cap_after + reference),
        "correction_magnitude_distribution": correction_counts(unlimited),
        "detector_reliability": {
            "total_frames": len(records),
            "successful_residual_detections": int(np.sum([record["residual_sprocket_y"] is not None for record in records])),
            "failed_residual_detections": int(np.sum([record["residual_sprocket_y"] is None for record in records])),
            "usable_residual_detections": int(np.sum(usable)),
            "unusable_measurements": int(np.sum(~usable)),
            "minimum_confidence_all": float(np.min(confidence)),
            "minimum_confidence_successful": float(np.min(confidence[confidence > 0])),
            "median_confidence": float(np.median(confidence)),
            "p05_confidence": float(np.percentile(confidence, 5)),
            "below_0_9": int(np.sum(confidence < 0.9)),
            "below_0_8": int(np.sum(confidence < 0.8)),
            "below_0_7": int(np.sum(confidence < 0.7)),
            "correlation_confidence_vs_absolute_correction": float(np.corrcoef(confidence, np.abs(unlimited))[0, 1]),
            "correlation_confidence_vs_absolute_post_residual": float(np.corrcoef(confidence, np.abs(unlimited_after))[0, 1]),
        },
        f"cap{args.cap:g}_comparison": {
            "frames_affected": int(np.sum(clipped)),
            "percent_affected": float(100 * np.mean(clipped)),
            "largest_unlimited_correction": float(np.max(np.abs(unlimited))),
            "largest_amount_clipped": float(np.max(np.abs(unlimited) - np.abs(cap_corrections))),
            "video": video,
        },
        "large_correction_events": large_events,
    }
    (run / "validation_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
