"""Golden restrained per-reel exposure and color normalization."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from .image_processing import rolling_median


def analyze_picture(path: Path) -> tuple[float, np.ndarray]:
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0
    height, width = rgb.shape[:2]
    roi = rgb[int(height * .12):int(height * .88), int(width * .15):int(width * .92)].reshape(-1, 3)
    luma = roi @ np.array([.2126, .7152, .0722], dtype=np.float32)
    usable = roi[(luma > .03) & (luma < .96)]
    if len(usable) < 100:
        usable = roi
    weights = np.array([.2126, .7152, .0722])
    return float(np.median(usable @ weights)), np.median(usable, axis=0)


def normalize_frames(paths: list[Path], output_dir: Path,
                     target_luma: float | None = None) -> tuple[list[dict], float]:
    measurements = [analyze_picture(path) for path in paths]
    luma = np.array([value[0] for value in measurements])
    channels = np.array([value[1] for value in measurements])
    target = float(np.median(luma)) if target_luma is None else float(target_luma)
    exposure = np.clip(target / np.maximum(luma, .03), 2 ** -.65, 2 ** .65)
    neutral = np.exp(np.mean(np.log(np.maximum(channels, .02)), axis=1))
    gains = np.clip(neutral[:, None] / np.maximum(channels, .02), .78, 1.28)
    gains = 1 + (gains - 1) * .25
    exposure = rolling_median(exposure[:, None])[:, 0]
    gains = rolling_median(gains)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for path, exp, gain, measured in zip(paths, exposure, gains, measurements):
        rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0
        corrected = rgb * exp * gain.reshape(1, 1, 3)
        corrected = np.clip(corrected / (1 + .12 * corrected), 0, 1)
        destination = output_dir / path.name
        Image.fromarray(np.uint8(corrected * 255 + .5), "RGB").save(
            destination, quality=95, subsampling=0)
        results.append({"median_luma": measured[0], "channel_median": measured[1].tolist(),
                        "exposure_gain": float(exp), "channel_gains_rgb": gain.tolist()})
    return results, target
