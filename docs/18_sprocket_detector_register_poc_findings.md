# P18 — Sprocket detector register POC findings

## Decision

**B — the existing detector evidence contains the register, but the Y estimator
needs a specific refinement.**

The trusted anchor is not related to P15 lower-top truth by a sufficiently
reliable fixed offset in its current form. A minimal fixed-X, fine 1-D
translation of the rigid pair, scored only by the four horizontal-edge
responses already present in the frozen P06/P07 template evidence, removes the
large held-out errors. No P15 value enters that search.

The demonstrated chain is therefore:

```text
sprocket detector -> horizontal evidence fine-Y rigid-pair fit -> +260.539 px fixed lower-top offset
```

This is a research result, not a production integration recommendation yet.

## Scope and method

- Reel_46335 frames 2000–2350.
- P15-valid population: 284/351 frames.
- Sources: Primary 241, physical-pair 3, P06 15, P07 25.
- Truth: `true_registration_y = measured_lower_top_y` from frozen P15.
- Existing value: trusted manifest `anchor_y`.
- Calibration split: even frame numbers (144 frames).
- Held-out split: odd frame numbers (140 frames).
- Errors below are `estimated_anchor_y + calibrated_offset - truth`.
- Threshold counts are strict `>2`, `>3`, and `>5` px counts.

The existing detector derives Y differently by stage. Primary uses the midpoint
of thresholded bright-band row extents. Physical-pair averages independently
segmented hole centers. P06 averages one segmented center and one template
center. P07 uses the mean of a rigid pair whose translation is selected on a
coarse/refine grid by a mixed score containing X walls, Y edges, corners,
contrast, geometry, and priors. Those are good acceptance/localization
estimators, but do not uniformly make Y the optimum of the physical horizontal
boundaries.

## Existing trusted anchor plus one fixed offset

The even-frame calibration offset is **+260.5369 px**. The uncalibrated overall
relationship has an approximately -260.5 px bias, as expected for pair center
versus lower-hole top. Calibration removes the central bias but not the tails.

| Population | n | Median bias | MAD | MedAE | P95 | Max | >2 | >3 | >5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Overall | 284 | 0.021 | 0.382 | 0.377 | 3.086 | 10.756 | 24 | 15 | 8 |
| Calibration | 144 | 0.000 | 0.372 | 0.372 | 3.040 | 9.607 | 12 | 8 | 4 |
| Held out | 140 | 0.025 | 0.385 | 0.382 | 2.842 | 10.756 | 12 | 7 | 4 |

### Existing result by source

| Source | n | Median bias | MAD | MedAE | P95 | Max | >2 | >3 | >5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Primary | 241 | 0.007 | 0.347 | 0.344 | 1.233 | 9.607 | 11 | 9 | 4 |
| physical-pair | 3 | 4.341 | 1.166 | 4.341 | 5.390 | 5.507 | 3 | 2 | 1 |
| P06 | 15 | 0.357 | 2.346 | 1.990 | 7.675 | 10.756 | 7 | 4 | 3 |
| P07 | 25 | 0.055 | 1.108 | 1.163 | 2.258 | 2.813 | 3 | 0 | 0 |

This rejects the “one fixed offset is enough” hypothesis. The odd-frame
holdout independently retains four >5 px errors and a 10.756 px maximum.

## Minimal same-evidence Y refinement

The POC holds detector X, pitch, hole size, and pair geometry fixed. It searches
only common pair translation Y over ±12 px at 0.25 px increments. At each
position it sums the frozen signed P07 line response for upper top, upper
bottom, lower top, and lower bottom. It adds no landmark detector, edge hunt,
motion term, temporal operation, or source-specific behavior.

The even-frame fixed offset after refinement is **+260.5391 px**.

| Population | n | Median bias | MAD | MedAE | P95 | Max | >2 | >3 | >5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Overall | 284 | 0.057 | 0.526 | 0.532 | 1.696 | 4.199 | 7 | 3 | 0 |
| Calibration | 144 | 0.000 | 0.551 | 0.551 | 1.763 | 4.199 | 6 | 3 | 0 |
| Held out | 140 | 0.118 | 0.507 | 0.527 | 1.510 | 2.065 | 1 | 0 | 0 |

### Refined result by source

| Source | n | Median bias | MAD | MedAE | P95 | Max | >2 | >3 | >5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Primary | 241 | 0.022 | 0.503 | 0.516 | 1.415 | 4.199 | 2 | 1 | 0 |
| physical-pair | 3 | 0.259 | 0.084 | 0.259 | 0.335 | 0.343 | 0 | 0 | 0 |
| P06 | 15 | 0.656 | 1.021 | 0.901 | 3.372 | 4.171 | 4 | 2 | 0 |
| P07 | 25 | -0.061 | 0.852 | 0.849 | 1.879 | 2.065 | 1 | 0 | 0 |

The refinement trades about 0.15 px of overall median absolute error for a
large tail reduction. That is the right trade for precise registration: all
eight >5 px failures disappear, and the genuinely held-out half has no >3 px
failure.

## Requested discrepancy frames and controls

Errors use each estimator's even-frame calibrated fixed offset.

| Frame | Source | Existing error | Fine-Y error | Fine-Y shift |
|---:|---|---:|---:|---:|
| 2003 | physical-pair | 5.507 | 0.259 | -5.25 |
| 2082 | P06 | -2.303 | 2.199 | +4.50 |
| 2093 | P07 | -2.136 | -1.134 | +1.00 |
| 2097 | P07 | 2.813 | 2.065 | -0.75 |
| 2144 | Primary | 9.607 | -0.141 | -9.75 |
| 2240 | P07 | -1.507 | -1.005 | +0.50 |
| 2242 | P06 | 5.118 | 0.621 | -4.50 |
| 2161 | Primary control | -1.085 | 0.167 | +1.25 |
| 2162 | P06 control | -0.730 | 1.772 | +2.50 |
| 2146 | P07 control | 0.564 | -0.433 | -1.00 |
| 2147 | Primary control | -0.299 | -0.297 | 0.00 |

The known failures are not explained by source-specific constants. Frame 2144
is Primary yet needs -9.75 px, while Primary control 2147 needs no change. The
physical evidence directly points to the required translation on 2003, 2144,
and 2242. Controls remain within 1.8 px, though 2162 degrades by about 1 px.

## Remaining limitations and recommendation

Three calibration-side frames remain above 3 px after refinement: 2040
(Primary, 4.199), 2244 (P06, 4.171), and 2112 (P06, 3.030). The very small
physical-pair population (n=3) also prevents a strong source-specific
generalization, although no source-specific rule was used.

Recommendation: retain decision B and validate this exact Y-only estimator and
single global offset on a newly frozen, independent reel/range before any
production proposal. Do not add smoothing, interpolation, source offsets, or a
new edge detector. If the independent set preserves the held-out tail behavior,
the estimator is the specific detector refinement needed to deliver the crop
register. If it does not, revisit decision C.

Artifacts:

- `research/p18_sprocket_detector_register_poc.py`
- `research/output/sprocket_xy/p18_sprocket_detector_register_poc/reel_46335_2000_2350/measurements.csv`
- `research/output/sprocket_xy/p18_sprocket_detector_register_poc/reel_46335_2000_2350/summary.json`

