# Capture-seeded physical-hole POC findings

Date: 2026-08-27

## Decision

**A — the hybrid approach clearly improves production and should proceed toward integration validation.**

This is not approval to integrate the research implementation unchanged. The
new detector replaces the weak local bright-band evidence with two independent
2-D perforation detections and reduces Reel_46335 interpolation from 1,201
frames in the previous hybrid POC to 198 frames. Of the previous hybrid gaps,
1,013 now have a trustworthy same-frame measurement. The highest-risk class is
the 956 Reel_46335 measurements supported by the physical seeded detector but
not the broad detector; representative visual review shows recognizable full
hole pairs, but this class still merits a larger blind review before production.

No production source, configuration, calibration, DNG, manifest, or production
output was changed.

## Detector and frozen calibration

The isolated implementation is
`research/p02_physical_hole_capture_prior_poc.py`; its safety tests are
`research/test_p02_physical_hole_capture_prior_poc.py`. It retains the preceding
`research/p01_hybrid_capture_prior_poc.py` as the unchanged production/broad-search
baseline and fallback.

Only capture records marked as an actual full pair may seed a search. Each
capture bounding box is transformed using its recorded preview/raw dimensions
and expanded independently. Within each small box-derived ROI, the detector
uses local P40/P99.5 intensity statistics, relative and adaptive/Otsu masks,
morphology, connected contours, and gates for width, height, aspect, area,
fill, solidity, ROI-edge escape, and distance from the predicted hole. Upper
and lower holes are found independently; pitch and X agreement validate the
pair. Capture coordinates determine where to look, never the final answer.

The Blue-only margin experiment evaluated 15%, 25%, 35%, and 50%. The frozen
25% expansion was the smallest setting satisfying the prespecified coverage
and agreement rule while detecting every named genuine Blue excursion. Frozen
production-anchor offsets are X=-17.125 px and Y=0 px. Broad agreement gates
are 12 px X and 25 px Y. Reel_28486 and Reel_46335 were evaluation-only.

## Phase 1: why the previous seeded detector failed

The 1,153 Reel_46335 frames with an eligible capture pair but no previous
bright-band evidence were classified before replacing the detector:

| Failure class | Frames |
|---|---:|
| Size/shape | 1,146 |
| Other (empty or out-of-frame transformed ROI) | 6 |
| Threshold/brightness | 1 |

The dominant failure was not poor contrast. Thresholding frequently merged the
hole with the bright surrounding film into row runs wider than the old 330 px
limit. A 1-D bright band was therefore the wrong physical representation.

## Full-reel comparison

| Reel | Frames | Production interpolated | Bright-band hybrid interpolated | Physical-hole interpolated | Physical pairs | Same-frame final |
|---|---:|---:|---:|---:|---:|---:|
| Blue_Reel | 5,153 | 25 | 5 | 5 | 5,131 | 5,148 |
| Reel_28486 | 5,125 | 1 | 0 | 0 | 4,965 | 5,125 |
| Reel_46335 | 4,615 | 1,294 | 1,201 | 198 | 4,251 | 4,417 |

Reel_46335 results:

- 4,535 frames had eligible actual capture pairs.
- 1,096 production-interpolated frames became same-frame measurements.
- 1,013 of the 1,201 previous-hybrid interpolated frames were recovered.
- 956 final measurements were physical-seeded-only; 3,104 agreed with the
  independently rerun broad detector; 357 used broad fallback.
- Remaining physical failures were size/shape 148, ROI-edge escape 108,
  ineligible capture evidence 80, pitch 20, solidity 7, and X agreement 1.

The reported 198 unresolved frames include 195 interpolated frames and three
segment-edge fallback holds. No smoothing or correction cap was introduced.

## Coordinate agreement and ground-truth projection

The physical-to-transformed-capture median X offsets were -16.49 px (Blue),
-14.49 px (Reel_28486), and -16.74 px (Reel_46335), confirming that capture
and production use different X landmarks. Median Y offsets were within 0.25 px.
This supports capture as a search prior rather than a registration answer.

Applying final-anchor deltas to the existing registered-output annotations:

| Reel | Upper MAE, production -> new | Lower MAE, production -> new |
|---|---:|---:|
| Blue_Reel | 7.24 -> 2.88 px | 9.53 -> 4.91 px |
| Reel_28486 | 7.98 -> 3.49 px | 8.08 -> 8.08 px |
| Reel_46335 | 45.24 -> 23.20 px | 19.21 -> 17.16 px |

This projection compares registration outcomes; it is not direct full-resolution
hole-landmark ground truth. Reel_46335 improves materially but retains a long
error tail, consistent with its 198 unresolved frames.

## Required regression frames

Blue frames 3260, 3451, 3615, 3676, 3754, 3846, and 3882 all produced physical
pairs and agreed with broad evidence. Large real excursions remain preserved;
the known contaminated frames 3615 and 3676 do not regress. Frame 3882 is
recovered, with physical Y=904.5 and broad final Y=928.0 inside the frozen
25 px broad-agreement gate. Reel_28486 frame 3574 remains accepted.

## Throughput and review

Mean detector-only time per frame was 7.64 ms on Blue, 7.82 ms on Reel_28486,
and 7.93 ms on Reel_46335, in addition to the independently rerun broad
detector's approximately 20.2 ms/frame. RAW development is excluded.

Contact sheets cover new recoveries, seeded-only acceptances, largest capture
disagreements, remaining failures, and questionable cases. Three retained
Reel_46335 event clips contain frames 2265-2313, 2577-2625, and 2972-3020 at
4 fps without interpolation. Visual inspection found recognizable upper and
lower perforations in the sampled seeded-only recoveries; damaged/merged holes
dominate the remaining failures. No sampled picture-content false registration
was identified, but the seeded-only population is large enough that broader
blind review is required before production integration.

## Recommendation

Proceed to a production-integration validation design that keeps the safety
architecture intact: capture actual-pair metadata supplies only local search
ROIs, full-resolution 2-D evidence supplies the measurement, and unchanged
broad production detection remains an independent fallback/anomaly check.
Before enabling it for deliverables, blind-review a statistically meaningful
sample of the 956 Reel_46335 seeded-only acceptances and define explicit
operational handling for broad disagreements and the remaining 198 gaps.
