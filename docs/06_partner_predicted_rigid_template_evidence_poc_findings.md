# P06 Partner-Predicted Rigid-Template Evidence POC

## Scope and architecture

P06 is an isolated research revision evaluated on the unchanged 198-frame
Reel_46335 problem population. It did not start, inspect, or use the protected
blind-validation package or human ground truth. Production code, DNGs,
calibration, manifests, historical outputs, and the P01–P05 implementations were
unchanged.

The unchanged normal physical-hole detector must first identify one trustworthy
same-frame intact sprocket. Its center plus frozen film construction predicts
the damaged partner. P06 then searches a 4 px grid within ±48 px of that center
and asks whether one immutable template is supported there. Capture boxes are
secondary ROI/anomaly information and never override the intact sprocket.

The template is fixed at width 381.5842105263158 px, height 272.0 px, pitch
785.0 px, and lower-minus-upper X offset +18.678947368421063 px. Width, height,
pitch, scale, rotation, and shape are never fitted.

Each candidate directly measures polarity-aware support for four walls/edges,
four curved transitions, and bright-interior/background contrast. Each physical
feature is classified `supported`, `missing`, or `contradicted`. Missing evidence
adds nothing; contradictory evidence is penalized. Corners are capped as a
group so adjacent damage cannot become three independent votes. Distance from
the intact-partner prediction contributes only a weak tie-breaker.

## Frozen-population results

| Stage | Recoveries | Unresolved |
|---|---:|---:|
| P03 partner-assisted contour fit | 88 | 110 |
| P04 single-landmark calibrated geometry | 62 | 136 |
| P05 rigid landmark consensus | 53 | 145 |
| P06 direct rigid-template evidence | 75 | 123 |

Against P05, P06 retains 40 recoveries, recovers 35 P05 failures, and drops 13
P05 recoveries. The 35 new cases comprise 19 P05 `insufficient_partner_evidence`
and 16 P05 `capture_prior_roi_incorrect` cases. Of the 13 dropped cases, nine
have contradictory physical evidence and four have insufficient direct template
support. Lower recovery is not treated as failure; these drops are deliberate
safety outcomes requiring review.

P06 recoveries by original failure class are 62 size/shape, 11 ineligible
capture evidence, and 2 ROI-edge escape. Forty-eight accepted templates have
seven supported feature classes and 27 have all eight. Seventy-four have no
contradicted class; one has one contradiction and is in the review queue.

Accepted competitor margins are 0.113 minimum, 0.659 median, and 0.978 P95.
Translation from the intact-hole prediction is 0 px minimum, 30.46 px median,
48.05 px P95, and 49.48 px maximum. X translations are tightly concentrated
(-4 px median; -32 to +4 px), while Y carries most of the correction (-4 px
median; -48 to +36 px). Twenty-nine accepted cases near the search boundary and
the single contradicted acceptance form a conservative 30-frame review queue.

Remaining failures are:

- 44 capture-prior/ROI-invalid intact seeds;
- 24 contradictory physical-evidence candidates;
- 19 frames with both holes damaged or ambiguous;
- 9 insufficient-template-support cases;
- 2 predicted ROIs outside the usable image;
- 1 ambiguous competing-template case;
- plus 24 frames where the unchanged normal detector already found the pair.

## Frame 42

The intact partner predicts the damaged-hole center at X=435.8211, Y=391.5.
P06 selects X=431.8211, Y=387.5: only -4/-4 px from calibrated construction.
The physical top edge has support 0.9406 and a 2 px residual. Both walls and all
four corners are supported; the torn bottom is correctly `missing` rather than
used to move the template. Seven of eight feature classes support the winner.

The winning robust score is 4.4096. The strongest separated runner-up is at
X=467.8211, Y=383.5 with score 3.3248, giving a 1.0813 margin. This is a direct
quantitative correction of P05's too-low Y=429 position: the unmistakable top
boundary now controls Y without hard-coding the frame.

## Safety regression

Frame 3341 remains `capture_prior_roi_incorrect`. No template or anchor is
accepted. Any future recovery of this frame remains a safety failure.

## Review status

P06 is not frozen for blind validation. The 35 new acceptances, 13 dropped P05
acceptances, 30 large-translation/contradiction review cases, and capture-pair
anomalies must be reviewed first. The protected blind validation remains stopped.

Reviewed-run hashes:

- `p06_partner_predicted_rigid_template_evidence_poc.py`: `42f72e5c11de95d235c3aed875c4b70bc27e178a5a66e599324fe994ffa2a5cf`
- `p06_partner_predicted_rigid_template_evidence_blue_frozen.json`: `7ffdd5aa84dc370727e646073c52e7a22b22dba58c98c70cbabcdeb2721c56c2`
- `test_p06_partner_predicted_rigid_template_evidence_poc.py`: `9d31451ec9b19467b38f4798c3e77097c0fbf63bacc29327d3e311cf2cebcbc8`
