"""Adapter for the existing production luminance-pair detector."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from PIL import Image

from ..config import DetectorCalibration
from ..models import SprocketDetection
from ..sprocket_detection import detect as detect_luminance_pair
from .base import DetectorDiagnostics, DetectorResult


class AdaptiveV1Detector:
    """State-free adapter; detection calculations remain in sprocket_detection."""

    name = "adaptive-v1"
    version = "1"
    stateful = False

    def __init__(self, calibration: DetectorCalibration, options: dict[str, Any] | None = None):
        if options:
            raise ValueError("adaptive-v1 does not accept sprocket detector options")
        self._calibration = calibration

    def detect(self, image: Image.Image) -> DetectorResult:
        try:
            detection = detect_luminance_pair(image, self._calibration)
        except ValueError as error:
            return DetectorResult(
                None,
                DetectorDiagnostics(self.name, self.version, False,
                                    details={"reason": str(error)}),
            )
        return DetectorResult(
            detection,
            DetectorDiagnostics(self.name, self.version, True,
                                details={"score": detection.score}),
        )

    def configuration(self) -> dict[str, Any]:
        return {"calibration": asdict(self._calibration), "options": {}}

    def get_state(self) -> dict[str, Any]:
        return {}

    def restore_state(self, state: dict[str, Any]) -> None:
        if state != {}:
            raise ValueError("adaptive-v1 has no restorable state")


def _factory(calibration: DetectorCalibration,
             options: dict[str, Any] | None = None) -> AdaptiveV1Detector:
    return AdaptiveV1Detector(calibration, options)
