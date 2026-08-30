# GrokCam RAW post-processing production guide

This is the operational and technical guide for the GrokCam production RAW
processor established by commit `2b7abbe` and baseline tag
`grokcam-production-v1`. It describes the current `grokcam/` package and is the
authoritative processing guide.

The canonical command is:

```bash
/home/todd/telecine/.venv/bin/python -m grokcam.cli.process_reel
```

The archival DNG directory is read-only source material. Processing creates
derived work and output files elsewhere; it never edits, renames, moves, or
deletes source DNGs.

## 1. Overview

The production path is:

```text
archival DNG
    |
    v
learned Darktable-matched rawpy development
    |
    v
temporary 16-bit RGB TIFF
    |
    v
sprocket-pair detection
    |
    v
batch validation and interpolation
    |
    v
optional residual sprocket measurement and recovery
    |
    v
one corrected full-resolution subpixel crop
    |
    v
orientation and contrast
    |
    v
restrained temporal exposure/color normalization
    |
    v
verified H.264 segment(s)
    |
    v
verified final movie + processing manifest
```

The design has two anchors:

- The sprocket holes are the physical registration reference. The processor does
  not substitute generic image stabilization.
- RAW appearance comes from a frozen, versioned calibration learned against the
  approved Darktable rendering. Production does not run Darktable per frame and
  does not learn while processing a reel.

## 2. Production architecture

The important modules are grouped by responsibility rather than framework
layers:

| Area | Modules | Responsibility |
|---|---|---|
| Entry and composition | `grokcam.cli.process_reel`, `grokcam.pipeline` | Parse the supported CLI, load calibration, and invoke the production pipeline. |
| Batch lifecycle | `grokcam.batch`, `grokcam.resume`, `grokcam.timing` | Select frames, lock an output, plan/resume batches, stage work, order the stages, report timing, clean work, and finalize. |
| RAW development | `grokcam.raw_development` | Validate and apply the frozen rawpy-to-Darktable match and write 16-bit TIFFs. |
| Film geometry | `grokcam.sprocket_detection`, `grokcam.physical_sprocket`, `grokcam.registration`, `grokcam.vertical_stabilization`, `grokcam.image_processing` | Detect and validate primary anchors, optionally recover rejected frames with frozen P07 physical evidence, refine vertical alignment, calculate crop coordinates, resample once for final output, orient, and apply contrast. |
| Presentation normalization | `grokcam.normalization` | Apply bounded, temporally smoothed exposure and channel corrections. |
| Video and records | `grokcam.encoding`, `grokcam.manifest`, `grokcam.regression` | Encode and verify video, write atomic manifests, calculate hashes, and compare results with a reference. |
| Configuration and data | `grokcam.config`, `grokcam.models` | Own calibrated constants and structured geometry/detection values. |

Data flow through one batch is:

```text
RunOptions + ProductionCalibration
              |
              v
        select contiguous DNGs
              |
              v
   threaded DarktableMatchedDeveloper
              |
              v
      detect each TIFF -> validate primary batch
              |
              v
 rejected only: capture-ROI physical pair -> P06 partner -> full P07
              |
              v
 optional residual measurement -> resolve corrections
              |
              v
 final full-resolution crop/register -> JPEG
              |
              v
      normalize sequence -> JPEG
              |
              v
       FFmpeg encode -> verify -> manifest
```

## 3. Canonical production command

### Runtime prerequisites

Use the project virtual environment at `/home/todd/telecine/.venv`. The Python
package dependencies are NumPy, Pillow, rawpy, and tifffile. Production also
requires FFmpeg and FFprobe; it does not require Darktable. Confirm the external
video tools before a long run:

```bash
/home/todd/telecine/.venv/bin/python -c \
  'import numpy, PIL, rawpy, tifffile; print(rawpy.__version__, rawpy.libraw_version)'
ffmpeg -version | head -1
ffprobe -version | head -1
```

The lock implementation uses POSIX `flock`, so this production command targets
the current Linux environment.

### Basic syntax

```bash
/home/todd/telecine/.venv/bin/python -m grokcam.cli.process_reel \
  RAW_DIR OUTPUT_DIR [options]
```

`RAW_DIR` and `OUTPUT_DIR` are positional and required.

### Recommended normal-reel command

```bash
/home/todd/telecine/.venv/bin/python -m grokcam.cli.process_reel \
  /mnt/GrokCam/projects/RAW_Test/raw \
  /mnt/GrokCam/projects/RAW_Test/outputs/production-v1 \
  --batch-frames 300 \
  --fps 16 \
  --jobs 3 \
  --minimum-free-gib 22
```

The CLI default batch size is 960 frames. A 300-frame batch is a conservative
operational choice that reduces peak disposable storage and restart cost.

