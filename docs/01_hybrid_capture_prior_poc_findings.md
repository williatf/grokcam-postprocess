# Hybrid capture-prior production-detector POC

Date: 2026-08-24

## Decision

**B — promising, but needs additional research.**

The hybrid architecture is validated in principle: it recovers genuine large same-frame motion that production temporal validation currently interpolates, preserves production's final coordinate convention, improves registered manual-ground-truth error, and causes no observed false registration in the reviewed recoveries. It is not ready for integration because it recovers only 93 of Reel_46335's 1,294 production-interpolated frames. The capture prior exists on 1,246 of those frames; the conservative production-style local evidence detector is the coverage bottleneck.

No production source, configuration, calibration, DNG, manifest, or existing output was changed.

## POC architecture

The isolated implementation is [p01_hybrid_capture_prior_poc.py](../research/p01_hybrid_capture_prior_poc.py), with focused safety tests in [test_p01_hybrid_capture_prior_poc.py](../research/test_p01_hybrid_capture_prior_poc.py).

For each reel it:

1. joins capture JSONL, DNG, and production manifest by exact frame number and fails on any missing, extra, duplicate, or filename mismatch;
2. permits seeding only for `raw_registration_mode=pair` plus `selected_source=pair_actual`;
3. scales both capture boxes using each record's preview/raw dimensions;
4. develops each DNG once with the frozen production developer;
5. remeasures both holes inside capture-seeded ROIs using the production luminance threshold, band-height, width, fill, pitch, and X-geometry conventions;
6. independently reruns the unchanged broad production detector;
7. retains the broad detector's coordinate when broad and seeded measurements agree (≤12 px X and ≤20 px Y);
8. accepts a seeded-only measurement only when two full-resolution bands pass every evidence gate;
9. otherwise preserves an existing accepted production anchor or interpolates within the original production segment boundary.

Capture coordinates are never copied into the final measurement. Capture single estimates, rejected singles, and held-last-good values are logged but cannot seed acceptance. There is no smoothing or correction cap.

The seeded X ROI is intersected with production's fixed X=100–570 strip. This is intentional: capture estimates the physical full-hole center, whereas the existing crop calibration uses production's threshold-defined, strip-clipped X landmark. Letting the seed expose the entire hole shifted otherwise-correct X anchors by roughly 15–25 pixels.

## Full-reel results

All 14,893 DNG/capture/manifest correspondences were verified one-to-one.

| Reel | Frames | Production same-frame | Production interpolated | Hybrid same-frame | Hybrid interpolated | Newly recovered | Relative gap reduction |
|---|---:|---:|---:|---:|---:|---:|---:|
| Blue_Reel | 5,153 | 5,128 (99.51%) | 25 (0.49%) | 5,148 (99.90%) | 5 (0.10%) | 20 | 80.0% |
| Reel_28486 | 5,125 | 5,124 (99.98%) | 1 (0.02%) | 5,125 (100%) | 0 | 1 | 100% |
| Reel_46335 | 4,615 | 3,321 (71.96%) | 1,294 (28.04%) | 3,414 (73.98%) | 1,201 (26.02%) | 93 | 7.19% |

Measurement sources:

| Reel | Capture-seeded full-resolution | Broad fallback | Interpolated/edge hold |
|---|---:|---:|---:|
| Blue_Reel | 5,137 | 11 | 5 |
| Reel_28486 | 5,118 | 7 | 0 |
| Reel_46335 | 3,346 | 68 | 1,201 |

Reel_46335 is the decisive limitation. Of its 1,294 production gaps:

- 1,246 had eligible actual capture pairs;
- 181 were independently detected again by the broad detector;
- only 93 passed the complete seeded evidence/independent-agreement path and became same-frame measurements;
- 1,201 remain interpolated.

Thus the capture metadata is available for almost all gaps, but the current bright-band measurement remains unable to prove the pair on most of them. This POC should not relax those gates merely to raise coverage.

## Coordinate agreement

Absolute transformed-capture to final-hybrid disagreement:

| Reel | X median | X p95 | Y median | Y p95 |
|---|---:|---:|---:|---:|
| Blue_Reel | 16.44 px | 19.53 px | 0.33 px | 1.25 px |
| Reel_28486 | 24.95 px | 33.80 px | 0.42 px | 14.42 px |
| Reel_46335 | 15.86 px | 20.11 px | 0.58 px | 4.75 px |

The persistent X offset is a landmark-definition difference, not evidence that capture should replace production X. Where broad and hybrid both exist, final hybrid X/Y equals the broad production measurement by design; capture provides corroboration, not coordinates.

Large capture/hybrid differences are retained in each reel's `large_capture_hybrid_disagreements.jpg`. No broad/seed disagreement exceeded the acceptance gate among accepted agreement-path frames. Seven Reel_46335 frames used seeded-only evidence; their dedicated safety sheet shows two clear full holes in each reviewed case. They remain the highest-risk class and should require a larger blind review before integration.

## Manual-ground-truth projection

The existing 175 annotations mark physical boundaries in registered output. Applying the hybrid anchor delta to those registered coordinates gives this before/after estimate:

