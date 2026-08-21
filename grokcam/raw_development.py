"""Learned rawpy renderer that reproduces the approved Darktable appearance."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rawpy
import tifffile


MATCH_MODEL = "quadratic RGB matrix followed by monotonic per-channel LUT"


def load_match_report(path: Path) -> dict:
    report = json.loads(path.read_text(encoding="utf-8"))
    fit = report.get("fit", {})
    if fit.get("model") != MATCH_MODEL:
        raise ValueError(f"unsupported match model in {path}")
    if len(fit.get("coefficients", [])) != 13:
        raise ValueError(f"expected 13 transform rows in {path}")
    if len(fit.get("luts", [])) != 3 or any(len(lut) != 256 for lut in fit["luts"]):
        raise ValueError(f"expected three 256-entry LUTs in {path}")
    if len(fit.get("white_balance_correction", [])) != 4:
        raise ValueError(f"expected four white-balance values in {path}")
    return report


def features(rgb: np.ndarray) -> np.ndarray:
    r, g, b = rgb.T
    return np.column_stack((np.ones(len(rgb)), r, g, b, np.sqrt(np.maximum(rgb, 0)),
                            r * r, g * g, b * b, r * g, r * b, g * b))


def apply_match(rgb: np.ndarray, fit: dict) -> np.ndarray:
    shape = rgb.shape
    flat = rgb.reshape(-1, 3)
    coefficients = np.asarray(fit["coefficients"], dtype=np.float32)
    transformed = np.clip((features(flat) @ coefficients).reshape(shape), 0, 1)
    positions = np.clip(transformed * 255, 0, 255)
    output = np.empty_like(transformed)
    for channel, values in enumerate(fit["luts"]):
        lut = np.asarray(values, dtype=np.float32)
        output[:, :, channel] = np.interp(positions[:, :, channel], np.arange(256), lut)
    return np.clip(output, 0, 1)


class DarktableMatchedDeveloper:
    def __init__(self, report_path: Path):
        self.report_path = report_path
        self.report = load_match_report(report_path)

    def develop(self, dng: Path, tiff: Path) -> None:
        fit = self.report["fit"]
        correction = np.asarray(fit["white_balance_correction"], dtype=np.float32)
        with rawpy.imread(str(dng)) as raw:
            camera_wb = np.asarray(raw.camera_whitebalance[:3], dtype=np.float32)
            camera_wb = np.array([camera_wb[0], camera_wb[1], camera_wb[2], camera_wb[1]])
            rendered = raw.postprocess(
                demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
                use_camera_wb=False,
                user_wb=(camera_wb * correction).tolist(),
                output_bps=16,
                no_auto_bright=True,
                gamma=(1, 1),
                output_color=rawpy.ColorSpace.sRGB,
            )
        matched = apply_match(rendered.astype(np.float32) / 65535.0, fit)
        tifffile.imwrite(tiff, np.uint16(matched * 65535 + 0.5))
