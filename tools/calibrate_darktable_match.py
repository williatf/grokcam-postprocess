#!/usr/bin/env python3
"""Fit a candidate rawpy renderer calibration to paired Darktable references.

This is an offline research command. It never changes the production calibration.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image
import rawpy

from grokcam.calibration.match_model import apply_model, fit_model, image_stats, sample_pair
from grokcam.config import DEFAULT_MATCH_REPORT, ProductionCalibration
from grokcam.sprocket_detection import detect

TOOL_VERSION = "1.0.0"
GROUPS = [
    ("early_experiment", range(120, 124)),
    ("landscape", range(1000, 1004)),
    ("indoor_transition", range(1400, 1404)),
    ("child_warm", range(1598, 1602)),
    ("people_green", range(1798, 1802)),
    ("bright_skin", range(2198, 2202)),
    ("color_objects", range(2798, 2802)),
    ("dark_holiday", range(3398, 3402)),
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def command_output(command: list[str]) -> str:
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"command failed: {' '.join(command)}\n{result.stderr}")
    return result.stdout or result.stderr


def develop_reference(darktable: Path, source: Path, target: Path, config: Path) -> None:
    config.mkdir(parents=True, exist_ok=True)
    command_output([str(darktable), str(source), str(target), "--core", "--configdir", str(config),
                    "--conf", "plugins/imageio/format/tiff/bpp=16",
                    "--conf", "plugins/imageio/format/tiff/compress=1"])


def image_array(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        if image.mode == "I;16":
            return np.asarray(image, dtype=np.float32)[:, :, None].repeat(3, axis=2) / 65535.0
        array = np.asarray(image.convert("RGB"))
    scale = 65535.0 if array.dtype.itemsize > 1 else 255.0
    return array.astype(np.float32) / scale


def render_raw(path: Path, correction: np.ndarray) -> np.ndarray:
    with rawpy.imread(str(path)) as raw:
        camera_wb = np.asarray(raw.camera_whitebalance[:3], dtype=np.float32)
        camera_wb = np.array([camera_wb[0], camera_wb[1], camera_wb[2], camera_wb[1]])
        output = raw.postprocess(
            demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
            use_camera_wb=False,
            user_wb=(camera_wb * correction).tolist(),
            output_bps=16,
            no_auto_bright=True,
            gamma=(1, 1),
            output_color=rawpy.ColorSpace.sRGB,
        )
    return output.astype(np.float32) / 65535.0


def bilinear_crop(image: np.ndarray, left: float, top: float,
                  width: int, height: int) -> np.ndarray:
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    x = np.clip(left + x, 0, image.shape[1] - 1)
    y = np.clip(top + y, 0, image.shape[0] - 1)
    x0, y0 = x.astype(np.int32), y.astype(np.int32)
    x1 = np.minimum(x0 + 1, image.shape[1] - 1)
    y1 = np.minimum(y0 + 1, image.shape[0] - 1)
    xf, yf = x - x0, y - y0
    upper = image[y0, x0] * (1 - xf[:, :, None]) + image[y0, x1] * xf[:, :, None]
    lower = image[y1, x0] * (1 - xf[:, :, None]) + image[y1, x1] * xf[:, :, None]
    return upper * (1 - yf[:, :, None]) + lower * yf[:, :, None]


def crop_register(image: np.ndarray, anchor: tuple[float, float]) -> np.ndarray:
    crop = ProductionCalibration().crop
    output = bilinear_crop(image, anchor[0] + crop.x_offset, anchor[1] + crop.y_offset,
                           crop.width, crop.height)
    return np.fliplr(np.rot90(output, 2))


def white_balance(args: argparse.Namespace) -> tuple[np.ndarray, dict]:
    if args.wb_report:
        report = json.loads(args.wb_report.read_text(encoding="utf-8"))
        rgb = report["render_correction_RGB_relative_to_embedded_D65"]
        values = np.array([rgb[0], rgb[1], rgb[2], rgb[1]], dtype=np.float32)
        return values, {"kind": "sprocket_white_report", "path": str(args.wb_report),
                        "rgb_correction": rgb}
    golden = json.loads(DEFAULT_MATCH_REPORT.read_text(encoding="utf-8"))
    values = np.asarray(golden["fit"]["white_balance_correction"], dtype=np.float32)
    return values, {"kind": "frozen_golden_seed", "path": str(DEFAULT_MATCH_REPORT),
                    "rgbg_correction": values.tolist()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--darktable", type=Path, default=Path("darktable-cli"))
    parser.add_argument("--output", type=Path, required=True,
                        help="new candidate JSON; production is never updated")
    parser.add_argument("--work-dir", type=Path, default=Path("work/darktable-match-calibration"))
    parser.add_argument("--calibration-id", required=True)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--wb-report", type=Path,
                        help="optional sprocket-white report for a new camera/illumination calibration")
    parser.add_argument("--keep-tiffs", action="store_true")
    parser.add_argument("--force", action="store_true", help="replace only the explicitly named candidate output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.raw_dir = args.raw_dir.expanduser().resolve()
    args.output = args.output.expanduser().resolve()
    args.work_dir = args.work_dir.expanduser().resolve()
    if args.wb_report:
        args.wb_report = args.wb_report.expanduser().resolve()
    if args.output.exists() and not args.force:
        raise SystemExit(f"candidate already exists: {args.output}; use a new path or --force")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    references = args.work_dir / "darktable"
    configs = args.work_dir / "configs"
    references.mkdir(parents=True, exist_ok=True)
    configs.mkdir(parents=True, exist_ok=True)
    correction, correction_source = white_balance(args)
    numbers = [number for _, group in GROUPS for number in group]
    missing = [number for number in numbers if not (args.raw_dir / f"frame_{number:06d}.dng").is_file()]
    if missing:
        raise SystemExit(f"missing calibration DNG frames: {missing}")

    def develop(number: int) -> None:
        develop_reference(args.darktable, args.raw_dir / f"frame_{number:06d}.dng",
                          references / f"frame_{number:06d}.tif", configs / f"frame_{number:06d}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        list(pool.map(develop, numbers))

    pairs = {}
    detector = ProductionCalibration().detector
    for number in numbers:
        reference = image_array(references / f"frame_{number:06d}.tif")
        raw = render_raw(args.raw_dir / f"frame_{number:06d}.dng", correction)
        preview = Image.fromarray(np.uint8(np.clip(reference * 255, 0, 255)))
        anchor = detect(preview, detector)
        pairs[number] = {"raw": crop_register(raw, (anchor.cx, anchor.cy)),
                         "darktable": crop_register(reference, (anchor.cx, anchor.cy))}

    train_numbers = [number for _, group in GROUPS[:-2] for number in group]
    holdout_numbers = [number for _, group in GROUPS[-2:] for number in group]
    inputs, targets = [], []
    for number in train_numbers:
        source, target = sample_pair(pairs[number]["raw"], pairs[number]["darktable"], 12000, number)
        inputs.append(source)
        targets.append(target)
    fit = fit_model(inputs, targets)
    fit["white_balance_correction"] = correction.tolist()
    metrics = []
    for number in numbers:
        matched = apply_model(pairs[number]["raw"], fit)
        reference = pairs[number]["darktable"]
        metrics.append({"frame": number, "split": "holdout" if number in holdout_numbers else "train",
                        "mean_absolute_rgb_error": float(np.mean(np.abs(matched - reference))),
                        "darktable": image_stats(reference), "matched": image_stats(matched)})

    with rawpy.imread(str(args.raw_dir / f"frame_{numbers[0]:06d}.dng")) as raw:
        source_dimensions = [raw.sizes.raw_width, raw.sizes.raw_height]
        camera_whitebalance = list(map(float, raw.camera_whitebalance))
    result = {
        "artifact_kind": "grokcam_darktable_match_calibration_candidate",
        "calibration_id": args.calibration_id, "schema_version": 1,
        "created": now(), "source_policy": "read_only", "tool_version": TOOL_VERSION,
        "camera_sensor_assumptions": {"source_dimensions": source_dimensions,
                                      "first_frame_camera_whitebalance": camera_whitebalance},
        "raw_dir": str(args.raw_dir), "selected_frames": numbers,
        "train_frames": train_numbers, "holdout_frames": holdout_numbers,
        "white_balance_source": correction_source, "fit": fit, "metrics": metrics,
        "tools": {"python": platform.python_version(), "numpy": np.__version__,
                  "rawpy": rawpy.__version__, "libraw": list(rawpy.libraw_version),
                  "darktable": command_output([str(args.darktable), "--version"]).splitlines()[0]},
        "adoption_status": "candidate_not_approved",
        "notes": "Validate independently; this command never changes production calibration.",
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not args.keep_tiffs:
        shutil.rmtree(references, ignore_errors=True)
        shutil.rmtree(configs, ignore_errors=True)
    print(args.output)


if __name__ == "__main__":
    main()
