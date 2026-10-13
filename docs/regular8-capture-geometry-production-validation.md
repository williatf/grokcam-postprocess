# Jan/Wendy Hintze Regular 8 capture-geometry validation

Date: 2026-09-22

The capture-specific artifact was evaluated on separated holdout bands 161–320,
481–640, and 801–960 (480 frames total). Calibration used the disjoint bands
1–160, 321–480, and 641–800.

## Holdout disposition

The primary detector found all 480 frames. The established batch gate admitted
479 and rejected frame 906. Calibrated P15 accepted 478 of the 479 admitted
primary frames. The two non-direct cases were:

| Frame | Primary gate | Calibrated P15 | P24 | Resulting hierarchy |
|---:|---|---|---|---|
| 528 | accepted | rejected (`no_valid_columns`) | rejected | existing P07/P22 fallback |
| 906 | rejected | not attempted | capture + physical corroboration passed | calibrated P24-guided P15 |

Thus the proposed hierarchy was 478 direct calibrated P15 results, one
P24-guided P15 result, and one P07/P22 fallback opportunity. No interpolation
was used.

The isolated P24 check evaluated all 480 holdout frames, including frames that
did not need recovery in the proposed hierarchy:

| Disposition | Count |
|---|---:|
| Calibrated capture gate passed | 447/480 (93.1%) |
| Physical pair available after capture gate | 447/447 |
| Physical Y corroboration passed | 404/447 (90.4%) |
| Physical fit rejected | 43 |
| Capture geometry gate rejected | 33 |

For the 447 physically available pairs, capture/physical lower-edge
disagreement had median 1.00 px, 95th percentile 2.00 px, and maximum 3.67
px. Frame 906 measured 3.67 px, within the unchanged 8 px agreement limit.
The existing physical fallback remains available for frame 528 and any future
primary/P15 failure.

## P07 quality review

The separated 13-frame P07/P22 sample accepted four frames. Calibrated P15
and P07/P22 differed by a median absolute 22.38 px, 95th percentile 55.72 px,
and maximum 58.42 px. Frames 481 and 906 were visually/geometrically
adjudicated against the visible lower sprocket edge and capture metadata; P07
selected a competing structure while calibrated P15 followed the sprocket
edge. This supports the calibrated P15-first ordering and does not justify
using P07 as an unconditional authority.

## End-to-end 1–960 benchmark

The fresh benchmark used the calibrated artifact, three raw-development jobs,
120-frame batches, local `/tmp` staging, existing crop/render, normalization,
encoding, and verification. It completed successfully without modifying the
source DNGs:

```text
input frames:       960
direct P15:         948 (98.75%)
P24 recovery:         4 (0.42%)
P07/P22 recovery:     4 (0.42%)
unresolved/excluded:  4 (0.42%)
P07 invocations:      8 (0.83%)
encoded frames:     956
wall time:          531 s (8m 51s)
throughput:         1.81 input frames/s
projected 4,955:    approximately 46 minutes
```

The output was a verified 1134×900, 16 fps movie. The four exclusions were
the existing physical ambiguity/insufficient-support cases at frames 1–3 and
768; they were not interpolated. The crop, orientation, normalization, and
encoding stages completed successfully. Residual vertical stabilization was
not enabled because the existing `physical-p07-v1` policy explicitly prohibits
that combination; no stabilization behavior was changed.

Visual inspection of representative output frames found consistent
orientation and vertical registration. The historical loose crop retains a
small left-edge sprocket sliver also present in the no-geometry control crop;
the capture-specific geometry did not introduce a new intrusion, so crop
geometry was intentionally not recalibrated in this change.

## Adoption boundary

The artifact is optional and strictly validated. Runs without it use the
legacy/default Regular 8 geometry. It is rejected for Super 8, recorded in the
manifest when used, and cannot be changed during resume. No Super 8 processing
algorithm or scheduler behavior was modified.

This validation supports production use for the Jan/Wendy capture with the
artifact supplied explicitly. It does not authorize a full 4,955-frame
production run; that remains a separate operational decision.
