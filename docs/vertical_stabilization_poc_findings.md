# Residual vertical-stabilization POC findings

## Scope

This is an isolated research result. It does not alter the production pipeline,
CLI, calibration, manifests, tests, or retained production outputs.

The POC is implemented in
`research/grokcam_vertical_stabilization_poc.py`. It reuses the production RAW
developer, primary sprocket detector and validator, calibrated crop,
orientation/contrast transform, encoder, and video verifier. The only new image
operations are the residual detector, a Y-only bicubic translation, and the
comparison overlay.

## Method

After production registration and orientation, the upper sprocket remnant is a
partial bright shape on the left edge of the 1133 x 900 loose crop. The residual
detector examines only `(x=0..90, y=150..285)`. It forms a bright-pixel fraction
for every row, smooths that one-dimensional profile, and estimates the strongest
falling edge at subpixel precision. This measures the lower boundary of the
partial hole without assuming the complete hole is visible.

The sequence median is the reference Y. Missing or low-confidence observations
are linearly interpolated. The selected raw, 3-frame-median, or 5-frame-median
signal produces only:

```text
correction_y = -(measured_y - reference_y)
```

No X translation, rotation, scale, perspective transform, or primary-anchor
smoothing is applied. `--max-correction` is optional; omitting it provides the
requested unlimited analytical mode.

## Representative run

Source DNGs were read without modification from Blue Reel frames 3000--3095.
All temporary TIFFs were created under `work/` and removed after the run. The
review artifacts are in:

```text
/home/todd/telecine/grokcam-postprocess/research/output/vertical_stabilization/blue_reel_3000_3095/
```

Reproduction command:

```bash
/home/todd/telecine/.venv/bin/python \
  -m research.grokcam_vertical_stabilization_poc \
  /mnt/GrokCam/projects/Blue_Reel/raw \
  --first-frame 3000 \
  --frame-count 96 \
  --smoothing none \
  --jobs 3
```

Without `--output-dir`, the POC derives a project-local run directory from the
source reel and selected range. An explicit `--output-dir` still overrides this
default hierarchy.

This range is a clean primary-registration test: all 96 primary detections were
detected and accepted, with none interpolated.

## Measured results

| Measurement | Before | After, raw unsmoothed correction |
|---|---:|---:|
| Residual detector success | 96/96 (100%) | 96/96 (100%) |
| Mean absolute residual from target | 0.465 px | 0.108 px |
| 95th percentile absolute residual | 1.017 px | 0.294 px |
| 99th percentile absolute residual | 3.307 px | 0.411 px |
| Maximum absolute residual | 3.608 px | 0.774 px |
| Mean absolute frame-to-frame movement | 0.739 px | 0.153 px |
| 95th percentile frame-to-frame movement | 1.913 px | 0.411 px |
| Maximum frame-to-frame movement | 4.072 px | 0.867 px |

Percentage of frames needing more than the stated absolute correction:

| Threshold | Frames above threshold |
|---|---:|
| 1 px | 5.21% |
| 2 px | 2.08% |
| 3 px | 2.08% |
| 4 px | 0% |
| 6 px | 0% |
| 8 px | 0% |

The median residual error is zero by construction. Typical residual error in
this range is within about +/-1--2 px, with rare real excursions into the
3--4 px range. It is not generally larger than that in this sample.

## Temporal-filter comparison

The raw signal is the best control signal for the physical objective. A
3-frame median differs from the raw measurement by 0.395 px on average; a
5-frame median differs by 0.404 px. Applying corrections from those filtered
signals would leave mean absolute frame-to-frame motion of 0.795 px and
0.742 px, respectively. Neither improves on the uncorrected 0.739 px value,
and both are far worse than the remeasured 0.153 px from raw correction.

The large one-frame events at frames 3046 and 3064 were inspected with their
neighbors. The sprocket boundary visibly moves by approximately the measured
amount, so these are not merely isolated detector spikes. Median filtering
would suppress the correction precisely where it is most valuable.

