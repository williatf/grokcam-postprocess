# P05 Rigid-Consensus Partial-Hole POC

## Scope

P05 is an isolated revision of P04, evaluated on the same frozen 198-frame
Reel_46335 problem population. It did not read or start the protected blind
validation package and did not use human ground truth. Production code, prior
POC outputs, calibration, DNGs, and manifests were unchanged.

The physical template remains immutable: width 381.5842105263158 px, height
272.0 px, pitch 785.0 px, and lower-minus-upper X offset 18.678947368421063 px.
Scale, rotation, shape, pitch, and dimensions are never fitted.

## Method

Vertical walls vote only for template X, horizontal edges vote only for template
Y, and independently detected corners vote for both. Robust one-dimensional
consensus forms X/Y translation clusters while allowing at most one assignment
per raw observation in a cluster. Joint translation hypotheses are then scored
with the unchanged same-frame contrast and physical-evidence gates. Landmarks
beyond the 25 px Blue-frozen corroboration radius are recorded as outliers and
cannot move the selected template.

Diagnostics record every observed landmark residual, assignment/inlier state,
supporting landmark count, feature-class count, consensus count, median/maximum
inlier residual, competitor margin, and the five strongest competing
translations.

## Frozen-population result

| Metric | P04 single landmark | P05 rigid consensus |
|---|---:|---:|
| Recoveries | 62 | 53 |
| Unresolved | 136 | 145 |
| Retained P04 recoveries | — | 32 |
| Newly recovered | — | 21 |
| Dropped P04 recoveries | — | 30 |
| Median model-median residual | 13.56 px | 10.58 px |
| P95 model-median residual | 22.67 px | 13.00 px |
| Maximum model-median residual | 24.67 px | 13.00 px |
| Median model-maximum residual | 32.41 px | 23.09 px |
| Maximum accepted inlier residual | 372.97 px | 25.00 px |

P05 accepted 8 original `ineligible`, 5 `roi_edge_escape`, and 40
`size_shape` cases. Accepted models have 6–13 supporting landmarks and 4–6
independent feature classes. The acceptance population changed materially, so
the result must be reviewed rather than presumed equivalent to P04.

Twenty-two frames are conservatively called questionable because an accepted
inlier reached 24–25 px or the competing-hypothesis margin was below 0.05:
42, 43, 181, 326, 327, 343, 948, 1971, 2091, 2098, 2112, 2169, 2220, 2226,
2234, 2237, 2254, 2315, 2605, 2607, 2997, and 3337. This label is a review
queue, not a ground-truth judgment and was not used to alter parameters.

## Required frames

Frame 42 remains accepted. Seven landmarks across five feature classes support
the consensus: left/right walls, bottom edge, lower-left corner, and upper-right
corner. Median/max inlier residuals are 11.18/16.00 px. The P05 model center is
X=422.2079, Y=429.0, versus the derived P04 center X=460.2079, Y=391.5. The
consensus therefore moves the template 38 px left and 37.5 px down. Its left
boundary and visible corner evidence align substantially better in the review
panel, directly correcting the reported right-wall-anchor failure. Its competitor
margin is only 0.0349, so frame 42 remains in the explicit review queue.

Frame 3341 remains rejected as `capture_prior_roi_incorrect`. It emits no
template or final anchor; regression here would be a safety failure.

## Decision

P05 is a successful implementation of rigid consensus, but it is intentionally
not frozen as the next blind-validation candidate yet. Frame 42 improves and
residual distributions tighten, while the 21-new/30-dropped population change
and 22-frame review queue require human review first. No blind validation was
restarted.

Implementation hashes for this reviewed run:

- `p05_rigid_consensus_partial_hole_poc.py`: `e2af71f12f24e3c02934e2baec791e6ae41c66a3d14a6b557d00a365f7e3b63e`
- `p05_rigid_consensus_partial_hole_blue_frozen.json`: `515ce552011e850d3d5e024ec1f12e1d66300060aa34bc6a74d4e2f0a0c930e4`
- `test_p05_rigid_consensus_partial_hole_poc.py`: `d605b50fad4c44a5b06dd3a3aa543878258efa4ed7aaf9fc8b1824fe48bd4152`
