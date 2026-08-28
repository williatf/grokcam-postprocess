import numpy as np

from research.prepare_sprocket_ground_truth import BLUE_REQUIRED, stratified_frames


def test_blue_selection_is_exact_and_contains_regressions() -> None:
    frames = stratified_frames(3000, 3999, 75, BLUE_REQUIRED)
    assert len(frames) == 75
    assert len(set(frames)) == 75
    assert BLUE_REQUIRED <= set(frames)
    assert frames == sorted(frames)
    assert frames[0] == 3000 and frames[-1] == 3999
    assert max(np.diff(frames)) < 25
