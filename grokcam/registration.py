"""Sprocket-referenced crop geometry."""

from .config import CropCalibration
from .models import CropGeometry, SprocketDetection


def crop_for_detection(detection: SprocketDetection, calibration: CropCalibration) -> CropGeometry:
    return CropGeometry(detection.cx + calibration.x_offset, detection.cy + calibration.y_offset,
                        calibration.width, calibration.height)
