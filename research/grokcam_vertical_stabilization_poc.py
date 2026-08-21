#!/usr/bin/env python3
"""Isolated POC for residual Y-only registration from a sprocket remnant."""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from grokcam.batch import RunOptions, frame_number, select_dngs
from grokcam.config import load_calibration
from grokcam.encoding import encode_segment, file_sha256, verify_video
from grokcam.image_processing import registered_frame
from grokcam.models import CropGeometry
from grokcam.raw_development import DarktableMatchedDeveloper
from grokcam.registration import crop_for_detection
from grokcam.sprocket_detection import detect, validate_batch


@dataclass(frozen=True)
class ResidualMeasurement:
    y: float | None
    confidence: float
    edge_strength: float = 0.0
    edge_contrast: float = 0.0
    bright_tail_fraction: float = 0.0


def _luminance(image: Image.Image) -> np.ndarray:
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    return rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def residual_sprocket_y(
    image: Image.Image,
    roi: tuple[int, int, int, int] = (0, 150, 90, 285),
    expected_y: float | None = None,
) -> ResidualMeasurement:
    """Locate the lower edge of the partial upper sprocket hole.

    The production loose crop leaves only the rightmost part of the hole.  A
    bright-pixel fraction by row is therefore more stable than a blob centroid
    and does not require the whole physical hole to be visible.
    """
    x0, y0, x1, y1 = roi
    lum = _luminance(image)[y0:y1, x0:x1]
    if lum.shape[0] < 7 or lum.shape[1] < 8:
        return ResidualMeasurement(None, 0.0)
    threshold = max(0.70, float(np.percentile(lum, 90)) * 0.88)
    profile = np.mean(lum >= threshold, axis=1)
    smooth = np.convolve(profile, np.array([1, 2, 3, 2, 1], dtype=float) / 9.0, mode="same")
    gradient = -np.gradient(smooth)
    # Initial measurement uses the strongest edge.  Post-correction
    # verification knows the intended reference and searches locally so a
    # large recrop cannot make the verifier switch to a different physical
    # boundary elsewhere in the partial sprocket shape.
    search_start, search_stop = 3, len(gradient) - 3
    if expected_y is not None:
        expected_index = int(round(expected_y - y0))
        search_start = max(search_start, expected_index - 10)
        search_stop = min(search_stop, expected_index + 11)
    index = int(np.argmax(gradient[search_start:search_stop]) + search_start)
    strength = float(gradient[index])
    if 0 < index < len(gradient) - 1:
        left, center, right = gradient[index - 1:index + 2]
        denominator = left - 2.0 * center + right
        offset = 0.5 * (left - right) / denominator if abs(denominator) > 1e-9 else 0.0
        offset = float(np.clip(offset, -0.75, 0.75))
    else:
        offset = 0.0
    bright_above = float(np.mean(smooth[max(0, index - 12):index]))
    dark_below = float(np.mean(smooth[index:min(len(smooth), index + 12)]))
    contrast = max(0.0, bright_above - dark_below)
    # A trustworthy terminal sprocket boundary should become dark immediately
    # below the selected falling edge.  A large value identifies an internal
    # edge through damaged/contaminated bright material (the known 3615/3676
    # failure mode) without using correction magnitude.
    bright_tail = float(np.mean(smooth[index + 2:min(len(smooth), index + 8)]))
    confidence = float(np.clip((strength / 0.08) * (contrast / 0.18), 0.0, 1.0))
    if strength < 0.018 or contrast < 0.045:
        return ResidualMeasurement(None, confidence, strength, contrast, bright_tail)
    return ResidualMeasurement(y0 + index + offset, confidence, strength, contrast, bright_tail)


