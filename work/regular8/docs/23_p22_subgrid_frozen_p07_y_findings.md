# P22 — Sub-grid refinement of frozen P07 rigid-pair Y

## Decision

**B — refinement clearly removes most of the grid-scale error, but one narrow
precision issue remains: some accepted hypotheses have a shallow local P07
score curve that does not define sub-grid Y strongly.**

On the 140 odd held-out truth frames, P22 reduces P95 from 2.198 to 1.367 px,
maximum from 3.390 to 2.182 px, and >3 px errors from one to zero. It introduces
no boundary seeking and completes all 67 fallback refinements. However, one even
calibration frame becomes a new >3 px error, and several valid/fallback frames
have very small local score margins. Independent-range validation should follow
only after this ambiguity is explicitly characterized.

## Exact refinement

P22 begins only after frozen P07 has accepted its hypothesis. It keeps pair
identity, X, pitch, hole dimensions, relative geometry, priors, acceptance,
competitors, and contradiction handling unchanged. It searches only common Y:

```text
frozen accepted upper/lower Y + shift, shift in [-3,+3] at 0.25 px
```

Each position is evaluated with the same non-full frozen P07 pair-candidate raw
score and frozen weak-prior penalty used to rank P07 fine-grid candidates. This
is the mathematically faithful ranking score: P07's later full evidence pass
validates the chosen candidate but does not re-rank candidates. No P18/P19
objective, edge detector, or truth value enters the search.

The score remains inherently piecewise because P07 samples raster gradients at
rounded coordinates. All 351 frames nevertheless had a unique sampled maximum;
ties were not used.

The even-frame P22 optical calibration is:

```text
p15_equivalent_lower_top = refined_model_lower_top + 4.178787846871160 px
```

## P21 versus P22 truth comparison

| Estimator/population | n | Median bias | MAD | MedAE | P90 | P95 | Max | >1 | >2 | >3 | >5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P21 overall | 284 | 0.128 | 0.937 | 0.886 | 1.947 | 2.175 | 3.390 | 132 | 25 | 2 | 0 |
| P22 overall | 284 | 0.043 | 0.506 | 0.510 | 1.142 | 1.355 | 3.402 | 44 | 5 | 1 | 0 |
| P21 calibration | 144 | 0.000 | 0.967 | 0.967 | 1.947 | 2.088 | 3.211 | 71 | 12 | 1 | 0 |
| P22 calibration | 144 | 0.000 | 0.505 | 0.505 | 1.096 | 1.316 | 3.402 | 22 | 4 | 1 | 0 |
| P21 held out | 140 | 0.234 | 0.812 | 0.856 | 1.926 | 2.198 | 3.390 | 61 | 13 | 1 | 0 |
| P22 held out | 140 | 0.107 | 0.475 | 0.525 | 1.253 | 1.367 | 2.182 | 22 | 1 | 0 | 0 |

The held-out grid-scale body clearly collapses. The P22/P21 held-out changes are:

- MedAE: -0.331 px;
- P95: -0.831 px;
- maximum: -1.207 px;
- >2 px: 13 to 1;
- >3 px: 1 to 0.

The caveat is calibration frame 2116: P21 error 1.918 px becomes P22 error
3.402 px after a +1.25 px shift. Its local score range across the entire ±3 px
window is only 0.127, the flattest of all valid frames. This is the specific
remaining limitation, not a search-boundary failure.

## Shift distribution and lattice relationship

On 284 overlap frames:

- median shift: 0.0 px;
- MAD: 0.75 px;
- range: -2.75 to +2.50 px;
- boundary hits: 0;
- shifts occupy 0.25 px increments inside the original 4 px cell;
- 26 frames have score margin <=0.01 against candidates at least 1 px away.

The populated shifts across nearly the whole cell and the reduction in truth
residuals show that P22 is resolving the original lattice rather than applying
another constant.

## Known frames and controls

