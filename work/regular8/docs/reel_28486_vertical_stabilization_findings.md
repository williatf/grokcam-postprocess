# Reel_28486 vertical-stabilization research findings

## Scope and conclusion

This research-only iteration examined all 5,125 Reel_28486 frames. Production
code, calibration, tests, and the completed production output were not changed.
The existing production manifest was read as the current-behavior diagnostic
baseline. A separate primary-registration movie was generated directly from the
immutable DNGs so visual comparisons do not reverse-shift cropped pixels.

The main failure is reference-edge selection, not correction mathematics or
transport. Reel_28486's light margin, image content near the left strip, fades,
and blank leader create high-confidence edges that are not sprocket boundaries.
The current single strongest-edge detector frequently selects them. Confidence
alone cannot distinguish these false edges, and correction magnitude cannot be
used as a rejection rule because real large excursions remain possible.

No production update is justified from this iteration. Multi-candidate physical
geometry is promising, but the tested variants either interpolate too often or
still retain plausible wrong pairs. They do not approach Blue Reel reliability.

## Current baseline

| Measurement | Result |
|---|---:|
| Frames | 5,125 |
| Trustworthy same-frame corrections | 5,001 |
| Valid top measurements | 4,104 |
| Valid bottom measurements | 4,947 |
| Top measured corrections | 4,104 |
| Bottom rescues | 897 |
| Interpolated corrections | 124 |

Current correction distribution:

| Metric | Pixels |
|---|---:|
| Mean absolute | 21.752 |
| Median absolute | 1.466 |
| RMS | 48.258 |
| 95th percentile absolute | 123.738 |
| 99th percentile absolute | 173.930 |
| Maximum absolute | 204.750 |

Target-aware post-verification was valid on 4,124 frames. On that selected
subset its mean absolute residual was 0.444 px, RMS 1.429 px, 95th percentile
2.571 px, and maximum 10.821 px. This subset excludes most catastrophic false
bottom corrections because their corrected crops do not expose a valid top edge;
it must not be read as an all-frame quality score.

## Top/bottom disagreement

Both correction estimates existed on 4,789 frames. Absolute disagreement was:

| Metric | Pixels |
|---|---:|
| Mean | 32.634 |
| Median | 2.331 |
| 95th percentile | 150.629 |
| Maximum | 257.171 |

There were 1,667 disagreements above 5 px. Within that difficult subset, median
absolute disagreement was 95.621 px and mean absolute disagreement was 90.563
px. The complete ranked data and classifications are retained as CSV.

## Candidate-edge evidence

Thirty-four frames covering the largest 25 disagreements, largest 10
corrections, and four required suspicious events were redeveloped from DNG and
inspected at their primary crop. Candidate reports record all local edges,
strength, contrast, bright-tail behavior, and calibrated-position distance.

The contact sheets demonstrate:

- ordinary picture frames around 1704–1805 retain a physical top/bottom pair
  near Y=224/756 and imply roughly +1–2 px, while the strongest bottom edge can
  imply about +203 px;
- frames 130, 2596, 5017, and 5063 are faded or nearly blank and lack enough
  independent evidence for the current bottom selection near Y=553;
- false edges can receive confidence 1.0, so confidence-only arbitration is
  unsafe;
- calibrated top/bottom spacing eliminates many false choices, but repeated
  margin/sprocket structure can produce more than one plausible pair.

## Experiment A: stronger top validation

The research policy retained a valid top measurement when the two sprockets
agreed or the current target-aware post-verifier confirmed it. Conflicting
bottom measurements did not override it.

| Result | Current | Top validated |
|---|---:|---:|
| Measured/validated decisions | 5,001 | 3,927 |
| Interpolated | 124 | 1,040 |
| Boundary fallback | 0 | 158 |
| Correction RMS | 48.258 px | 10.261 px |
| 95th percentile absolute | 123.738 px | 28.540 px |
| Maximum absolute | 204.750 px | 56.085 px |

This suppresses catastrophic choices but rejects far too many frames. The lower
correction distribution is not itself proof of accuracy and is not a final
post-crop residual measurement.

## Experiment B: confidence-weighted dual-sprocket fusion

Agreeing measurements were confidence-weighted. When they disagreed, a source
was selected only if its confidence was at least twice the other; otherwise the
frame was invalidated.

This performed worse: correction RMS rose to 55.933 px, the 95th percentile to
131.743 px, and 994 frames required interpolation. The cause is clear in the
candidate review: wrong bottom/content edges often have higher confidence than
the physical sprocket. Confidence must not arbitrate disagreement by itself.

## Experiment C: adaptive multi-candidate pairing

Every frame of the verified primary-registration movie was scanned for multiple
falling top and rising bottom candidates. Candidates had to pass the existing
edge-quality gates and imply corrections agreeing within 5 px. Among agreeing
pairs, combined boundary quality selected the pair. Magnitude was not scored or
capped, and interpolation occurred only after no trustworthy pair remained.

| Result | Adaptive candidate pairing |
|---|---:|
| Same-frame pairs | 3,260 |
| Interpolated | 1,864 |
| Boundary fallback | 1 |
| Correction RMS | 28.244 px |
| 95th percentile absolute | 84.781 px |
| Maximum absolute | 120.221 px |

The adaptive experiment reduces the +200 px failure class, but still produces
too many invalid frames and some large geometrically plausible wrong pairs.
All-frame candidate analysis used the verified H.264 primary baseline; the 34
selected events were independently checked from newly developed TIFF data.

## Classification

Candidate-pair evidence classified the 1,667 >5 px disagreements as:

| Class | Frames |
|---|---:|
| A. Consistent with real physical movement | 488 |
| B. Wrong sprocket/reference edge detected | 430 |
| C. Ambiguous | 749 |

These are research classifications, not ground truth. Ambiguous frames remain
the largest group, another reason not to update production yet.

## Recommended next validation logic

1. Preserve the full-resolution corrected-recrop architecture and primary
   registration unchanged.
2. Replace single strongest-edge selection with explicit sprocket-shape models:
   paired entrance/exit boundaries, expected hole height, bright interior fill,
   and terminal darkness outside the hole.
3. Search multiple x-strips or segment the margin so scene content cannot
   dominate a single 90-pixel profile.
4. Require top/bottom physical-spacing agreement when both are observable.
5. Treat high-confidence single-sprocket measurements as ambiguous when their
   mate is absent; confidence alone is insufficient.
6. Retain correction interpolation only after same-frame shape/geometry paths
   fail. Do not add a magnitude cap or temporal smoothing.
7. Validate a new detector on both Blue Reel and Reel_28486, including fades,
   blank leader, contamination, and known real large excursions, before any
   production proposal.

## Artifacts

All generated artifacts are Git-ignored under:

```text
research/output/vertical_stabilization/reel_28486_poc_v2/
```

The directory includes the full before/current/comparison movies, baseline and
adaptive summaries, diagnostics and decisions, candidate-edge CSV, six contact
sheets, 34 annotated candidate frames, and eight slow-motion event clips.
