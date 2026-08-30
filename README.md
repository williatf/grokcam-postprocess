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
    -> legacy sprocket-pair detection -> primary validation
    -> optional frozen P07 same-frame physical-pair fallback
    -> include trusted same-frame registrations; exclude unresolved frames
    -> optional residual sprocket measurement/recovery
    -> one corrected full-resolution subpixel crop -> rotate/mirror/contrast
    -> restrained exposure and color normalization
    -> verified segment -> verified joined movie + JSON manifest
```

The detector works in full developed-frame pixels. `anchor_x` and `anchor_y`
are the midpoint of two adjacent sprocket bands. `crop_left` and `crop_top` are
that anchor plus the calibrated crop offsets. In `physical-p07-v1`, no temporal
anchor is manufactured: a frame still unresolved after all same-frame stages is
excluded and preserved as an uncropped developed TIFF for review. The rollback
`legacy` mode retains its historical interpolation behavior.

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
`--vertical-stabilization`. `--sprocket-detector-mode` selects either the
rollback-compatible `legacy` path or `physical-p07-v1`; the latter must be used
with a fresh output directory. The second-stage vertical registration is disabled
by default so existing commands preserve their established crop behavior.

Enable it for a new output directory with:

```bash
/home/todd/telecine/.venv/bin/python -m grokcam.cli.process_reel \
  RAW_DIR OUTPUT_DIR --vertical-stabilization
```

Enable the validated physical cascade deliberately with:

```bash
/home/todd/telecine/.venv/bin/python -m grokcam.cli.process_reel \
  RAW_DIR NEW_OUTPUT_DIR --sprocket-detector-mode physical-p07-v1
```

## Physical P07 cascade

`physical-p07-v1` keeps accepted legacy measurements and invokes the frozen
full-domain joint rigid-pair detector only for missing or locally rejected
primary measurements. Same-frame physical evidence is resolved before the
final include/exclude decision. Eligible `pair_actual` capture JSONL boxes
may define small physical-hole search ROIs; they never supply the accepted
registration coordinate. Missing/ineligible capture metadata falls through to
P07's complete independent physical search.

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
debug TIFF paths, and consecutive exclusion runs. Resume fails if an existing
output uses a different detector mode or failure policy. P07 reuses
the already-developed TIFF; residual vertical stabilization still adjusts crop
coordinates before the one final bicubic sample from that TIFF.

The fallback order is capture-seeded full-resolution two-hole evidence, P06
partner reconstruction only after one hole is independently evidenced, then
full-domain P07. P07's domain is never limited or vetoed by capture, primary,
or temporal priors. Any unresolved or ambiguous result is excluded from the
movie in this mode, whether isolated or consecutive; processing continues and
the omission is reported for review.

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
