# Physically Aware Residual Sprocket Detector POC

## Scope and status

This is an isolated research detector for the residual vertical-stabilization
measurement only. It does not alter primary registration, calibration,
manifests, production code, or existing production output. The source movies
are primary-registered crops; final POC review movies are recropped directly
from each full-resolution developed TIFF using the established sign convention:

`corrected_crop_top = primary_crop_top + residual_correction_y`

There is no correction cap and no temporal smoothing. Missing measurements are
interpolated only after all same-frame candidate selection is complete.

## Detector design

The left 90-pixel sprocket area is divided into five 18-pixel strips. Candidate
top (falling) and bottom (rising) boundaries receive subpixel positions and are
scored using:

- edge score: strength of the thresholded boundary gradient;
- strip score: support and positional agreement across the five strips;
- shape score: contiguous horizontal width and bright-hole depth/continuity;
- location score: a deliberately weak expected-position prior;
- geometry score: agreement between the correction implied by top and bottom
  references, with an 8-pixel pairing tolerance;
- temporal score: reported evidence based on the preceding accepted correction.

Paired score weights are 20% edge, 20% strip agreement, 30% shape, 25% dual
geometry, and 5% location. Single-reference score weights are 25% edge, 25%
strip agreement, 40% shape, and 10% location. A top single requires a score of
at least 0.58 plus shape and strip gates. A bottom single is deliberately much
stricter (0.78, stronger shape, and stronger strip support). An abrupt unpaired
change over 15 pixels requires an overwhelming single score of at least 0.90.

Temporal consistency is a validation gate, not a correction transform. When a
candidate conflicts with recent position, the detector may choose another
same-frame, physically valid pair/top candidate. It never substitutes the
previous correction or smooths a measured correction.

## Results

### Blue Reel, frames 3000-3999

The physical detector produced 1,000 same-frame measurements and no
interpolation: 995 paired and 5 top-only. Correction statistics were 0.872 px
mean absolute, 5.199 px RMS, 1.431 px at the 95th percentile, and 94.699 px
maximum. Mean correction movement was 1.444 px/frame.

The required large excursions were preserved:

| Frame | Source | Correction |
|---:|---|---:|
| 3260 | top | +13.857 px |
| 3487 | paired | +94.699 px |
| 3882 | paired | +82.715 px |

The verified H.264 review render yielded 745 usable legacy top-verifier
measurements, with 1.019 px mean absolute residual, 1.404 px RMS, 2.321 px at
the 95th percentile, and 10.095 px maximum. This metric is not directly
equivalent to the existing detector's target-local pre-encode verifier, so it
should be treated as a playback-output check, not a sharpness or quality claim.

### Reel_28486, frames 1-5125

The physical detector produced 4,838 same-frame measurements and interpolated
287 frames: 4,242 paired and 596 top-only. It produced no bottom-only rescue.
Correction statistics were 2.488 px mean absolute, 4.532 px RMS, 8.993 px at
the 95th percentile, and 62.462 px maximum. Mean correction movement was 1.858
px/frame.

The existing detector's Reel_28486 corrections were 21.752 px mean absolute,
48.258 px RMS, 123.738 px at the 95th percentile, and 204.750 px maximum. Its
source counts were 4,104 measured, 897 bottom rescues, and 124 interpolated.
The new detector removed every correction over 100 px, including the false
Y≈553 family, without using a correction cap.

Required false-positive events were handled conservatively:

| Frame | Physical result | Correction |
|---:|---|---:|
| 130 | interpolated | -11.425 px |
| 2596 | interpolated | +15.089 px |
| 5017 | top | +9.679 px |
| 5063 | top | +1.754 px |

The existing detector had 1,667 top/bottom disagreements over 5 px and a
maximum disagreement of 257.171 px. The new detector never accepts a pair with
more than 8 px disagreement; exact accepted-pair statistics are retained in
`validation_report.json`.

## Remaining failure modes and tradeoffs

- On Reel_28486, conservative rejection increased interpolation from 124 to
  287 frames. The POC therefore does not meet the requested "less
  interpolation" criterion on that reel, although Blue remained at zero.
- Light fades and partial holes can remove enough vertical continuity to reject
  all same-frame candidates. That is intentional until there is stronger
  evidence than a bright horizontal edge.
- A strong top-only physical shape can still be selected when the bottom is not
  visible. The stricter abrupt-change gate limits, but cannot mathematically
  eliminate, all single-reference ambiguity.
- Metrics produced by different verifier populations must not be compared as if
  they measure identical frame subsets.
- The detector was evaluated on two reels. Other stocks, exposure ranges,
  sprocket formats, and crop geometries remain out of sample.

## Recommendation

Do not integrate this iteration yet. It is a substantially safer candidate to
replace only the residual detector, but the Reel_28486 interpolation increase
should be understood and reviewed before production use. A next iteration
should improve same-frame recovery using physical evidence (for example a
calibrated rounded-rectangle/template score), while preserving the present
false-positive rejection behavior.

It should not influence primary registration at this stage. Any use in primary
registration needs a separate POC and validation set because that expands the
detector's role beyond the architecture tested here.