### Supported arguments

| Argument | Default | Meaning |
|---|---:|---|
| `raw_dir` | required | Directory containing the source `frame_*.dng` sequence. |
| `output_dir` | required | Dedicated directory for the manifest, staging, segments, and final movie. It is created if missing. |
| `--first N` | all | Select frames numbered `N` or higher. Inclusive. |
| `--last N` | all | Select frames numbered `N` or lower. Inclusive. |
| `--batch-frames N` | `960` | Maximum frames in each independently encoded batch. Must be positive. |
| `--fps N` | `16` | Input sequence and output movie frame rate. |
| `--jobs N` | `3` | Maximum concurrent rawpy development workers. At least one worker is used. |
| `--crop-preset loose` | `loose` | The only supported crop preset. |
| `--ffmpeg PATH` | discovered in `PATH`, otherwise `/usr/local/bin/ffmpeg` | FFmpeg executable. |
| `--ffprobe PATH` | discovered in `PATH`, otherwise `/usr/local/bin/ffprobe` | FFprobe executable. |
| `--minimum-free-gib N` | `22.0` | Refuse to start or continue a batch below this free-space threshold on the output filesystem. |
| `--plan-only` | off | Show selected remaining ranges and batches without processing images. |
| `--dry-run` | off | Exact alias for `--plan-only`. |
| `--calibration FILE` | none | Advanced JSON overrides for production calibration. Not needed for normal v1 processing. |
| `--match-report FILE` | repository v1 artifact | Explicitly override the learned match report. Avoid for normal v1 production. |
| `--vertical-stabilization` | off | Enable second-stage physical vertical registration. Use a new output directory. |
| `--sprocket-detector-mode MODE` | `legacy` | Select `legacy` rollback behavior or the frozen `physical-p07-v1` same-frame fallback cascade. Never mix modes in one output directory. |
| `-h`, `--help` | — | Print the authoritative CLI usage and exit. |

The current configuration loader accepts detector, crop, match-report,
vertical-stabilization, and contrast overrides. It also parses normalization-related keys, but the v1
normalizer uses its frozen code constants directly; do not expect those JSON
keys to change normalization behavior.

### Short representative test

Use a new output directory so the test manifest cannot be confused with a full
reel:

```bash
/home/todd/telecine/.venv/bin/python -m grokcam.cli.process_reel \
  /mnt/GrokCam/projects/RAW_Test/raw \
  /home/todd/telecine/grokcam-postprocess/work/reel-smoke-test \
  --first 120 \
  --last 123 \
  --batch-frames 4 \
  --jobs 2 \
  --minimum-free-gib 1
```

### Capturing a console log

The application writes progress and stage timing to stdout/stderr; it does not
create a standalone log file. Capture one with the shell when desired:

```bash
set -o pipefail
mkdir -p /mnt/GrokCam/projects/RAW_Test/outputs/production-v1
/home/todd/telecine/.venv/bin/python -m grokcam.cli.process_reel \
  /mnt/GrokCam/projects/RAW_Test/raw \
  /mnt/GrokCam/projects/RAW_Test/outputs/production-v1 \
  --batch-frames 300 --fps 16 --jobs 3 --minimum-free-gib 22 \
  2>&1 | tee /mnt/GrokCam/projects/RAW_Test/outputs/production-v1/run.log
```

## 4. Input and output directory structure

### Input requirements

The processor searches only for lowercase filenames matching:

```text
frame_*.dng
```

The integer after the final underscore is the frame number. A typical source is:

```text
/mnt/GrokCam/projects/RAW_Test/raw/
├── frame_000001.dng
├── frame_000002.dng
├── frame_000003.dng
└── ...
```

After `--first` and `--last` filtering, frame numbers must be contiguous. Uppercase
`.DNG`, unrelated names, and a sequence with a missing number are not accepted by
the current enumerator.

Never use the archival RAW directory as `OUTPUT_DIR`.

### Output during processing

For a batch covering frames 1–300, the output may temporarily look like:

```text
production-v1/
├── .pipeline.lock
├── .staging/
│   └── segment_000001_000300/
│       ├── tiff/
│       │   ├── frame_000001.tif
│       │   └── ...
│       ├── registered/
│       │   ├── frame_000001.jpg
│       │   └── ...
│       └── normalized/
│           ├── frame_000001.jpg
│           └── ...
├── segments/
│   ├── frames_000001_000300_16fps.mp4
│   └── frames_000301_000600_16fps.mp4
└── processing_manifest.json
```

The segment filename currently contains the literal suffix `_16fps` even when a
non-default `--fps` is selected. The encoded rate follows `--fps`; the segment
basename is a v1 naming quirk. The final movie name uses the actual requested
rate.