Recommendation: use no temporal smoothing for this concept. Confidence gating
and interpolation should handle true measurement failures instead.

## Diagnostic conclusion

The evidence supports **C: both real residual registration error and residual
measurement noise, dominated by real registration error**.

- Real error: unsmoothed Y correction reduces mean frame-to-frame sprocket
  movement by about 79%, and the inspected 3--4 px impulses are visible in the
  source registered frames.
- Measurement/resampling floor: after applying the exact measured correction,
  the detector reports 0.108 px mean absolute target error and 0.153 px mean
  frame-to-frame movement. These small residuals include detector precision,
  bicubic sampling, and JPEG effects.

The side-by-side video appears materially steadier at the sprocket boundary and
in the picture content during the measured impulses. The cyan guide makes the
difference easiest to review. This is a short six-second sample, so the visual
conclusion should not be generalized to an entire reel without broader tests.

## Artifacts

```text
before.mp4             current production registration
after.mp4              residual Y-stabilized registration
comparison.mp4         before left, after right, cyan reference guide
diagnostics.csv        per-frame measurements and corrections
diagnostics.json       equivalent structured diagnostics
summary.json           statistics, hashes, and video verification
before_frames/         encoded source JPEG sequence
after_frames/          corrected JPEG sequence
comparison_frames/     side-by-side JPEG sequence
```

All three videos contain 96 verified frames at 16 fps. Exact SHA-256 values and
FFprobe results are retained in `summary.json`.

## Recommendation

For this test range, a practical cap of **+/-4 px** covers every measured
correction; +/-6 or +/-8 adds no benefit. A production proposal should not yet
freeze that value. First repeat the POC across multiple reel sections,
including exposure changes, damaged or occluded sprocket remnants, scene cuts,
and primary-detection interpolation.

The concept is strong enough for broader isolated validation and is a plausible
future production feature. It is not yet ready to integrate based on one
96-frame range. Before integration, add detector-confidence regression cases,
define behavior when the remnant is absent, measure several reels, and have a
human review the comparison videos at normal playback speed.

## 1,000-frame Blue Reel validation: frames 3000--3999

This section supersedes the short-run cap recommendation above. The longer run
used the same isolated POC with no smoothing and no correction cap. It read the
archival DNGs without modification and wrote ignored research artifacts to:

```text
research/output/vertical_stabilization/blue_reel_3000_3999_unlimited/
```

The continuous 1,000-frame run completed at 16 fps. All three original videos
and the cap-4 video passed FFprobe frame-count checks and full FFmpeg decode
verification.

### Residual statistics

`post_correction_residual_y` is explicit in `validation_diagnostics.csv` and
`validation_diagnostics.json`. It is the remeasured stabilized sprocket Y minus
the sequence reference Y of 224.929 pixels.

| Residual statistic | Before | Unlimited after | Cap-4 after |
|---|---:|---:|---:|
| Mean absolute | 0.764 px | 0.140 px | 0.360 px |
| Median absolute | 0.357 px | 0.095 px | 0.095 px |
| RMS | 3.494 px | 0.258 px | 3.118 px |
| 95th percentile absolute | 1.429 px | 0.371 px | 0.418 px |
| 99th percentile absolute | 5.493 px | 0.762 px | 2.930 px |
| Maximum absolute | 67.206 px | 3.582 px | 63.206 px |

The large before and cap-4 RMS/maxima include three rejected-primary frames and
two residual-detector mistakes discussed below. They are retained in the
all-frame statistics rather than hidden. After excluding those five special
events, cap-4 has 0.162 px mean absolute residual, 0.469 px RMS, 1.484 px at the
99th percentile, and a 9.863 px maximum at genuine frame 3260.

