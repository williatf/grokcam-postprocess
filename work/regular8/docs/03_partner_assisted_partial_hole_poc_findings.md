# Partner-assisted partial-hole recovery POC

Date: 2026-08-27

## Decision

**B — promising, but needs another POC/blind landmark validation.**

The isolated fallback recovered 88 of the 198 frozen Reel_46335 problem frames
using same-frame partner boundary evidence. It did not alter the existing
physical-hole detector, its calibration, its outputs, or production. After a
first-pass review exposed one unsafe picture-content seed (frame 3341), the POC
added the already-frozen production/Blue sprocket X domain as a seed gate. The
final run rejects that frame and contains no visually obvious false recovery,
but seven marginal cases remain explicitly questionable. That review history
and the lack of direct full-resolution landmark ground truth make A premature.

## Method

The POC operates only on the frozen 198-frame unresolved population. It calls
the unchanged normal per-hole detector independently. If exactly one hole has
same-frame physical evidence, its center plus the Blue-frozen 785 px pitch and
normal near-zero upper/lower X displacement predicts a tight partner ROI. The
predicted coordinate is never used as the answer.

Within that ROI the fallback searches position and scale and independently
scores left/right walls, top/bottom boundaries, and four curved-corner arcs.
It permits missing portions but requires at least four boundary sources,
including a vertical wall, horizontal boundary, and corner, plus bright-hole
interior contrast and separation from a spatial competitor. The fitted partner
and intact hole must still pass the frozen pitch and X geometry. Frames with no
intact pixel-supported seed remain unresolved; no temporal interpolation is
used as evidence.

No Reel_28486 or Reel_46335 manual annotation was used for tuning. Geometry and
the seed X domain come from existing Blue/production calibration.

## Results

| Final POC classification | Frames |
|---|---:|
| Partner-assisted partial-hole recovery | 88 |
| Capture prior/ROI incorrect | 44 |
| Insufficient partner evidence | 23 |
| Both holes damaged/ambiguous | 19 |
| Normal detector success, still blocked by broad disagreement | 24 |

The fallback leaves 110 of the original 198 frames unresolved. Recovery by
original failure class:

| Original class | Recovered | Original count |
|---|---:|---:|
| Size/shape | 71 | 89 |
| Ineligible capture evidence | 12 | 48 |
| ROI-edge escape | 5 | 18 |
| Pitch | 0 | 19 |
| Other/broad disagreement | 0 | 24 |

Both partner directions worked: 62 lower-to-upper and 26 upper-to-lower.

Boundary-feature usage among the 88 recoveries was: left wall 85, right wall
61, top boundary 73, bottom boundary 25, upper-left corner 80, upper-right 78,
lower-right 50, and lower-left 48. This distribution is consistent with the
intended tolerance for torn/missing bottom portions without accepting geometry
alone.

## Agreement and safety review

For 76 recoveries with a comparable transformed capture midpoint, fitted-anchor
X disagreement had median -15.75 px and p95 absolute 30.37 px. Y disagreement
had median -1.19 px and p95 absolute 29.39 px. The X offset is consistent with
the known capture/production landmark difference. Frame 4589 has a 269.97 px Y
capture disagreement; visual evidence supports the fitted physical partner,
but it remains questionable because the capture prior itself is anomalous.

Only two recovered frames had broad same-frame coordinates, too few for a useful
broad agreement conclusion. Their Y disagreements were approximately 10.6 and
16.0 px.

Seven recoveries are conservatively flagged for manual review because they have
minimum feature count, low competitor margin, or large capture disagreement:
42, 2163, 2216, 2217, 2243, 2290, and 4589. Their fitted outlines look physically
plausible in the generated panels, but they are counted as questionable rather
than silently treated as validated. After adding the frozen X-domain safeguard,
visual review found zero obvious picture-content false recoveries.

## Recommendation

Continue with another isolated validation step before integration. The next
step should obtain blind full-resolution landmark review for all seven marginal
cases plus a random sample of strong recoveries and rejected cases. It should
also formalize capture-prior anomaly handling such as frame 4589. Preserve the
current conservative evidence gates and the rule that geometry can constrain a
search but cannot manufacture a detection.

