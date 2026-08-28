# Capture-time versus production post-processing sprocket detection

Date: 2026-08-24

## Scope and conclusion

This audit compares the two deployed regimes, not the OpenCV research detector:

- capture commit `e0152e1`, preserved under `research/input/GrokCam_capture_source`;
- post-processing commit `2b8d7a6`, under `grokcam`.

Neither implementation was modified. Existing DNGs, outputs, manifests, and manual annotations were read only.

**Recommendation: E — use a hybrid architecture.** Capture measurements should become a strong, frame-specific prior/seed and an independent validation signal for production detection. They should not yet replace post-processing measurement or normally be trusted as final crop coordinates. Capture provides excellent temporal continuity and much higher coverage, while post-processing provides full-resolution measurement, explicit batch outlier rejection, and boundary refinement from the actual developed image. The two systems have complementary failure modes.

The strongest quantitative reason is that the capture pair midpoint has a direct physical Y mapping into the developed frame:

```text
developed_y = capture_preview_y * (1520 / 570) - 0.167 px
```

Using the Blue-derived mapping unchanged, it agrees within 5 developed pixels with accepted production primary anchors on 98.09% of Blue, 91.70% of Reel_28486, and 95.03% of Reel_46335 frames. Outliers remain large enough that direct unconditional trust would be unsafe.

## Capture-time pipeline

### Input and coordinate system