| Frame-to-frame statistic | Before | Unlimited after | Cap-4 after |
|---|---:|---:|---:|
| Mean absolute | 1.235 px | 0.210 px | 0.651 px |
| 95th percentile absolute | 3.008 px | 0.542 px | 0.651 px |
| 99th percentile absolute | 13.551 px | 1.268 px | 10.278 px |
| Maximum absolute | 67.883 px | 3.654 px | 63.393 px |

Unlimited unsmoothed correction reduced mean frame-to-frame sprocket movement
by 83%. The 3-frame and 5-frame median simulations left 1.205 px and 1.256 px,
respectively, versus 1.235 px before correction. Temporal smoothing again
failed the physical registration objective.

### Correction distribution

The thresholds below are cumulative, as requested.

| Magnitude | Count | Percent |
|---|---:|---:|
| At or below 0.25 px | 372 | 37.2% |
| At or below 0.5 px | 615 | 61.5% |
| At or below 1 px | 904 | 90.4% |
| At or below 2 px | 964 | 96.4% |
| At or below 3 px | 975 | 97.5% |
| At or below 4 px | 984 | 98.4% |
| Above 4 px | 16 | 1.6% |
| Above 5 px | 11 | 1.1% |
| Above 6 px | 9 | 0.9% |

Residual motion is still usually in the +/-1--2 px range: 90.4% is within one
pixel and 96.4% within two. It is not exclusively in that range. After removing
the three rejected-primary events and two detector errors, 20 genuine ordinary
events exceed 3 px, 11 exceed 4 px, four exceed 6 px, and two exceed 8 px. The
largest inspected ordinary residual is +13.883 px at frame 3260.

### Detector reliability and confidence

| Measurement | Result |
|---|---:|
| Total frames | 1,000 |
| Successful residual detections | 998 |
| Failed/unusable detections | 2 |
| Usable detections | 998 (99.8%) |
| Minimum confidence, all frames | 0.000 |
| Minimum confidence, successful only | 0.403 |
| Median confidence | 0.892 |
| 5th-percentile confidence | 0.716 |
| Confidence below 0.9 | 535 |
| Confidence below 0.8 | 185 |
| Confidence below 0.7 | 39 |

Confidence is informative but insufficient as a gate. Its correlation with
absolute correction is -0.107 and with absolute post-correction residual is
-0.187. Successful measurements below 0.7 average 3.819 px correction and
0.426 px post-correction error, compared with 0.669 px and 0.117 px at
confidence 0.9 or above. However, a rejected-primary event at frame 3846 has
confidence 1.0, so confidence alone cannot distinguish every dangerous case.

Low-confidence cases correlate most clearly with damaged or contaminated hole
edges, changing partial visibility, and dark picture content adjacent to the
ROI. They do not correlate exclusively with any one condition, and the reviewed
contact sheets show no consistent association with visible splices. The two
outright failures are frames 3487 and 3882; both also coincide with rejected
primary detections and are safely interpolated by the POC.

### Inspection of every correction above 3 px

All 25 events have five-frame contact sheets and a row in
`large_correction_review.csv`.

- 20 are real physical residual movements after an accepted primary detection.
- Three (3451, 3754, and 3846) are real large displacement after the primary
  detector was rejected and its anchor interpolated. They belong to a
  primary-failure regime, not normal residual jitter.
- Two (3615 and 3676) are residual-detector errors. Damage or contamination at
  the sprocket boundary causes the simple strongest-edge detector to select an
  internal edge.
- None remained ambiguous after neighbor inspection.

Most genuine events converge to well under one pixel. Frame 3101 is the notable
ordinary exception at 1.571 px post-correction residual and confidence 0.726.
Frame 3064 repeats the short-run behavior with -0.762 px post residual. The
largest genuine ordinary event, frame 3260, moves +13.883 px and converges to
-0.076 px when unlimited. This demonstrates that large-correction convergence
is generally good but that detector precision is not uniform.

### Evaluation of the +/-4 px cap

Cap-4 affects 16 frames (1.6%). The largest analytical correction is 67.206 px,
so the largest amount clipped is 63.206 px. That extreme is a rejected-primary
event and must not be used to justify a larger residual cap.

