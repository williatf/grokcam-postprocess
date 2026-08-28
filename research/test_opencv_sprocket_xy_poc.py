from __future__ import annotations

import cv2
import numpy as np

from research.opencv_sprocket_xy_poc import measure_frame


def test_detects_synthetic_upper_and_lower_openings() -> None:
    image = np.full((900, 1134, 3), 25, dtype=np.uint8)
    cv2.rectangle(image, (0, 80), (42, 225), (220, 220, 220), -1)
    cv2.rectangle(image, (0, 757), (40, 890), (210, 210, 210), -1)
    candidates = measure_frame(image, 1)
    top = next(item for item in candidates if item.region == "top")
    bottom = next(item for item in candidates if item.region == "bottom")
    assert abs(top.x - 40) < 5 and abs(top.y - 225) < 5
    assert abs(bottom.x - 38) < 5 and abs(bottom.y - 757) < 5

