"""Shared detector contract and structured per-frame results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from PIL import Image

from ..config import DetectorCalibration
from ..models import SprocketDetection


@dataclass(frozen=True)
class DetectorDiagnostics:
    detector: str
    version: str
    success: bool
    confidence: float | None = None
    fallback_used: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DetectorResult:
    detection: SprocketDetection | None
    diagnostics: DetectorDiagnostics


class SprocketDetector(Protocol):
    """Per-reel detector instance; implementations may retain sequential state."""

    name: str
    version: str
    stateful: bool

    def detect(self, image: Image.Image) -> DetectorResult:
        """Detect the sprocket pair in one image and return structured diagnostics."""

    def configuration(self) -> dict[str, Any]:
        """Return the JSON-compatible settings that affect detector output."""

    def get_state(self) -> dict[str, Any]:
        """Return JSON-compatible state suitable for a manifest checkpoint."""

    def restore_state(self, state: dict[str, Any]) -> None:
        """Restore a state previously returned by ``get_state``."""
