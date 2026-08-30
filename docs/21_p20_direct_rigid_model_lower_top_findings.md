# P20 — Direct P15 versus rigid-model lower-top

## Decision

**B — the rigid-model lower-top contains the register, but has specific,
identifiable precision limitations.**

The model coordinate tracks the physical lower-top with an approximately fixed
4 px optical/geometric difference. It is not already a reliable precision
register: the odd-frame holdout has 1.143 px median absolute error, 4.924 px P95,
and 6.293 px maximum after one global calibration.

The limitations are structural and visible in the frozen detectors:

- P06 template translation is searched on a 4 px grid. It fits only the damaged
  partner as a fixed template and combines that with an independently segmented
  seed; it does not jointly fit both observed centers as one rigid translation.
- P07 coarse/refine template positions also use a 4 px grid. Its selected Y
  optimizes a mixed detection/acceptance score rather than precise boundary Y.

Thus the fitted geometry contains a coarse physical register, but its stored
model Y is not precise enough to use directly with only a fixed offset.

## Apples-to-apples source definitions

Only 40 of the 284 P15-valid frames have comparable fixed rigid-template
geometry: 15 P06 and 25 P07.

- **P07:** diagnostics store fixed-template `lower_center` directly.
  `model_lower_top_y = lower_center_y - 272/2`.
- **P06:** diagnostics store the fitted fixed-template `partner_center` and an
  independent physical seed. The rigid pair is derived from the fitted partner,
  not from the trusted anchor or seed/model average. If the partner is lower,
  its Y is the lower center; if upper, fixed pitch 785 is added. Then 136 is
  subtracted for the fixed half-height.
- **Primary:** no fixed rigid-template pair is produced. It stores a thresholded
  bright-band center only, so no comparison is manufactured.
- **physical-pair:** two holes are independently segmented with measured,
  variable dimensions and pitch. It is not the P06/P07 fixed rigid model and is
  excluded.

No manifest `anchor_y`, P18/P19 estimate, edge search, or temporal value enters
`model_lower_top_y`.

## Raw delta by source

`delta = p15_lower_top_y - model_lower_top_y`. Residual magnitudes here are
measured around each source's median raw delta.

| Source | n | Median delta | MAD | Median abs residual | P95 abs residual | Max abs residual | >1 | >2 | >3 | >5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P06 | 15 | 3.680 | 1.292 | 1.292 | 5.561 | 5.601 | 11 | 5 | 3 | 2 |
| P07 | 25 | 3.982 | 1.108 | 1.108 | 2.225 | 2.759 | 14 | 4 | 0 | 0 |

P07 shows the clearer fixed relationship but retains roughly grid-scale
dispersion. P06 has a materially heavier tail.

## One global calibration and held-out test

The single offset, frozen from the 20 even-numbered comparable frames, is:

```text
calibrated_lower_top = model_lower_top_y + 4.429488612 px
```

Held-out odd frames:

| Population | n | Median error | MAD | MedAE | P95 | Max | >1 | >2 | >3 | >5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P06 + P07 | 20 | 0.954 | 1.352 | 1.143 | 4.924 | 6.293 | 13 | 7 | 4 | 1 |
| P06 | 7 | 2.041 | 0.995 | 2.748 | 5.861 | 6.293 | 6 | 5 | 3 | 1 |
| P07 | 13 | 0.447 | 0.956 | 1.036 | 2.891 | 3.206 | 7 | 2 | 1 | 0 |

The held-out bias also shows that the combined even-frame offset does not fully
transfer to the small odd P06/P07 mixture. No held-out value was used to adjust
it.

## Known frames and controls

| Frame | Source | Model lower-top | P15 lower-top | Raw delta | Calibrated error |
|---:|---|---:|---:|---:|---:|
| 2003 | physical-pair | — | 1047.280 | — | — |
| 2082 | P06 | 1090.000 | 1092.340 | 2.340 | 2.090 |
| 2093 | P07 | 1070.667 | 1076.840 | 6.173 | -1.744 |
| 2097 | P07 | 1063.000 | 1064.224 | 1.224 | 3.206 |
| 2144 | Primary | — | 1071.680 | — | — |
| 2240 | P07 | 1057.000 | 1062.544 | 5.544 | -1.114 |
| 2242 | P06 | 1058.000 | 1062.918 | 4.918 | -0.489 |
| 2161 | Primary control | — | 1083.372 | — | — |
| 2162 | P06 control | 1062.000 | 1066.767 | 4.767 | -0.337 |
| 2146 | P07 control | 1069.500 | 1072.973 | 3.473 | 0.957 |
| 2147 | Primary control | — | 1087.836 | — | — |

Dashes explicitly indicate that no genuine P06/P07 rigid model exists; no
anchor-derived substitute was used.

## P15-missing frames

Only **16/67** hard frames contain genuine fixed P06/P07 model geometry:

- P06: 14
- P07: 2

Frames:

```text
2019 2091 2098 2113 2131 2145 2188 2198
2216 2217 2220 2233 2236 2243 2254 2283
```

Their geometric model lower-tops range from 1038.0 to 1091.0 px, with median
1056.75 px. Producing a P15-equivalent coordinate requires only adding the
frozen +4.429488612 px offset. This is a geometric extrapolation, not an
accuracy claim: these frames have no P15 truth, and the valid-frame holdout
shows that the coordinate can miss by more than 6 px.

The other 51 hard frames were resolved by Primary or physical-pair and do not
contain the comparable rigid reconstruction required by the proposed
architecture.

## Recommendation

Do not use the stored P06/P07 geometric lower-top directly as the precision crop
register. Retain decision B because the approximately fixed relationship is
real and the limitation is identifiable, but correcting it would require a
specific refinement of fitted model translation—not another constant. That is
outside this direct-comparison POC.

Artifacts:

- `research/p20_direct_rigid_model_lower_top.py`
- `research/output/sprocket_xy/p20_direct_rigid_model_lower_top/reel_46335_2000_2350/measurements.csv`
- `research/output/sprocket_xy/p20_direct_rigid_model_lower_top/reel_46335_2000_2350/summary.json`

