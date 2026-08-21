"""Production-equivalent geometry adapters for retained research scripts."""

from __future__ import annotations

from PIL import Image

from grokcam.config import ProductionCalibration
from grokcam.sprocket_detection import detect

_CALIBRATION = ProductionCalibration()
PRESETS = {"loose": {"x_offset": _CALIBRATION.crop.x_offset,
                     "y_offset": _CALIBRATION.crop.y_offset,
                     "width": _CALIBRATION.crop.width,
                     "height": _CALIBRATION.crop.height}}


def detect_anchor(image: Image.Image) -> tuple[float, float, float]:
    result = detect(image, _CALIBRATION.detector)
    return float(result.score), result.cx, result.cy


def subpixel_crop(image: Image.Image, left: float, top: float,
                  width: int, height: int) -> Image.Image:
    return image.transform((width, height), Image.Transform.EXTENT,
                           (left, top, left + width, top + height),
                           resample=Image.Resampling.BICUBIC)
