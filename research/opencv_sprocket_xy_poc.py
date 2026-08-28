#!/usr/bin/env python3
"""Research-only OpenCV candidate generator for two-axis sprocket measurement.

Coordinates are in the current registered 1134x900 research frame:
* x is the film-side (right) boundary of the left sprocket opening.
* y is the lower boundary of the upper opening or upper boundary of the lower.
Corrections use reference - measurement for both axes. This tool measures only;
it does not crop, stabilize, or modify production behavior.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import av
import cv2
import numpy as np


@dataclass(frozen=True)
class XYMeasurement:
    frame: int
    region: str
    x: float
    y: float
    width: int
    height: int
    area: int
    solidity: float
    local_threshold: float
    score: float


def normalized_mask(gray: np.ndarray) -> tuple[np.ndarray, float]:
    """Expose locally bright hole material without a global intensity floor."""
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 8))
    normalized = clahe.apply(gray)
    threshold, mask = cv2.threshold(
        normalized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 9))
    )
    return mask, float(threshold) / 255.0


def region_measurements(
    gray: np.ndarray, frame: int, region: str, roi_width: int = 120
) -> list[XYMeasurement]:
    height = gray.shape[0]
    y0, y1 = ((0, height // 2) if region == "top" else (height // 2, height))
    roi = gray[y0:y1, :roi_width]
    mask, threshold = normalized_mask(roi)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    measurements: list[XYMeasurement] = []
    for label in range(1, count):
        x, y, width, component_height, area = map(int, stats[label])
        if x > 3 or width < 9 or width > roi_width - 2 or component_height < 14 or area < 180:
            continue
        component = labels == label
        points = np.column_stack(np.nonzero(component))
        if len(points) < 3:
            continue
        contour_points = np.column_stack((points[:, 1], points[:, 0])).astype(np.int32)
        hull_area = float(cv2.contourArea(cv2.convexHull(contour_points)))
        solidity = float(np.clip(area / hull_area, 0.0, 1.0)) if hull_area > 0 else 0.0
        if solidity < 0.35:
            continue

        # Robust percentiles avoid single-pixel dirt projections. The top and
        # bottom sprockets use opposite horizontal boundaries.
        right_x = float(np.percentile(points[:, 1], 95))
        column_boundaries = [
            (np.max(points[points[:, 1] == column, 0]) if region == "top" else
             np.min(points[points[:, 1] == column, 0]))
            for column in np.unique(points[:, 1])
        ]
        boundary_y = float(np.median(column_boundaries) + y0)
        width_score = float(np.clip(1.0 - abs(width - 38) / 50.0, 0.0, 1.0))
        solidity_score = float(np.clip((solidity - 0.35) / 0.55, 0.0, 1.0))
        area_score = float(np.clip(area / 2500.0, 0.0, 1.0))
        score = 0.4 * width_score + 0.35 * solidity_score + 0.25 * area_score
        measurements.append(XYMeasurement(
            frame, region, right_x, boundary_y, width, component_height,
            area, solidity, threshold, score
        ))
    return sorted(measurements, key=lambda item: item.score, reverse=True)


def measure_frame(rgb: np.ndarray, frame: int, roi_width: int = 120) -> list[XYMeasurement]:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    return (region_measurements(gray, frame, "top", roi_width) +
            region_measurements(gray, frame, "bottom", roi_width))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--first-frame", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--roi-width", type=int, default=120)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    decoded = measured = 0
    with av.open(str(args.video)) as container:
        stream = container.streams.video[0]
        for index, video_frame in enumerate(container.decode(stream)):
            if args.limit is not None and decoded >= args.limit:
                break
            decoded += 1
            if index % args.stride:
                continue
            source_frame = args.first_frame + index
            candidates = measure_frame(video_frame.to_ndarray(format="rgb24"), source_frame, args.roi_width)
            measured += 1
            region_ranks = {"top": 0, "bottom": 0}
            for candidate in candidates:
                region_ranks[candidate.region] += 1
                row = asdict(candidate); row["rank"] = region_ranks[candidate.region]; rows.append(row)

    fields = list(asdict(XYMeasurement(0, "", 0, 0, 0, 0, 0, 0, 0, 0))) + ["rank"]
    with (args.output_dir / "xy_candidates.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fields); writer.writeheader(); writer.writerows(rows)
    best = {(row["frame"], row["region"]): row for row in rows if row["rank"] == 1}
    paired = [(best[(frame, "top")], best[(frame, "bottom")])
              for frame in sorted({row["frame"] for row in rows})
              if (frame, "top") in best and (frame, "bottom") in best]
    x_disagreement = np.asarray([abs(top["x"] - bottom["x"]) for top, bottom in paired])
    spacing = np.asarray([bottom["y"] - top["y"] for top, bottom in paired])
    summary = {
        "video": str(args.video), "decoded_frames": decoded, "measured_frames": measured,
        "candidate_rows": len(rows), "frames_with_top": len({r["frame"] for r in rows if r["region"] == "top"}),
        "frames_with_bottom": len({r["frame"] for r in rows if r["region"] == "bottom"}),
        "frames_with_paired_candidates": len(paired),
        "paired_x_disagreement_median": float(np.median(x_disagreement)) if len(paired) else None,
        "paired_x_disagreement_p95": float(np.percentile(x_disagreement, 95)) if len(paired) else None,
        "paired_y_spacing_median": float(np.median(spacing)) if len(paired) else None,
        "paired_y_spacing_p05_p95": ([float(np.percentile(spacing, 5)),
                                      float(np.percentile(spacing, 95))] if len(paired) else None),
        "coordinate_convention": "correction_x/y = reference_x/y - measured_x/y",
        "status": "candidate-generation benchmark only; not stabilization",
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
