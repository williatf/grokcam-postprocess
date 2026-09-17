# Adaptive Sprocket Visibility Normalization POC

## Scope

This isolated research iteration addresses low-visibility residual sprocket
regions. It does not modify primary detection, crop anchors, calibration,
production configuration, manifests, tests, or production stabilization.

All experiments use the existing physical shape/strip/geometry scoring and
temporal Variant C gates. There is no temporal smoothing and no correction cap.

## Threshold experiments

Four strategies were evaluated on Blue 3000–3999, Reel_28486, and Reel_46335:

1. Relative percentile: `median + 0.60 × (p99 - median)`.
2. Relative high: `median + 0.72 × (p99 - median)`.
3. Otsu threshold over the local sprocket ROI.
4. Fixed-first relative-high fallback: preserve every valid fixed-threshold
   physical decision; invoke relative-high visibility only when fixed detection
   fails.

Direct adaptive replacement improves candidate availability but changes known
Blue measurements. At frame 3260, the three direct strategies return roughly
-0.21, -0.17, and -3.45 px instead of the validated +13.86 px correction. They
were rejected as cross-reel strategies.

## Selected method

The selected method is **fixed-first relative-high fallback**:

```text
run fixed physical detector
if accepted:
    retain the exact fixed measurement
else:
    threshold = ROI median + 0.72 * (ROI p99 - median)
    run unchanged physical detector
    validate adaptive candidate with temporal Variant C
```

Top and bottom ROIs are normalized independently. The temporal prediction is
confidence evidence only. Accepted adaptive corrections retain their exact
same-frame value; rejected frames are interpolated only after validation.

On the 2,552 Reel_46335 frames requiring adaptive visibility:

- frames with any pre-normalization candidate increase from 57 to 2,552;
- mean raw candidate count increases from 0.52 to 29.23;
- median top threshold changes from 0.700 to 0.441;
- median ROI intensity is 0.111;
- median p99-minus-median local contrast is 0.441.

Physical shape and temporal validation remain essential: 860 adaptive physical
measurements pass the 5 px temporal gate, while 1,622 are rejected. Variant C
recovers 20 additional eligible candidates.

## Cross-reel decision results

| Dataset | Same-frame | Interpolated | Fallback | Maximum correction | >100 px |
|---|---:|---:|---:|---:|---:|
| Blue selected | 1,000/1,000 | 0 | 0 | 94.699 px | 0 |
| Reel_28486 selected | 4,988/5,125 | 137 | 0 | 62.462 px | 0 |
| Reel_46335 baseline | 2,065/4,615 | 2,486 | 64 | 86.925 px | 0 |
| Reel_46335 selected | 2,936/4,615 | 1,679 | 0 | 86.925 px | 0 |

Blue frames 3260, 3487, and 3882 are byte-for-byte decision equivalents at
+13.857, +94.699, and +82.715 px. Reel_28486 frames 2596, 5017, and 5063 remain
free of the historic large false correction. Frame 130 receives a small
adaptive same-frame measurement rather than the former interpolation and is
included in the full-resolution event/post-residual review.

Reel_46335 interpolation falls by 807 frames (32.5%), and endpoint fallback is
eliminated. The selected detector still interpolates 36.4% of the reel, so the
visibility problem is improved but not solved.

One newly accepted Reel_46335 measurement exceeds 25 px: frame 3133 at +32.17
px. Its full-resolution corrected recrop measures a -1.33 px post residual
(confidence 0.845), supporting it as real film movement rather than a newly
introduced false jump.

## Full-resolution post-correction validation

| Dataset | Variant | Mean signed | Mean absolute | RMS | P95 absolute | Maximum absolute |
|---|---|---:|---:|---:|---:|---:|
| Reel_28486 | prior physical + Variant C | -0.808 px | 1.600 px | 2.272 px | 4.351 px | 10.821 px |
| Reel_28486 | selected adaptive fallback | -0.803 px | 1.605 px | 2.284 px | 4.362 px | 10.821 px |
| Reel_46335 | prior physical + Variant C | +1.116 px | 3.218 px | 4.546 px | 9.857 px | 10.821 px |
| Reel_46335 | selected adaptive fallback | +0.775 px | 2.712 px | 4.067 px | 9.476 px | 10.821 px |

The Reel_46335 image-level result improves, while Reel_28486 is effectively
flat with a small numerical regression. No correction above 100 px returns on
Reel_28486. Frame 130 changes from a -11.42 px interpolation to a +1.18 px
adaptive same-frame correction; the post detector cannot make a valid
measurement on that low-confidence frame, so it is retained in the visual
review rather than presented as numerically proven. Frames 5017 and 5063 remain
unchanged at +9.68 and +1.75 px. Frame 2596 remains interpolated (+18.90 px)
because adaptive visibility does not produce a trustworthy same-frame result.

## Remaining limitations

- Candidate proliferation is large. Physical and temporal gates reject most
  adaptive candidates; removing either safeguard would be unsafe.
- Reel_46335 still has 1,679 interpolated frames.
- Fixed-anchor linear prediction can reject real motion inside very long gaps
  if that motion differs by more than 5 px from the endpoint trajectory.
- The fallback is intentionally asymmetric: it preserves established fixed
  measurements even if adaptive visibility finds another candidate.
- Only three reels are represented. Other exposure normalization regimes remain
  out of sample.

## Recommendation

**NEEDS ADDITIONAL RESEARCH.**

The fixed-first fallback is the first visibility strategy that improves
Reel_46335 without regressing established Blue decisions or returning
Reel_28486-style >100 px errors. Nevertheless, 36.4% interpolation on
Reel_46335 is too high for production validation.

The next iteration should investigate temporal validation within long
low-visibility runs using multiple mutually consistent adaptive physical
measurements, while continuing to preserve fixed measurements and without
smoothing the correction signal. The selected strategy must be rerun unchanged
on all three reels after any such change.