### Output after successful finalization

For frames 1–3483 at 16 fps:

```text
production-v1/
├── .pipeline.lock
├── .staging/
├── RAW_review_000001_003483_16fps.mp4
├── processing_manifest.json
└── run.log                         # only if captured with tee
```

After final verification, component segment videos and `segments.txt` are
deleted, and `segments/` is removed if empty. Batch TIFFs and both JPEG sequences
are also deleted after their segment is verified. The empty `.staging/` directory
and lock file may remain.

The lock file's existence does not mean a process is running: exclusivity is
provided by an operating-system `flock`, which is released when the process
exits.

## 5. RAW development and Darktable matching

Production does **not** invoke Darktable for each reel frame. It uses rawpy and
the frozen artifact `calibrations/darktable_match_v1.json` to reproduce the
approved Darktable appearance.

For each DNG, `DarktableMatchedDeveloper` performs this exact sequence:

1. Read the DNG with rawpy.
2. Read the first three embedded camera-white-balance values and form RGBG as
   `[R, G, B, G]`.
3. Multiply by the frozen RGBG correction:

   ```text
   [1.06982421875, 1.0, 1.0991804599761963, 1.0]
   ```

4. Call rawpy with:
   - AHD demosaicing;
   - `use_camera_wb=False` and the calculated `user_wb`;
   - 16-bit output;
   - no automatic brightening;
   - linear gamma `(1, 1)`;
   - sRGB output color space.
5. Convert the 16-bit result to float32 `[0,1]`.
6. Build 13 features per pixel: constant, linear RGB, square-root RGB, squared
   RGB, and the three cross-channel products.
7. Apply the fitted 13×3 coefficients and clip to `[0,1]`.
8. Map each channel through its monotonic 256-entry LUT using linear
   interpolation, then clip again.
9. Round to unsigned 16-bit and write a TIFF with tifffile.

The matrix/LUT combination captures the selected Darktable color and tonal
behavior without invoking Darktable during normal production. It was fitted
offline from paired renders of representative frames.

## 6. Frozen production calibration

Production v1 owns two repository files:

```text
calibrations/darktable_match_v1.json
calibrations/darktable_match_v1.metadata.json
```

The artifact SHA-256 is:

```text
d5a4526b6b5e38fd9d7b37876b0ec39cb37a370d066419433db38f978cb3dc96
```

Verify it from the repository root:

```bash
sha256sum calibrations/darktable_match_v1.json
```

The metadata identifies calibration ID `grokcam-darktable-match-v1`, adoption
status `golden_production`, 24 training frames, eight holdout frames, 2028×1520
RAW/processed dimensions, RGBG CFA assumptions, and the reference software:

| Component | Recorded version |
|---|---:|
| Python | 3.14.4 |
| NumPy | 2.5.2 |
| rawpy | 0.27.0 |
| LibRaw | 0.22.1 |
| Darktable used for fitting | 5.4.1 |

Before the first development batch, production reads the JSON and validates the supported model name,
13 coefficient rows, three 256-entry LUTs, and four white-balance values. It
does not write the artifact. A new manifest records its resolved path, SHA-256,
model, creation date, and training/holdout identifiers.

Inference is deterministic for fixed DNG bytes, calibration bytes, code,
rawpy/LibRaw/NumPy/tifffile versions, and compatible floating-point behavior.
Rawpy or LibRaw changes can alter demosaicing or metadata interpretation even
when the JSON is unchanged, so exact upgrades require the v1 regression.

## 7. Sprocket detection

Detection operates in full developed-frame pixel coordinates: origin `(0,0)` is
the upper-left of the approximately 2028×1520 RGB TIFF; `x` increases rightward
and `y` downward.

Current detector constants are:

| Parameter | Value |
|---|---:|
| Search region | `x = 100..569` (`100:570`) |
| Bright percentile | 99.0 |
| Threshold multiplier | 0.90 |
| Minimum bright pixels in a row | 131 effectively (`sum > 130`) |
| Valid bright-band height | 180–330 px inclusive |
| Expected pair pitch | 785 px |
| Pitch tolerance | 100 px |
| Minimum qualifying bright columns | 200 |
| Required per-column band fill | greater than 55% |
| Expected hole width used by score | 365 px |
| Horizontal batch outlier limit | strictly less than 12 px |
| Vertical batch outlier limit | strictly less than 45 px |

The detector averages RGB to luminance inside the left search strip. Pixels above
90% of the strip's 99th-percentile luminance are marked bright. Consecutive rows
with enough bright pixels form horizontal bands. Adjacent bands become pair
candidates when their center pitch is close to 785 px and each band contains a
wide, consistently bright horizontal span.

Each candidate receives a lower-is-better score composed of:

- pitch error;
- twice the difference between the two horizontal centers;
- 0.2 times the difference between mean measured width and 365 px.

The best candidate supplies `cx` as the mean horizontal center and `cy` as the
midpoint between the two band centers. If no candidate survives, that frame has
no direct detection.

### Batch validation and failure policy

Direct detections are validated separately in `x` and `y` against a five-frame
local median with edge padding. A measurement is accepted only when it is finite
and lies strictly within the 12 px horizontal and 45 px vertical limits.

The rollback `legacy` mode fills rejected or missing coordinates with its
historical NumPy interpolation. In `physical-p07-v1`, a rejected primary instead
passes through the same-frame physical-pair, P06, and full-domain P07 cascade.
If every stage fails, the frame is excluded from encoding, its uncropped
developed TIFF is preserved under `debug/excluded_frames/`, and processing
continues. No temporal registration interpolation occurs in this mode.

This is the primary detector. When second-stage vertical stabilization is
enabled, its result still determines the initial frame location; residual
registration refines only the final vertical crop coordinate.

## 8. Registration and cropping

Detection measures film position; registration uses that measurement to place a
fixed presentation window. They are distinct stages.

For each accepted trusted anchor (or historical legacy interpolated anchor):

```text
crop_left = anchor_x + 159.0
crop_top  = anchor_y - 413.0
width     = 1133
height    = 900
```

The coordinates can be fractional. With residual stabilization disabled, this
is the unchanged final crop. With it enabled, production measures the retained
upper and lower sprocket boundaries in an in-memory provisional registration,
then computes:

```text
corrected_crop_top = crop_top + residual_correction_y
```

The normal upper-sprocket ROI is tried first. If the primary measurement was
rejected and that ROI has no valid terminal edge, an expanded upper ROI handles
large transport excursions. A separately validated lower sprocket is the
same-frame rescue when the upper edge is dirty or unavailable. Only when both
measurements fail is the correction interpolated between neighboring valid
corrections (or held from the nearest valid correction at a batch boundary).
The correction is never silently set to zero.

Large corrections are allowed: their physical edge strength, contrast, terminal
boundary quality, crop bounds, and upper/lower agreement are evaluated rather
than their magnitude. A valid upper measurement remains authoritative when the
two boundaries disagree; they are never blindly averaged.

Pillow's `EXTENT` transform resamples the
1133×900 crop with bicubic interpolation, correcting horizontal weave and
vertical transport drift without integer-pixel stepping.

After cropping, the processor:

1. rotates the frame 180 degrees without expanding it;
2. flips it horizontally;
3. applies Pillow contrast factor `1.04`;
4. writes a quality-95 JPEG with chroma subsampling disabled.

The registered and normalized still frames are 1133×900. FFmpeg pads odd video
dimensions to even values, so the encoded video is normally 1134×900. There is
no temporal smoothing or generic content-based stabilization. The optional
stage is a second physical registration correction, not "jitter smoothing."
The retained output always comes directly from the full-resolution developed
TIFF with one final bicubic crop; cropped pixels are never shifted and exposed
areas are never filled with synthetic black.

## 9. Temporal normalization

Normalization is deliberately restrained. It reduces modest frame-to-frame
exposure and channel-balance variation while avoiding aggressive restoration or
making every scene look neutral.

For each registered JPEG:

1. Measure the picture aperture `x = 15%..92%`, `y = 12%..88%`.
2. Calculate Rec. 709-like luma weights `[0.2126, 0.7152, 0.0722]`.
3. Prefer pixels with luma between `0.03` and `0.96`; fall back to the whole ROI
   if fewer than 100 qualify.
4. Set the reel target from the first processed segment's median frame luma and
   store it as `normalization.target_median_luma`. Later segments reuse it.
5. Calculate per-frame exposure and clamp it to ±0.65 stops.
6. Calculate channel gains from the geometric-mean neutral level, clamp raw
   gains to `[0.78, 1.28]`, then apply only 25% of that correction.
7. Smooth exposure and RGB gains with a radius-four rolling median—up to nine
   frames within the current segment.
8. Apply `x / (1 + 0.12x)` soft compression and clip to `[0,1]`.
9. Write quality-95 JPEGs with chroma subsampling disabled.

The normalizer does not identify scene neutrals, perform gray-world correction,
remove film fading/dye crossover, recover clipped channels, or force distinct
scenes to a single appearance. Smoothing is calculated inside each independently
processed segment; it does not use neighboring JPEGs from another segment.

## 10. Batch processing

### Enumeration and planning

Frames are sorted numerically by the suffix after the final underscore. The
selected range must be contiguous. Remaining frames are divided into contiguous
groups and then into batches no larger than `--batch-frames`.

