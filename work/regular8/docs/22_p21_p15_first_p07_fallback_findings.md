# P21 — P15-first crop register with P07 fallback

## Decision

**B — the architecture is sound and provides complete coverage here, but the
frozen P07 fallback has a specific grid-scale precision limitation requiring a
narrow follow-up.**

P15 supplies authoritative Y on 284/351 frames. Forced frozen P07 accepts every
one of the 67 P15-missing frames, independent of historical cascade source, so
the architecture provides 351/351 registers with no temporal fill and no
unresolved frame. The single P07-to-P15 calibration is stable to roughly 2 px
at P95, but one odd held-out error exceeds 3 px. That is consistent with P07's
frozen 4 px template-translation lattice and is not precision-equivalent to
P15.

## Exact architecture tested

```text
frozen P15 lower-top valid -> authoritative register_y
frozen P15 missing         -> forced frozen physical-p07-v1
                           -> lower_center_y - 136
                           -> +3.944868879 px optical calibration
                           -> register_y
P07 rejection              -> unresolved (none in this range)
```

P07 was run directly on every frame. Historical Primary, physical-pair, P06,
or P07 source labels did not veto or select the run. The forced stage retained
the frozen P07 search, evidence, score, geometry, and acceptance rules, including
its normal capture/physical/P06 search priors. Those priors only seed search;
accepted coordinates come from full-resolution P07 image evidence.

No P18/P19 value, historical registration Y, source-specific offset, temporal
operation, neighboring frame, motion objective, or new detector was used.

## P07/P15 overlap calibration

P07 was attempted on all 284 P15-valid frames:

- P07 accepted: 284
- P07 rejected: 0
- raw `delta = P15 - (P07 lower_center_y - 136)` median: 3.817 px
- raw delta range: 0.555 to 7.156 px
- raw delta MAD / median absolute residual: 0.937 px
- P95 absolute residual around the median relationship: 2.283 px
- maximum absolute residual: 3.340 px
- residual counts >1/>2/>3/>5 px: 132/27/2/0

The one global offset was frozen from all 144 even-numbered overlaps:

```text
p15_equivalent_lower_top_y = p07_model_lower_top_y + 3.944868878638772
```

### Odd-frame held-out validation

| n | Median error | MAD | MedAE | P90 | P95 | Max | >1 | >2 | >3 | >5 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 140 | 0.234 | 0.812 | 0.856 | 1.926 | 2.198 | 3.390 | 61 | 13 | 1 | 0 |

P07 lower-center coordinates occupy discrete fractional strata determined by
the 4 px coarse/refine grids and the origins of their priors. The overlap errors
have the expected approximately ±2 px grid-scale body, though the maximum is
larger. This POC documents but does not correct that quantization.

## P07 fallback on all 67 P15-missing frames

- Attempted: 67
- Accepted: 67
- Rejected: 0
- Total P15 + P07 coverage: 351/351 (100%)
- Unresolved: 0
- Unresolved frame list: empty

Historical sources of these 67 frames, retained only as diagnostics:

| Historical source | Frames |
|---|---:|
| physical-pair | 33 |
| Primary | 18 |
| P06 | 14 |
| P07 | 2 |

Every accepted fallback's upper/lower model centers, model lower-top,
calibrated P15-equivalent lower-top, score, margin, support, contradictions, and
historical source are recorded in `measurements.csv`.

### Safety-diagnostic audit

Fallback P07 diagnostics:

- joint score min/median/max: 8.695/12.166/12.593, versus frozen minimum 5.2;
- competitor margin min/median/max: 0.486/2.625/4.474, versus frozen minimum 0.1;
- supported features: 44 frames with 16, 22 with 15, 1 with 14;
- contradictions: 66 frames with zero, 1 frame with one.

Frame 2293 is the sole conservative review flag: score 8.695, margin 0.486,
14 supported features, and one contradiction. It still clears every frozen P07
acceptance threshold. No numerical accuracy is claimed for any fallback frame
because P15 truth is unavailable there.

## Continuity and visual review

The continuous diagnostic movie contains all 351 frames and labels each frame
as P15 or P07 for authoritative Y. P07 model X is used consistently for the
diagnostic crop on every frame so historical X sources cannot confound the
source-switch review. There is no interpolation or smoothing.

There are 80 P15/P07 source transitions. Raw frame-to-frame register jumps:

- median absolute: 6.277 px
- P95 absolute: 14.102 px
- maximum absolute: 30.040 px

These values are diagnostics, not errors: they include actual transport motion
and scene/frame movement and were not minimized. Representative visual review
of early transitions, high-jump regions, frame 2293, and frames 2313–2315 found
no obvious systematic P15/P07 vertical step or gross fallback displacement.
The full labeled movie remains the authoritative review artifact.

## Answers

1. P07 succeeds on 284/284 frames where P15 succeeds.
2. One global offset is stable to 2.198 px held-out P95 and 3.390 px maximum;
   useful, but less precise than P15 and visibly limited at grid scale.
3. P07 recovers 67/67 P15-missing frames when actually run on all of them.
4. Resulting crop-register coverage is 351/351.
5. No frames remain unresolved.
6. Sampled source transitions appear consistently registered; full movie review
   is provided, with frame/source labels and no temporal modification.

## Recommendation

Advance P15-first/P07-fallback as the candidate architecture, subject to one
narrow follow-up focused only on P07's stored Y quantization/precision. Do not
change P15, add other fallback sources, or introduce temporal filling. The
follow-up should establish whether a sub-grid evaluation of the already chosen
P07 rigid hypothesis can reduce the held-out tail without changing detection
or acceptance semantics.

Artifacts:

- `research/config/p21_p15_first_p07_fallback.json`
- `research/p21_run_forced_frozen_p07.py`
- `research/p21_analyze_and_render.py`
- `work/regular8/p21_p15_first_p07_fallback/p07_valid.csv`
- `work/regular8/p21_p15_first_p07_fallback/p07_missing.csv`
- `work/regular8/Reel_46335_p21_p15_first_p07_fallback_2000_2350_20260829/measurements.csv`
- `work/regular8/Reel_46335_p21_p15_first_p07_fallback_2000_2350_20260829/summary.json`
- `work/regular8/Reel_46335_p21_p15_first_p07_fallback_2000_2350_20260829/Reel_46335_002000_002350_p21_p15_first_p07_fallback_16fps.mp4`

