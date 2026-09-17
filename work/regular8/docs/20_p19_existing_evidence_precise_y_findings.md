# P19 — Precise Y from existing sprocket evidence

## Decision

**C — P06/P07 can identify these sprockets, but the surviving evidence does
not provide enough observable Y information for precision registration on the
hard frames.**

The frozen evidence does provide precise Y when an actual lower-top boundary
response survives. Existing corner/transition evidence can corroborate that
position. It cannot replace the missing boundary: its response is deliberately
broad and saturating for detection acceptance, and mutually agreeing corners
frequently lock onto displaced structure near the search limit.

## Evidence interpretation

The frozen P06/P07 model contains:

- top and bottom horizontal line responses, which directly constrain Y when a
  signed physical boundary is present;
- corner responses, which are Y-sensitive but spatially broad because they
  aggregate a rounded arc and clip coherent gradient support;
- vertical walls, whose sampled central segments establish X and existence but
  do not define a unique Y translation;
- contrast, geometry, priors, missing-state handling, and contradiction tests,
  which aid identity/acceptance but are not affirmative Y positions.

P19 sampled only the existing line and corner definitions. It did not redetect
sprockets or add an edge detector. A feature was eligible only when its signed
response exceeded the frozen feature threshold, dominated the opposite sign,
and had an interior response peak. Missing evidence and absence of contradiction
contributed nothing.

## Frozen estimator

The estimator was frozen before extracting or inspecting the 67 P15-missing
frames:

1. Hold detector X, pitch, hole dimensions, and pair geometry fixed.
2. Sample each existing Y-sensitive response over ±12 px at 0.25 px.
3. Require an affirmative, non-boundary lower-hole top-edge peak.
4. Require at least one other affirmative P06/P07 feature residual within
   1.5 px as physical corroboration.
5. Use the lower-top residual as common pair translation. Other features gate
   the estimate but do not pull it.
6. Reject when the reference boundary is absent or uncorroborated. There is no
   fallback consensus without it, because truth-set tests showed corner-only
   consensus was not precise.

The single even-frame calibration mapping is
`true_registration_y = refined_anchor_y + 256.717236737 px`.

## Validation 1 — 284 P15-valid frames

P19 accepts 271/284 and conservatively rejects 13. Its held-out population is
135 odd-numbered frames.

| Estimator/population | n | Median bias | MAD | MedAE | P95 | Max | >2 | >3 | >5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Existing anchor, all | 284 | 0.021 | 0.382 | 0.377 | 3.086 | 10.756 | 24 | 15 | 8 |
| Frozen P18, all | 284 | 0.057 | 0.526 | 0.532 | 1.696 | 4.199 | 7 | 3 | 0 |
| P19 accepted, all | 271 | 0.002 | 0.309 | 0.310 | 0.885 | 5.276 | 1 | 1 | 1 |
| P19 accepted, held out | 135 | 0.014 | 0.303 | 0.311 | 0.897 | 1.219 | 0 | 0 | 0 |

The lone P19 outlier is even calibration frame 2142 (P06), at -5.276 px.

### P19 by source

| Source | n | Median bias | MAD | MedAE | P95 | Max | >2 | >3 | >5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Primary | 238 | -0.006 | 0.287 | 0.293 | 0.876 | 1.201 | 0 | 0 | 0 |
| physical-pair | 2 | -0.129 | 0.066 | 0.129 | 0.189 | 0.195 | 0 | 0 | 0 |
| P06 | 14 | 0.200 | 0.157 | 0.339 | 2.387 | 5.276 | 1 | 1 | 1 |
| P07 | 17 | -0.005 | 0.363 | 0.358 | 0.981 | 1.219 | 0 | 0 | 0 |

This confirms the residual formulation is excellent when the direct positional
boundary exists. It does not establish a substitute for missing boundaries.

## Requested frames

| Frame | Source | P19 status/error | Existing error | P18 error |
|---:|---|---:|---:|---:|
| 2003 | physical-pair | accepted, -0.063 | 5.507 | 0.259 |
| 2082 | P06 | rejected: uncorroborated | -2.303 | 2.199 |
| 2093 | P07 | accepted, -0.456 | -2.136 | -1.134 |
| 2097 | P07 | accepted, -0.006 | 2.813 | 2.065 |
| 2144 | Primary | accepted, -0.462 | 9.607 | -0.141 |
| 2240 | P07 | accepted, -0.327 | -1.507 | -1.005 |
| 2242 | P06 | accepted, 0.299 | 5.118 | 0.621 |
| 2161 | Primary control | accepted, -0.154 | -1.085 | 0.167 |
| 2162 | P06 control | accepted, -0.800 | -0.730 | 1.772 |
| 2146 | P07 control | accepted, -0.005 | 0.564 | -0.433 |
| 2147 | Primary control | accepted, 0.131 | -0.299 | -0.297 |

## Validation 2 — 67 P15-missing frames

The unchanged frozen rule nominally accepts 38 and rejects 29:

- 28 lack an affirmative interior lower-top response;
- 1 has an uncorroborated response;
- accepted correction range: -11.75 to +11.75 px;
- accepted median correction: -10.875 px;
- 36/38 have absolute correction at least 10 px;
- 32/38 are at or below -10 px;
- 22/38 have absolute correction at least 11 px;
- exact ±12 px boundary hits: 0, because those peaks are explicitly rejected.

The P18 systematic negative collapse is therefore **not eliminated**. It has
merely moved just inside the rejection boundary. This occurs even with several
nominal corroborators: 27 accepted frames have at least four agreeing features,
and some have eight. The agreement is not independent precision information;
the broad corner arcs and other damaged/partial boundaries respond together to
the same displaced image structure.

Accepted hard frames by source are Primary 17, physical-pair 9, P06 12, and P07
0. Rejections are physical-pair 24, Primary 1, P06 2, and P07 2. Because no
ground truth exists and the correction distribution reproduces the known P18
failure signature, the 38 nominal passes cannot responsibly be labeled
physically supported precise registers.

## Recommendation

Stop this estimator line at decision C. Preserve P06/P07 as identity and
acceptance detectors, but do not claim that their surviving non-boundary
evidence yields precise common Y on these damaged frames. A conservative system
must leave these frames unresolved unless a genuinely positional physical
feature survives.

No diagnostic movie was rendered: there are not enough **reliable** hard-frame
estimates, and filling or displaying the nominal passes as registered would
conceal the demonstrated observability failure. No temporal fill was used.

Artifacts:

- `research/config/p19_affirmative_y_residual_consensus.json`
- `research/p19_extract_y_residual_evidence.py`
- `research/p19_evaluate_y_residual_consensus.py`
- `research/output/sprocket_xy/p19_y_residual_consensus/reel_46335_2000_2350/measurements.csv`
- `research/output/sprocket_xy/p19_y_residual_consensus/reel_46335_2000_2350/summary.json`
- `work/regular8/p19_y_residual_evidence/valid_evidence.jsonl`
- `work/regular8/p19_y_residual_evidence/missing_evidence.jsonl`

