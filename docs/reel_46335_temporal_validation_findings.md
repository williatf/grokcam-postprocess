# Reel_46335 Physical + Temporal Validation

## Conclusion

**NEEDS ADDITIONAL RESEARCH**

The frozen physically aware detector and temporal Variant C do not generalize
reliably to Reel_46335. The safety behavior remains good—real supported large
movements are preserved and no correction exceeds 100 px—but same-frame
coverage falls to 44.75%. The dominant problem occurs before temporal
validation: normalized sprocket regions frequently remain below the physical
detector's fixed 0.70 brightness floor, so no candidate is generated.

No thresholds, geometry constants, scoring weights, or temporal settings were
changed for this reel.

## Validation configuration

- Input: `/mnt/GrokCam/projects/Reel_46335/raw`, 4,615 immutable DNGs.
- Before baseline: existing 4,615-frame primary-registered production movie.
- Residual measurement: frozen physically aware multi-strip/top-bottom detector.
- Candidate validation: frozen temporal Variant C.
- Temporal smoothing: none.
- Final sampling: direct full-resolution developed-TIFF corrected recrop.
- Production code, configuration, calibration, manifests, outputs, and tests:
  unchanged.

## Summary

| Measurement path | Frames | Percent |
|---|---:|---:|
| Paired physical | 1,993 | 43.19% |
| Top-only physical | 65 | 1.41% |
| Temporal-assisted selection | 7 | 0.15% |
| Interpolated | 2,486 | 53.87% |
| Endpoint fallback | 64 | 1.39% |

There were seven temporal-assisted alternate selections and no bottom-only
rescues. Same-frame measurements total 2,065 after temporal recovery. Variant C
recovered 7 baseline interpolations and newly rejected no baseline measurement.

### Correction statistics

| Metric | Result |
|---|---:|
| Mean correction | +3.748 px |
| Median correction | +2.323 px |
| RMS correction | 9.290 px |
| P95 absolute correction | 21.051 px |
| Maximum absolute correction | 86.925 px |
| Corrections >10 px | 816 |
| Corrections >25 px | 152 |
| Corrections >50 px | 9 |
| Corrections >100 px | 0 |

### Post-correction verification

The full-resolution corrected render produced 4,214 usable post measurements:

| Metric | Result |
|---|---:|
| Mean absolute residual | 3.218 px |
| RMS residual | 4.546 px |
| P95 absolute residual | 9.857 px |
| Maximum absolute residual | 10.821 px |

These results are substantially poorer than the prior validation reels and are
consistent with long interpolated intervals.

## Comparison with prior reels

| Reel | Frames | Same-frame | Interpolated | Fallback | Maximum correction |
|---|---:|---:|---:|---:|---:|
| Blue 3000–3999 | 1,000 | 1,000 (100%) | 0 | 0 | 94.699 px |
| Reel_28486 Variant C | 5,125 | 4,930 (96.2%) | 195 | 0 | 62.462 px |
| Reel_46335 Variant C | 4,615 | 2,065 (44.7%) | 2,486 | 64 | 86.925 px |

Reel_46335 behaves unlike either prior validation set. It preserves supported
large motion like Blue, but its candidate availability is far worse than
Reel_28486.

## Event findings

The top 25 absolute corrections include paired events at frames 4,094
(-86.925 px) and 1,011 (-82.644 px). The surrounding physical measurements
support these large movements. They were not rejected merely for being large.

Temporal validation prevents implausible large alternatives at frames 1,896,
4,092, and 4,093. The full candidate table also contains many physically
plausible alternate candidates that are temporally inconsistent; those remain
available for review with their prediction, error, and component scores.

Variant C accepts seven candidates because physical evidence and temporal
agreement both pass unchanged gates: frames 75–78, 106, 643, and 1,845.

Indexed videos and CSVs cover:

- all top 25 corrections;
- the largest temporal rejections;
- the longest interpolation runs;
- the largest interpolated corrections;
- a deterministic random interpolation sample.

## Interpolation analysis

Twenty interpolation runs occur. The two dominant runs are:

- frames 1,954–3,111: 1,158 frames;
- frames 3,122–3,905: 784 frames.

The final 64 frames use endpoint fallback because there is no subsequent valid
measurement.

Of the 2,550 interpolated/fallback frames:

- 2,494 have left-ROI peak luminance below 0.70;
- 2,495 generate no physical candidate;
- sampled long-run frames show visible, apparently intact sprocket openings;
- no sampled case establishes damaged sprocket film as the cause.

The dominant classification is **detector limitation caused by the absolute
brightness floor after normalization**. Poor normalized sprocket contrast is
the input condition. Film-content edges contribute rejected alternatives, but
are not the reason for the long no-candidate runs. Sprocket damage was not
observed in the sampled review.

## Answers to the validation questions

1. **Does the physical detector identify sprocket structure reliably?** No.
   It works in brighter sections but fails to emit candidates through large
   normalized low-level sections despite visible sprocket structure.
2. **Does temporal validation reduce false candidates without suppressing real
   movement?** Yes where candidates exist. It rejects impossible alternatives
   and preserves supported corrections up to 86.925 px. It cannot repair an
   empty physical candidate set.
3. **Are large supported corrections preserved?** Yes. No arbitrary cap or
   magnitude-only rejection is used.
4. **What percentage requires interpolation?** 53.87% interpolated, plus 1.39%
   endpoint fallback; 55.25% lacks a trusted same-frame correction.
5. **Why are frames interpolated?** Predominantly normalized brightness below
   the fixed detector floor. This is a detector limitation, not confirmed film
   damage. Film content mainly affects rejected alternate candidates.
6. **New failure mode?** Yes: sensitivity to segment-normalized absolute
   sprocket brightness. This did not dominate Blue or Reel_28486.

## Recommendation

The detector is **not ready for production validation** as currently frozen.
Additional research should address photometric normalization of the sprocket
ROI or replace the absolute brightness floor with a physically constrained
relative/local contrast model. Any change must be developed as a new iteration
and rerun unchanged across Blue, Reel_28486, and Reel_46335 to confirm that the
previous false-edge protections remain intact.

The temporal layer should remain a validation layer only. It must not be used
to conceal missing physical measurements through smoothing.