RAW capture configures a 760×570 `BGR888` preview alongside the immutable 2028×1520 `SRGGB12` DNG stream ([app.py](../research/input/GrokCam_capture_source/app.py#L28), [app.py](../research/input/GrokCam_capture_source/app.py#L766)). Detection runs on the already rendered 8-bit BGR preview while DNG writing proceeds concurrently; it does not inspect the Bayer DNG.

The preview pitch and area gates are scaled from full-resolution calibration ([app.py](../research/input/GrokCam_capture_source/app.py#L1432)). Exposure and gain are manually controlled with AE/AWB disabled ([app.py](../research/input/GrokCam_capture_source/app.py#L1781)). This controlled illumination is helpful but neither detector uses a single global fixed brightness threshold.

### Fast detector

`FastSprocketDetector.detect()` predicts two hole centers, runs one small ROI detector around each, then validates pair pitch and X agreement ([fast_sprocket.py](../research/input/GrokCam_capture_source/fast_sprocket.py#L39)).

- Initial centers are fixed normalized positions; subsequent centers are the previous accepted pair ([fast_sprocket.py](../research/input/GrokCam_capture_source/fast_sprocket.py#L63)).
- Each ROI is approximately ±270×±190 reference pixels, scaled to the preview ([fast_sprocket.py](../research/input/GrokCam_capture_source/fast_sprocket.py#L71)).
- Grayscale threshold is local: `background_p40 + 0.58*(peak_p99.5-background)`, clamped to 120–245 ([fast_sprocket.py](../research/input/GrokCam_capture_source/fast_sprocket.py#L86)). A 3×3 morphological open follows.
- A horizontal gate around the expected perforation width prevents bright picture content from merging into the hole ([fast_sprocket.py](../research/input/GrokCam_capture_source/fast_sprocket.py#L96)).
- External contours are gated by scaled width, height, aspect ratio, minimum area, ROI-edge contact, vertical ROI fill, rectangular fill, and distance from the prediction ([fast_sprocket.py](../research/input/GrokCam_capture_source/fast_sprocket.py#L110)).
- The two results must agree with calibrated pitch within 90 reference Y pixels and with X within 90 reference X pixels ([fast_sprocket.py](../research/input/GrokCam_capture_source/fast_sprocket.py#L49)).

This is genuine full-perforation detection: the returned tuple is the contour bounding-box center, width, height, and box area.

### Fallback detector

When fast detection fails, `run_raw_capture()` calls `SprocketDetector.detect(..., mode="profile")` ([app.py](../research/input/GrokCam_capture_source/app.py#L1964)). Despite the mode name, `detect()` first runs the scored contour detector, then merges legacy profile candidates if fewer than two contours were found ([sprocket.py](../research/input/GrokCam_capture_source/sprocket.py#L53)).

The fallback begins with the left 40% of the frame; after three samples it locks a tighter X-only dynamic ROI around observed holes, and resets after three misses ([app.py](../research/input/GrokCam_capture_source/app.py#L1441), [sprocket.py](../research/input/GrokCam_capture_source/sprocket.py#L72), [sprocket.py](../research/input/GrokCam_capture_source/sprocket.py#L93)).

Its contour path uses:

- grayscale and Gaussian blur;
- Gaussian adaptive threshold OR Otsu threshold;
- elliptical morphological open and close;
- external contours;
- dimension, calibrated area, aspect ratio, solidity, vertical-position, and frame-edge scoring.

The implementation is at [sprocket.py](../research/input/GrokCam_capture_source/sprocket.py#L285); geometry scoring is at [sprocket.py](../research/input/GrokCam_capture_source/sprocket.py#L579).

The legacy profile supplement samples the ROI center column, finds bands above 95% of its maximum, measures width on a row at 25% hole height, requires a row peak of 180, and applies geometry/area gates ([sprocket.py](../research/input/GrokCam_capture_source/sprocket.py#L441)).

Fallback results seed the fast detector ([app.py](../research/input/GrokCam_capture_source/app.py#L1990)). Every 25th frame, or when preview clipping reaches 15%, fallback cross-checks a successful fast result. A disagreement above 20 preview pixels replaces fast with the fallback pair and reseeds tracking ([app.py](../research/input/GrokCam_capture_source/app.py#L1977), [app.py](../research/input/GrokCam_capture_source/app.py#L2019)).

### Full/partial classification and pair selection

`classify_sprockets()` marks any bounding box within the vertical edge margin as partial ([sprocket.py](../research/input/GrokCam_capture_source/sprocket.py#L149)). Only full holes enter registration in RAW capture ([app.py](../research/input/GrokCam_capture_source/app.py#L1983)).

Pair selection tests every ordered pair. Pitch tolerance is the larger of 12 pixels or 35% of expected pitch. Its score combines pitch (45%), proximity of pair midpoint to frame center (30%), and the two individual geometry scores (12.5% each); minimum pair score is 0.30 ([sprocket.py](../research/input/GrokCam_capture_source/sprocket.py#L178)). If no pair is trustworthy, the best single full hole may be returned ([sprocket.py](../research/input/GrokCam_capture_source/sprocket.py#L231)).

### Temporal phase, registration, and transport

For a pair, registration Y is the midpoint of the two full-hole centers ([sprocket.py](../research/input/GrokCam_capture_source/sprocket.py#L248)). `RegistrationTracker`:

- accepts a pair midpoint directly and makes it the last-good position;
- converts a single hole to two possible pair midpoints using ±half pitch, choosing the phase nearest last-good;
- accepts that estimate only within a scaled 40-pixel full-resolution jump limit;
- otherwise holds last-good;
- also holds last-good when no measurement exists.

See [registration.py](../research/input/GrokCam_capture_source/registration.py#L25) and its half-pitch candidates at [registration.py](../research/input/GrokCam_capture_source/registration.py#L109). `smoothing_alpha` is stored but is not used; pair measurements are not smoothed.

Capture separately flags a pair-to-previous-pair phase jump above 0.22 pitch. Such a pair can still be selected for the preview crop, but it is barred from updating transport ([app.py](../research/input/GrokCam_capture_source/app.py#L2062), [app.py](../research/input/GrokCam_capture_source/app.py#L2084)). Trusted pair error relative to preview center drives the bounded adaptive motor controller; partial holes, disagreement, and phase jumps cannot update it.

The preview crop is registration-relative and scaled from the calibrated full-resolution crop ([app.py](../research/input/GrokCam_capture_source/app.py#L419)). Its purpose is live framing and transport control; the DNG itself remains uncropped.

After three consecutive missing pairs, capture steps forward in 10-step increments, using fallback full-pair detection until a pair lies within 80 preview pixels of target or 300 steps are exhausted ([app.py](../research/input/GrokCam_capture_source/app.py#L2140), [app.py](../research/input/GrokCam_capture_source/app.py#L245)).

## Production post-processing pipeline

### Development stage and input

Production selects contiguous `frame_*.dng` files only ([batch.py](../grokcam/batch.py#L52)). It develops every DNG once to a 16-bit TIFF using rawpy AHD demosaicing, calibrated camera white balance, linear gamma, sRGB output, and the frozen Darktable-match transform ([raw_development.py](../grokcam/raw_development.py#L49)). Primary sprocket detection runs on that full-resolution developed TIFF ([batch.py](../grokcam/batch.py#L177)).

No production module reads `raw_capture_metadata_*.jsonl`, `registration_metadata_*.jsonl`, capture crop rectangles, capture hole boxes, transport state, or capture detector confidence. Capture information is currently retained only as external debug provenance.

### Primary full-hole pair detector

`sprocket_detection.detect()` is a NumPy luminance-band detector, not the capture OpenCV contour logic ([sprocket_detection.py](../grokcam/sprocket_detection.py#L24)).

- ROI is a fixed developed-frame strip, X=100–570, across full image height.
- Luminance is the simple RGB mean.
- Threshold is 90% of the ROI 99th percentile.
- Rows with more than 130 bright pixels are grouped into contiguous bands.
- Band height must be 180–330 pixels.
- Adjacent bands must be separated by 785±100 pixels.
- Within each band, columns must be bright for more than 55% of its height; at least 200 columns are required.
- Candidate score combines pitch error, twice the two holes' X disagreement, and width error relative to 365 pixels.

Defaults are defined at [config.py](../grokcam/config.py#L12). The selected anchor is mean hole X and the midpoint between the two band centers. This detects the bright full-hole regions in projection, but does not form contours, calculate solidity, distinguish full from partial explicitly, or retain multiple holes after selecting the best adjacent pair.

### Batch validation and interpolation

Detection failures become `None`. `validate_batch()` compares X and Y independently against a five-frame local median, rejecting deviations of 12 X pixels or 45 Y pixels. Every rejected/missing coordinate is linearly interpolated inside the batch; `numpy.interp` holds the first/last valid value at batch edges ([sprocket_detection.py](../grokcam/sprocket_detection.py#L56)). There is no cross-batch temporal detector state.

This is temporally safer against isolated false anchors than capture's unconditional pair acceptance, but real single-frame transport excursions beyond 45 pixels are deliberately rejected and then incorrectly smoothed unless residual stabilization recovers them.

### Primary crop

The primary anchor becomes a source-space crop directly:

```text
crop_left = anchor_x + 159
crop_top  = anchor_y - 413
crop_size = 1133 × 900
```

See [registration.py](../grokcam/registration.py#L7) and [config.py](../grokcam/config.py#L30). Final output is sampled once from the developed TIFF with a bicubic extent transform, then vertically reoriented and contrast-adjusted ([image_processing.py](../grokcam/image_processing.py#L11)).

### Residual vertical stabilization

When enabled, production makes an in-memory provisional primary crop, JPEG-serializes it at quality 95 to match the validated detector input, and measures residual sprocket boundaries ([batch.py](../grokcam/batch.py#L188)). This stage refines crop Y only; it does not replace primary X registration.

The normal top detector searches output ROI `(0,150,90,285)` for the falling lower boundary of the retained upper hole. It uses Rec.709 luminance, a threshold of `max(0.70, p90*0.88)`, a smoothed bright-row fraction, gradient strength, local contrast, confidence, and a bright-tail rejection intended to exclude internal dirt/content edges ([vertical_stabilization.py](../grokcam/vertical_stabilization.py#L49)).

If primary was rejected and normal top detection is invalid, adaptive search expands upward to Y=60 ([vertical_stabilization.py](../grokcam/vertical_stabilization.py#L138)). An independent bottom detector searches `(0,550,90,900)` for the rising boundary of the lower retained hole ([vertical_stabilization.py](../grokcam/vertical_stabilization.py#L82)).

Top correction is `224.9286 - measured_top_y`; bottom correction is `757 - measured_bottom_y`. Out-of-source crops are rejected. A valid top wins; bottom rescues only an invalid top; otherwise correction is interpolated within the batch or held at batch edges ([vertical_stabilization.py](../grokcam/vertical_stabilization.py#L149)). Top/bottom disagreement is logged, but the current resolver does not use agreement to choose between two valid measurements.

The corrected crop is sampled directly from the original developed TIFF, so residual stabilization does not compound crops. Post-crop top residual is remeasured near the reference ([vertical_stabilization.py](../grokcam/vertical_stabilization.py#L213)).

## Side-by-side comparison

| Property | Capture production | Post-processing production |
|---|---|---|
| Detection image | 760×570 rendered BGR preview | 2028×1520 developed 16-bit TIFF; residual uses provisional 8-bit JPEG |
| Primary physical feature | Full bright perforation contour/bounding box | Full bright perforation row/column band |
| Residual feature | None | Upper/lower physical hole boundaries after primary crop |
| ROI | Two predicted local ROIs; fallback left 40% then dynamic X ROI | Fixed X=100–570 full height; residual fixed narrow left ROIs |
| Threshold | Fast local percentile contrast; fallback adaptive+Otsu plus profile maximum | Primary p99×0.90; residual max(0.70,p90×0.88) |
| Shape logic | Contours, size, aspect, area, fill, solidity, edge contact | No contours/solidity; band height, width, pitch, X agreement |
| Pitch | Calibrated; pair scoring and half-pitch single-hole phase | Fixed 785±100 pair gate; residual uses separately calibrated boundary references |
| Temporal state | Previous ROI centers, dynamic fallback ROI, last-good phase, single-hole estimate, motor control | Stateless primary detector; five-frame batch median and interpolation; residual same-frame rescue then interpolation |
| Partial holes | Explicitly classified and excluded from pair registration | Usually fail band/pair geometry; not explicitly classified |
| Picture false-edge defense | Local prediction, horizontal gate, contour geometry, solidity/fill, pair pitch/X, fallback cross-check | Narrow strip, high brightness percentile, large-band geometry, pair pitch/X; residual strength/contrast/tail gates |
| Failure behavior | Fallback, single ±half-pitch estimate, hold last-good, physical transport reacquisition | Reject then interpolate; residual expanded top and bottom rescue; fail batch if no usable measurement |
| Capture JSONL use | Writes it | Does not read it |
| X stabilization | Hole-center-derived preview crop, but archival DNG unchanged | Primary full-hole anchor controls final X crop |
| Y stabilization | Controls transport and preview crop | Primary anchor plus optional physical-boundary residual recrop |

The systems share the idea of two vertically adjacent bright holes, calibrated pitch, X consistency, and a sprocket-relative crop. They do **not** share detector code, thresholding, ROI strategy, contour logic, or temporal policy.

## Artifact benchmark

### Coverage and throughput

All percentages below use the unmodified capture JSONL and existing production manifests.

| Reel | Frames | Capture fast | Capture fallback/validation | Capture pair | Capture same-frame/estimated selected | Production detected | Production accepted | Production interpolated |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Blue | 5,153 | 5,136 (99.67%) | 17 (0.33%) | 5,140 (99.75%) | 5,153 (100%) | 5,150 (99.94%) | 5,128 (99.51%) | 25 (0.49%) |
| Reel_28486 | 5,125 | 5,110 (99.71%) | 15 (0.29%) | 5,119 (99.88%) | 5,122 (99.94%) | 5,125 (100%) | 5,124 (99.98%) | 1 (0.02%) |
| Reel_46335 | 4,615 | 4,528 (98.11%) | 86 plus 1 failure | 4,535 (98.27%) | 4,615 (100%) | 3,385 (73.35%) | 3,321 (71.96%) | 1,294 (28.04%) |

Capture selected-source details:

- Blue: 5,140 pair actual, 13 rejected-single/held values.
- Reel_28486: 5,119 pair actual, 3 rejected-single holds, 3 frames with no selected value at session start.
- Reel_46335: 4,535 pair actual, 65 single estimates, 13 rejected-single holds, 2 held-last-good.

Capture attempted reacquisition on 4/2/18 frames respectively and succeeded on 4/2/15. Mean logged capture detection time was 20.53/20.90/22.37 ms per frame; p95 was 31.21/33.84/98.57 ms. These timings exclude DNG writing and transport.

Production manifests do not retain detector-only duration, so detector throughput cannot be compared fairly after the temporary TIFFs have been deleted. Whole-pipeline manifest rates (development, registration, normalization, encoding, and I/O included) are not detector benchmarks and are therefore not presented as such.

### Coordinate agreement

Capture Y is a pair midpoint in preview pixels; production primary Y is a band-pair midpoint in developed pixels. They are comparable after scale conversion, although their threshold-defined centers can differ.

The mapping derived from Blue was only sensor scaling plus a subpixel offset:

```text
production_anchor_y ~= capture_selected_y * 2.6666667 - 0.1667
```

Applied without retuning:

| Reel | Comparable accepted frames | Y MAE | Y p95 absolute error | Within 5 px | Within 10 px | Maximum |
|---|---:|---:|---:|---:|---:|---:|
| Blue | 5,128 | 1.34 | 1.17 | 98.09% | 98.65% | 394.33 |
| Reel_28486 | 5,121 | 2.07 | 14.58 | 91.70% | 92.68% | 211.58 |
| Reel_46335 | 3,321 | 1.39 | 4.92 | 95.03% | 96.45% | 81.33 |

MAE exceeding p95 is caused by a very small, very large outlier tail. This is precisely why capture is suitable as a prior and disagreement alarm, but not as an unconditional final answer.

For X, Blue calibration is approximately:

```text
production_anchor_x ~= mean(capture_hole_x) * (2028/760) - 16.445
```

It is within 5 pixels on 93.80% of Blue and 94.97% of Reel_46335, but only 40.34% of Reel_28486; that reel has a median +8.51-pixel residual under the Blue X mapping. The offset is consistent with the two algorithms measuring different threshold-defined full-hole extents and possibly reel-dependent lateral film position. X therefore needs a per-capture calibration or a production refinement search around the capture prior.

### Manual ground truth and comparability

The 75 Blue, 50 Reel_28486, and 50 Reel_46335 annotations mark **upper and lower physical corners/boundaries in registered output ROIs**. They do not mark capture bounding-box centers or production primary bright-band centers. Calling center-to-corner distance a localization error would be invalid.

They can evaluate the final registered output against residual references, but the samples come from the existing research annotation packages and include visibility/damage cases. Against Y=224.9286 upper and Y=757 lower, the observed upper/lower MAE was:

- Blue: 7.24 / 9.53 px;
- Reel_28486: 7.98 / 8.08 px;
- Reel_46335: 45.24 / 19.21 px.

Those values characterize the annotated registered imagery, not capture detector localization. Reel_46335's high errors are consistent with its 28% primary interpolation rate and the known long difficult region. A future fair absolute benchmark would annotate the full-hole centers in the capture preview or transform the annotated source boundary into the uncropped developed frame.

### Known difficult frames

| Reel/frame | Capture result | Production primary | Existing production/residual finding |
|---|---|---|---|
| Blue 3260 | fast pair actual; transformed Y agrees by 0.08 px | accepted | real +13.883 px residual preserved |
| Blue 3451 | fast pair actual | primary rejected; capture and primary differ 40.54 px | residual rescued +46.929 px |
| Blue 3615 | fast pair actual; agrees 0.00 px | accepted | dirty top rejected; bottom rescue +1.611 px |
| Blue 3676 | fast pair actual; agrees 0.58 px | accepted | dirty top rejected; bottom rescue −1.000 px |
| Blue 3754 | fast pair actual | primary rejected; differs 45.12 px | residual rescued +67.206 px |
| Blue 3846 | fast pair actual | primary rejected; differs 42.29 px | residual rescued +57.095 px |
| Blue 3882 | fast pair actual | primary rejected; differs 37.08 px | expanded residual rescued +82.429 px |
| Reel_28486 3574 | fast pair actual; agrees 0.25 px | accepted | residual correction −0.905 px |
| Reel_46335 1010 | fast pair actual | production rejected/interpolated | manual/research detector difficult case |
| Reel_46335 1011/1013 | fallback single, converted by half-pitch temporal phase | production rejected/interpolated | capture supplies continuity, but not two-hole confirmation |

The Blue large-transport failures are particularly informative: capture retained a same-frame full pair on all of them while production's five-frame primary validation rejected the large motion. Capture JSONL would have provided an immediate warning against interpolation. Conversely, capture also has rare very large mapping outliers, so it cannot be treated as infallible.

## Does post-processing unnecessarily redetect capture information?

Partly, but not entirely.

It unnecessarily discards a high-coverage, same-frame full-hole pair observation that is already tied to the exact DNG frame number. Redetecting independently is still valuable because:

1. production operates at full resolution on its actual developed image;
2. capture and production thresholds define slightly different hole centers, especially in X;
3. post-processing must remain reproducible when JSONL is missing or an old capture version was used;
4. capture pair acceptance and last-good behavior can preserve a wrong phase/outlier;
5. residual stabilization measures physical boundaries that capture never measured.

Therefore the waste is not the second measurement; it is failing to use the first measurement as prior and cross-check.

## Recommended hybrid architecture (not implemented)

1. Import capture JSONL as optional, immutable provenance and verify one-to-one frame-number/DNG correspondence.
2. Transform capture pair boxes into developed coordinates using recorded preview/raw dimensions, not hard-coded dimensions.
3. Seed a bounded production search around the predicted two hole boxes. Keep the current independent broad search as recovery.
4. Compare capture and production implied pair midpoint, pitch, and X. Agreement should increase confidence; disagreement should be logged and sent to same-frame residual/boundary validation rather than immediate interpolation.
5. On a production-primary temporal rejection, prefer a geometrically sound capture full pair as a strong prior for expanded full-resolution or residual search. Blue 3451, 3754, 3846, and 3882 are the motivating cases.
6. Treat capture single estimates and held-last-good values as temporal priors only, never as direct registration measurements.
7. Retain production residual top/bottom boundary refinement and final full-resolution one-pass crop.
8. Preserve operation without capture metadata and record the chosen source and coordinate transform in the production manifest.

This architecture gains capture's continuity and physical transport knowledge without losing production's reproducibility, resolution, independent validation, and final-boundary precision.

## Evidence locations

- Capture JSONL: `/mnt/GrokCam/projects/{Blue_Reel,Reel_28486,Reel_46335}/debug/raw_capture_metadata_*.jsonl`
- Production manifests:
  - `/mnt/GrokCam/projects/Blue_Reel/outputs/production-v1/processing_manifest.json`
  - `/mnt/GrokCam/projects/Reel_28486/output_stabilized/processing_manifest.json`
  - `/mnt/GrokCam/projects/Reel_46335/output/processing_manifest.json`
- Manual annotations: `research/output/sprocket_xy/opencv_ground_truth_benchmark/*ground_truth.csv`
- Existing validated event results: [vertical_stabilization_production_validation.md](vertical_stabilization_production_validation.md)

