# P07 Joint Rigid Sprocket-Pair Evidence POC

## Scope

P07 is an isolated evaluation on the unchanged 198-frame Reel_46335 problem
population. It did not inspect or use the protected blind-validation answers or
manual ground truth. Production code, calibration, DNGs, manifests, existing
POCs, and historical outputs were unchanged.

Unlike P03-P06, P07 does not require one sprocket to be accepted before testing
the other. It searches the frozen sprocket X domain, evaluates two immutable
physical-hole templates jointly, and accepts only when both holes provide
independent same-frame pixel evidence. Capture, normal-detector, and P06
positions can add search candidates, but the same full search runs without
them; no prior coordinate is returned as a measurement.

The Blue-frozen model remains width 381.5842105263158 px, height 272.0 px,
pitch 785.0 px, and lower-minus-upper X offset +18.678947368421063 px. P07 fits
translation only. Width, height, pitch, X offset, scale, rotation, and shape are
never fitted.

Each candidate records support, absence, contradiction, polarity, contrast,
residuals, cross-hole evidence distribution, geometry, competing hypotheses,
and prior distances. A modeled boundary with direct support is not reclassified
as contradictory merely because a stronger parallel edge exists nearby.
Similarly, displaced same-polarity evidence is missing evidence with a residual,
not opposite-polarity contradiction. These are general evidence semantics, not
frame-specific or ground-truth tuning.

## Frozen-population result

| Stage | Accepted/recovered | Unresolved |
|---|---:|---:|
| P03 partner-assisted contour fit | 88 | 110 |
| P04 single-landmark fixed geometry | 62 | 136 |
| P05 rigid landmark consensus | 53 | 145 |
| P06 partner-predicted template evidence | 75 | 123 |
| P07 joint rigid-pair evidence | 192 | 6 |

P07 retained 74 of 75 P06 recoveries, added 118 accepted measurements, and
dropped one. Twenty-three of the 118 were already classified as normal-detector
successes by P06, so the net new fallback recovery population is 95 frames.
Nineteen P07 acceptances had no normal-detector seed at all.

Accepted pair evidence was strong: 98 frames supported all 8+8 feature classes,
88 supported 7+7 or better, and only two accepted pairs fell below 6+6. Every
accepted result had zero contradictory feature classes. Competitor margin was
0.274 minimum, 2.498 median, and 3.452 P95. Pair-geometry residual was 0 px
median, 2 px P95, and 6 px maximum.

The six unresolved frames are 2606-2608 and 4599-4601. The first three lack
sufficient joint support; the latter three have competing pair positions whose
scores are too close to separate safely. P06 frame 2607 is the only dropped
recovery (joint score 5.021 and competitor margin 0.248). Its rejection is the
appropriate conservative result.

## Why the joint search succeeds

- It can measure two damaged-but-evidenced holes without requiring either one
  to pass the intact-hole detector first.
- It searches the physical X domain independently, recovering 41 cases where
  P06's capture prior/ROI was wrong and one capture-ROI anomaly.
- Evidence must be distributed across both independently evaluated templates;
  pitch and X offset corroborate two holes but do not manufacture either one.
- Missing torn boundaries do not distort the immutable geometry, while
  opposite-polarity evidence at a modeled boundary remains a hard penalty.
- Separated competing pair hypotheses are retained and ambiguous winners are
  rejected rather than resolved from temporal or capture preference.

## Required frames

Frame 42 is accepted at upper center (430.947, 385.333) and lower center
(449.6259, 1170.333). Both holes support seven feature classes, with the damaged
upper bottom and lower top recorded as missing. There are no contradictions;
the geometric residual is 1 px and competitor margin is 2.013. The fixed model
aligns naturally to the visible top/wall/corner evidence rather than being
pulled by the damaged contour.

Frame 3341 is accepted at upper center (412.0, 438.0) and lower center
(430.6789, 1223.0), with 8+7 supported classes, zero contradictions, zero
geometry residual, and a 2.326 competitor margin. Visual review confirms these
positions are the two actual perforations. The erroneous capture prior is
1,283.9 px away and is ignored. Thus P07 does not reproduce the historical
picture-content false registration; it independently recovers real physical
holes. This changed regression outcome must nevertheless be included in the
next blind review.

## Visual review and disposition

All 192 acceptances have per-frame overlays. Dedicated sheets cover all
recoveries, new-versus-P06 results, the dropped P06 case, remaining failures,
both-damaged/bridged cases, lowest margins, largest prior translations,
contradictions, weakest acceptances, and no-normal-seed recoveries. Review found
no obvious picture-content acceptance. A conservative 19-frame review queue is
recorded in `validation_report.json` for the lowest-support, no-seed, or largest
residual cases.

Recommendation: **A — sufficiently strong to freeze for a new blind-validation
candidate.** This does not authorize production integration. Freeze/hash P07,
include frame 3341 and the 19-frame review queue in the blinded population, and
restart validation only after explicit approval. No blind validation was
started by this run.

Reviewed-run hashes:

- `p07_joint_rigid_sprocket_pair_evidence_poc.py`: `d78bc8478308451af69d37dc7485cb5c0a15cd7a59ccdb75ec86932a498fd13d`
- `p07_joint_rigid_sprocket_pair_evidence_blue_frozen.json`: `334abf89ee43a0eb18c7f33e68eb8afb9f38556ff981136ac16f5d30b646a1c6`
- `test_p07_joint_rigid_sprocket_pair_evidence_poc.py`: `82bc6487ffd3d9bc8c9dc86a206355f4973202ed19b79f9c59a8cb1438558e4d`