### Locking and disk checks

The processor opens `OUTPUT_DIR/.pipeline.lock` and requests a nonblocking
exclusive `flock`. A second process targeting the same output exits immediately.
Free space on the output filesystem is checked once before planning and again
before every batch.

### Stage order

Within each batch:

1. Recreate `.staging/segment_FIRST_LAST/` from scratch.
2. Develop DNGs concurrently into 16-bit TIFFs.
3. Detect sprockets serially; validate them and apply the configured failure policy.
4. Crop, orient, and write registered JPEGs.
5. Delete TIFFs.
6. Normalize registered JPEGs.
7. Encode a temporary H.264 segment.
8. Verify its frame count with FFprobe and fully decode it with FFmpeg.
9. Atomically replace the final segment path and write its manifest record.
10. Delete that batch's entire staging directory.

Encoding uses libx264, preset `fast`, CRF 15, one encoding thread, `yuv420p`, and
even-dimension padding. The sequence frame rate and movie rate both use `--fps`.

### Finalization

When verified segment ranges cover the selected frame numbers exactly, the
processor writes `segments.txt`, concatenates codec-identical segments with
`-c copy`, verifies final frame count, and fully decodes the temporary final
movie. Only then does it atomically install the final movie, hash it, update the
manifest, remove component segments, and remove `segments.txt`.

Verified segments bound data loss and restart cost: an interruption affects at
most the current batch instead of requiring one enormous uninterrupted render.

## 11. Resume and recovery

### What counts as completed

At startup, a segment is reusable only when:

- its manifest entry has `verified: true`; and
- the file named by its `video` field currently exists.

Those frame numbers are removed from the new processing plan. The processor does
not re-probe or decode an existing segment during resume; it trusts the manifest
flag and file existence until final verification.

### Normal interruption recovery

Restart with the same raw directory, output directory, frame range, fps, and
calibration settings:

```bash
/home/todd/telecine/.venv/bin/python -m grokcam.cli.process_reel \
  /mnt/GrokCam/projects/RAW_Test/raw \
  /mnt/GrokCam/projects/RAW_Test/outputs/production-v1 \
  --batch-frames 300 --fps 16 --jobs 3 --minimum-free-gib 22
```

The lock from the dead process is automatically released by the OS even though
`.pipeline.lock` remains. Previously verified component segments are preserved.
An incomplete staging directory for the next batch is deleted and regenerated.
An unverified `.tmp.mp4` is not treated as complete and is overwritten by the
next encoding attempt.

The existing manifest receives a new in-memory `batch_history` entry when loaded;
it becomes durable on the next manifest write. Completed segment records and the
first segment's normalization target are reused.

### Suspected corrupt segment

Because resume trusts an existing verified segment, quarantine a suspect file so
its manifest path is absent, then rerun the same command. For example:

```bash
mkdir -p /mnt/GrokCam/projects/RAW_Test/outputs/production-v1/quarantine
mv /mnt/GrokCam/projects/RAW_Test/outputs/production-v1/segments/frames_000301_000600_16fps.mp4 \
   /mnt/GrokCam/projects/RAW_Test/outputs/production-v1/quarantine/
```

The missing segment is planned again, and the new record replaces the record
with the same `first`/`last` range. Preserve the quarantined file and manifest
until the cause is understood.

### Important completed-output behavior

After successful finalization, component segments are deliberately deleted and
their manifest records receive `retained: false`. Therefore, rerunning the same
command against an already finalized output is **not** a no-op: the segment files
no longer exist, so all frames are considered remaining and will be processed
again. Do not rerun a completed output directory merely to “check” it. Inspect
the final manifest/movie or use a new output directory for a new proof.

Also keep one output directory tied to one frame selection and processing recipe.
The current loader does not reject every possible argument mismatch against an
existing manifest.

## 12. Processing manifest

`processing_manifest.json` is written atomically through a temporary JSON file
and `os.replace`. It is the processing recipe, diagnostic record, segment index,
and final verification record—not a replacement for the source DNGs.

### Top-level fields

| Field | Meaning |
|---|---|
| `pipeline`, `version`, `created` | Production identity and manifest creation time. |
| `raw_dir`, `source_policy` | Resolved source path and its `read_only` policy. |
| `frame_range`, `frame_count` | Selected inclusive range and count. |
| `fps`, `batch_frames` | Requested movie rate and batch setting. |
| `raw_development_calibration` | Calibration path, SHA-256, model, creation date, and training/holdout frames. |
| `crop_preset`, `crop` | `loose` and the four crop values. |
| `vertical_stabilization` | Enabled state, upper/lower reference positions, confidence threshold, and agreement tolerance. |
| `normalization` | Picture aperture, bounds/blend metadata, and eventually `target_median_luma`. |
| `tools` | Python, Pillow, rawpy, and FFmpeg versions recorded at creation. |
| `segments` | Per-segment state, verification, timing, and frame records. |
| `batch_history` | Later invocation start times/batch sizes once written. |
| `final` | Final movie path, bytes, SHA-256, verification, and completion time. |
| `retention` | What the successful run retained and removed. |

