"""Explicit composition point for the complete production execution path."""

from .batch import RunOptions, run_reel
from .config import ProductionCalibration


class ProductionPipeline:
    """Small facade owning the calibrated production stages and batch runner."""

    def __init__(self, calibration: ProductionCalibration):
        self.calibration = calibration

    def process_reel(self, options: RunOptions) -> None:
        run_reel(options, self.calibration)
