"""Golden-manifest and image comparison utilities."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image


GEOMETRY_FIELDS = ("anchor_x", "anchor_y", "crop_left", "crop_top")


def frame_records(manifest: dict) -> dict[int, dict]:
    return {int(record["frame"]): record
            for segment in manifest.get("segments", [])
            for record in segment.get("frame_records", [])}


def compare_manifests(reference: Path, candidate: Path) -> dict:
    left = frame_records(json.loads(reference.read_text(encoding="utf-8")))
    right = frame_records(json.loads(candidate.read_text(encoding="utf-8")))
    common = sorted(set(left) & set(right))
    differences = {field: [abs(float(left[n][field]) - float(right[n][field])) for n in common]
                   for field in GEOMETRY_FIELDS}
    return {"reference_frames": len(left), "candidate_frames": len(right), "compared_frames": len(common),
            "missing_from_candidate": sorted(set(left) - set(right)),
            "maximum_geometry_difference": {k: max(v, default=0.0) for k, v in differences.items()},
            "detector_mismatches": sum(left[n].get("detected") != right[n].get("detected") for n in common),
            "acceptance_mismatches": sum(left[n].get("accepted") != right[n].get("accepted") for n in common)}


def compare_images(reference: Path, candidate: Path) -> dict:
    left = np.asarray(Image.open(reference).convert("RGB"), dtype=np.float64)
    right = np.asarray(Image.open(candidate).convert("RGB"), dtype=np.float64)
    if left.shape != right.shape:
        return {"reference_shape": left.shape, "candidate_shape": right.shape, "same_shape": False}
    delta = np.abs(left - right)
    mse = float(np.mean((left - right) ** 2))
    return {"same_shape": True, "mean_absolute_error": float(delta.mean()),
            "maximum_absolute_error": float(delta.max()), "mse": mse,
            "psnr_db": math.inf if mse == 0 else 20 * math.log10(255 / math.sqrt(mse))}
