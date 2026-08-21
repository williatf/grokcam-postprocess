"""Fit and evaluate the frozen Darktable-match model family."""

from __future__ import annotations

import numpy as np

from grokcam.raw_development import apply_match, features

MODEL_NAME = "quadratic RGB matrix followed by monotonic per-channel LUT"
LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def fit_matrix(inputs: list[np.ndarray], targets: list[np.ndarray]) -> np.ndarray:
    coefficients, *_ = np.linalg.lstsq(
        features(np.concatenate(inputs)), np.concatenate(targets), rcond=1e-6)
    return coefficients


def apply_matrix(rgb: np.ndarray, coefficients: np.ndarray) -> np.ndarray:
    shape = rgb.shape
    return np.clip((features(rgb.reshape(-1, 3)) @ coefficients).reshape(shape), 0, 1)


def fit_luts(predictions: list[np.ndarray], targets: list[np.ndarray],
             bins: int = 256) -> list[np.ndarray]:
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
        if not valid.any():
            raise ValueError(f"no samples available to fit LUT channel {channel}")
        lut = np.interp(np.arange(bins), np.flatnonzero(valid), lut[valid])
        luts.append(np.maximum.accumulate(lut).astype(np.float32))
    return luts


def sample_pair(source: np.ndarray, target: np.ndarray, limit: int,
                seed: int) -> tuple[np.ndarray, np.ndarray]:
    source, target = source.reshape(-1, 3), target.reshape(-1, 3)
    luma = target @ LUMA
    indices = np.flatnonzero((luma > 0.015) & (luma < 0.985))
    if len(indices) > limit:
        indices = np.random.default_rng(seed).choice(indices, limit, replace=False)
    return source[indices], target[indices]


def fit_model(inputs: list[np.ndarray], targets: list[np.ndarray]) -> dict:
    coefficients = fit_matrix(inputs, targets)
    transformed = [apply_matrix(values.reshape(-1, 1, 3), coefficients).reshape(-1, 3)
                   for values in inputs]
    luts = fit_luts(transformed, targets)
    return {"model": MODEL_NAME, "sample_limit_per_frame": 12000,
            "coefficients": coefficients.tolist(), "luts": [lut.tolist() for lut in luts]}


def apply_model(image: np.ndarray, fit: dict) -> np.ndarray:
    return apply_match(image, fit)


def image_stats(image: np.ndarray) -> dict:
    pixels = image[int(image.shape[0] * .10):int(image.shape[0] * .90),
                   int(image.shape[1] * .10):int(image.shape[1] * .90)].reshape(-1, 3)
    luma = pixels @ LUMA
    return {"median_luma": float(np.median(luma)),
            "channel_median_rgb": np.median(pixels, axis=0).tolist(),
            "highlight_fraction": float(np.mean(np.max(pixels, axis=1) > .99)),
            "shadow_fraction": float(np.mean(np.max(pixels, axis=1) < .01))}
