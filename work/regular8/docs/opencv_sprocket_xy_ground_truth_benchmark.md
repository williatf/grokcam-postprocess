# OpenCV Sprocket X/Y Ground-Truth Benchmark

## Scope and method

This is isolated research. Production code, calibration, manifests, DNGs, and
outputs are unchanged.

Seventy-five Blue Reel frames were annotated blind using the virtual
intersection of the straight film-side edge and straight horizontal sprocket
edge. OpenCV variants were evaluated only on Blue. The selected parameters were
then frozen in `research/opencv_sprocket_xy_blue_frozen.json` before inference
or manual review of Reel_28486 and Reel_46335.

The validation reels used prediction-assisted review after freezing. A reported
zero validation error means the reviewer explicitly accepted the displayed
marker without moving it: it is correct at visual/mouse review resolution, not
mathematical proof of exact or subpixel equality.

## Frozen detector

The detector uses independently normalized CLAHE ROIs, Gaussian-smoothed
horizontal and vertical physical edge profiles, subpixel peak fitting, fixed
Blue-derived measurement-bias corrections, and paired upper/lower confidence
and geometry gates.

Single-process throughput is 58–65 fps on the validation system.

## Results

| Metric | Blue | Reel_28486 | Reel_46335 |
|---|---:|---:|---:|
| Full-reel paired acceptance | 99.9% | 51.7% | 59.5% |
| Reviewed upper coverage | 100% | 54.0% | 53.1% |
| Reviewed lower coverage | 100% | 55.1% | 61.9% |
| Accepted false registrations | 0 | 0 | 0 |
| Median accepted X error | 0.89 / 0.97 px | 0 / 0 px* | 0 / 0 px* |
| P95 accepted X error | 2.86 / 3.40 px | 0 / 0 px* | 0 / 0 px* |
| Median accepted Y error | 1.03 / 1.64 px | 0 / 0 px* | 0 / 0 px* |
| P95 accepted Y error | 3.16 / 3.74 px | 0 / 0 px* | 0 / 0 px* |
| Median accepted geometry error | 1.91 / 2.12 px | 0 / 0 px* | 0 / 0 px* |

Upper/lower values are separated by `/`. `*` denotes explicit unchanged-marker
acceptance at manual review resolution.

The paired gates are safe but over-conservative. Among reviewed visible
sprockets, 14 upper and 13 lower Reel_28486 candidates and 16 upper and 16 lower
Reel_46335 candidates were within 3 px of ground truth but rejected at the pair
level.

## Geometry and rotation

| Dataset | Median lower_x − upper_x | Median Y spacing | Median angle | Angle standard deviation |
|---|---:|---:|---:|---:|
| Blue | −13.04 px | 524.01 px | −1.425° | 0.245° |
| Reel_28486 | −11.02 px | 519.65 px | −1.213° | 0.288° |
| Reel_46335 | −12.08 px | 522.33 px | −1.328° | 0.132° |

The approximately 15 px original detector offset was a combination of real
film/camera geometry and detector bias. All reels retain a roughly −1.2° to
−1.4° axis, supporting a camera-fixed component with smaller reel/frame
variation. Roughly 1.3° corresponds to about 20 px lateral displacement over a
900 px frame and is geometrically material.

Test a fixed research rotation first. Per-frame rotation is not yet justified:
its repeatability and added resampling cost need separate validation.

## Failure classification

- Reel_28486 raw false candidates concentrate in severe bright/leader
  transitions around frames 4928–4963. The frozen pair gates reject them.
- Reel_46335 has upper-edge failures in low-visibility/content regions and a
  non-visible lower corner in 8/50 reviewed frames. These cases are rejected.
- There were no accepted false registrations in either reviewed validation set.
- The dominant failure is false rejection, not unsafe acceptance.

## Recommendation

**NEEDS ADDITIONAL RESEARCH.**

Localization is trustworthy when the frozen paired detector accepts, but
52–60% full-reel acceptance is insufficient. The next experiment should use
the existing frozen results to design confidence/geometry fusion that can
accept individually correct same-frame candidates without weakening rejection
of bright/leader and low-visibility failures. Any new detector must be developed
without tuning on these validation labels, then frozen and rerun across all
three reels.

