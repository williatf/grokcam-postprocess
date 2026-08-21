#!/usr/bin/env python3
"""Compare faster rawpy rendering choices against the current production path."""

from __future__ import annotations

import argparse
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

try:
    import rawpy
except ImportError as exc:
    raise SystemExit(
        "rawpy is required; use the project environment, for example "
        "/home/todd/telecine/.venv/bin/python"
    ) from exc

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
VARIANTS = [
    "current_ahd_camera_wb_8bit",
    "calibrated_ahd_16bit",
    "calibrated_amaze_16bit",
]
LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def roi_pixels(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    return image[int(height * 0.10):int(height * 0.90),
                 int(width * 0.10):int(width * 0.90)].reshape(-1, 3)


def stats(image: np.ndarray) -> dict:
    pixels = roi_pixels(image)
    luma = pixels @ LUMA
    usable = pixels[(luma > 0.025) & (luma < 0.975)]
    if len(usable) < 100:
        usable = pixels
    usable_luma = usable @ LUMA
    return {
        "median_luma": float(np.median(usable_luma)),
        "channel_median_rgb": np.median(usable, axis=0).tolist(),
        "shadow_fraction": float(np.mean(np.max(pixels, axis=1) < 0.01)),
        "highlight_fraction": float(np.mean(np.max(pixels, axis=1) > 0.99)),
        "channel_clip_fraction_rgb": [
            float(np.mean(pixels[:, index] > 0.995)) for index in range(3)
        ],
    }


def load_calibrated_wb(path: Path) -> tuple[list[float], dict]:
    if not path.exists():
        raise FileNotFoundError(
            f"white-balance report not found: {path}; pass --wb-report or run "
            "the sprocket-white POC first"
        )
    report = json.loads(path.read_text(encoding="utf-8"))
    correction = report.get("render_correction_RGB_relative_to_embedded_D65")
    if not correction or len(correction) != 3:
        raise ValueError(f"white-balance correction missing from {path}")
    rgb_correction = [float(value) for value in correction]
    # rawpy expects RGBG: red, green, blue, and the second green plane.
    return [rgb_correction[0], rgb_correction[1], rgb_correction[2], rgb_correction[1]], {
        "report": str(path),
        "render_correction_RGB_relative_to_embedded_D65": rgb_correction,
        "rawpy_user_wb_RGBG_correction": [rgb_correction[0], rgb_correction[1], rgb_correction[2], rgb_correction[1]],
    }


def render_raw(path: Path, demosaic: str, wb: str, wb_correction: list[float] | None) -> np.ndarray:
    kwargs = {
        "demosaic_algorithm": getattr(rawpy.DemosaicAlgorithm, demosaic),
        "output_bps": 16,
        "no_auto_bright": True,
        "gamma": (1, 1),
        "output_color": rawpy.ColorSpace.sRGB,
    }
    if wb == "camera":
        kwargs["use_camera_wb"] = True
    else:
        kwargs["use_camera_wb"] = False
    with rawpy.imread(str(path)) as raw:
        if wb == "user":
            camera_wb = np.asarray(raw.camera_whitebalance[:3], dtype=np.float32)
            camera_wb = np.array([camera_wb[0], camera_wb[1], camera_wb[2], camera_wb[1]])
            kwargs["user_wb"] = (camera_wb * np.asarray(wb_correction, dtype=np.float32)).tolist()
        return raw.postprocess(**kwargs)


def supports_amaze(source: Path, wb_correction: list[float]) -> tuple[bool, str | None]:
    try:
        render_raw(source, "AMAZE", "user", wb_correction)
    except rawpy.NotSupportedError as exc:
        return False, str(exc)
    return True, None


def filmic_render(rgb16: np.ndarray) -> np.ndarray:
    image = np.maximum(rgb16.astype(np.float32) / 65535.0, 1e-6)
    median_luma = float(np.median(image @ LUMA))
    if median_luma < 0.04:
        midtone_lift, dynamic_range, shoulder_power = 0.22, 11.5, 1.15
    elif median_luma < 0.09:
        midtone_lift, dynamic_range, shoulder_power = 0.17, 12.0, 1.25
    else:
        midtone_lift, dynamic_range, shoulder_power = 0.10, 12.5, 1.40
    x = np.clip((np.log2(image) + dynamic_range) / dynamic_range, 0.0, 1.0)
    toe = np.power(x, 1.45)
    shoulder = 1.0 - np.power(1.0 - x, shoulder_power)
    blend = np.clip((x - 0.2) / 0.6, 0.0, 1.0)
    output = (1.0 - blend) * toe + blend * shoulder
    output = np.clip(output + midtone_lift * (1.0 - output) * output * 4.0, 0.0, 1.0)
    luma = output @ LUMA
    sat_fade = np.clip(1.0 - (luma - 0.82) / 0.18, 0.35, 1.0)
    output = luma[:, :, None] + sat_fade[:, :, None] * (output - luma[:, :, None])
    return np.clip(output, 0.0, 1.0)


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


def normalize(images: dict[int, np.ndarray]) -> tuple[dict[int, np.ndarray], float]:
    measurements = {number: stats(image) for number, image in images.items()}
    luma = np.array([row["median_luma"] for row in measurements.values()])
    channels = np.array([row["channel_median_rgb"] for row in measurements.values()])
    target = float(np.median(luma))
    exposure = np.clip(target / np.maximum(luma, 0.03), 2 ** -0.65, 2 ** 0.65)
    neutral = np.exp(np.mean(np.log(np.maximum(channels, 0.02)), axis=1))
    gains = np.clip(neutral[:, None] / np.maximum(channels, 0.02), 0.78, 1.28)
    gains = 1 + (gains - 1) * 0.25
    normalized = {}
    for index, number in enumerate(images):
        image = images[number] * exposure[index] * gains[index].reshape(1, 1, 3)
        normalized[number] = np.clip(image / (1 + 0.12 * image), 0, 1)
    return normalized, target


def save_review(image: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.uint8(np.clip(image, 0, 1) * 255 + 0.5), "RGB").save(path, quality=95, subsampling=0)


def contact_sheet(paths: list[Path], destination: Path) -> None:
    tile_width, tile_height = 380, 330
    canvas = Image.new("RGB", (tile_width * 3, tile_height * ((len(paths) + 2) // 3)), (24, 24, 24))
    draw = ImageDraw.Draw(canvas)
    for index, path in enumerate(paths):
        image = Image.open(path).convert("RGB")
        image.thumbnail((tile_width - 12, tile_height - 42), Image.Resampling.LANCZOS)
        x, y = (index % 3) * tile_width, (index // 3) * tile_height
        canvas.paste(image, (x + 6, y + 32))
        draw.text((x + 8, y + 8), path.parent.name, fill="white")
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, quality=94)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("/mnt/GrokCam/projects/RAW_Test/raw"))
    parser.add_argument("--work-dir", type=Path, default=Path("work/rawpy-quality-poc"))
    parser.add_argument("--output-dir", type=Path, default=Path("/mnt/GrokCam/projects/RAW_Test/outputs/rawpy-quality-poc"))
    parser.add_argument("--wb-report", type=Path, default=Path("/mnt/GrokCam/projects/RAW_Test/outputs/sprocket-white-poc/poc-report.json"))
    args = parser.parse_args()
    args.work_dir = args.work_dir.resolve()
    args.output_dir = args.output_dir.resolve()
    args.raw_dir = args.raw_dir.expanduser().resolve()
    args.wb_report = args.wb_report.expanduser().resolve()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    user_wb, wb_source = load_calibrated_wb(args.wb_report)
    selected = [number for _, numbers in GROUPS for number in numbers]
    records = []
    amaze_available, amaze_error = supports_amaze(args.raw_dir / f"frame_{selected[0]:06d}.dng", user_wb)
    active_variants = VARIANTS if amaze_available else VARIANTS[:2]
    timings = {variant: 0.0 for variant in active_variants}
    variant_images = {variant: {} for variant in active_variants}
    anchors = {}

    for number in selected:
        source = args.raw_dir / f"frame_{number:06d}.dng"
        quick = render_raw(source, "AHD", "camera", None)
        anchor_image = Image.fromarray(np.uint8(np.clip(quick / 65535.0, 0, 1) * 255 + 0.5), "RGB")
        try:
            _, anchor_x, anchor_y = detect_anchor(anchor_image)
        except ValueError:
            anchor_image = Image.fromarray(np.uint8(np.clip(filmic_render(quick), 0, 1) * 255 + 0.5), "RGB")
            _, anchor_x, anchor_y = detect_anchor(anchor_image)
        anchors[number] = {"x": anchor_x, "y": anchor_y}
        for variant in active_variants:
            started = time.perf_counter()
            demosaic = "AHD" if variant != "calibrated_amaze_16bit" else "AMAZE"
            wb = "camera" if variant == "current_ahd_camera_wb_8bit" else "user"
            rendered = filmic_render(render_raw(source, demosaic, wb, user_wb))
            cropped = crop_register(rendered, (anchor_x, anchor_y))
            cropped = np.clip((cropped - 0.5) * 1.04 + 0.5, 0, 1)
            if variant == "current_ahd_camera_wb_8bit":
                cropped = np.uint8(cropped * 255 + 0.5).astype(np.float32) / 255.0
            variant_images[variant][number] = cropped
            timings[variant] += time.perf_counter() - started

    for variant in active_variants:
        normalized, target = normalize(variant_images[variant])
        variant_images[variant] = normalized
        for number, image in normalized.items():
            output = args.output_dir / "frames" / variant / f"frame_{number:06d}.jpg"
            save_review(image, output)
            row = stats(image)
            row.update({"frame": number, "variant": variant, "normalization_target": target})
            records.append(row)

    for number in selected:
        paths = [args.output_dir / "frames" / variant / f"frame_{number:06d}.jpg" for variant in active_variants]
        contact_sheet(paths, args.output_dir / "comparisons" / f"frame_{number:06d}.jpg")
    for group, numbers in GROUPS:
        for variant in active_variants:
            paths = [args.output_dir / "frames" / variant / f"frame_{number:06d}.jpg" for number in numbers]
            contact_sheet(paths, args.output_dir / "groups" / group / f"{variant}.jpg")

    report = {
        "poc": "grokcam_rawpy_quality_poc", "version": VERSION, "created": now(),
        "source_policy": "read_only", "raw_dir": str(args.raw_dir), "selected_frames": selected,
        "groups": [name for name, _ in GROUPS],
        "variants": {
            "current_ahd_camera_wb_8bit": "AHD, embedded camera WB, current tone curve and normalization, JPEG only for review output",
            "calibrated_ahd_16bit": "AHD, sprocket-calibrated user WB, float/16-bit processing until review JPEG",
            "calibrated_amaze_16bit": "AMaZE, sprocket-calibrated user WB, float/16-bit processing until review JPEG",
        },
        "white_balance": wb_source, "timings_seconds": timings, "anchors": anchors,
        "available_variants": active_variants,
        "unavailable_variants": {"calibrated_amaze_16bit": amaze_error} if not amaze_available else {},
        "measurements": records,
        "tools": {"python": platform.python_version(), "numpy": np.__version__, "rawpy": rawpy.__version__},
        "output_dir": str(args.output_dir),
    }
    (args.output_dir / "poc-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    index_text = (
        "# rawpy quality POC\n\n"
        "Compare the three variants in `comparisons/`; group-level sheets are under `groups/`.\n\n"
        "The calibrated variants use the sprocket-white correction and keep floating-point image data until the review JPEG is written.\n\n"
        f"Available variants in this run: {', '.join(active_variants)}.\n\n"
    )
    if not amaze_available:
        index_text += f"AMaZE was unavailable: {amaze_error}\n\n"
    index_text += "See `poc-report.json` for exact settings, timings, white-balance provenance, and metrics.\n"
    (args.output_dir / "index.md").write_text(index_text, encoding="utf-8")
    print(args.output_dir / "index.md")


if __name__ == "__main__":
    main()