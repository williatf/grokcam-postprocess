#!/usr/bin/env python3
"""Isolated capture-prior + production-evidence sprocket detector POC.

Capture coordinates only define search ROIs. Every returned hybrid anchor is
remeasured from the full-resolution developed TIFF and must pass production-like
brightness and pair-geometry gates.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import shutil
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grokcam.config import DetectorCalibration, load_calibration
from grokcam.raw_development import DarktableMatchedDeveloper
from grokcam.sprocket_detection import detect as production_detect


DEFAULT_OUTPUT = ROOT / "research/output/sprocket_xy/hybrid_capture_prior_poc"
REELS = {
    "Blue_Reel": {
        "project": Path("/mnt/GrokCam/projects/Blue_Reel"),
        "manifest": Path("/mnt/GrokCam/projects/Blue_Reel/outputs/production-v1/processing_manifest.json"),
    },
    "Reel_28486": {
        "project": Path("/mnt/GrokCam/projects/Reel_28486"),
        "manifest": Path("/mnt/GrokCam/projects/Reel_28486/output_stabilized/processing_manifest.json"),
    },
    "Reel_46335": {
        "project": Path("/mnt/GrokCam/projects/Reel_46335"),
        "manifest": Path("/mnt/GrokCam/projects/Reel_46335/output/processing_manifest.json"),
    },
}
SPECIAL = {
    "Blue_Reel": [3260, 3451, 3615, 3676, 3754, 3846, 3882],
    "Reel_28486": [3574],
    "Reel_46335": [1010, 1011, 1013],
}


@dataclass
class HoleMeasurement:
    cx: float
    cy: float
    width: float
    height: float
    bright_fraction: float
    prediction_distance: float


@dataclass
class SeededPair:
    cx: float
    cy: float
    score: float
    upper: HoleMeasurement
    lower: HoleMeasurement
    pitch: float
    x_disagreement: float
    threshold: float


def contiguous_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    padded = np.pad(mask.astype(np.int8), (1, 1))
    changes = np.diff(padded)
    return list(zip(np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)))


def load_capture(project: Path) -> dict[int, dict]:
    result: dict[int, dict] = {}
    for name in sorted(glob.glob(str(project / "debug/raw_capture_metadata_*.jsonl"))):
        with open(name, encoding="utf-8") as handle:
            for line in handle:
                item = json.loads(line)
                if "frame_number" not in item:
                    continue
                number = int(item["frame_number"])
                if number in result:
                    raise RuntimeError(f"duplicate capture metadata for frame {number}: {project}")
                result[number] = item
    return result


def load_manifest(path: Path) -> tuple[dict, dict[int, dict], list[tuple[int, int]]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    records: dict[int, dict] = {}
    segments = []
    for segment in manifest["segments"]:
        segments.append((int(segment["first"]), int(segment["last"])))
        for record in segment["frame_records"]:
            records[int(record["frame"])] = record
    return manifest, records, segments


def validate_correspondence(project: Path, capture: dict[int, dict], records: dict[int, dict]) -> list[Path]:
    dngs = sorted((project / "raw").glob("frame_*.dng"))
    dng_numbers = [int(path.stem.rsplit("_", 1)[1]) for path in dngs]
    if len(dng_numbers) != len(set(dng_numbers)):
        raise RuntimeError(f"duplicate DNG frame numbers: {project}")
    expected = set(dng_numbers)
    problems = {
        "capture_missing": sorted(expected - set(capture)),
        "capture_extra": sorted(set(capture) - expected),
        "manifest_missing": sorted(expected - set(records)),
        "manifest_extra": sorted(set(records) - expected),
    }
    if any(problems.values()):
        raise RuntimeError(f"one-to-one frame correspondence failed for {project}: {problems}")
    for path in dngs:
        number = int(path.stem.rsplit("_", 1)[1])
        saved = Path(capture[number].get("saved_frame_path", "")).name
        if saved and saved != path.name:
            raise RuntimeError(f"capture/DNG name mismatch at {number}: {saved} != {path.name}")
    return dngs


def actual_pair_prediction(item: dict) -> list[tuple[float, float, float, float]] | None:
    if item.get("raw_registration_mode") != "pair" or item.get("selected_source") != "pair_actual":
        return None
    sprockets = item.get("sprockets") or []
    if len(sprockets) < 2:
        return None
    pair = sorted(sprockets, key=lambda value: float(value[1]))[:2]
    return [(float(v[0]), float(v[1]), float(v[2]), float(v[3])) for v in pair]


def transform_boxes(item: dict) -> list[tuple[float, float, float, float]] | None:
    pair = actual_pair_prediction(item)
    if pair is None:
        return None
    preview_w, preview_h = float(item["preview_width"]), float(item["preview_height"])
    raw_w, raw_h = float(item["raw_width"]), float(item["raw_height"])
    sx, sy = raw_w / preview_w, raw_h / preview_h
    return [(x * sx, y * sy, w * sx, h * sy) for x, y, w, h in pair]


def measure_hole(bright: np.ndarray, prediction: tuple[float, float, float, float],
                 calibration: DetectorCalibration) -> HoleMeasurement | None:
    px, py, pw, ph = prediction
    height, width = bright.shape
    # Preserve the production detector's threshold-defined X landmark. Its crop
    # calibration was learned with the fixed X strip, so allowing a seeded ROI
    # to expose more of the hole would shift X even when both detections are
    # physically correct.
    x0 = max(calibration.search_x0, int(math.floor(px - 0.85 * pw)))
    x1 = min(calibration.search_x1, int(math.ceil(px + 0.85 * pw)))
    y0 = max(0, int(math.floor(py - 0.85 * ph)))
    y1 = min(height, int(math.ceil(py + 0.85 * ph)))
    roi = bright[y0:y1, x0:x1]
    if roi.size == 0:
        return None
    row_minimum = min(calibration.minimum_bright_row_pixels, max(40, int(round(pw * 0.32))))
    bands = [(a, b) for a, b in contiguous_runs(roi.sum(axis=1) > row_minimum)
             if calibration.band_height_min <= b - a <= calibration.band_height_max]
    candidates: list[HoleMeasurement] = []
    for top, bottom in bands:
        column_mask = roi[top:bottom].sum(axis=0) > (bottom - top) * calibration.column_fill
        column_runs = [(a, b) for a, b in contiguous_runs(column_mask)
                       if b - a >= calibration.minimum_bright_columns]
        for left, right in column_runs:
            cx = x0 + (left + right) / 2.0
            cy = y0 + (top + bottom) / 2.0
            measured_w, measured_h = float(right - left), float(bottom - top)
            if not (0.40 * calibration.expected_width <= measured_w <= 1.60 * calibration.expected_width):
                continue
            region = roi[top:bottom, left:right]
            fraction = float(np.mean(region))
            distance = math.hypot((cx - px) / max(pw, 1.0), (cy - py) / max(ph, 1.0))
            if distance > 0.75 or fraction < 0.45:
                continue
            candidates.append(HoleMeasurement(cx, cy, measured_w, measured_h, fraction, distance))
    if not candidates:
        return None
    return min(candidates, key=lambda value: value.prediction_distance + abs(value.width - calibration.expected_width) / 500.0)


def capture_seeded_detect(image: Image.Image, item: dict,
                          calibration: DetectorCalibration) -> SeededPair | None:
    boxes = transform_boxes(item)
    if boxes is None:
        return None
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    luminance = rgb[:, calibration.search_x0:calibration.search_x1].mean(axis=2)
    threshold = float(np.percentile(luminance, calibration.bright_percentile) * calibration.threshold_scale)
    full_luminance = rgb.mean(axis=2)
    bright = full_luminance > threshold
    holes = [measure_hole(bright, box, calibration) for box in boxes]
    if any(hole is None for hole in holes):
        return None
    upper, lower = sorted(holes, key=lambda value: value.cy)  # type: ignore[arg-type]
    pitch = lower.cy - upper.cy
    pitch_error = abs(pitch - calibration.expected_pitch)
    x_disagreement = abs(lower.cx - upper.cx)
    if pitch_error > calibration.pitch_tolerance or x_disagreement > 100.0:
        return None
    score = (pitch_error + 2.0 * x_disagreement
             + 0.2 * abs(statistics.mean([upper.width, lower.width]) - calibration.expected_width)
             + 20.0 * (upper.prediction_distance + lower.prediction_distance))
    return SeededPair(statistics.mean([upper.cx, lower.cx]),
                      statistics.mean([upper.cy, lower.cy]), score,
                      upper, lower, pitch, x_disagreement, threshold)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=float), fraction * 100.0))


def interpolate_hybrid(rows: list[dict], segments: list[tuple[int, int]]) -> None:
    by_frame = {int(row["frame"]): row for row in rows}
    for first, last in segments:
        segment = [by_frame[number] for number in range(first, last + 1)]
        good = np.array([row["hybrid_measured_x"] is not None for row in segment], dtype=bool)
        if not good.any():
            raise RuntimeError(f"no trustworthy hybrid measurements in segment {first}-{last}")
        positions = np.arange(len(segment))
        for axis in ("x", "y"):
            values = np.array([np.nan if row[f"hybrid_measured_{axis}"] is None
                               else row[f"hybrid_measured_{axis}"] for row in segment], dtype=float)
            filled = np.interp(positions, positions[good], values[good])
            for row, value in zip(segment, filled):
                row[f"hybrid_final_{axis}"] = float(value)
        first_good, last_good = positions[good][0], positions[good][-1]
        for index, row in enumerate(segment):
            if row["hybrid_measured_x"] is None:
                row["hybrid_source"] = "interpolated" if first_good < index < last_good else "fallback_hold"
            row["hybrid_interpolated"] = row["hybrid_measured_x"] is None


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def save_review(image: Image.Image, row: dict, path: Path) -> None:
    preview = image.convert("RGB").resize((760, 570), Image.Resampling.BILINEAR)
    draw = ImageDraw.Draw(preview)
    sx, sy = 760.0 / image.width, 570.0 / image.height
    for key, color, label in (("production_validated", "orange", "PROD"),
                              ("capture_prediction", "cyan", "CAP"),
                              ("hybrid_measured", "lime", "HYB")):
        x, y = row.get(f"{key}_x"), row.get(f"{key}_y")
        if x is None or y is None:
            continue
        xx, yy = float(x) * sx, float(y) * sy
        draw.line((xx - 9, yy, xx + 9, yy), fill=color, width=2)
        draw.line((xx, yy - 9, xx, yy + 9), fill=color, width=2)
        draw.text((xx + 11, yy - 7), label, fill=color)
    draw.rectangle((0, 0, 759, 34), fill=(0, 0, 0))
    draw.text((8, 8), f"frame {row['frame']}  {row.get('hybrid_source')}  "
              f"prod accepted={row.get('production_accepted')}", fill="white")
    path.parent.mkdir(parents=True, exist_ok=True)
    preview.save(path, quality=86, subsampling=0)


def process_reel(name: str, spec: dict, output: Path, work_root: Path,
                 jobs: int, batch_size: int, save_reviews: bool) -> tuple[list[dict], dict]:
    project, manifest_path = spec["project"], spec["manifest"]
    capture = load_capture(project)
    manifest, records, segments = load_manifest(manifest_path)
    dngs = validate_correspondence(project, capture, records)
    calibration = load_calibration()
    developer = DarktableMatchedDeveloper(calibration.match.report.expanduser().resolve())
    reel_output = output / name
    review_dir = reel_output / "review_frames"
    rows: list[dict] = []
    started = time.perf_counter()
    develop_seconds = detect_seconds = 0.0

    for batch_start in range(0, len(dngs), batch_size):
        batch = dngs[batch_start:batch_start + batch_size]
        temporary = Path(tempfile.mkdtemp(prefix=f"hybrid_{name}_", dir=work_root))
        try:
            before = time.perf_counter()
            with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
                futures = {}
                for dng in batch:
                    target = temporary / f"{dng.stem}.tif"
                    futures[pool.submit(developer.develop, dng, target)] = target
                for future in as_completed(futures):
                    future.result()
            develop_seconds += time.perf_counter() - before
            before = time.perf_counter()
            for dng in batch:
                frame = int(dng.stem.rsplit("_", 1)[1])
                cap, prod = capture[frame], records[frame]
                pair_boxes = transform_boxes(cap)
                capture_x = capture_y = None
                if pair_boxes:
                    capture_x = statistics.mean(value[0] for value in pair_boxes)
                    capture_y = statistics.mean(value[1] for value in pair_boxes)
                with Image.open(temporary / f"{dng.stem}.tif") as image:
                    try:
                        broad = production_detect(image, calibration.detector)
                    except ValueError:
                        broad = None
                    seeded = capture_seeded_detect(image, cap, calibration.detector)
                    seed_broad_agree = bool(
                        seeded is not None and broad is not None
                        and abs(seeded.cx - broad.cx) <= calibration.detector.horizontal_outlier_limit
                        and abs(seeded.cy - broad.cy) <= 20.0
                    )
                    seed_broad_disagreement = bool(seeded is not None and broad is not None and not seed_broad_agree)
                    if seed_broad_agree:
                        # The broad detector supplies the final production-defined
                        # landmark; capture-seeded evidence corroborates that it is
                        # the intended same-frame pair despite temporal motion.
                        measured_x, measured_y, source = broad.cx, broad.cy, "capture_seeded_broad_agreement"
                    elif seeded is not None and broad is None:
                        measured_x, measured_y, source = seeded.cx, seeded.cy, "capture_seeded_only"
                    elif bool(prod["accepted"]):
                        measured_x, measured_y, source = float(prod["anchor_x"]), float(prod["anchor_y"]), "broad_fallback"
                    else:
                        measured_x = measured_y = None
                        source = None
                    row = {
                        "reel": name, "frame": frame,
                        "capture_detection_method": cap.get("detection_method"),
                        "capture_registration_mode": cap.get("raw_registration_mode"),
                        "capture_selected_source": cap.get("selected_source"),
                        "capture_pair_seed_eligible": pair_boxes is not None,
                        "capture_prediction_x": capture_x, "capture_prediction_y": capture_y,
                        "production_detected": bool(prod["detected"]),
                        "production_accepted": bool(prod["accepted"]),
                        "production_validated_x": float(prod["anchor_x"]),
                        "production_validated_y": float(prod["anchor_y"]),
                        "broad_rerun_detected": broad is not None,
                        "broad_rerun_x": None if broad is None else broad.cx,
                        "broad_rerun_y": None if broad is None else broad.cy,
                        "hybrid_seed_evidence": seeded is not None,
                        "seed_broad_agree": seed_broad_agree,
                        "seed_broad_disagreement_anomaly": seed_broad_disagreement,
                        "hybrid_seed_score": None if seeded is None else seeded.score,
                        "hybrid_seed_pitch": None if seeded is None else seeded.pitch,
                        "hybrid_seed_x_disagreement": None if seeded is None else seeded.x_disagreement,
                        "hybrid_measured_x": measured_x, "hybrid_measured_y": measured_y,
                        "hybrid_source": source,
                        "capture_hybrid_dx": None if capture_x is None or measured_x is None else measured_x - capture_x,
                        "capture_hybrid_dy": None if capture_y is None or measured_y is None else measured_y - capture_y,
                        "broad_hybrid_dx": None if broad is None or measured_x is None else measured_x - broad.cx,
                        "broad_hybrid_dy": None if broad is None or measured_y is None else measured_y - broad.cy,
                        "new_same_frame_recovery": bool(not prod["accepted"] and measured_x is not None),
                        "special_frame": frame in SPECIAL.get(name, []),
                    }
                    rows.append(row)
                    if save_reviews:
                        save_review(image, row, review_dir / f"frame_{frame:06d}.jpg")
            detect_seconds += time.perf_counter() - before
        finally:
            shutil.rmtree(temporary)
        done = min(batch_start + len(batch), len(dngs))
        print(f"{name}: {done}/{len(dngs)}", flush=True)

    interpolate_hybrid(rows, segments)
    elapsed = time.perf_counter() - started
    recoveries = [row for row in rows if row["new_same_frame_recovery"]]
    remaining = [row for row in rows if row["hybrid_interpolated"]]
    cap_dx = [abs(float(row["capture_hybrid_dx"])) for row in rows if row["capture_hybrid_dx"] is not None]
    cap_dy = [abs(float(row["capture_hybrid_dy"])) for row in rows if row["capture_hybrid_dy"] is not None]
    broad_dx = [abs(float(row["broad_hybrid_dx"])) for row in rows if row["broad_hybrid_dx"] is not None]
    broad_dy = [abs(float(row["broad_hybrid_dy"])) for row in rows if row["broad_hybrid_dy"] is not None]
    summary = {
        "reel": name, "frames": len(rows), "correspondence_verified": True,
        "capture_pair_seed_eligible": sum(bool(r["capture_pair_seed_eligible"]) for r in rows),
        "production_accepted": sum(bool(r["production_accepted"]) for r in rows),
        "production_interpolated": sum(not bool(r["production_accepted"]) for r in rows),
        "hybrid_same_frame_measured": sum(not bool(r["hybrid_interpolated"]) for r in rows),
        "hybrid_interpolated": len(remaining),
        "capture_seeded_measurements": sum(str(r["hybrid_source"]).startswith("capture_seeded") for r in rows),
        "capture_seeded_recoveries": len(recoveries),
        "broad_fallback_measurements": sum(r["hybrid_source"] == "broad_fallback" for r in rows),
        "capture_hybrid_abs_dx_median": percentile(cap_dx, 0.5),
        "capture_hybrid_abs_dx_p95": percentile(cap_dx, 0.95),
        "capture_hybrid_abs_dy_median": percentile(cap_dy, 0.5),
        "capture_hybrid_abs_dy_p95": percentile(cap_dy, 0.95),
        "broad_hybrid_abs_dx_median": percentile(broad_dx, 0.5),
        "broad_hybrid_abs_dx_p95": percentile(broad_dx, 0.95),
        "broad_hybrid_abs_dy_median": percentile(broad_dy, 0.5),
        "broad_hybrid_abs_dy_p95": percentile(broad_dy, 0.95),
        "development_seconds": develop_seconds, "measurement_seconds": detect_seconds,
        "elapsed_seconds": elapsed, "measurement_ms_per_frame": 1000.0 * detect_seconds / len(rows),
        "special_frames": [{key: row.get(key) for key in (
            "frame", "production_accepted", "capture_pair_seed_eligible", "hybrid_seed_evidence",
            "hybrid_source", "hybrid_interpolated", "capture_hybrid_dx", "capture_hybrid_dy",
            "broad_hybrid_dx", "broad_hybrid_dy")}
            for row in rows if row["special_frame"]],
    }
    write_csv(reel_output / "diagnostics.csv", rows)
    (reel_output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return rows, summary


def make_contact_sheet(paths: list[Path], destination: Path, title: str, columns: int = 4) -> None:
    if not paths:
        return
    thumb_w, thumb_h, header = 380, 285, 42
    rows = math.ceil(len(paths) / columns)
    sheet = Image.new("RGB", (columns * thumb_w, header + rows * thumb_h), "black")
    draw = ImageDraw.Draw(sheet)
    draw.text((10, 12), title, fill="white")
    for index, path in enumerate(paths):
        with Image.open(path) as image:
            sheet.paste(image.resize((thumb_w, thumb_h), Image.Resampling.BILINEAR),
                        ((index % columns) * thumb_w, header + (index // columns) * thumb_h))
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, quality=90)


def generate_review_outputs(output: Path, all_rows: dict[str, list[dict]]) -> None:
    for reel, rows in all_rows.items():
        review = output / reel / "review_frames"
        recovered = [r for r in rows if r["new_same_frame_recovery"]]
        remaining = [r for r in rows if r["hybrid_interpolated"]]
        disagreements = sorted(
            [r for r in rows if r["capture_hybrid_dy"] is not None],
            key=lambda r: math.hypot(float(r["capture_hybrid_dx"]),
                                     float(r["capture_hybrid_dy"])), reverse=True)
        categories = {
            "newly_recovered": recovered[:48],
            "remaining_interpolated": remaining[:48],
            "large_disagreements": disagreements[:48],
            "seeded_only_safety_review": [
                r for r in rows if r["hybrid_source"] == "capture_seeded_only"
            ],
            "special_frames": [r for r in rows if r["special_frame"]],
        }
        for category, selected in categories.items():
            paths = [review / f"frame_{int(r['frame']):06d}.jpg" for r in selected]
            paths = [path for path in paths if path.exists()]
            make_contact_sheet(paths, output / reel / "contact_sheets" / f"{category}.jpg",
                               f"{reel}: {category}")

        # Slow event clips from retained review frames; no interpolation.
        events = [int(r["frame"]) for r in recovered[:3]]
        if reel == "Reel_46335":
            long_region = [r for r in recovered if 1954 <= int(r["frame"]) <= 3111]
            if long_region:
                events.extend(int(long_region[round(i * (len(long_region) - 1) / 5)]["frame"])
                              for i in range(6))
        events.extend(int(r["frame"]) for r in rows if r["special_frame"])
        event_dir = output / reel / "event_clips"
        event_dir.mkdir(parents=True, exist_ok=True)
        for event in sorted(set(events)):
            paths = [review / f"frame_{number:06d}.jpg" for number in range(max(1, event - 24), event + 25)]
            paths = [path for path in paths if path.exists()]
            if not paths:
                continue
            first = cv2.imread(str(paths[0]))
            writer = cv2.VideoWriter(str(event_dir / f"frame_{event:06d}_hybrid_review.mp4"),
                                     cv2.VideoWriter_fourcc(*"mp4v"), 4.0,
                                     (first.shape[1], first.shape[0]))
            for path in paths:
                writer.write(cv2.imread(str(path)))
            writer.release()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--work-dir", type=Path, default=ROOT / "work")
    parser.add_argument("--reel", action="append", choices=sorted(REELS))
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=24)
    parser.add_argument("--no-review-frames", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    selected = args.reel or list(REELS)
    all_rows, summaries = {}, []
    for reel in selected:
        rows, summary = process_reel(reel, REELS[reel], args.output_dir, args.work_dir,
                                     args.jobs, args.batch_size, not args.no_review_frames)
        all_rows[reel] = rows
        summaries.append(summary)
    generate_review_outputs(args.output_dir, all_rows)
    report = {"poc": "hybrid_capture_prior", "production_modified": False,
              "capture_coordinates_used_as_final": False, "reels": summaries}
    (args.output_dir / "validation_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
