# GrokCam production post-processing

This repository contains one production processing path for GrokCam archival
DNG captures. It preserves the approved learned Darktable-matched RAW
development, physical sprocket registration, calibrated loose crop, orientation
correction, restrained temporal normalization, and verified H.264 output.

The DNG source directory is read-only input. Disposable intermediates belong in
`work/`; retained movies and manifests belong under the project's `outputs/`
directory.

New processing manifests identify the consolidated application as
`grokcam_postprocess`. The earlier
`grokcam_raw_production_darktable_matched` identifier remains historical
provenance only.

## Processing flow

```text
DNG -> matched RAW development -> 16-bit RGB TIFF
    -> primary detector places frozen P15 lower-top ROI
    -> P15 success: authoritative optical lower-top
    -> P15 failure: forced frozen P07 -> frozen P22 common-Y refinement
    -> include registered frames; exclude and preserve P07 rejections
    -> one corrected full-resolution subpixel crop -> rotate/mirror/contrast
    -> restrained exposure and color normalization
    -> verified segment -> verified joined movie + JSON manifest
```

The detector works in full developed-frame pixels. `anchor_x` and `anchor_y`
are the midpoint of two adjacent sprocket bands. In `physical-p07-v1`, crop Y
comes from the optical lower-top landmark, not the historical anchor. No temporal
anchor is manufactured: a frame still unresolved after all same-frame stages is
excluded and preserved as an uncropped developed TIFF for review. The rollback
`legacy` mode retains its historical interpolation behavior.

The complete batch lifecycle lives in the production package. `grokcam.batch`
owns selection, locking, restart planning, staging, stage order, cleanup, and
finalization; `grokcam.encoding` owns FFmpeg and verification; and
`grokcam.manifest` owns atomic processing state. Historical scripts are not
runtime dependencies.

## Run a reel

Use the single canonical GrokCam production environment already provisioned for
the telecine VM: `/home/todd/telecine/.venv`. The project is installed there in
editable mode while development continues. The equivalent installed console
entry point is `grokcam-process-reel`.

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
`--vertical-stabilization`. Production staging defaults to the local
`/mnt/grokcam-scratch` filesystem; use `--staging-dir PATH` to override it.
`--sprocket-detector-mode` selects the production
default `physical-p07-v1` or rollback-only `legacy`; either must use an output
directory whose manifest has the same recorded policy. Residual vertical
registration is available only in legacy mode.

Enable it for a new output directory with:

```bash
/home/todd/telecine/.venv/bin/python -m grokcam.cli.process_reel \
  RAW_DIR OUTPUT_DIR --sprocket-detector-mode legacy --vertical-stabilization
```

The promoted policy is now the default; it can also be named explicitly with:

```bash
/home/todd/telecine/.venv/bin/python -m grokcam.cli.process_reel \
  RAW_DIR NEW_OUTPUT_DIR --sprocket-detector-mode physical-p07-v1
```

## Physical P07 cascade

`physical-p07-v1` first uses the current primary to place frozen P15. If that
measurement is unavailable or rejects, the frozen P24 gate may place P15 from
capture metadata only after exact capture-geometry and local physical-hole
corroboration predicates pass. A P24-guided P15 success registers frozen
P25-calibrated capture X and measured P15 Y. Otherwise unchanged P07 searches
its full physical domain and accepted P07 proceeds to P22. Capture Y is guidance
only and physical-hole evidence is corroboration only.

P07 uses immutable 381.5842105263158 × 272 px holes, 785 px pitch, and
+18.678947368421063 px lower-minus-upper X offset. Evidence is classified as
supported, missing, or contradicted; missing damage cannot deform the template,
and competing physical placements remain rejected. Its only optimized behavior
is exact invocation-local candidate memoization. Coarse spacing 24/32 and the
uint8 histogram percentile experiment remain rejected as non-equivalent.

The manifest records the detector mode, frozen source/configuration hashes,
exact-cache hash, fallback attempts, physical centers and anchor, feature
states, joint/geometry/competitor scores, rejection reason, and final source.
It also records the failure policy, source-to-encoded-frame mapping, preserved
debug TIFF paths, consecutive exclusion runs, and separate P15/P07/P22 timings.
Resume fails if an existing output uses a different detector mode, policy, or
implementation hash. P07 and P22 reuse the already-developed TIFF.

After P07 accepts, P22 searches only a ±3 px common-Y translation at 0.25 px,
then adds the frozen 4.178787846871160 px optical calibration. It cannot change
identity, X, geometry, or acceptance. Crop top is optical lower-top minus
673.5297914597816 px. Residual vertical stabilization is prohibited in this
mode. Any P07 rejection is excluded from the movie, preserved, and reported;
processing continues.

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

The manifest records source identity, disposition, source-to-output mapping,
detection score, trusted anchor and crop coordinates, exclusion provenance,
residual stabilization measurements and sources when enabled, normalization
measurements/corrections, timings, checksums, and video verification. A missing
match report, noncontiguous
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