The cap succeeds as damage containment for the two residual-detector errors,
limiting their wrong translations to four pixels. It fails as a complete
stabilization policy for genuine events. Examples:

- Frame 3122: +7.848 px genuine correction; cap-4 leaves -3.848 px.
- Frame 3260: +13.883 px genuine correction; cap-4 leaves -9.863 px.
- Frame 3947: +9.429 px genuine correction; cap-4 leaves -5.429 px.

Those clipped frames visibly retain one-frame jitter. A +/-5 px cap affects 11
frames and +/-6 px affects nine, but +/-6 still clips four genuine ordinary
events and permits two more pixels of damage on false detections. Therefore
+/-6 is safer for image stability than +/-4, but neither value solves the
underlying classification problem. A fixed cap alone cannot distinguish a
genuine 13.9 px shift from a false 19--29 px edge selection.

The previous recommendation to use +/-4 as a prospective production cap is not
supported as a general stabilization limit. It remains a defensible conservative
failsafe for the current simple detector, at the cost of visible residual jitter.
Before choosing a production cap, improve the detector/gate using edge-shape or
template consistency, primary-acceptance state, neighboring-frame agreement,
and explicit damaged-edge rejection. Re-run this validation afterward.

### Interpretation and integration readiness

1. The residual detector is highly available (99.8%) but not sufficiently safe
   without additional gating because two successful detections select a damaged
   internal edge.
2. Motion is generally +/-1--2 px, with a meaningful small tail above it.
3. Genuine ordinary 3--4 px corrections occur in nine frames; 20 ordinary
   genuine frames exceed 3 px when the larger tail is included.
4. Yes. Eleven ordinary genuine corrections exceed 4 px; the maximum is
   13.883 px.
5. Yes. Per-frame unsmoothed correction remains clearly superior.
6. Yes. Unlimited correction consistently reduces visible vertical jitter on
   valid detections, including large genuine excursions.
7. The stabilized sprocket is 0.095 px from target at the median, 0.371 px at
   the 95th percentile, and 0.762 px at the 99th percentile.
8. On valid detections, the remaining floor is mainly detector precision,
   bicubic resampling, and JPEG measurement effects.
9. No, not as a general correction limit. It is useful only as conservative
   containment until a stronger validity gate exists.
10. The concept is mature enough for a production-integration **design
    proposal**, but not for implementation. The proposal must solve validity
    gating and cap policy first and must be validated on additional reels.

### Long-run review artifacts

```text
before.mp4
after_unlimited.mp4
after_cap4.mp4
comparison.mp4
worst_genuine_frame_3260_comparison.mp4
diagnostics.csv
diagnostics.json
validation_diagnostics.csv
validation_diagnostics.json
summary.json
validation_report.json
large_correction_review.csv
large_correction_contact_sheets/
```

`comparison.mp4` places current production registration on the left and
unlimited residual stabilization on the right with the cyan target guide. The
three-second worst-event clip is centered around genuine frame 3260.

## Corrected full-resolution recrop and interpolation validation

The final POC architecture was validated on the same Blue Reel frames
3000--3999 in:

```text
research/output/vertical_stabilization/blue_reel_3000_3999_recrop_interpolation/
```

This remains isolated research code. No production module, calibration,
manifest, CLI, test, or production output was changed.

### Architecture and crop sign

Each DNG is developed exactly once. Its developed full-resolution TIFF remains
in the disposable work cache through these steps:

```text
primary detection and validation
→ provisional production crop for residual measurement
→ residual validity decision and sequence interpolation
→ corrected crop coordinate
→ one final registered_frame bicubic crop from the developed TIFF
```

The provisional crop is discarded as a measurement aid; it is not shifted to
create the final image. There is no black-fill translation and no second
resampling of an already cropped frame.

Production orientation is equivalent to a vertical flip after cropping. For a
fixed source feature:

