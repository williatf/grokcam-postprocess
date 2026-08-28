# Two-Axis Sprocket Stabilization Research Plan

## Objective

Develop a fast, conservative sprocket measurement system that supplies exact
same-frame X and Y translation evidence. Production integration is out of scope
until accuracy, coverage, and false-positive behavior are validated across the
Blue Reel, Reel_28486, and Reel_46335.

## Coordinate model

- `x`: film-side/right boundary of the left sprocket opening.
- `y_top`: lower boundary of the upper opening.
- `y_bottom`: upper boundary of the lower opening.
- `correction_x = reference_x - measured_x`.
- `correction_y = reference_y - measured_y`.

Upper and lower measurements must first be transformed through calibrated
fixed geometry. They must not be averaged in raw coordinates. The initial
Reel_46335 sparse benchmark shows a median 15 px raw X difference and 545.5 px
raw Y spacing, confirming that calibration is required.

## Research sequence

1. Build a manually reviewed, stratified ground-truth set containing normal,
   dark, damaged, dirty, large-transport, and primary-rejected frames from all
   three reels.
2. Calibrate the stable upper/lower X offset and Y spacing without changing
   production calibration.
3. Compare CLAHE/Otsu connected components, gradient contours, and template or
   distance-transform localization using the same ground truth.
4. Add subpixel boundary fitting and upper/lower geometry agreement.
5. Apply temporal evidence only after same-frame physical validation; retain
   the exact accepted measurement and do not smooth at measurement time.
6. Produce X-only, Y-only, and X/Y review renders from a single full-resolution
   source sampling operation.

## Evaluation gates

- Report measurement coverage separately from validated acceptance coverage.
- Report X and Y error independently, including signed mean, MAE, RMS, p95,
  maximum, and catastrophic-error counts.
- Preserve all established Blue Reel large movements.
- Reintroduce none of Reel_28486's known false large corrections.
- Improve Reel_46335 same-frame coverage without weakening physical gates.
- Benchmark throughput on one CPU process and with restartable parallel batches.
- Reject or interpolate when same-frame evidence is not trustworthy.

## Current baseline

`research/opencv_sprocket_xy_poc.py` is a candidate-generation benchmark, not a
stabilizer. On every 16th frame of the 4,615-frame Reel_46335 validation video:

- measured frames: 289;
- upper candidates: 187 (64.7%);
- lower candidates: 188 (65.1%);
- paired candidates: 169 (58.5%);
- median raw upper/lower X disagreement: 15.0 px;
- p95 raw X disagreement: 17.6 px;
- median raw Y spacing: 545.5 px.

This is sufficient to establish the tooling and expose geometry, but not yet
reliable enough to drive a crop.

