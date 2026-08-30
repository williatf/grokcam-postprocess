# P23 — Independent validation of P15-first / refined-P07 fallback

## Decision

**B — the architecture generalizes, but the P22 local-Y objective has a reproducible tail that needs a narrow follow-up before production-integration planning.**

The frozen architecture achieved 450/450 register coverage and transferred its typical precision: overall MedAE was 0.520 px, essentially the 0.525 px development held-out result. The independent P95 was 1.459 px versus 1.367 px in development. However, its tail did not reproduce: 11/449 overlap errors exceeded 2 px and 6 exceeded 3 px, versus 1/140 and 0/140 in the development holdout. The maximum was 4.698 px versus 2.182 px.

This was validation only. No estimator, threshold, calibration, or production file was changed.

## Frozen inputs and independent populations

The complete pre-evaluation declaration and hashes are in `research/config/p23_independent_validation_freeze.json`. It freezes P15, forced P07, P22, the 4.17878784687116 px model-to-optical offset, and the unchanged shallow threshold `margin <= 0.01`.

The ranges were selected before examining errors, based only on independence, contiguity, RAW availability, and metadata availability:

| Population | Frames | Reason |
|---|---:|---|
| Reel_46335 | 3000–3149 | Non-overlapping with development range 2000–2350 |
| Reel_28486 | 3000–3149 | Different reel and content/exposure population |
| Blue_Reel | 3000–3149 | Different reel and notably different content/exposure population |

Total: 450 independent frames. Archival DNGs were read only.

## Validation A — P15 / refined-P07 overlap

Error is frozen `refined_model_lower_top + 4.17878784687116 - P15_lower_top`.

| Population | Total | P15 valid | Overlap | Median | MAD | MedAE | P90 | P95 | P99 | Max | >1 | >2 | >3 | >5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Reel_46335 | 150 | 149 | 149 | 0.344 | 0.439 | 0.549 | 1.273 | 1.958 | 3.526 | 3.666 | 29 | 7 | 4 | 0 |
| Reel_28486 | 150 | 150 | 150 | 0.148 | 0.506 | 0.551 | 1.251 | 1.558 | 3.441 | 4.698 | 26 | 4 | 2 | 0 |
| Blue_Reel | 150 | 150 | 150 | 0.209 | 0.443 | 0.470 | 0.924 | 1.077 | 1.409 | 1.621 | 12 | 0 | 0 | 0 |
| **Overall** | **450** | **449** | **449** | **0.230** | **0.448** | **0.520** | **1.134** | **1.459** | **3.240** | **4.698** | **67** | **11** | **6** | **0** |

The independent median optical/geometric offset was 3.949095 px, 0.229693 px below the frozen 4.178788 px offset. Per population it was 3.834380, 4.030922, and 3.969497 px respectively. Thus the single calibration transfers to substantially below one pixel in central tendency; it is not the explanation for the several-pixel tail. These diagnostic medians were not used to recalibrate results.

## Validation B — coverage

| Population | P15 success | P15 miss / fallback attempts | P07 accepts | Rejects | Final coverage |
|---|---:|---:|---:|---:|---:|
| Reel_46335 | 149 | 1 | 1 | 0 | 150/150 |
| Reel_28486 | 150 | 0 | 0 | 0 | 150/150 |
| Blue_Reel | 150 | 0 | 0 | 0 | 150/150 |
| **Overall** | **449** | **1** | **1** | **0** | **450/450** |

There were no unresolved frames. The only fallback was Reel_46335 frame 3000: frozen model lower-top 1115.667, P22 shift 0.000, refined model 1115.667, calibrated register 1119.846, P07 score 12.123, competitor margin 2.676, 15 supported features, zero contradictions, and shallow margin 0.004459. P15 failed for insufficient column consensus. Its P07 pair is visually plausible and the 3000→3001 P22-to-P15 transition is visually consistent, but there is no P15 truth for a numerical accuracy claim.

Coverage generalization is therefore demonstrated for this sample, but fallback recovery is not statistically validated: only one of 450 frames invoked it.

## Validation C — P22 behavior

Across all 450 accepted P07 results, the refinement shift had median 0.000 px, MAD 0.500 px, P5/P95 -2.000/+2.000 px, and range -2.750 to +2.750 px. There were no boundary hits. One exact tie occurred (Reel_46335 frame 3133, shift -0.75 px); visual inspection did not show a registration failure. Eight unusually large shifts at `|shift| >= 2.5` were inspected: Reel_46335 3003 and 3061, and Reel_28486 3005, 3010, 3033, 3045, 3135, and 3141. None exceeded 2 px truth error, hit the boundary, or showed an incorrect rigid pair.

