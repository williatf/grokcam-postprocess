"""Golden crop/orientation and restrained reel normalization."""

from __future__ import annotations

import numpy as np
import cv2
from PIL import Image, ImageEnhance

from .models import CropGeometry


def registered_frame(image: Image.Image, crop: CropGeometry, contrast: float = 1.04,
                     vertical_flip: bool = True) -> Image.Image:
    output = image.convert("RGB").transform(
        (crop.width, crop.height), Image.Transform.EXTENT,
        (crop.left, crop.top, crop.left + crop.width, crop.top + crop.height),
        resample=Image.Resampling.BICUBIC,
    )
    # The historical Regular 8 transform is equivalent to a vertical flip.
    # Keep that default for compatibility, while allowing format-specific
    # rendering to state its orientation explicitly.
    if vertical_flip:
        output = output.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    return ImageEnhance.Contrast(output).enhance(contrast)


def rgb16_to_pillow(rgb: np.ndarray) -> Image.Image:
    """Convert a 16-bit RGB array to the 8-bit view used by detectors."""
    return Image.fromarray(np.uint8(np.clip(rgb.astype(np.float32) / 257.0 + .5, 0, 255)), "RGB")


def registered_frame_16bit(rgb: np.ndarray, crop: CropGeometry,
                           contrast: float = 1.04,
                           vertical_flip: bool = True) -> np.ndarray:
    """Crop/orient/contrast a developed RGB frame without reducing bit depth."""
    xs = (crop.left + np.arange(crop.width, dtype=np.float32) + .5)[None, :]
    ys = (crop.top + np.arange(crop.height, dtype=np.float32) + .5)[:, None]
    map_x = np.broadcast_to(xs, (crop.height, crop.width)).copy()
    map_y = np.broadcast_to(ys, (crop.height, crop.width)).copy()
    output = cv2.remap(rgb, map_x, map_y, cv2.INTER_CUBIC,
                       borderMode=cv2.BORDER_REPLICATE)
    if vertical_flip:
        output = cv2.flip(output, 0)
    values = output.astype(np.float32)
    gray = values @ np.array([.299, .587, .114], dtype=np.float32)
    gray_mean = float(gray.mean())
    values = gray_mean + (values - gray_mean) * float(contrast)
    return np.uint16(np.clip(values, 0, 65535) + .5)


def rolling_median(values: np.ndarray, radius: int = 4) -> np.ndarray:
    return np.array([np.median(values[max(0, i-radius):min(len(values), i+radius+1)], axis=0)
                     for i in range(len(values))])
