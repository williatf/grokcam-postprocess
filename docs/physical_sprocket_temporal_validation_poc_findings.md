# Temporal Candidate Validation POC Findings

## Scope

This research iteration adds bidirectional temporal evidence to the isolated
physically aware residual sprocket detector. It does not modify the physical
candidate generator, primary registration, calibration, manifests, production
code, or production outputs.

Temporal evidence is used only to accept or reject a same-frame candidate. A
candidate that is accepted retains its measured correction exactly. There is
no temporal averaging, correction filtering, or smoothing.

## Temporal method

For each frame, the nearest preceding and following baseline-valid physical
measurements define a linear predicted correction. For candidate correction
`c` and prediction `p`:

```text
temporal_error = abs(c - p)
temporal_score = exp(-0.5 * (temporal_error / 3 px)^2)
```

The prediction is evidence only. It is never substituted for an accepted
candidate. Normal interpolation remains the final fallback after candidate
rejection.

Three variants were measured:

- Variant A adds the temporal score to diagnostics but preserves every baseline
  decision.
- Variant B recovers a rejected candidate when physical score is at least 0.52,
  shape is at least 0.50, strip support is at least 0.35, and temporal error is
  at most 3 px.
- Variant C ranks eligible candidates using 70% physical score, 20% temporal
  score, and 10% geometry score. It retains physical score ≥0.48, shape ≥0.50,
  strip support ≥0.20, temporal error ≤5 px, and combined score ≥0.45.

Only narrow-boundary, unconfirmed-single, and prior abrupt-single rejection
classes are eligible for temporal rescue. Lost hole depth, broken continuity,
full-width margins, and inconsistent strip positions remain hard physical
rejections.

## Results

### Blue Reel 3000-3999

All variants preserve the physical-detector baseline exactly:

- 1,000/1,000 same-frame measurements;
- zero interpolation;
- zero corrections over 100 px;
- 94.699 px maximum correction;
- 5.199 px RMS correction;
- 1.431 px 95th-percentile absolute correction.

Required large events remain accepted at their measured values:

| Frame | Source | Correction |
|---:|---|---:|
| 3260 | baseline physical top | +13.857 px |
| 3487 | baseline physical pair | +94.699 px |
| 3882 | baseline physical pair | +82.715 px |

### Reel_28486

| Variant | Same-frame | Interpolated | Recovered | RMS correction | P95 absolute | Maximum |
|---|---:|---:|---:|---:|---:|---:|
| Physical baseline / A | 4,838 | 287 | 0 | 4.532 px | 8.993 px | 62.462 px |
| B: assisted acceptance | 4,883 | 242 | 45 | 4.530 px | 8.993 px | 62.462 px |
| C: assisted selection | 4,930 | 195 | 92 | 4.510 px | 8.929 px | 62.462 px |

Variant C reduces interpolation by 92 frames, or about 32%, without introducing
any correction over 100 px. Temporal inconsistency identifies 128 rejected
frames containing physically tempting candidate corrections over 100 px. Those
candidates remain rejected rather than being pulled toward the prediction.

The known false-positive history remains safe:

- frame 130 stays interpolated near -11.425 px;
- frame 2596 stays interpolated near +15.089 px;
- frame 5017 retains the physical top measurement near +9.679 px;
- frame 5063 retains the physical top measurement near +1.754 px.

## Interpretation

Variant A confirms that temporal error is a useful discriminator: many bright
edge candidates have plausible local edge/shape scores but implausible
corrections relative to both neighboring valid frames.

Variant B is the more conservative recovery policy. Variant C recovers twice as
many frames while maintaining the same maximum correction and slightly reducing
RMS and 95th-percentile correction magnitude. Its modest increase in mean
frame-to-frame correction movement reflects use of actual frame measurements
instead of interpolated values; the accepted measurements are intentionally not
smoothed.

## Remaining limitations

- The prediction is based on baseline-valid anchors. Long gaps with incorrect
  anchors could give misleading temporal evidence.
- Bidirectional validation is naturally an offline/finalization operation. A
  streaming implementation would need deferred decisions or a bounded lookahead.
- A candidate near the prediction can still be wrong. Physical shape gates
  remain essential and cannot be replaced by temporal proximity.
- Only two reels have been validated. Stock, exposure, fade, crop, and sprocket
  variations remain out of sample.
- Recovered-frame visual review is required before considering production use.

## Recommendation

Variant C is a promising candidate for the residual-only stabilization stage,
provided the recovered-event review is satisfactory and additional reels show
the same safety behavior. It should not yet be integrated into production from
this POC alone.

Do not use this temporal layer to influence primary registration. That would be
a separate architectural change requiring independent calibration and
validation.