The canonical `pipeline` value is `grokcam_postprocess`. Manifests from the
pre-consolidation production path may contain the historical value
`grokcam_raw_production_darktable_matched`; that value is no longer emitted by
new output directories.

### Segment fields

Each segment records:

```text
first, last, frames, source_frames, excluded, video, video_bytes, video_sha256
verified, verification, reference_sprocket_x
detected, accepted, interpolated
elapsed_seconds, completed, frame_records, retained
```

`verification` contains FFprobe stream/format data. `elapsed_seconds` is total
batch wall time. Individual stage timings are printed to the console but are not
currently persisted in the manifest.

### Frame records

Each frame record contains:

```text
frame, source_name, source_bytes
anchor_x, anchor_y
detected, accepted, detector_score
crop_left, crop_top
output_disposition, encoded_output_frame, final_registration_source
exclusion_reason, debug_developed_image, primary_rejected_anchor
physical_fallback_stage, physical_diagnostics
vertical_stabilization_enabled
residual_sprocket_y, residual_confidence, residual_search_mode
residual_source, residual_correction_y, corrected_crop_top
bottom_sprocket_y, bottom_confidence, top_bottom_correction_disagreement_y
post_correction_residual_y, post_correction_confidence
normalization
```

`crop_top` preserves the primary crop coordinate. `corrected_crop_top` is the
actual sampled vertical coordinate when stabilization is enabled.
`residual_source` is `measured`, `expanded_residual`, `bottom_rescue`,
`interpolated`, or `fallback`. Rejection reasons and detailed normal/expanded
edge measurements are retained for auditing. When disabled, the enabled flag is
false and the residual-only fields are absent, preserving the former frame path.

The `normalization` object contains `median_luma`, `channel_median`,
`exposure_gain`, and `channel_gains_rgb`.

In `physical-p07-v1`, `accepted: false` and `output_disposition: excluded` mean
the frame has no final anchor and no encoded output frame. The top-level
`frame_mapping` records source, included, excluded, and encoded counts; its
invariants require included equals encoded and source equals included plus
excluded. `exclusion_runs` records consecutive omissions, their duration,
trusted neighbors, reasons, and debug paths. Legacy manifests retain their
historical interpretation.

Pretty-print the manifest with:

```bash
/home/todd/telecine/.venv/bin/python -m json.tool \
  /mnt/GrokCam/projects/RAW_Test/outputs/production-v1/processing_manifest.json \
  | less
```

List non-accepted frame records without extra dependencies:

```bash
/home/todd/telecine/.venv/bin/python - <<'PY'
import json
from pathlib import Path

path = Path("/mnt/GrokCam/projects/RAW_Test/outputs/production-v1/processing_manifest.json")
manifest = json.loads(path.read_text())
for segment in manifest.get("segments", []):
    for frame in segment.get("frame_records", []):
        if not frame.get("accepted", False):
            print(frame["frame"], frame["detected"], frame["detector_score"],
                  frame["anchor_x"], frame["anchor_y"],
                  frame["crop_left"], frame["crop_top"])
PY
```

## 13. Diagnostics and troubleshooting

### No DNGs found

Message:

```text
No DNG frames selected
```

Check that the input contains lowercase `frame_*.dng` names and that the
inclusive `--first`/`--last` selection actually intersects them:

```bash
find /mnt/GrokCam/projects/RAW_Test/raw -maxdepth 1 -type f -name 'frame_*.dng' | sort | head
```

If the selected numeric sequence has a gap, the processor instead reports:

```text
Selected DNG sequence is not contiguous
```

### Insufficient disk space

At startup:

```text
Only N.N GiB free; need N.N GiB
```

Between batches:

```text
Stopping safely: only N.N GiB free
```

Inspect both relevant filesystems before a long run:

```bash
df -h /home/todd/telecine/grokcam-postprocess /mnt/GrokCam
```

Free space or choose a smaller `--batch-frames`; do not lower the safety threshold
without understanding peak TIFF/JPEG usage.

### Calibration missing or invalid

Verify the production artifact and hash:

```bash
test -f calibrations/darktable_match_v1.json
sha256sum calibrations/darktable_match_v1.json
```

