# Production vertical-stabilization validation

## Scope

The first production integration was validated on Blue Reel frames 3000–3999
using the canonical production command, one 1000-frame batch, 16 fps, and three
RAW-development workers. Both runs read the same immutable DNG sequence from
`/mnt/GrokCam/projects/Blue_Reel/raw`.

The baseline used the default disabled behavior. The candidate added
`--vertical-stabilization`. Both final movies passed frame-count probing and a
full decode at 1000 frames and 62.5 seconds.

## Registration results

The production manifest contains 1000 residual records:

| Correction source | Frames |
|---|---:|
| measured upper sprocket | 995 |
| expanded upper search | 2 |
| bottom-sprocket rescue | 3 |
| interpolated residual correction | 0 |
| nearest-valid fallback | 0 |

All five primary-rejected frames obtained trustworthy same-frame residual
measurements. The post-crop upper-edge verifier was valid on 999 frames; frame
3635 was the one unavailable verification measurement.

| Metric | Before residual correction | After residual correction |
|---|---:|---:|
| Mean absolute residual | 0.899 px | 0.163 px |
| RMS residual | 5.214 px | 0.314 px |
| 95th percentile absolute residual | 1.429 px | 0.405 px |
| 99th percentile absolute residual | 5.493 px | 0.649 px |
| Maximum absolute residual | 96.810 px | 4.044 px |

The before series is the magnitude of each selected production correction; the
after series contains the 999 valid target-aware post-crop measurements. This
definition differs slightly from the earlier POC's dynamically centered
diagnostic series, so small differences in the before summary are expected.

Required regression events retained the validated behavior:

| Frame | Primary accepted | Source | Correction | Post residual |
|---:|:---:|---|---:|---:|
| 3260 | yes | measured | +13.883 px | -0.134 px |
| 3451 | no | measured | +46.929 px | -1.429 px |
| 3487 | no | expanded residual | +96.810 px | -0.275 px |
| 3615 | yes | bottom rescue | +1.611 px | -3.429 px |
| 3676 | yes | bottom rescue | -1.000 px | -4.044 px |
| 3754 | no | measured | +67.206 px | -1.143 px |
| 3846 | no | measured | +57.095 px | -1.198 px |
| 3882 | no | expanded residual | +82.429 px | -0.060 px |

The dirty upper boundaries on frames 3615 and 3676 were rejected as
`nonterminal_bright_boundary`; their large false corrections were not applied.

## Performance

| Measurement | Disabled baseline | Enabled candidate | Difference |
|---|---:|---:|---:|
| Frames | 1000 | 1000 | — |
| RAW developments | 1000 | 1000 | 0 |
| Crop/register stage | 57.9 s | 130.7 s | +72.8 s (+125.7%) |
| Non-development stage total | 162.8 s | 235.4 s | +72.6 s (+44.6%) |
| Modeled total with equal RAW time | 532.3 s | 605.1 s | +72.8 s (+13.7%) |
| Total measured stage time | 530.0 s | 495.2 s | -34.8 s |
| End-to-end wall time | 532.32 s | 497.49 s | -34.83 s |

End-to-end time is not a stable overhead estimate because RAW development was
107.4 seconds faster in the enabled run. The comparable incremental cost is
72.8 ms/frame in crop/register, or about 13.7% of the baseline end-to-end run
when RAW time is held equal. It is the in-memory provisional crop, residual
measurements, and post-crop verification; DNG development, normalization, and
encoding counts are unchanged.

## Review artifacts

Generated artifacts are Git-ignored under:

```text
research/output/vertical_stabilization/production_integration_3000_3999/
```

It contains the baseline and stabilized movies and manifests plus
`comparison.mp4`, a labeled 2268×900 side-by-side video with 1000 synchronized
frames at 16 fps.

## Remaining risks

- Residual interpolation operates within each restartable production batch. A
  failure at a batch edge uses the nearest valid same-batch correction.
- The bottom sprocket prevents catastrophic application of the known dirty top
  edges, but frames 3615 and 3676 remain the largest post-correction residuals
  at about 3.4–4.0 px.
- Upper/lower disagreement is logged rather than blindly averaged. This
  preserves frame 3260's validated upper correction but should be monitored on
  reels with different damage or exposure characteristics.
- The validated reference geometry is specific to the current loose crop and
  camera geometry. Those values should not be reused after a geometry or crop
  calibration change without revalidation.
