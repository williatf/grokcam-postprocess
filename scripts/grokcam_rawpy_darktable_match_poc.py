#!/usr/bin/env python3
"""Fit a restrained rawpy display transform to paired Darktable references."""

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
from PIL import Image, ImageDraw

try:
    import rawpy
except ImportError as exc:
    raise SystemExit("rawpy is required; use /home/todd/telecine/.venv/bin/python") from exc

from grokcam_raw_production import PRESETS, detect_anchor

VERSION = "0.1.0"
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
LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run(command: list[str]) -> None:
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"command failed: {' '.join(map(str, command))}\n{result.stderr}")


def bilinear_crop(image: np.ndarray, left: float, top: float, width: int, height: int) -> np.ndarray:
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    x = np.clip(left + x, 0, image.shape[1] - 1)
    y = np.clip(top + y, 0, image.shape[0] - 1)
    x0, y0 = x.astype(np.int32), y.astype(np.int32)
    x1, y1 = np.minimum(x0 + 1, image.shape[1] - 1), np.minimum(y0 + 1, image.shape[0] - 1)
    xf, yf = x - x0, y - y0
    top_row = image[y0, x0] * (1 - xf[:, :, None]) + image[y0, x1] * xf[:, :, None]
    bottom_row = image[y1, x0] * (1 - xf[:, :, None]) + image[y1, x1] * xf[:, :, None]
    return top_row * (1 - yf[:, :, None]) + bottom_row * yf[:, :, None]


def crop_register(image: np.ndarray, anchor: tuple[float, float]) -> np.ndarray:
    crop = PRESETS["loose"]
    output = bilinear_crop(image, anchor[0] + crop["x_offset"], anchor[1] + crop["y_offset"],
                           crop["width"], crop["height"])
    return np.fliplr(np.rot90(output, 2))


def render_raw(path: Path, wb_correction: np.ndarray) -> np.ndarray:
    with rawpy.imread(str(path)) as raw:
        camera_wb = np.asarray(raw.camera_whitebalance[:3], dtype=np.float32)
        camera_wb = np.array([camera_wb[0], camera_wb[1], camera_wb[2], camera_wb[1]])
        output = raw.postprocess(
            demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
            use_camera_wb=False,
            user_wb=(camera_wb * wb_correction).tolist(),
            output_bps=16,
            no_auto_bright=True,
            gamma=(1, 1),
            output_color=rawpy.ColorSpace.sRGB,
        )
    return output.astype(np.float32) / 65535.0