The expected SHA-256 is
`d5a4526b6b5e38fd9d7b37876b0ec39cb37a370d066419433db38f978cb3dc96`.
Errors such as `unsupported match model`, `expected 13 transform rows`,
`expected three 256-entry LUTs`, or `expected four white-balance values` mean the
selected report is not a valid production-v1 artifact. Do not repair it in place;
restore the version-controlled file.

### Sprocket detection failure

In `physical-p07-v1`, an unresolved frame is excluded after every same-frame
physical stage fails; it is never temporally registered. Consecutive exclusions
do not stop the reel, but are prominently recorded for manual review. A source
batch containing no trustworthy registration cannot produce a video segment and
stops explicitly. In rollback `legacy` mode, a batch with no usable measurements
stops with:

```text
No usable sprocket measurements in batch
```

Retain the staging data and console log if present, inspect the source range, and
try a smaller test range in a new output directory. Do not adjust detector
constants as part of recovering the production-v1 run; that would create a new
algorithm/calibration variant requiring regression.

### Excluded detections

For `physical-p07-v1`, inspect `frame_mapping`, `exclusion_runs`, and records
whose `output_disposition` is `excluded`. Review their preserved full-resolution
TIFFs and detector provenance. Any consecutive run warrants explicit visual
review; it is an intentional movie-time discontinuity, not interpolation.

### Abnormal framing

Compare `anchor_x`, `anchor_y`, `crop_left`, and `crop_top` with neighboring
records. By definition:

```text
crop_left - anchor_x = 159.0
crop_top  - anchor_y = -413.0
```

If those relationships are correct but the picture is poorly framed, inspect
the trusted anchor and source frame rather than treating crop and
detection as the same problem.

### Encoding failure

Confirm executables and versions:

```bash
ffmpeg -version | head -1
ffprobe -version | head -1
```

Use `--ffmpeg` and `--ffprobe` only if the executables are elsewhere. The raised
`Command failed (...)` message includes the exact command and captured stderr.
No segment manifest record is committed until encoding and verification succeed.

### Corrupt or incomplete segment

