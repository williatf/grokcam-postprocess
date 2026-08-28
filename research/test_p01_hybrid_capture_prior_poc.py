from pathlib import Path

import numpy as np
import pytest

from grokcam.config import DetectorCalibration
from research.p01_hybrid_capture_prior_poc import actual_pair_prediction, measure_hole, transform_boxes


def metadata(mode="pair", source="pair_actual"):
    return {"raw_registration_mode": mode, "selected_source": source,
            "preview_width": 760, "preview_height": 570,
            "raw_width": 2028, "raw_height": 1520,
            "sprockets": [[150, 180, 140, 96, 1], [152, 474, 140, 96, 1]]}


def test_only_actual_pairs_are_seed_eligible():
    assert actual_pair_prediction(metadata()) is not None
    assert actual_pair_prediction(metadata("single", "single_estimated")) is None
    assert actual_pair_prediction(metadata("none", "held_last_good")) is None


def test_preview_boxes_transform_by_recorded_dimensions():
    boxes = transform_boxes(metadata())
    assert boxes is not None
    assert boxes[0] == pytest.approx((400.2631578947368, 480.0, 373.57894736842104, 256.0))


def test_full_resolution_bright_band_is_remeasured():
    bright = np.zeros((1520, 2028), dtype=bool)
    bright[360:600, 220:585] = True
    predicted = (400.0, 480.0, 374.0, 256.0)
    measured = measure_hole(bright, predicted, DetectorCalibration())
    assert measured is not None
    assert measured.cx == 395.0
    assert measured.cy == 480.0


def test_picture_content_outside_seed_roi_is_not_selected():
    bright = np.zeros((1520, 2028), dtype=bool)
    bright[360:600, 900:1400] = True
    assert measure_hole(bright, (400.0, 480.0, 374.0, 256.0), DetectorCalibration()) is None
