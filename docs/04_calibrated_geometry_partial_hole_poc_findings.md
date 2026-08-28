# Calibrated-Geometry Partial-Hole POC

## Scope and data protection

This isolated revision was evaluated only on the frozen 198-frame Reel_46335
problem population from the capture-seeded physical-hole POC. The existing
physical-hole detector was imported unchanged and remains the baseline. No
production source, calibration, DNG, manifest, or prior POC output was changed.

The interrupted blind-validation package was excluded from development and
analysis. No blind answers or browser local-storage values were read. Existing
human annotations remain protected evaluation data.

## Frozen geometry and method

The model uses Blue-derived physical geometry: 381.5842 px hole width, 272.0 px
hole height, 785.0 px pitch, and +18.6789 px normal lower-minus-upper X offset.
A confident intact partner predicts the damaged partner ROI. Independent X/Y
gradient profiles and corner transitions generate landmark hypotheses. A single
wall, edge, or corner anchors the fixed-size model; all other detected features
are corroboration. The damaged contour never determines hole dimensions.

Acceptance still requires same-frame image contrast, multiple boundary feature
classes, adequate model score, competitor separation, landmark agreement,
pair-pitch/X checks, and the existing sprocket-X-domain safeguard. Geometry
alone cannot accept a frame.

## Results

| Result | Frames |
|---|---:|
| Problem population | 198 |
| Existing detector now succeeds normally | 24 |
| Calibrated-geometry recoveries | 62 |
| Unresolved | 136 |
| Insufficient partner evidence | 47 |
| Capture prior / ROI incorrect | 46 |
| Both holes damaged or ambiguous | 19 |

Recoveries by original failure class were 51 size/shape, 6 ROI-edge escape, and
5 ineligible-capture cases. Anchor sources were 24 bottom edges, 20 top edges,
8 right walls, 6 left walls, and 4 corners. Ten recoveries had all eight modeled
features; all accepted cases had the required mix of independently measured
walls, edges, and corners.

Across accepted models, the median landmark residual was 13.56 px and the P95
of per-model median residual was 23.04 px. The maximum per-model median was
24.67 px. One isolated unmatched feature produced a 372.97 px maximum residual;
the other features on that model agreed and the frame was retained for blind
validation rather than used to tune the detector.

Compared with the prior contour-fit POC, recoveries fell from 88 to 62: 53 were
retained, 9 were newly recovered, and 35 prior acceptances were conservatively
dropped. This is the intended safety trade: damage cannot stretch or translate
the calibrated hole shape.

## Required regressions

- Frame 42 is recovered from a right-wall anchor corroborated by a top edge and
  four corner regions. Its fixed 381.5842 x 272.0 px model is centered at the
  calibrated location; the torn lower contour does not pull the box downward.
- Frame 3341 remains rejected as `capture_prior_roi_incorrect`; no physical model
  or registration anchor is emitted.

Eight accepted frames were conservatively flagged for blind/manual review based
on elevated residual summaries: 43, 1677, 2082, 2090, 2103, 2234, 2604, and
3902. Their detector-only review panels show plausible physical alignment, but
that visual audit is not ground truth and did not alter the frozen parameters.

## Conclusion

The revision is sufficiently frozen to restart blind validation. This is not a
production-integration recommendation: the lower recovery count and eight
flagged acceptances make blind localization and false-registration measurement
the required next gate. The prior completed annotations should be preserved as
a separate protected dataset; a restarted review should use a new package/key
and must not silently reuse or overwrite them.

Frozen implementation hashes:

- `p04_calibrated_geometry_partial_hole_poc.py`: `30ffd450697e37f30f0d2cb2b307208d811df6436c3ff6c8be0f0ef92352a827`
- `p04_calibrated_geometry_partial_hole_blue_frozen.json`: `1bbbd84e36cd0a8a3e8ab9449e3939a433c801efd81feca2cdb6a6568c39fb76`
- `test_p04_calibrated_geometry_partial_hole_poc.py`: `9f8dd600605323677b90d28aca672d8076dc6758e444cfc63d1fa26239e31c6d`
