#!/usr/bin/env python3
"""Finalize diagnostics and quality metrics for a corrected-recrop POC run."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
from PIL import Image

from research.grokcam_vertical_stabilization_poc import residual_sprocket_y


def fill(values: list[float | None]) -> np.ndarray:
    array = np.array([np.nan if value is None else value for value in values], dtype=float)
    good = np.isfinite(array)
    positions = np.arange(len(array))
    return np.interp(positions, positions[good], array[good])


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


def luminance(path: Path) -> np.ndarray:
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0
    return rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def quality_metrics(old_path: Path, new_path: Path, correction: float) -> dict:
    old, new = luminance(old_path), luminance(new_path)
    interior_old, interior_new = old[80:-80, 80:-80], new[80:-80, 80:-80]

    def gradient_energy(value: np.ndarray) -> float:
        return float(np.mean(np.diff(value, axis=0) ** 2) + np.mean(np.diff(value, axis=1) ** 2))

    band_height = max(1, int(np.ceil(abs(correction))))
    old_band = old[:band_height] if correction > 0 else old[-band_height:]
    new_band = new[:band_height] if correction > 0 else new[-band_height:]
    return {
        "frame": int(old_path.stem.rsplit("_", 1)[-1]),
        "correction_y": correction,
        "compared_edge_band_height": band_height,
        "old_shift_near_black_fraction": float(np.mean(old_band < 0.01)),
        "recrop_near_black_fraction": float(np.mean(new_band < 0.01)),
        "interior_mean_absolute_difference": float(np.mean(np.abs(interior_old - interior_new))),
        "old_shift_interior_gradient_energy": gradient_energy(interior_old),
        "recrop_interior_gradient_energy": gradient_energy(interior_new),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recrop_run", type=Path)
    parser.add_argument("shifted_run", type=Path)
    args = parser.parse_args()
    run, shifted = args.recrop_run.resolve(), args.shifted_run.resolve()
    records = json.loads((run / "diagnostics.json").read_text(encoding="utf-8"))
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    reference = float(summary["reference_y"])

    post_values: list[float | None] = []
    for record in records:
        frame = int(record["frame"])
        measurement = residual_sprocket_y(
            Image.open(run / "after_recrop_frames" / f"frame_{frame:06d}.jpg"), expected_y=reference)
        record["stabilized_sprocket_y"] = measurement.y
        record["stabilized_confidence"] = measurement.confidence
        record["post_correction_residual_y"] = None if measurement.y is None else measurement.y - reference
        post_valid = (
            measurement.y is not None and measurement.confidence >= 0.20
            and measurement.bright_tail_fraction <= 0.30
        )
        record["post_correction_measurement_valid"] = post_valid
        post_values.append(record["post_correction_residual_y"] if post_valid else None)

    fields = list(records[0])
    (run / "diagnostics.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    with (run / "diagnostics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(records)
    invalid = [record for record in records if not record["residual_measurement_valid"]]
    with (run / "invalid_measurement_review.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(invalid)

    before = fill([record["raw_residual_error_y"] for record in records])
    after = fill(post_values)
    representative = (3046, 3260, 3451, 3487, 3615, 3676, 3754, 3846, 3882, 3947)
    quality = []
    for frame in representative:
        record = next(item for item in records if item["frame"] == frame)
        quality.append(quality_metrics(
            shifted / "after_frames" / f"frame_{frame:06d}.jpg",
            run / "after_recrop_frames" / f"frame_{frame:06d}.jpg",
            float(record["applied_correction_y"]),
        ))
    event_frames = (3260, 3451, 3487, 3615, 3676, 3754, 3846, 3882)
    report = {
        "architecture": summary["architecture"],
        "processing_benchmark": summary["processing_benchmark"],
        "range": summary["range"],
        "reference_y": reference,
        "measured_corrections": summary["valid_measured_corrections"],
        "invalid_residual_measurements": summary["invalid_residual_measurements"],
        "interpolated_corrections": summary["interpolated_corrections"],
        "nearest_valid_fallback_corrections": summary["nearest_valid_fallback_corrections"],
        "expanded_residual_corrections": summary.get("expanded_residual_corrections", 0),
        "bottom_valid_measurements": summary.get("bottom_valid_measurements", 0),
        "bottom_rescue_corrections": summary.get("bottom_rescue_corrections", 0),
        "before_residual": distribution(before),
        "after_recrop_trusted_residual": distribution(after),
        "before_frame_to_frame_movement": movement(before),
        "after_recrop_frame_to_frame_movement": movement(after),
        "invalid_measurements": [{key: record[key] for key in (
            "frame", "residual_rejection_reason", "measured_correction_y",
            "correction_source", "applied_correction_y", "post_correction_residual_y",
        )} for record in invalid],
        "required_event_frames": [{key: record[key] for key in (
            "frame", "primary_accepted", "residual_measurement_valid", "correction_source",
            "measured_correction_y", "applied_correction_y", "corrected_crop_top",
            "post_correction_residual_y",
        )} for record in records if record["frame"] in event_frames],
        "shifted_vs_recrop_quality_metrics": quality,
        "quality_metric_limitations": (
            "JPEG-domain diagnostic only; gradient energy and near-black fractions support visual review "
            "but do not independently prove perceived sharpness."
        ),
        "review_artifacts": {
            "before_video": str(run / "before.mp4"),
            "after_recrop_video": str(run / "after_recrop.mp4"),
            "before_after_comparison": str(run / "comparison.mp4"),
            "three_way_comparison": (
                str(run / "comparison_three_way.mp4") if (run / "comparison_three_way.mp4").exists() else None
            ),
            "event_clips": [str(run / "event_clips" / f"frame_{frame}_before_after_slow.mp4")
                            for frame in event_frames],
        },
    }
    (run / "validation_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary["trusted_target_verification"] = {
        "residual": report["after_recrop_trusted_residual"],
        "frame_to_frame_movement": report["after_recrop_frame_to_frame_movement"],
        "method": "target-local post-correction edge verification with untrusted results interpolated",
    }
    (run / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