Incomplete `.tmp.mp4` files are not resumable and are overwritten. If a segment
marked verified is suspected corrupt, quarantine it as described in
[Resume and recovery](#resume-and-recovery), then restart the same command.

### Interrupted processing

Do not delete `.pipeline.lock` merely because it remains. First confirm no
processor is active:

```bash
pgrep -af 'grokcam.cli.process_reel'
```

If no process is running, rerun the exact command. The OS lock is already free.

### Final verification failure

The final movie is first created as `RAW_review_...tmp.mp4`; it is not installed
at the final path until FFprobe frame-count verification and a complete FFmpeg
decode succeed. Preserve the manifest, segments, temporary movie, and log for
diagnosis. Correct the external/tool/storage problem and rerun; verified segment
files can be reused while they still exist.

## 14. Planning a reel before processing

Always plan a large reel first:

```bash
/home/todd/telecine/.venv/bin/python -m grokcam.cli.process_reel \
  /mnt/GrokCam/projects/RAW_Test/raw \
  /mnt/GrokCam/projects/RAW_Test/outputs/production-v1 \
  --batch-frames 300 \
  --fps 16 \
  --jobs 3 \
  --minimum-free-gib 22 \
  --plan-only
```

The output reports:

- verified segment ranges that will be preserved;
- total remaining frame count;
- number of batches;
- each planned inclusive range and its frame count.

Planning also validates that DNG selection is nonempty and contiguous and that
the output filesystem meets the free-space threshold.

`--plan-only` performs no image development or encoding, but it is not completely
filesystem-neutral: it creates the output directory, lock file, `.staging/`, and
`segments/`; on a new output it also creates the initial manifest and queries the
FFmpeg version. Use the same dedicated output directory intended for processing.

## 15. Calibration versus production

These are separate systems:

```text
PRODUCTION

reel DNGs
    |
    v
frozen, approved darktable_match_v1.json
    |
    v
deterministic processing under fixed software
    |
    v
verified movie + manifest
```

```text
CALIBRATION / RESEARCH

named calibration DNG set
    |
    v
sprocket-white measurement
    |
    v
fresh Darktable references + rawpy candidates
    |
    v
matrix/LUT fitting and holdout metrics
    |
    v
candidate JSON comparison
    |
    v
explicit human review and separate adoption change
```

The production command imports no fitter and cannot automatically retrain,
approve, or overwrite the golden artifact.

## 16. Recalibrating in the future

Recalibration may be justified by a camera/sensor/CFA change, capture illumination
change, rawpy or LibRaw behavior change, a deliberate change to the approved
Darktable rendering, or important source material poorly represented by v1.

Keep archival DNGs in place; write candidate work under `work/` or another
explicit review directory.

### 1. Derive a candidate sprocket-white correction

```bash
/home/todd/telecine/.venv/bin/python -m tools.calibrate_sprocket_white \
  --raw-dir /mnt/GrokCam/projects/RAW_Test/raw \
  --work-dir work/sprocket-white-calibration \
  --output-dir work/sprocket-white-candidate
```

Supported options are `--raw-dir`, `--work-dir`, and `--output-dir`. The v1
sprocket reader assumes the documented 2028×1520 packed 12-bit BGGR layout.

### 2. Fit a candidate Darktable match

```bash
/home/todd/telecine/.venv/bin/python -m tools.calibrate_darktable_match \
  --raw-dir /mnt/GrokCam/projects/RAW_Test/raw \
  --darktable /usr/bin/darktable-cli \
  --wb-report work/sprocket-white-candidate/poc-report.json \
  --work-dir work/darktable-match-calibration \
  --output work/darktable-match-candidate.json \
  --calibration-id grokcam-darktable-match-candidate-YYYYMMDD \
  --jobs 3
```

Required options are `--raw-dir`, `--output`, and `--calibration-id`.
`--darktable`, `--work-dir`, `--jobs`, `--wb-report`, `--keep-tiffs`, and
`--force` are supported. Without `--wb-report`, the tool deliberately seeds from
the frozen golden correction to reproduce the existing fit. Without `--force`,
it refuses to overwrite an existing candidate output.

Every generated report is marked `candidate_not_approved`; the tool never edits
the production artifact.

### 3. Compare candidate and production

```bash
/home/todd/telecine/.venv/bin/python -m tools.compare_darktable_calibrations \
  calibrations/darktable_match_v1.json \
  work/darktable-match-candidate.json \
  --require-exact-fit
```

The comparison accepts `reference`, `candidate`, and optional
`--require-exact-fit`. Exact fit is appropriate when reproducing v1. A deliberately
new calibration instead requires review of learned-value differences, training
and holdout metrics, representative images, and the full production regression.

A candidate becomes production only through a separate, explicit versioned
artifact/configuration change after human approval. Never overwrite v1 in place.
See the [calibration guide](calibration.md) for source frame identifiers and
full provenance.

## 17. Production-v1 regression baseline

Frames 120–123 are the golden refactoring proof. Production v1 requires:

```text
Anchor geometry difference: 0.0 px
Crop geometry difference:   0.0 px
Detector mismatches:        0
Acceptance mismatches:      0
```

The golden proof movie SHA-256 is:

```text
bc13e671530a3483dce0f510c1420ad32cf481c942956a8221197297541c5f76
```

The test suite freezes the four anchors/crops and movie hash. The comparison CLI
checks a new manifest against the reference:

```bash
/home/todd/telecine/.venv/bin/python -m grokcam.cli.compare_reference \
  work/matched-timed-proof/processing_manifest.json \
  work/new-proof/processing_manifest.json
```

This protects geometry, detector decisions, crop registration, learned RAW
appearance, normalization, encoding arguments, and final deterministic output
from accidental change during refactoring. A changed algorithm should establish
a deliberately reviewed new baseline rather than weakening the v1 check.

## 18. Research code

`research/` contains retained investigations into rawpy renderer/demosaic
choices, downstream normalization, and residual restoration casts. A small
geometry adapter keeps those experiments runnable with current production
constants.

Research modules are not imported by `grokcam.cli.process_reel`, do not participate
in reel processing, and do not change the frozen calibration. They are reference
material for future algorithm investigations, not alternate production commands.

## 19. Quick-reference workflow

1. Mount and verify the reel storage:

   ```bash
   mount | grep GrokCam
   df -h /mnt/GrokCam
   ```

2. Locate and sample the source sequence:

   ```bash
   find /mnt/GrokCam/projects/RAW_Test/raw -maxdepth 1 -type f -name 'frame_*.dng' \
     | sort | head
   ```

3. Verify the frozen calibration:

   ```bash
   sha256sum calibrations/darktable_match_v1.json
   ```

4. Run the complete command with `--plan-only` and review every planned range.

5. Run a short representative range into a separate test output; inspect framing,
   orientation, color, and manifest detector decisions.

6. Start the normal reel command, preferably capturing stdout/stderr with
   `set -o pipefail` and `tee`.

7. If interrupted, confirm no process is active and rerun the exact same command.

8. Confirm successful finalization:
   - console says `Complete and verified`;
   - `final.verified` is true in `processing_manifest.json`;
   - the final `RAW_review_FIRST_LAST_FPSfps.mp4` exists;
   - component segments have been removed.

9. Retain the final movie and manifest with the immutable DNG archive. Review
   segment interpolation counts and all frame records with `accepted: false`.

10. Do not rerun an already finalized output directory unless intentional
    reprocessing is desired; use a new output directory for further proofs.