| Frame | Frozen lower-top | Refined lower-top | Shift | P15 truth | P21 error | P22 error |
|---:|---:|---:|---:|---:|---:|---:|
| 2003 | 1043.500 | 1043.500 | 0.00 | 1047.280 | 0.165 | 0.399 |
| 2082 | 1090.000 | 1090.250 | 0.25 | 1092.340 | 1.605 | 2.089 |
| 2093 | 1070.667 | 1071.667 | 1.00 | 1076.840 | -2.228 | -0.994 |
| 2097 | 1063.000 | 1062.000 | -1.00 | 1064.224 | 2.721 | 1.955 |
| 2144 | 1067.000 | 1067.500 | 0.50 | 1071.680 | -0.735 | -0.001 |
| 2240 | 1057.000 | 1057.500 | 0.50 | 1062.544 | -1.599 | -0.865 |
| 2242 | 1059.000 | 1059.500 | 0.50 | 1062.918 | 0.026 | 0.760 |
| 2161 | 1080.500 | 1079.500 | -1.00 | 1083.372 | 1.073 | 0.307 |
| 2162 | 1064.000 | 1063.750 | -0.25 | 1066.767 | 1.178 | 1.162 |
| 2146 | 1069.500 | 1068.500 | -1.00 | 1072.973 | 0.472 | -0.294 |
| 2147 | 1083.000 | 1083.500 | 0.50 | 1087.836 | -0.891 | -0.158 |

All listed frames have accepted forced-P07 hypotheses; no source substitution
was needed.

## P15-missing fallback population

The refinement was frozen before running the 67 misses.

- completed: 67/67;
- median shift: 0.0 px;
- shift MAD: 0.5 px;
- range: -2.0 to +2.0 px;
- boundary hits: 0;
- exact maximum ties: 0;
- numerical accuracy claimed: no, because P15 truth is unavailable.

Five fallback optima are poorly defined under the conservative `<=0.01` local
margin diagnostic:

| Frame | Shift | 1 px-separated margin | Full local score range |
|---:|---:|---:|---:|
| 2042 | +0.50 | 0.000485 | 0.380 |
| 2100 | -2.00 | 0.007728 | 0.804 |
| 2173 | +0.25 | 0.000691 | 1.286 |
| 2216 | +0.25 | 0.003009 | 0.886 |
| 2334 | +0.75 | 0.005906 | 0.571 |

These estimates are retained because P22 is not allowed to change P07
acceptance. They are diagnostic cautions for independent validation.

Frame 2293 shifts -1.0 px, has no boundary hit, and has 1 px-separated margin
0.015. Its refined calibrated fallback coordinate is 1068.179 px. Direct visual
review found no gross new displacement.

## Visual comparison

The P22 movie uses authoritative P15 Y on 284 frames and refined/calibrated P07
Y on all 67 misses. X, development, normalization, crop mapping, labels, frame
rate, and encoding follow P21. No temporal operation is used.

A second movie places P21 on the left and P22 on the right. Representative
review of early switches, large-jump regions, frame 2293, and frames 2313–2315
shows only small intended sub-grid shifts and no new visible instability.

P22 transition-jump diagnostics remain dominated by real transport movement:
80 switches, 6.464 px median absolute jump, 13.786 px P95, and 29.774 px max.
They were not optimized or used in fitting.

## Recommendation

Retain decision B. P22 is a meaningful precision improvement and should replace
frozen-grid P21 in the next independent-range validation candidate, but the
follow-up must explicitly track local score identifiability. In particular,
validate whether a predeclared shallow-score diagnostic predicts the isolated
tail without tuning it against the new range. Do not change pair detection,
acceptance, or introduce temporal correction.

Artifacts:

- `research/config/p22_subgrid_frozen_p07_y.json`
- `research/p22_refine_frozen_p07_y.py`
- `research/p22_analyze_and_render.py`
- `work/regular8/p22_subgrid_p07_y/p22_valid.csv`
- `work/regular8/p22_subgrid_p07_y/p22_missing.csv`
- `work/regular8/Reel_46335_p22_subgrid_p07_y_2000_2350_20260829/measurements.csv`
- `work/regular8/Reel_46335_p22_subgrid_p07_y_2000_2350_20260829/summary.json`
- `work/regular8/Reel_46335_p22_subgrid_p07_y_2000_2350_20260829/Reel_46335_002000_002350_p22_p15_first_refined_p07_16fps.mp4`
- `work/regular8/Reel_46335_p22_subgrid_p07_y_2000_2350_20260829/Reel_46335_002000_002350_p21_vs_p22_side_by_side_16fps.mp4`

