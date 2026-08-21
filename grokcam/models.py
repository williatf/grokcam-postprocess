"""Structured values passed between production processing stages."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class SprocketDetection:
    cx: float
    cy: float
    score: float | None
    detector: str = "luminance_pair"
    detected: bool = True
    accepted: bool = True
    interpolated: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CropGeometry:
    left: float
    top: float
    width: int
    height: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FrameRecord:
    frame: int
    source_name: str
    source_bytes: int
    detection: SprocketDetection
    crop: CropGeometry
    normalization: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        # Preserve the golden manifest's flat fields for downstream consumers,
        # while adding explicit coordinate-system metadata.
        return {
            "frame": self.frame,
            "source_name": self.source_name,
            "source_bytes": self.source_bytes,
            "anchor_x": self.detection.cx,
            "anchor_y": self.detection.cy,
            "detected": self.detection.detected,
            "accepted": self.detection.accepted,
            "detector_score": self.detection.score,
            "detector": self.detection.detector,
            "interpolated": self.detection.interpolated,
            "crop_left": self.crop.left,
            "crop_top": self.crop.top,
            "crop_width": self.crop.width,
            "crop_height": self.crop.height,
            "coordinate_system": "developed_frame_pixels",
            "normalization": self.normalization,
        }