def image_array(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        if image.mode == "I;16":
            return np.asarray(image, dtype=np.float32)[:, :, None].repeat(3, axis=2) / 65535.0
        array = np.asarray(image.convert("RGB"))
        scale = 65535.0 if array.dtype.itemsize > 1 else 255.0
        return array.astype(np.float32) / scale


def features(rgb: np.ndarray) -> np.ndarray:
    r, g, b = rgb.T
    return np.column_stack((np.ones(len(rgb)), r, g, b, np.sqrt(np.maximum(rgb, 0)),
                            r * r, g * g, b * b, r * g, r * b, g * b))


def fit_matrix(inputs: list[np.ndarray], targets: list[np.ndarray]) -> np.ndarray:
    coefficients, *_ = np.linalg.lstsq(features(np.concatenate(inputs)), np.concatenate(targets), rcond=1e-6)
    return coefficients


def apply_matrix(rgb: np.ndarray, coefficients: np.ndarray) -> np.ndarray:
    shape = rgb.shape
    return np.clip((features(rgb.reshape(-1, 3)) @ coefficients).reshape(shape), 0, 1)


def fit_luts(predictions: list[np.ndarray], targets: list[np.ndarray], bins: int = 256) -> list[np.ndarray]:
    source, target = np.concatenate(predictions), np.concatenate(targets)
    edges = np.linspace(0, 1, bins + 1)
    luts = []
    for channel in range(3):
        values = []
        for low, high in zip(edges[:-1], edges[1:]):
            mask = (source[:, channel] >= low) & (source[:, channel] < high)
            values.append(float(np.median(target[mask, channel])) if mask.any() else np.nan)
        lut = np.asarray(values, dtype=np.float32)
        valid = np.isfinite(lut)
        lut = np.interp(np.arange(bins), np.flatnonzero(valid), lut[valid])
        luts.append(np.maximum.accumulate(lut).astype(np.float32))
    return luts


def apply_luts(rgb: np.ndarray, luts: list[np.ndarray]) -> np.ndarray:
    positions = np.clip(rgb * 255, 0, 255)
    output = np.empty_like(rgb)
    for channel, lut in enumerate(luts):
        output[:, :, channel] = np.interp(positions[:, :, channel], np.arange(256), lut)
    return np.clip(output, 0, 1)


def sample_pair(source: np.ndarray, target: np.ndarray, limit: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    source, target = source.reshape(-1, 3), target.reshape(-1, 3)
    luma = target @ LUMA
    indices = np.flatnonzero((luma > 0.015) & (luma < 0.985))
    if len(indices) > limit:
        indices = np.random.default_rng(seed).choice(indices, limit, replace=False)
    return source[indices], target[indices]


def stats(image: np.ndarray) -> dict:
    pixels = image[int(image.shape[0] * .10):int(image.shape[0] * .90),
                   int(image.shape[1] * .10):int(image.shape[1] * .90)].reshape(-1, 3)
    luma = pixels @ LUMA
    return {"median_luma": float(np.median(luma)), "channel_median_rgb": np.median(pixels, axis=0).tolist(),
            "highlight_fraction": float(np.mean(np.max(pixels, axis=1) > .99)),
            "shadow_fraction": float(np.mean(np.max(pixels, axis=1) < .01))}


def save_jpeg(image: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.uint8(np.clip(image, 0, 1) * 255 + .5), "RGB").save(path, quality=95, subsampling=0)


def sheet(paths: list[Path], destination: Path) -> None:
    width, height = 390, 330
    canvas = Image.new("RGB", (width * len(paths), height), (24, 24, 24))
    draw = ImageDraw.Draw(canvas)
    for index, path in enumerate(paths):
        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((width - 12, height - 42), Image.Resampling.LANCZOS)
            canvas.paste(image, (index * width + 6, 32))
        draw.text((index * width + 8, 8), path.parent.name, fill="white")
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, quality=94)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("/mnt/GrokCam/projects/RAW_Test/raw"))
    parser.add_argument("--darktable", type=Path, default=Path("darktable-cli"))
    parser.add_argument("--work-dir", type=Path, default=Path("work/rawpy-darktable-match-poc"))
    parser.add_argument("--output-dir", type=Path, default=Path("/mnt/GrokCam/projects/RAW_Test/outputs/rawpy-darktable-match-poc"))
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--wb-report", type=Path, default=Path("/mnt/GrokCam/projects/RAW_Test/outputs/sprocket-white-poc/poc-report.json"))
    parser.add_argument("--keep-tiffs", action="store_true")
    args = parser.parse_args()
    args.raw_dir = args.raw_dir.expanduser().resolve()
    args.work_dir = args.work_dir.resolve()
    args.output_dir = args.output_dir.resolve()
    args.wb_report = args.wb_report.expanduser().resolve()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = json.loads(args.wb_report.read_text(encoding="utf-8"))
    rgb_correction = np.asarray(report["render_correction_RGB_relative_to_embedded_D65"], dtype=np.float32)
    wb_correction = np.array([rgb_correction[0], rgb_correction[1], rgb_correction[2], rgb_correction[1]])
    numbers = [number for _, group in GROUPS for number in group]
    reference_dir, configs_dir = args.work_dir / "darktable", args.work_dir / "configs"
    reference_dir.mkdir(parents=True, exist_ok=True)
    configs_dir.mkdir(parents=True, exist_ok=True)

    def develop(number: int) -> None:
        source = args.raw_dir / f"frame_{number:06d}.dng"
        config = configs_dir / f"frame_{number:06d}"
        config.mkdir(parents=True, exist_ok=True)
        run([str(args.darktable), str(source), str(reference_dir / f"frame_{number:06d}.tif"), "--core",
             "--configdir", str(config), "--conf", "plugins/imageio/format/tiff/bpp=16",
             "--conf", "plugins/imageio/format/tiff/compress=1"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        list(pool.map(develop, numbers))

    pairs = {}
    for number in numbers:
        darktable = image_array(reference_dir / f"frame_{number:06d}.tif")
        raw = render_raw(args.raw_dir / f"frame_{number:06d}.dng", wb_correction)
        preview = Image.fromarray(np.uint8(np.clip(darktable * 255, 0, 255)))
        _, anchor_x, anchor_y = detect_anchor(preview)
        pairs[number] = {"raw": crop_register(raw, (anchor_x, anchor_y)),
                         "darktable": crop_register(darktable, (anchor_x, anchor_y))}

    train_numbers = [number for _, group in GROUPS[:-2] for number in group]
    holdout_numbers = [number for _, group in GROUPS[-2:] for number in group]
    train_raw, train_darktable = [], []
    for number in train_numbers:
        raw_sample, darktable_sample = sample_pair(pairs[number]["raw"], pairs[number]["darktable"], 12000, number)
        train_raw.append(raw_sample)
        train_darktable.append(darktable_sample)
    coefficients = fit_matrix(train_raw, train_darktable)
    transformed_train = [apply_matrix(values.reshape(-1, 1, 3), coefficients).reshape(-1, 3) for values in train_raw]
    luts = fit_luts(transformed_train, train_darktable)
    metrics, output_paths = [], {}
    for number in numbers:
        raw_crop, darktable_crop = pairs[number]["raw"], pairs[number]["darktable"]
        matched = apply_luts(apply_matrix(raw_crop, coefficients), luts)
        paths = {name: args.output_dir / "frames" / name / f"frame_{number:06d}.jpg" for name in
                 ("darktable_reference", "rawpy_unmatched", "rawpy_darktable_matched")}
        save_jpeg(darktable_crop, paths["darktable_reference"])
        save_jpeg(raw_crop, paths["rawpy_unmatched"])
        save_jpeg(matched, paths["rawpy_darktable_matched"])
        output_paths[number] = paths
        metrics.append({"frame": number, "split": "holdout" if number in holdout_numbers else "train",
                        "mean_absolute_rgb_error": float(np.mean(np.abs(matched - darktable_crop))),
                        "darktable": stats(darktable_crop), "matched": stats(matched)})

    for group, group_numbers in GROUPS:
        number = list(group_numbers)[0]
        sheet([output_paths[number][name] for name in ("darktable_reference", "rawpy_unmatched", "rawpy_darktable_matched")],
              args.output_dir / "groups" / f"{group}.jpg")
    if not args.keep_tiffs:
        shutil.rmtree(reference_dir, ignore_errors=True)
        shutil.rmtree(configs_dir, ignore_errors=True)
    result = {"poc": "grokcam_rawpy_darktable_match_poc", "version": VERSION, "created": now(),
              "source_policy": "read_only", "selected_frames": numbers, "train_frames": train_numbers,
              "holdout_frames": holdout_numbers, "darktable": str(args.darktable), "raw_dir": str(args.raw_dir),
              "fit": {"model": "quadratic RGB matrix followed by monotonic per-channel LUT",
                      "sample_limit_per_frame": 12000, "coefficients": coefficients.tolist(),
                      "luts": [lut.tolist() for lut in luts], "white_balance_correction": wb_correction.tolist()},
              "metrics": metrics, "tools": {"python": platform.python_version(), "numpy": np.__version__,
              "rawpy": rawpy.__version__}, "output_dir": str(args.output_dir)}
    (args.output_dir / "poc-report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "index.md").write_text("# rawpy to Darktable matching POC\n\n"
        "Each group sheet shows Darktable reference, unmatched rawpy, and fitted rawpy output.\n\n"
        "The first six scene groups train the global fit. The final two groups are held out for validation.\n\n"
        "See `poc-report.json` for the fitted transform and per-frame RGB errors.\n", encoding="utf-8")
    print(args.output_dir / "index.md")


if __name__ == "__main__":
    main()