```text
oriented_y = crop_height - 1 - source_y + crop_top
```

Therefore a positive correction, which must move content down, requires:

```text
corrected_crop_top = primary_crop_top + applied_correction_y
```

The opposite sign was rejected by a focused smoke test before the 1,000-frame
run. All final corrected crops remained within the 1520-pixel developed source.

### Measurement validity and fallback

Validity does not use correction magnitude and does not reject a frame merely
because its primary measurement was rejected. The detector records confidence,
edge strength, contrast, and the fraction of bright material immediately below
the selected boundary. A value above 0.30 for that last metric indicates the
known damaged/internal-edge failure mode. Source bounds are checked separately.

Of 1,000 frames:

- 998 produced a residual edge;
- 995 measurements were accepted;
- five were invalid;
- all five corrections were linearly interpolated between valid neighbors;
- no nearest-valid edge fallback was required.

The invalid frames were 3487 and 3882 (no edge) plus 3615, 3635, and 3676
(nonterminal bright boundary). Raw invalid measurements remain in diagnostics.
The applied results for the two known detector failures were:

| Frame | Rejected measured correction | Applied interpolation |
|---|---:|---:|
| 3615 | +28.962 px | -0.059 px |
| 3676 | +19.000 px | +0.460 px |

This prevents catastrophic false shifts. It does not fully stabilize those two
frames: target-local verification reports -4.929 px and -2.357 px residual.
Without a trustworthy same-frame boundary, temporal interpolation cannot know
about real one-frame motion. This remains an integration-design problem.

### Required large-event results

Magnitude-independent validity preserved the required large corrections:

| Frame | Primary accepted | Applied correction | Post-correction residual |
|---|---|---:|---:|
| 3260 | yes | +13.883 px | -0.134 px |
| 3451 | no | +46.929 px | -1.429 px |
| 3754 | no | +67.206 px | -1.143 px |
| 3846 | no | +57.095 px | -1.198 px |

Primary rejection therefore does not block residual rescue. Post-correction
verification searches locally around the known target Y; this prevents a large
recrop from making the verifier switch to another physical edge elsewhere in
the partial sprocket shape.

### Residual statistics

Target-local post verification excludes untrustworthy post measurements and
interpolates them only for sequence statistics.

| Statistic | Before | Corrected recrop |
|---|---:|---:|
| Mean absolute residual | 0.764 px | 0.162 px |
| Median absolute residual | 0.357 px | 0.113 px |
| RMS residual | 3.494 px | 0.316 px |
| 95th percentile absolute | 1.429 px | 0.405 px |
| 99th percentile absolute | 5.493 px | 0.646 px |
| Maximum absolute | 67.206 px | 4.929 px |
| Mean frame-to-frame movement | 1.235 px | 0.246 px |
| 95th percentile frame-to-frame | 3.008 px | 0.561 px |
| 99th percentile frame-to-frame | 13.551 px | 2.293 px |
| Maximum frame-to-frame | 67.883 px | 4.940 px |

The earlier shifted-frame run measured 0.140 px mean absolute residual and
0.210 px mean frame-to-frame movement. The recrop path is slightly worse
numerically because it deliberately interpolates the newly rejected damaged
measurements, but it avoids their catastrophic incorrect corrections and has
production-quality edge behavior.

### Processing overhead

The matched in-run benchmark covers the common provisional crop/measurement
plus either the old cropped-frame translation or new full-resolution recrop. It
excludes RAW development, primary detection, JPEG writing, and video encoding,
which are common or not part of the stabilization-operation comparison.

| Architecture | Average time per frame |
|---|---:|
| Previous provisional crop plus shift | 0.105 s |
| Provisional crop plus corrected recrop | 0.118 s |

Estimated stabilization-stage overhead is 12.7%. The complete 1,000-frame run,
including one-time RAW development and three verified video encodes, took
631.8 seconds.

### Shifted-frame versus corrected-recrop quality