def bottom_sprocket_y(
    image: Image.Image,
    roi: tuple[int, int, int, int] = (0, 550, 90, 900),
) -> ResidualMeasurement:
    """Locate the rising upper boundary of the lower sprocket remnant."""
    x0, y0, x1, y1 = roi
    lum = _luminance(image)[y0:y1, x0:x1]
    if lum.shape[0] < 7 or lum.shape[1] < 8:
        return ResidualMeasurement(None, 0.0)
    threshold = max(0.70, float(np.percentile(lum, 90)) * 0.88)
    profile = np.mean(lum >= threshold, axis=1)
    smooth = np.convolve(profile, np.array([1, 2, 3, 2, 1], dtype=float) / 9.0, mode="same")
    gradient = np.gradient(smooth)
    index = int(np.argmax(gradient[3:-3]) + 3)
    strength = float(gradient[index])
    if 0 < index < len(gradient) - 1:
        left, center, right = gradient[index - 1:index + 2]
        denominator = left - 2.0 * center + right
        offset = 0.5 * (left - right) / denominator if abs(denominator) > 1e-9 else 0.0
        offset = float(np.clip(offset, -0.75, 0.75))
    else:
        offset = 0.0
    dark_above = float(np.mean(smooth[max(0, index - 12):index]))
    bright_below = float(np.mean(smooth[index:min(len(smooth), index + 12)]))
    contrast = max(0.0, bright_below - dark_above)
    bright_tail = float(np.mean(smooth[index + 2:min(len(smooth), index + 8)]))
    confidence = float(np.clip((strength / 0.04) * (contrast / 0.14), 0.0, 1.0))
    if strength < 0.009 or contrast < 0.055 or bright_tail < 0.05:
        return ResidualMeasurement(None, confidence, strength, contrast, bright_tail)
    return ResidualMeasurement(y0 + index + offset, confidence, strength, contrast, bright_tail)


def top_measurement_rejection(measurement: ResidualMeasurement, minimum_confidence: float) -> list[str]:
    reasons = []
    if measurement.y is None:
        reasons.append("no_residual_edge")
    elif measurement.confidence < minimum_confidence:
        reasons.append("confidence_below_minimum")
    if measurement.bright_tail_fraction > 0.30:
        reasons.append("nonterminal_bright_boundary")
    return reasons


def bottom_measurement_rejection(measurement: ResidualMeasurement) -> list[str]:
    reasons = []
    if measurement.y is None:
        reasons.append("no_bottom_edge")
    elif measurement.confidence < 0.20:
        reasons.append("bottom_confidence_below_minimum")
    if measurement.y is not None and measurement.bright_tail_fraction < 0.05:
        reasons.append("bottom_bright_region_too_weak")
    return reasons


def rolling_median(values: np.ndarray, width: int) -> np.ndarray:
    radius = width // 2
    return np.array([
        np.median(values[max(0, i - radius):min(len(values), i + radius + 1)])
        for i in range(len(values))
    ])


def fill_missing(values: list[float | None]) -> np.ndarray:
    result = np.array([np.nan if value is None else value for value in values], dtype=float)
    good = np.isfinite(result)
    if not good.any():
        raise RuntimeError("No usable residual sprocket measurements")
    positions = np.arange(len(result))
    return np.interp(positions, positions[good], result[good])


def translate_y(image: Image.Image, correction_y: float) -> Image.Image:
    """Translate content vertically by correction_y using bicubic sampling."""
    return image.transform(
        image.size,
        Image.Transform.AFFINE,
        (1.0, 0.0, 0.0, 0.0, 1.0, -correction_y),
        resample=Image.Resampling.BICUBIC,
        fillcolor=(0, 0, 0),
    )


def movement(series: np.ndarray) -> dict[str, float]:
    delta = np.diff(series)
    absolute = np.abs(delta)
    return {
        "mean_absolute_frame_to_frame": float(np.mean(absolute)) if len(absolute) else 0.0,
        "p95_absolute_frame_to_frame": float(np.percentile(absolute, 95)) if len(absolute) else 0.0,
        "maximum_absolute_frame_to_frame": float(np.max(absolute)) if len(absolute) else 0.0,
    }