| Reel | Upper MAE production → hybrid | Lower MAE production → hybrid |
|---|---:|---:|
| Blue_Reel | 7.24 → 2.88 px | 9.53 → 4.91 px |
| Reel_28486 | 7.98 → 3.49 px | 8.08 → 8.08 px |
| Reel_46335 | 45.24 → 23.02 px | 19.21 → 17.29 px |

Blue upper p95 falls from 48.33 to 4.74 px and maximum from 92.05 to 6.41 px. Reel_46335 improves materially but remains poor (upper p95 about 150 px), consistent with 1,201 unresolved frames. This projection is useful comparative evidence, but not a substitute for annotating uncropped full-resolution hole landmarks.

## Regression frames

| Reel/frame | Production | Capture eligibility | Hybrid classification |
|---|---|---|---|
| Blue 3260 | accepted | actual pair | accepted broad/seed agreement; unchanged Y |
| Blue 3451 | interpolated | actual pair | recovered same-frame |
| Blue 3615 | accepted | actual pair | accepted broad/seed agreement; unchanged Y |
| Blue 3676 | accepted | actual pair | accepted broad/seed agreement; unchanged Y |
| Blue 3754 | interpolated | actual pair | recovered same-frame |
| Blue 3846 | interpolated | actual pair | recovered same-frame |
| Blue 3882 | interpolated | actual pair | recovered same-frame; large capture/final difference retained as anomaly evidence |
| Reel_28486 3574 | accepted | actual pair | accepted broad/seed agreement; unchanged Y |
| Reel_46335 1010 | interpolated | actual pair | remains interpolated; seeded image evidence failed |
| Reel_46335 1011 | interpolated | single estimate | remains interpolated; correctly ineligible to seed |
| Reel_46335 1013 | interpolated | single estimate | remains interpolated; correctly ineligible to seed |

The Blue result establishes the core benefit: temporal outlier rejection no longer destroys a valid large same-frame measurement when capture prediction and fresh full-resolution evidence corroborate it. Frames 3615/3676 do not regress.

## Remaining interpolation and continuity

Reel_46335 production gaps comprise 509 runs; the hybrid has 518 runs because it punches isolated trustworthy measurements into existing gaps. The longest production run is 17 frames (935–951); the longest hybrid run is 16 frames (936–951). Other remaining hybrid runs are generally 8–10 frames. The 1954–3111 region gains 19 same-frame recoveries, represented in `long_region_recoveries.jpg` and three 4 fps clips, but it is not substantially solved.

Final-anchor adjacent-frame jumps are not capped or smoothed. Counts above 25/50/100 px are:

- Blue: 154 / 56 / 21;
- Reel_28486: 54 / 7 / 5;
- Reel_46335: 100 / 29 / 17.

These include real transport motion and existing broad measurements; they require event review rather than automatic suppression. No newly accepted visual review frame showed an obvious picture-content false registration, but the long-tail discontinuities and seeded-only cases prevent a production-readiness claim.

## Throughput

The full POC measurement stage (broad rerun, seeded detector, diagnostics, and review rendering) averaged 86.8–87.8 ms/frame, excluding RAW development. A separate 30-frame, three-reel benchmark measured:

- unchanged broad detector: 18.60 ms/frame mean;
- seeded full-resolution detector: 48.96 ms/frame mean;
- sequential combined detection: 67.56 ms/frame mean.

The incremental seeded-search cost is therefore about 49 ms/frame in this unoptimized research implementation. It can likely be reduced by sharing the luminance/threshold computation and running the seeded search only where broad temporal validation is doubtful, but optimization was outside this POC.

## Review artifacts

All output is Git-ignored under:

`research/output/sprocket_xy/hybrid_capture_prior_poc/`

Each reel contains:

- `diagnostics.csv`
- `summary.json`
- `review_frames/`
- `contact_sheets/`
- `event_clips/`

Top-level `validation_report.json` summarizes the frozen run. Event clips contain original review frames at 4 fps with no motion interpolation. Named Blue cases contain 49 frames each; start-of-reel clips are necessarily shorter.

Particularly useful review outputs:

- `Blue_Reel/contact_sheets/newly_recovered.jpg`
- `Blue_Reel/contact_sheets/remaining_interpolated.jpg`
- `Reel_46335/contact_sheets/newly_recovered.jpg`
- `Reel_46335/contact_sheets/remaining_interpolated.jpg`
- `Reel_46335/contact_sheets/seeded_only_safety_review.jpg`
- `Reel_46335/contact_sheets/long_region_recoveries.jpg`
- `Reel_46335/event_clips/frame_002044_long_region_recovery.mp4`
- `Reel_46335/event_clips/frame_002412_long_region_recovery.mp4`
- `Reel_46335/event_clips/frame_002436_long_region_recovery.mp4`

## Recommendation and next research step

Continue research, but do not integrate this detector as written.

The next iteration should keep the same capture eligibility and independent-evidence policy while replacing the seeded local **bright-band** measurement with a more robust full-resolution physical-hole measurement. It should explain why 1,153 eligible Reel_46335 production gaps fail seeded evidence before changing gates. Candidate work includes diagnostics for the exact failed gate, multi-candidate local segmentation, and physically aware corner/boundary evidence inside the capture-predicted boxes. Reel_28486 and Reel_46335 ground truth must remain evaluation-only.

The architecture is useful; the current seeded measurement coverage is not yet sufficient.
