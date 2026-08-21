# GrokCam production post-processing

This repository contains one production processing path for GrokCam archival
DNG captures. It preserves the approved learned Darktable-matched RAW
development, physical sprocket registration, calibrated loose crop, orientation
correction, restrained temporal normalization, and verified H.264 output.

The DNG source directory is read-only input. Disposable intermediates belong in
`work/`; retained movies and manifests belong under the project's `outputs/`
directory.

## Processing flow

```text
DNG -> matched RAW development -> 16-bit RGB TIFF
    -> sprocket-pair detection -> primary validation/interpolation
    -> optional residual sprocket measurement/recovery
    -> one corrected full-resolution subpixel crop -> rotate/mirror/contrast
    -> restrained exposure and color normalization
    -> verified segment -> verified joined movie + JSON manifest
```

The detector works in full developed-frame pixels. `anchor_x` and `anchor_y`
are the midpoint of two adjacent sprocket bands. `crop_left` and `crop_top` are
that anchor plus the calibrated crop offsets. An interpolated anchor is a
registration fallback after a missing or rejected measurement; it is not a
second image detector.

The complete batch lifecycle lives in the production package. `grokcam.batch`
owns selection, locking, restart planning, staging, stage order, cleanup, and
finalization; `grokcam.encoding` owns FFmpeg and verification; and
`grokcam.manifest` owns atomic processing state. Historical scripts are not
runtime dependencies.

## Run a reel

Use the processing virtual environment already provisioned for this project:

```bash
/home/todd/telecine/.venv/bin/python -m grokcam.cli.process_reel \
  /mnt/GrokCam/projects/RAW_Test/raw \
  /mnt/GrokCam/projects/RAW_Test/outputs/my-reel \
  --batch-frames 300 --fps 16 --jobs 3 --minimum-free-gib 22
```

First inspect a plan without processing:

```bash
/home/todd/telecine/.venv/bin/python -m grokcam.cli.process_reel \
  RAW_DIR OUTPUT_DIR --plan-only
```

Useful options are `--first`, `--last`, `--batch-frames`, `--jobs`, `--fps`,
`--minimum-free-gib`, `--calibration`, `--match-report`, and
`--vertical-stabilization`. The second-stage physical registration is disabled
by default so existing commands preserve their established crop behavior.

Enable it for a new output directory with:

```bash
/home/todd/telecine/.venv/bin/python -m grokcam.cli.process_reel \
  RAW_DIR OUTPUT_DIR --vertical-stabilization
```

## Calibration

Golden values live in `grokcam/config.py`. They include the sprocket search
window and geometry, outlier limits, crop offsets/dimensions, normalization
bounds, and match-report path. `--calibration FILE.json` may override named
values; unknown keys fail clearly. Camera/color matching coefficients and LUTs
live in the versioned golden report and are validated before any frame is
processed.

The golden report is now version-controlled under `calibrations/`. Offline
relearning and candidate validation are documented in
[`docs/calibration.md`](docs/calibration.md); production never retrains itself.

## Output, resume, and failures

Each verified batch is recorded in `processing_manifest.json`. A restart keeps
segments only when both their manifest record and video exist. It processes
remaining contiguous ranges without bridging gaps. A final movie is retained
only after frame-count probing and a full decode; reproducible TIFF/JPEG caches
and component segments are then removed.

The manifest records source identity, detection score, measured/interpolated
status, anchor and crop coordinates, residual stabilization measurements and
sources when enabled, normalization measurements/corrections, timings,
checksums, and video verification. A missing match report, noncontiguous
input, insufficient free space, absence of any usable sprocket measurements, or
failed video verification stops the run explicitly.

## Regression checks

Compare geometry and detector decisions with a saved reference manifest:

```bash
/home/todd/telecine/.venv/bin/python -m grokcam.cli.compare_reference \
  reference/processing_manifest.json candidate/processing_manifest.json
```

Add `--reference-image` and `--candidate-image` to report MAE, maximum error,
MSE, and PSNR for representative still images.

Run tests with:

```bash
/home/todd/telecine/.venv/bin/python -m unittest discover -s tests -v
```

## Troubleshooting

- Missed sprockets: inspect `detected`, `accepted`, `interpolated`, and
  `detector_score` in each frame record. A whole batch without a usable anchor
  is fatal.
- Registration or crop anomalies: compare `anchor_x/y` and `crop_left/top`
  against neighbors. Coordinates are developed-frame pixels.
- Resume surprises: verify the segment path still exists and its manifest entry
  says `verified: true`.
- Color differences: confirm the exact `--match-report` and its recorded model,
  coefficients, LUTs, and white-balance correction.
- Processing failures: retain the manifest and console log; the current batch's
  staging directory is disposable and can be regenerated from DNGs.