This is qualitatively consistent with development behavior and shows no boundary collapse.

## Shallow-score diagnostic

| Group | n | MedAE | P95 | Max | >2 | >3 | >5 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Shallow (`<=0.01`) | 25 | 0.625 | 2.768 | 4.017 | 2 | 2 | 0 |
| Non-shallow | 424 | 0.511 | 1.397 | 4.698 | 9 | 4 | 0 |

The frozen diagnostic predicts a heavier-error population: shallow P95 and >3 rate are materially higher. It is not a sufficient tail detector: it caught only 2/6 errors over 3 px and 2/11 over 2 px. Nineteen of 25 shallow overlap frames were still within 1 px, so those are false alarms under the requested “highly accurate” interpretation. The fallback frame was also shallow, without available truth.

## Frame-level failure audit

Cyan audit lines are P15; magenta lines are calibrated P22. In every listed frame, visual inspection supports the P15 line as the physical optical top and shows that P07 selected the correct rigid sprocket pair. No wrong-pair hypothesis or clear P15 truth failure was found.

| Reel | Frame | Error px | Shallow | Finding |
|---|---:|---:|---|---|
| Reel_28486 | 3004 | -4.017 | yes | Correct pair; shallow/ambiguous local score and imprecise Y |
| Reel_28486 | 3011 | -2.301 | no | Correct pair; imprecise local Y |
| Reel_28486 | 3015 | -4.698 | no | Correct pair; imprecise local Y despite non-shallow score |
| Reel_28486 | 3023 | -2.842 | no | P15 has only 38 valid columns but its visible edge is coherent; correct pair, imprecise Y |
| Reel_46335 | 3022 | +2.203 | no | Correct pair; imprecise local Y |
| Reel_46335 | 3055 | +3.433 | no | Correct pair; imprecise local Y |
| Reel_46335 | 3069 | +2.978 | no | Correct pair; imprecise local Y |
| Reel_46335 | 3075 | +2.641 | no | Correct pair; imprecise local Y |
| Reel_46335 | 3081 | +3.611 | no | Correct pair; near-threshold but non-shallow local score; imprecise Y |
| Reel_46335 | 3134 | +3.031 | yes | Correct pair; shallow/ambiguous local score and imprecise Y |
| Reel_46335 | 3145 | +3.666 | no | Correct pair; imprecise local Y |

The failure signs cluster by short reel regions, but the independent median calibration remains close and Blue_Reel has no >2 px errors. The specific limitation is the local P22 scoring surface’s occasional several-pixel displacement from the optical lower-top relationship; the shallow diagnostic identifies some, not most, of those cases.

## Answers and recommendation

1. **Calibration transfer:** yes in central tendency (0.230 px overall median error), with modest reel-to-reel median variation.
2. **Typical precision:** yes. MedAE 0.520 px and P95 1.459 px remain subpixel-to-low-pixel and close to development.
3. **Fallback recovery:** the sole P15 miss was recovered, but one attempt cannot establish “nearly all” on independent material.
4. **Refinement stability:** yes; no boundary hits or collapse, and the shift distribution matches development qualitatively.
5. **Shallow diagnostic:** partially. It enriches large errors but has poor sensitivity and many accurate flags.
6. **Transitions:** the only available fallback transition is visually consistent. Broader transition behavior is not established.
7. **Architecture validity:** typical performance and calibration generalize, but the independent several-pixel tail is systematic enough to prevent an A decision.

Validation recommendation: retain the architecture as the candidate, with the
several-pixel P22 tail and sparse independent fallback sample explicitly recorded
as limitations. Do not recalibrate per reel or add temporal behavior.

Subsequent project decision: promote the frozen architecture into production
despite Decision B, accepting the observed P22 tail as a known production
limitation. The promotion must reproduce the frozen P15/P07/P22 behavior and
global calibration exactly; it is not authorization to tune the algorithms.

## Artifacts

- `work/Reel_P23_independent_validation/summary.json` — complete metrics, frozen declaration, fallback record, and flagged rows
- `work/Reel_P23_independent_validation/measurements.csv` — all 450 frame-level outputs
- `work/Reel_P23_independent_validation/audit/` — tail, fallback, tie, and unusual-shift overlays
- `work/Reel_P23_independent_validation/reel46335_3000_3149_p15_first_p22_fallback_16fps.mp4`
- `work/Reel_P23_independent_validation/reel28486_3000_3149_p15_first_p22_fallback_16fps.mp4`
- `work/Reel_P23_independent_validation/blue_reel_3000_3149_p15_first_p22_fallback_16fps.mp4`

All movies were verified as 150 frames, 1134×900, 16 fps, 9.375 seconds. Their SHA-256 hashes are recorded in `summary.json`.