The three-way review compares primary registration, previous shifted-crop
stabilization, and corrected full-resolution recropping.

- Synthetic black fill is eliminated. On representative large corrections,
  99--100% of the old exposed band is near-black, while the recrop contains
  actual developed source pixels. Naturally dark source content can still be
  near-black; it is not synthesized fill.
- No crop-boundary failure was observed.
- High-contrast edges and interior detail look equivalent in the reviewed
  stills and clips. Interior JPEG-domain mean absolute differences are small
  on valid like-for-like events.
- The diagnostic gradient-energy metric does not prove that recrop output is
  visibly sharper, so no sharpness improvement is claimed. Architecturally it
  avoids the prior second resampling and its potential loss.

### Remaining failure modes

Before production integration, a design must address:

- damaged-edge frames with real one-frame motion that interpolation cannot
  fully recover;
- a stronger shape/template validity model tested across other reels;
- behavior for invalid runs at sequence edges, where nearest-valid fallback is
  necessary;
- broader performance and memory/disk-bounded batch integration;
- regression fixtures for genuine large corrections, primary rejection rescue,
  damaged boundaries, and consecutive invalid runs.

The corrected-recrop architecture itself is validated and preferable to
shifting a finished crop. The validity/interpolation policy is substantially
safer but still requires design work before production integration.

### Recrop review artifacts

```text
before.mp4
after_recrop.mp4
comparison.mp4
comparison_three_way.mp4
validation_report.json
diagnostics.csv
diagnostics.json
invalid_measurement_review.csv
event_clips/frame_3260_primary_shifted_recrop_slow.mp4
event_clips/frame_3451_primary_shifted_recrop_slow.mp4
event_clips/frame_3615_primary_shifted_recrop_slow.mp4
event_clips/frame_3676_primary_shifted_recrop_slow.mp4
event_clips/frame_3754_primary_shifted_recrop_slow.mp4
event_clips/frame_3846_primary_shifted_recrop_slow.mp4
```

## Adaptive residual search and bottom-sprocket validation

The next isolated iteration fixes the frame 3882 out-of-ROI failure and adds an
independent lower sprocket boundary. The validated output is under:

```text
research/output/vertical_stabilization/blue_reel_3000_3999_adaptive_bottom/
```

The successful corrected-recrop architecture is unchanged: one DNG development,
one final bicubic crop from the full-resolution developed TIFF, the documented
positive crop-top sign, and no black-fill translation.

### Adaptive top search

The normal top ROI remains `(0, 150, 90, 285)`. Only when the primary detector
was rejected and the normal residual boundary is invalid does the POC try the
expanded ROI `(0, 60, 90, 285)`. Expanded results must pass the same confidence,
terminal-boundary, and source-bounds gates; the strongest edge is not accepted
without those checks.

Frame 3882 now finds the boundary near Y=142.5, applies +82.429 px rather than
the previous -0.657 px interpolation, agrees with bottom within 1.071 px, and
finishes at -0.060 px target residual. The expanded search also discovers a
second missed primary excursion at frame 3487: +96.810 px applied and -0.275 px
afterward.

### Bottom measurement and selection policy

The bottom detector searches `(0, 550, 90, 900)` for the rising upper boundary
of the lower sprocket remnant. Its sequence reference is Y=757.0. Both top and
bottom produce corrections in the common oriented-output coordinate system:

```text
top correction    = top_reference_y - top_measured_y
bottom correction = bottom_reference_y - bottom_measured_y
```

Corrections within 5 px agree. A valid top measurement remains authoritative;
bottom agreement strengthens the evidence, while disagreement is recorded and
never blindly averaged. If top is unavailable or fails its existing dirt gate,
valid bottom becomes the same-frame rescue. Temporal interpolation is used only
if neither path is valid.

Bottom was valid on 999/1000 frames. Among 996 frames where both boundaries
were valid, 964 agreed and 32 logged a disagreement. Source selection was:

| Correction source | Frames |
|---|---:|
| Normal residual | 995 |
| Expanded residual | 2 |
| Bottom rescue | 3 |
| Temporal interpolation | 0 |
| Nearest-valid edge fallback | 0 |

Frame 3260 deliberately remains a normal residual correction despite a 13.38 px
bottom disagreement. Its top boundary passes the established gate, its +13.883
px correction is a required regression result, and target-local verification
finishes at -0.134 px. Bottom disagreement alone is not sufficient to override
a valid top measurement.

### Regression classifications

| Frame | Primary accepted | Classification | Applied correction | Post residual |
|---|---|---|---:|---:|
| 3260 | yes | accepted residual | +13.883 px | -0.134 px |
| 3451 | no | accepted residual | +46.929 px | -1.429 px |
| 3615 | yes | accepted bottom rescue; dirty top rejected | +1.611 px | -3.429 px |
| 3676 | yes | accepted bottom rescue; dirty top rejected | -1.000 px | -4.044 px |
| 3754 | no | accepted residual | +67.206 px | -1.143 px |
| 3846 | no | accepted residual | +57.095 px | -1.198 px |
| 3882 | no | accepted expanded residual | +82.429 px | -0.060 px |

The third dirty-boundary frame, 3635, also uses bottom rescue (-3.500 px). The
false top measurements at 3615 and 3676 remain rejected; bottom validation does
not rehabilitate them.

The isolated checker
`research/check_vertical_stabilization_regressions.py` asserts the required
source classifications, large-correction preservation, dirty-edge rejection,
primary-rejection status, and post-correction limits.

### Updated validation metrics

Adaptive search exposes real excursions that the earlier run silently replaced,
so the new before statistics are more complete rather than directly identical.

| Statistic | Before | Adaptive/bottom recrop |
|---|---:|---:|
| Mean absolute residual | 0.942 px | 0.162 px |
| Median absolute residual | 0.357 px | 0.113 px |
| RMS residual | 5.327 px | 0.314 px |
| 95th percentile absolute | 1.429 px | 0.405 px |
| 99th percentile absolute | 6.938 px | 0.646 px |
| Maximum absolute | 96.810 px | 4.044 px |
| Mean frame-to-frame movement | 1.592 px | 0.247 px |
| 95th percentile frame-to-frame | 3.285 px | 0.567 px |
| 99th percentile frame-to-frame | 30.465 px | 2.298 px |
| Maximum frame-to-frame | 97.199 px | 4.215 px |

Versus the preceding recrop/interpolation run, mean absolute residual is
effectively unchanged (0.16210 to 0.16233 px) and mean frame-to-frame movement
changes from 0.24598 to 0.24705 px. The important improvement is tail safety and
recovery: maximum trusted residual falls from 4.929 to 4.044 px, frame 3882 is
rescued, another 96.8 px excursion is recovered, and interpolation is eliminated
for this range.

Bottom rescue is safer than applying the false +28.96/+19.00 px top values, but
damaged frames 3615/3635/3676 still dominate the roughly 4 px residual floor.
The two sprocket boundaries do not always imply identical correction, so future
integration design still needs a stronger model for disagreement, perforation
damage, and local geometry. This iteration validates bottom as an independent
rescue signal; it does not prove that bottom should override every valid top
disagreement.

### Adaptive/bottom artifacts

```text
before.mp4
after_recrop.mp4
comparison.mp4
validation_report.json
diagnostics.csv
diagnostics.json
invalid_measurement_review.csv
event_clips/frame_3260_before_after_slow.mp4
event_clips/frame_3451_before_after_slow.mp4
event_clips/frame_3487_before_after_slow.mp4
event_clips/frame_3615_before_after_slow.mp4
event_clips/frame_3676_before_after_slow.mp4
event_clips/frame_3754_before_after_slow.mp4
event_clips/frame_3846_before_after_slow.mp4
event_clips/frame_3882_before_after_slow.mp4
```