def signal_summary(errors: np.ndarray, corrections: np.ndarray) -> dict:
    absolute = np.abs(errors)
    return {
        "median_residual_error": float(np.median(errors)),
        "mean_absolute_residual_error": float(np.mean(absolute)),
        "p95_absolute_residual": float(np.percentile(absolute, 95)),
        "p99_absolute_residual": float(np.percentile(absolute, 99)),
        "maximum_absolute_residual": float(np.max(absolute)),
        "percent_requiring_correction_over_px": {
            str(limit): float(np.mean(np.abs(corrections) > limit) * 100.0)
            for limit in (1, 2, 3, 4, 6, 8)
        },
    }


def correction_for(series: np.ndarray, reference_y: float, cap: float | None) -> np.ndarray:
    correction = -(series - reference_y)
    return np.clip(correction, -cap, cap) if cap is not None else correction


def encode(ffmpeg: Path, ffprobe: Path, frames: Path, destination: Path,
           first: int, count: int, fps: int) -> dict:
    temporary = destination.with_suffix(".tmp.mp4")
    encode_segment(ffmpeg, frames, temporary, first, count, fps)
    verification = verify_video(ffmpeg, ffprobe, temporary, count)
    os.replace(temporary, destination)
    return {"path": str(destination), "sha256": file_sha256(destination), "verification": verification}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_dir", type=Path)
    parser.add_argument("--first-frame", type=int, default=3000)
    parser.add_argument("--last-frame", type=int)
    parser.add_argument("--frame-count", type=int, default=96,
                        help="default range length when --last-frame is omitted")
    parser.add_argument("--output-dir", type=Path,
                        help="override the project-local reel/range output directory")
    parser.add_argument("--smoothing", choices=("none", "3", "5"), default="none")
    parser.add_argument("--max-correction", type=float,
                        help="absolute pixel cap; omitted means unlimited analytical mode")
    parser.add_argument("--fps", type=int, default=16)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--ffmpeg", type=Path, default=Path("/usr/bin/ffmpeg"))
    parser.add_argument("--ffprobe", type=Path, default=Path("/usr/bin/ffprobe"))
    parser.add_argument("--minimum-confidence", type=float, default=0.20)
    parser.add_argument("--guide", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.frame_count < 3:
        raise SystemExit("--frame-count must be at least 3")
    if args.max_correction is not None and args.max_correction <= 0:
        raise SystemExit("--max-correction must be positive")
    last = args.last_frame
    if last is None:
        last = args.first_frame + args.frame_count - 1
    raw_dir = args.raw_dir.expanduser().resolve()
    if args.output_dir is None:
        source_name = raw_dir.parent.name if raw_dir.name.lower() == "raw" else raw_dir.name
        reel_slug = re.sub(r"[^a-z0-9]+", "_", source_name.lower()).strip("_") or "raw"
        run_name = f"{reel_slug}_{args.first_frame}_{last}"
        output = Path(__file__).resolve().parent / "output" / "vertical_stabilization" / run_name
    else:
        output = args.output_dir.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    for name in ("before_frames", "after_recrop_frames", "comparison_frames"):
        (output / name).mkdir()

    options = RunOptions(raw_dir, output, first=args.first_frame, last=last,
                         minimum_free_gib=0)
    dngs = select_dngs(options)
    first, last = frame_number(dngs[0]), frame_number(dngs[-1])
    calibration = load_calibration()
    developer = DarktableMatchedDeveloper(calibration.match.report)

    temp_root = Path("work").resolve()
    temp_root.mkdir(exist_ok=True)
    run_started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="vertical-stabilization-", dir=temp_root) as temporary_name:
        tiffs = Path(temporary_name)

        def develop(path: Path) -> Path:
            target = tiffs / f"{path.stem}.tif"
            developer.develop(path, target)
            return target

        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            futures = [pool.submit(develop, path) for path in dngs]
            for completed, future in enumerate(as_completed(futures), 1):
                future.result()
                if completed == 1 or completed % 25 == 0 or completed == len(dngs):
                    print(f"Developed {completed}/{len(dngs)}", flush=True)
        with Image.open(tiffs / f"{dngs[0].stem}.tif") as developed_probe:
            developed_width, developed_height = developed_probe.size

        raw_primary = []
        for dng in dngs:
            with Image.open(tiffs / f"{dng.stem}.tif") as image:
                try:
                    raw_primary.append(detect(image, calibration.detector))
                except ValueError:
                    raw_primary.append(None)
        primary = validate_batch(raw_primary, calibration.detector)

        normal_measurements: list[ResidualMeasurement] = []
        expanded_measurements: list[ResidualMeasurement | None] = []
        measurements: list[ResidualMeasurement] = []
        measurement_modes: list[str] = []
        bottom_measurements: list[ResidualMeasurement] = []
        primary_crops: list[CropGeometry] = []
        provisional_seconds = 0.0
        for index, (dng, anchor) in enumerate(zip(dngs, primary), 1):
            started = time.perf_counter()
            primary_crop = crop_for_detection(anchor, calibration.crop)
            primary_crops.append(primary_crop)
            with Image.open(tiffs / f"{dng.stem}.tif") as image:
                before = registered_frame(image, primary_crop, calibration.contrast)
            before_path = output / "before_frames" / f"frame_{frame_number(dng):06d}.jpg"
            before.save(before_path, quality=95, subsampling=0)
            # Measure the same serialized frame stream that is encoded and that
            # the after-correction detector sees; this avoids a JPEG asymmetry
            # in the numerical before/after validation.
            with Image.open(before_path) as serialized_before:
                normal = residual_sprocket_y(serialized_before)
                normal_measurements.append(normal)
                expanded = None
                selected = normal
                mode = "normal"
                if not anchor.accepted and top_measurement_rejection(normal, args.minimum_confidence):
                    expanded = residual_sprocket_y(serialized_before, roi=(0, 60, 90, 285))
                    if not top_measurement_rejection(expanded, args.minimum_confidence):
                        selected = expanded
                        mode = "expanded"
                expanded_measurements.append(expanded)
                measurements.append(selected)
                measurement_modes.append(mode)
                bottom_measurements.append(bottom_sprocket_y(serialized_before))
            provisional_seconds += time.perf_counter() - started
            if index == 1 or index % 25 == 0 or index == len(dngs):
                print(f"Registered and measured {index}/{len(dngs)}", flush=True)
        # Establish the reference from terminal, usable boundaries.  Magnitude
        # is deliberately absent from this gate.
        reference_candidates = [
            measurement.y for measurement in measurements
            if measurement.y is not None
            and measurement.confidence >= args.minimum_confidence
            and measurement.bright_tail_fraction <= 0.30
        ]
        if not reference_candidates:
            raise RuntimeError("No trustworthy residual measurements for reference Y")
        reference_y = float(np.median(reference_candidates))

        bottom_reference_candidates = [
            measurement.y for measurement, anchor in zip(bottom_measurements, primary)
            if anchor.accepted and not bottom_measurement_rejection(measurement)
        ]
        if not bottom_reference_candidates:
            raise RuntimeError("No trustworthy bottom-sprocket measurements for reference Y")
        bottom_reference_y = float(np.median(bottom_reference_candidates))

        measured_corrections: list[float | None] = []
        valid: list[bool] = []
        top_valids: list[bool] = []
        rejection_reasons: list[str] = []
        bottom_corrections: list[float | None] = []
        bottom_valid: list[bool] = []
        bottom_rejection_reasons: list[str] = []
        correction_disagreements: list[float | None] = []
        corrections_agree: list[bool | None] = []
        selected_sources: list[str | None] = []
        agreement_tolerance = 5.0
        for measurement, mode, bottom, crop in zip(
                measurements, measurement_modes, bottom_measurements, primary_crops):
            top_reasons = top_measurement_rejection(measurement, args.minimum_confidence)
            top_correction = None if measurement.y is None else reference_y - measurement.y
            bottom_reasons = bottom_measurement_rejection(bottom)
            bottom_correction = None if bottom.y is None else bottom_reference_y - bottom.y
            if top_correction is not None:
                # registered_frame vertically flips the crop.  For a fixed
                # source feature, oriented_y = height - 1 - source_y + crop_top.
                # Increasing crop_top therefore moves content down:
                # corrected_top = primary_top + correction_y.
                proposed_top = crop.top + top_correction
                if proposed_top < 0 or proposed_top + crop.height > developed_height:
                    top_reasons.append("corrected_crop_out_of_source_bounds")
            if bottom_correction is not None:
                proposed_bottom_top = crop.top + bottom_correction
                if proposed_bottom_top < 0 or proposed_bottom_top + crop.height > developed_height:
                    bottom_reasons.append("bottom_corrected_crop_out_of_source_bounds")

            top_ok, bottom_ok = not top_reasons, not bottom_reasons
            disagreement = (
                None if top_correction is None or bottom_correction is None
                else bottom_correction - top_correction
            )
            agree = None if disagreement is None else abs(disagreement) <= agreement_tolerance
            # A valid top residual remains authoritative; bottom agreement adds
            # evidence and disagreement is logged rather than blindly averaged.
            # If top is invalid/unavailable, bottom becomes the same-frame rescue.
            if top_ok:
                selected_correction = top_correction
                selected_source = "expanded_residual" if mode == "expanded" else "residual"
            elif bottom_ok:
                selected_correction = bottom_correction
                selected_source = "bottom_rescue"
            else:
                selected_correction = None
                selected_source = None
            measured_corrections.append(selected_correction)
            valid.append(selected_correction is not None)
            top_valids.append(top_ok)
            rejection_reasons.append(";".join(top_reasons))
            bottom_corrections.append(bottom_correction)
            bottom_valid.append(bottom_ok)
            bottom_rejection_reasons.append(";".join(bottom_reasons))
            correction_disagreements.append(disagreement)
            corrections_agree.append(agree)
            selected_sources.append(selected_source)

        good = np.array(valid, dtype=bool)
        if not good.any():
            raise RuntimeError("No valid residual corrections")
        positions = np.arange(len(dngs))
        raw_values = np.array([
            np.nan if correction is None else correction for correction in measured_corrections
        ], dtype=float)
        applied = np.interp(positions, positions[good], raw_values[good])
        sources = []
        good_positions = positions[good]
        for index, is_valid in enumerate(valid):
            if is_valid:
                sources.append(selected_sources[index])
            elif index < good_positions[0] or index > good_positions[-1]:
                sources.append("nearest_valid_fallback")
            else:
                sources.append("interpolation")
        if args.smoothing != "none":
            applied = rolling_median(applied, int(args.smoothing))
        if args.max_correction is not None:
            applied = np.clip(applied, -args.max_correction, args.max_correction)

        after_measurements: list[ResidualMeasurement] = []
        corrected_crops: list[CropGeometry] = []
        final_recrop_seconds = 0.0
        old_shift_benchmark_seconds = 0.0
        for index, (dng, primary_crop, correction) in enumerate(
                zip(dngs, primary_crops, applied), 1):
            number = frame_number(dng)
            # Benchmark the prior discarded-crop shift on the same input.  Its
            # result is not retained or used by the recrop architecture.
            with Image.open(output / "before_frames" / f"frame_{number:06d}.jpg") as before:
                benchmark_started = time.perf_counter()
                translate_y(before, float(correction))
                old_shift_benchmark_seconds += time.perf_counter() - benchmark_started

            # Sign relationship: positive correction moves output content down;
            # after the production vertical flip this requires sampling a
            # larger full-resolution source Y coordinate.
            corrected_crop = CropGeometry(
                primary_crop.left, primary_crop.top + float(correction),
                primary_crop.width, primary_crop.height,
            )
            corrected_crops.append(corrected_crop)
            recrop_started = time.perf_counter()
            with Image.open(tiffs / f"{dng.stem}.tif") as image:
                after = registered_frame(image, corrected_crop, calibration.contrast)
            final_recrop_seconds += time.perf_counter() - recrop_started
            after_path = output / "after_recrop_frames" / f"frame_{number:06d}.jpg"
            after.save(after_path, quality=95, subsampling=0)
            with Image.open(after_path) as serialized_after:
                after_measurements.append(residual_sprocket_y(serialized_after, expected_y=reference_y))
            with Image.open(output / "before_frames" / f"frame_{number:06d}.jpg") as before:
                comparison = Image.new("RGB", (before.width * 2, before.height), "black")
                comparison.paste(before, (0, 0))
                comparison.paste(after, (before.width, 0))
            if args.guide:
                draw = ImageDraw.Draw(comparison)
                guide_y = int(round(reference_y))
                draw.line((0, guide_y, comparison.width - 1, guide_y), fill=(0, 255, 255), width=1)
            comparison.save(output / "comparison_frames" / f"frame_{number:06d}.jpg",
                            quality=95, subsampling=0)
            if index == 1 or index % 25 == 0 or index == len(dngs):
                print(f"Corrected recrop {index}/{len(dngs)}", flush=True)

    # TIFFs have now been discarded; each DNG was developed exactly once.
    usable = [
        measurement.y if measurement.y is not None
        and measurement.confidence >= args.minimum_confidence else None
        for measurement in measurements
    ]
    filled = fill_missing(usable)
    after_filled = fill_missing([
        measurement.y if measurement.y is not None
        and measurement.confidence >= args.minimum_confidence
        and measurement.bright_tail_fraction <= 0.30 else None
        for measurement in after_measurements
    ])
    records = []
    for i, (dng, anchor, primary_crop, corrected_crop, measured, after_measured) in enumerate(
            zip(dngs, primary, primary_crops, corrected_crops, measurements, after_measurements)):
        records.append({
            "frame": frame_number(dng),
            "primary_anchor_x": anchor.cx,
            "primary_anchor_y": anchor.cy,
            "primary_detected": anchor.detected,
            "primary_accepted": anchor.accepted,
            "primary_crop_top": primary_crop.top,
            "normal_residual_sprocket_y": normal_measurements[i].y,
            "normal_residual_confidence": normal_measurements[i].confidence,
            "expanded_residual_sprocket_y": (
                None if expanded_measurements[i] is None else expanded_measurements[i].y
            ),
            "expanded_residual_confidence": (
                None if expanded_measurements[i] is None else expanded_measurements[i].confidence
            ),
            "residual_search_mode": measurement_modes[i],
            "residual_sprocket_y": measured.y,
            "residual_confidence": measured.confidence,
            "residual_usable": usable[i] is not None,
            "residual_edge_strength": measured.edge_strength,
            "residual_edge_contrast": measured.edge_contrast,
            "residual_bright_tail_fraction": measured.bright_tail_fraction,
            "residual_measurement_valid": top_valids[i],
            "residual_rejection_reason": rejection_reasons[i],
            "reference_y": reference_y,
            "raw_residual_error_y": None if measured.y is None else measured.y - reference_y,
            "bottom_sprocket_y": bottom_measurements[i].y,
            "bottom_confidence": bottom_measurements[i].confidence,
            "bottom_edge_strength": bottom_measurements[i].edge_strength,
            "bottom_edge_contrast": bottom_measurements[i].edge_contrast,
            "bottom_bright_tail_fraction": bottom_measurements[i].bright_tail_fraction,
            "bottom_measurement_valid": bottom_valid[i],
            "bottom_rejection_reason": bottom_rejection_reasons[i],
            "bottom_reference_y": bottom_reference_y,
            "bottom_measured_correction_y": bottom_corrections[i],
            "top_bottom_correction_disagreement_y": correction_disagreements[i],
            "top_bottom_corrections_agree": corrections_agree[i],
            "selected_smoothing": args.smoothing,
            "correction_source": sources[i],
            "measured_correction_y": measured_corrections[i],
            "applied_correction_y": applied[i],
            "corrected_crop_top": corrected_crop.top,
            "stabilized_sprocket_y": after_measured.y,
            "post_correction_residual_y": (
                None if after_measured.y is None else after_measured.y - reference_y
            ),
            "stabilized_confidence": after_measured.confidence,
            "post_correction_measurement_valid": (
                after_measured.y is not None
                and after_measured.confidence >= args.minimum_confidence
                and after_measured.bright_tail_fraction <= 0.30
            ),
        })
    fieldnames = list(records[0])
    with (output / "diagnostics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
    (output / "diagnostics.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    invalid = [record for record in records if not record["residual_measurement_valid"]]
    with (output / "invalid_measurement_review.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(invalid)

    videos = {
        "before": encode(args.ffmpeg, args.ffprobe, output / "before_frames", output / "before.mp4",
                         first, len(dngs), args.fps),
        "after_recrop": encode(args.ffmpeg, args.ffprobe, output / "after_recrop_frames",
                        output / "after_recrop.mp4",
                        first, len(dngs), args.fps),
        "comparison": encode(args.ffmpeg, args.ffprobe, output / "comparison_frames",
                             output / "comparison.mp4", first, len(dngs), args.fps),
    }
    raw_errors = filled - reference_y
    common_per_frame = provisional_seconds / len(dngs)
    old_per_frame = common_per_frame + old_shift_benchmark_seconds / len(dngs)
    new_per_frame = common_per_frame + final_recrop_seconds / len(dngs)
    summary = {
        "poc": "residual-vertical-stabilization-corrected-recrop",
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_policy": "read-only archival DNGs",
        "production_code_modified": False,
        "range": {"first": first, "last": last, "frames": len(dngs), "fps": args.fps},
        "residual_roi_xyxy": [0, 150, 90, 285],
        "successful_residual_detections": int(sum(value is not None for value in usable)),
        "failed_residual_detections": int(sum(value is None for value in usable)),
        "valid_measured_corrections": int(sum(top_valids)),
        "invalid_residual_measurements": int(sum(not value for value in top_valids)),
        "bottom_valid_measurements": int(sum(bottom_valid)),
        "expanded_residual_corrections": int(sum(source == "expanded_residual" for source in sources)),
        "bottom_rescue_corrections": int(sum(source == "bottom_rescue" for source in sources)),
        "interpolated_corrections": int(sum(source == "interpolation" for source in sources)),
        "nearest_valid_fallback_corrections": int(sum(source == "nearest_valid_fallback" for source in sources)),
        "reference_y": reference_y,
        "bottom_reference_y": bottom_reference_y,
        "top_bottom_agreement_tolerance_px": agreement_tolerance,
        "selected_smoothing": args.smoothing,
        "maximum_correction": args.max_correction,
        "raw_residual": signal_summary(raw_errors, -raw_errors),
        "frame_to_frame_sprocket_movement_before": movement(filled),
        "frame_to_frame_sprocket_movement_after_remeasured": movement(after_filled),
        "remeasured_after_error": signal_summary(after_filled - reference_y, applied),
        "architecture": {
            "dng_developments_per_frame": 1,
            "final_sampling_source": "full-resolution developed TIFF",
            "final_resampling": "one production registered_frame bicubic crop",
            "crop_sign_relationship": "corrected_crop_top = primary_crop_top + applied_correction_y",
            "black_fill_translation": False,
            "developed_source_dimensions": [developed_width, developed_height],
        },
        "processing_benchmark": {
            "scope": "provisional crop/residual measurement plus stabilization operation; excludes common RAW development, primary detection, JPEG encode, and video encode",
            "modeled_previous_shift_seconds_per_frame": old_per_frame,
            "corrected_recrop_seconds_per_frame": new_per_frame,
            "estimated_overhead_percent": 100 * (new_per_frame - old_per_frame) / old_per_frame,
            "provisional_crop_and_measure_total_seconds": provisional_seconds,
            "old_shift_benchmark_total_seconds": old_shift_benchmark_seconds,
            "final_recrop_total_seconds": final_recrop_seconds,
            "wall_seconds_including_video": time.perf_counter() - run_started,
        },
        "primary_detection": {
            "detected": int(sum(item.detected for item in primary)),
            "accepted": int(sum(item.accepted for item in primary)),
            "interpolated": int(sum(item.interpolated for item in primary)),
        },
        "production_reuse": [
            "DarktableMatchedDeveloper", "sprocket_detection.detect", "validate_batch",
            "crop_for_detection", "registered_frame", "encode_segment", "verify_video",
        ],
        "videos": videos,
        "tools": {"python": platform.python_version(), "numpy": np.__version__, "pillow": Image.__version__},
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
