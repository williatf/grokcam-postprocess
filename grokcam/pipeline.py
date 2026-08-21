"""Production pipeline assembly.

The batch lifecycle remains in the proven runner for this release.  Stage
implementations are injected here explicitly, replacing the former wrapper's
implicit global monkey-patch with one documented composition point.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from .config import ProductionCalibration
from .models import SprocketDetection
from .raw_development import DarktableMatchedDeveloper
from .sprocket_detection import detect, validate_batch


def _load_batch_runner():
    path = Path(__file__).resolve().parents[1] / "scripts" / "grokcam_raw_production_with_timings.py"
    spec = importlib.util.spec_from_file_location("grokcam._batch_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load production batch runner: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run(calibration: ProductionCalibration, argv: list[str]) -> None:
    runner = _load_batch_runner()
    developer = DarktableMatchedDeveloper(calibration.match.report.expanduser().resolve())

    def develop_one(dng: Path, tiff: Path) -> None:
        developer.develop(dng, tiff)

    def detect_anchor(image: Image.Image) -> tuple[float, float, float]:
        result = detect(image, calibration.detector)
        return float(result.score), result.cx, result.cy

    def robust_anchors(raw: np.ndarray, detected_mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        items = [None if not detected_mask[i] else
                 SprocketDetection(float(raw[i, 0]), float(raw[i, 1]), None)
                 for i in range(len(raw))]
        results = validate_batch(items, calibration.detector)
        coordinates = np.array([(item.cx, item.cy) for item in results])
        accepted = np.array([item.accepted for item in results], dtype=bool)
        return coordinates, accepted

    runner.develop_one_rawpy = develop_one
    runner.detect_anchor = detect_anchor
    runner.robust_anchors = robust_anchors
    runner.PRESETS = {"loose": {"x_offset": calibration.crop.x_offset,
                                "y_offset": calibration.crop.y_offset,
                                "width": calibration.crop.width,
                                "height": calibration.crop.height}}
    previous = sys.argv
    try:
        sys.argv = ["grokcam-process-reel", *argv]
        runner.main()
    finally:
        sys.argv = previous
