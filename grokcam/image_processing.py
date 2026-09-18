"""Golden crop/orientation and restrained reel normalization."""

from __future__ import annotations

import numpy as np
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


def rolling_median(values: np.ndarray, radius: int = 4) -> np.ndarray:
    return np.array([np.median(values[max(0, i-radius):min(len(values), i+radius+1)], axis=0)
                     for i in range(len(values))])
