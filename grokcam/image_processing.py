"""Golden crop/orientation and restrained reel normalization."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageEnhance

from .models import CropGeometry


def registered_frame(image: Image.Image, crop: CropGeometry, contrast: float = 1.04) -> Image.Image:
    output = image.convert("RGB").transform(
        (crop.width, crop.height), Image.Transform.EXTENT,
        (crop.left, crop.top, crop.left + crop.width, crop.top + crop.height),
        resample=Image.Resampling.BICUBIC,
    )
    output = output.rotate(180, expand=False).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    return ImageEnhance.Contrast(output).enhance(contrast)


def rolling_median(values: np.ndarray, radius: int = 4) -> np.ndarray:
    return np.array([np.median(values[max(0, i-radius):min(len(values), i+radius+1)], axis=0)
                     for i in range(len(values))])
