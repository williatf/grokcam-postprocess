# Historical GrokCam RAW workflow notes

> This document records the pre-consolidation Darktable workflow. Its referenced
> standalone production script has been removed. Use the repository `README.md`
> and `python -m grokcam.cli.process_reel` for current production processing.

This guide documents the GrokCam DNG workflow developed for Todd's Regular 8 mm film captures. It is intended to be sufficient to repeat the work later without relying on memory or this conversation.

Historical production script (removed): `grokcam_raw_production.py`.

## The short version

GrokCam captures one archival DNG per film frame. Post-processing runs on the Mac and:

1. reads the DNG archive without modifying it;
2. temporarily develops DNGs into TIFFs with Darktable;
3. detects two sprocket holes at full resolution;
4. stabilizes the film vertically and horizontally;
5. applies an offline presentation crop independent of GrokCam's UI crop;
6. rotates and mirrors the image into the intended viewing orientation;
7. applies restrained exposure and color normalization;
8. encodes verified 16 fps video segments;
9. joins and verifies the complete review movie;
10. deletes all reproducible working images and component videos.

The permanent source is the DNG archive. The durable processing records are the production script, processing manifest, and verified output movie.

## Files to preserve

### Source archive

The DNG directory is the archival camera capture. For the current test project it is:

```text
/Volumes/AFP SG1TB/GrokCam/projects/RAW_Test/raw/
```

Never edit, rename, recompress, or delete the DNGs as part of post-processing. Back them up separately. The production pipeline opens them read-only.

### Production script

```text
grokcam_raw_production.py
```

This is the complete batch processor. Keep the exact version used for a finished movie with that movie and its manifest.

### Processing manifest

```text
processing_manifest.json
```

The manifest records:

- pipeline and tool versions;
- source location and frame range;
- frame rate and batch size;
- offline crop definition;
- sprocket location and crop coordinates for every frame;
- rejected or interpolated detections;
- normalization measurements and corrections;
- segment verification data and checksums;
- final movie verification data and checksum;
- which temporary artifacts were removed.

The manifest does not replace the DNGs. It is the recipe and audit trail needed to reproduce the derived movie.

### Final review movie

The completed file is named similarly to:

```text
RAW_review_000001_003483_16fps.mp4
```

This is a viewing/review derivative, not a replacement for the DNG archive.

## Required Mac software

The tested setup uses:

- Python 3 with NumPy and Pillow;
- Darktable and `darktable-cli`;
- FFmpeg and FFprobe;
- macOS `caffeinate` while a long run is active.

Paths used by the current script defaults:

```text
/Applications/darktable.app/Contents/MacOS/darktable-cli
/usr/local/bin/ffmpeg
/usr/local/bin/ffprobe
```

The Python runtime used during development was:

```text
/Users/todd/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
```

If that runtime no longer exists, create or select a Python environment containing NumPy and Pillow, then use its `python3` executable.

Confirm the tools before beginning:

```bash
/Applications/darktable.app/Contents/MacOS/darktable-cli --version
/usr/local/bin/ffmpeg -version | head -1
/usr/local/bin/ffprobe -version | head -1
```

## Before a long run

1. Mount the source volume and verify that the DNG directory is readable.
2. Connect the Mac to power.
3. Keep a MacBook lid open.
4. Ensure that no other copy of the pipeline is running.
5. Have at least 22 GiB free; 30 GiB or more is preferable.
6. Start `caffeinate` in a separate Terminal window.

```bash
caffeinate -dimsu
```

The displays may be turned off without stopping processing:

```bash
pmset displaysleepnow
```

Stop `caffeinate` afterward with Control-C.

## Recommended test run

Always test a short contiguous range before processing a new reel or changing software versions. From the directory containing the production script:

```bash
PYTHON="/Users/todd/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"

"$PYTHON" grokcam_raw_production.py \
  "/Volumes/AFP SG1TB/GrokCam/projects/RAW_Test/raw" \
  "/path/to/RAW_Test_short_test" \
  --first 1400 \
  --last 1499 \
  --batch-frames 100 \
  --jobs 3 \
  --minimum-free-gib 22
```

Inspect the resulting movie for orientation, crop, color, exposure, and registration before running the full set.

## Full test-set command

The first 960-frame test segment was retained. Because Time Machine snapshots can temporarily retain deleted TIFF blocks, subsequent work uses smaller 300-frame batches:

```bash
PYTHON="/Users/todd/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"

"$PYTHON" grokcam_raw_production.py \
  "/Volumes/AFP SG1TB/GrokCam/projects/RAW_Test/raw" \
  "/path/to/RAW_Test_production" \
  --batch-frames 300 \
  --fps 16 \
  --jobs 3 \
  --crop-preset loose \
  --minimum-free-gib 22 \
  2>&1 | tee "/path/to/RAW_Test_production/run.log"
```

Using `tee` preserves the terminal progress as `run.log`. The current pipeline run initiated through Codex may not have that log; future manual runs should use it.

### Command options

- `--first N`: begin at frame N.
- `--last N`: end at frame N.
- `--batch-frames N`: maximum temporary batch size. The default is 960.
- `--fps N`: review-movie frame rate. Regular 8 mm is being treated as 16 fps.
- `--jobs N`: concurrent Darktable workers. Three is the tested setting.
- `--crop-preset loose`: use the current presentation crop.
- `--minimum-free-gib N`: refuse to start or continue a batch below this free-space threshold.
- `--plan-only`: show which verified ranges will be preserved and which batches remain, without processing images.
- `--darktable`, `--ffmpeg`, and `--ffprobe`: override tool paths if they move.

## What happens inside a batch

### 1. DNG development

Darktable develops each DNG into a temporary TIFF. Each worker receives an isolated temporary Darktable configuration so workers do not contend for one database.

Darktable's `data.db` files are disposable application databases. The script removes each worker configuration immediately after conversion. They are not archival metadata.

### 2. Full-resolution sprocket detection

The detector examines the left film-edge region of the developed 2028 × 1520 frame. It finds two adjacent bright sprocket holes and checks:

- expected hole height and width;
- expected vertical pitch between holes;
- horizontal agreement between the two holes;
- overall candidate geometry.

Using a pair is more robust than trusting a single bright rectangle. The midpoint becomes the film-coordinate anchor.

### 3. Rejection and interpolation

Isolated measurements that move implausibly far from their local neighbors are rejected. If a measurement cannot be trusted, its coordinates are interpolated from accepted neighboring frames. The manifest explicitly records whether every frame was detected, accepted, or interpolated.

### 4. Offline crop and registration

The post-processing crop does not use GrokCam's project/UI crop. The `loose` crop is defined relative to the detected sprocket-pair midpoint:

```text
x offset: +159 pixels
y offset: -413 pixels
width:    1133 pixels
height:    900 pixels
```

The crop uses fractional-pixel bicubic sampling. This avoids one-pixel stepping and corrects both vertical registration and horizontal film weave. The loose crop intentionally preserves some film edge or adjacent-frame character.

After cropping, the image is rotated 180 degrees and mirrored horizontally to match the chosen viewing orientation.

### 5. Restrained normalization

Measurements come from the interior picture area, excluding most sprocket and border content. The processor applies bounded, temporally smoothed exposure and white-balance corrections. It deliberately avoids making every frame identical, preserving genuine scene brightness, indoor warmth, and the character of aged reversal film.

The first completed segment establishes a consistent reel-wide median-luminance target. Later batches reuse it to reduce visible batch-boundary changes.

### 6. Encoding and verification

Each batch is encoded as H.264 at 16 fps. FFprobe confirms frame count and stream metadata, and FFmpeg fully decodes the segment to detect corrupt output.

Only after verification does cleanup occur.

### 7. Final joining and retention

Verified segments are losslessly concatenated. The joined movie is probed and fully decoded again. Once it passes:

- temporary TIFFs are gone;
- Darktable configurations and databases are gone;
- registered JPEGs are gone;
- normalized JPEGs are gone;
- component segment videos are removed;
- the final movie and manifest remain.

## Disk-space behavior

At 16 fps, one minute is 960 frames. A one-minute batch generally needs approximately:

- 14–16 GiB for temporary TIFFs;
- 1 GiB or less for temporary JPEG derivatives;
- additional margin for encoding, databases, filesystem behavior, and incomplete work.

Plan on 22–26 GiB peak additional use and reserve roughly 30 GiB for comfort. The script checks free space before starting and before every batch.

For approximately 22,735 frames, batching keeps peak working use near one batch instead of requiring hundreds of gigabytes of simultaneous TIFF storage.

## Monitoring progress

Count only canonical TIFF filenames. This avoids counting any unexpected retry suffixes:

```bash
find "/path/to/RAW_Test_production/.staging" \
  -type f -name 'frame_??????.tif' | wc -l
```

The number rises toward the current batch size, then returns to zero after that batch is verified and cleaned.

Check working storage:

```bash
du -sh "/path/to/RAW_Test_production"
```

Check free disk space:

```bash
df -h "/path/to/RAW_Test_production"
```

Check for pipeline processes:

```bash
pgrep -fl grokcam_raw_production
```

There should be exactly one pipeline process. Darktable workers may appear while conversion is active.

Inspect completed segments in the manifest:

```bash
python3 - <<'PY'
import json
from pathlib import Path

path = Path("/path/to/RAW_Test_production/processing_manifest.json")
data = json.loads(path.read_text())
print("Selected frames:", data["frame_count"])
for segment in data.get("segments", []):
    print(segment["first"], segment["last"], "verified=", segment["verified"])
print("Final:", data.get("final", {}).get("verified", False))
PY
```

## Resume and interruption

The output directory contains `.pipeline.lock`. The script uses an operating-system lock to prevent two pipeline copies from intentionally using the same output directory. A resumed run preserves any verified segment files recorded in the manifest even if `--batch-frames` is changed; only uncovered contiguous ranges are divided into new batches.

Preview a resume plan safely:

```bash
python3 grokcam_raw_production.py \
  "/path/to/raw" \
  "/path/to/production-output" \
  --batch-frames 300 \
  --plan-only
```

For a normal Terminal run, interrupt once with Control-C and allow active Darktable commands to stop. Do not immediately launch another copy while workers are still present.

Before resuming, verify:

```bash
pgrep -fl grokcam_raw_production
pgrep -fl darktable-cli
```

If neither command reports an old worker, rerun the exact original command. Verified segments recorded in the manifest are skipped. An incomplete staging batch is recreated.

Do not manually edit `processing_manifest.json` to force a segment to appear complete.

If the script says another pipeline is using the directory, first determine whether a genuine process is active. Do not simply delete `.pipeline.lock`; deleting the file does not stop the process that holds the operating-system lock.

## Troubleshooting

### TIFF count exceeds the batch size

Stop and investigate. Look for suffixes such as `_01.tif` or `_02.tif`:

```bash
find "/path/to/RAW_Test_production/.staging" \
  -type f -name '*_[0-9][0-9].tif' | head
```

This can indicate overlapping or lingering Darktable workers. Ensure only one pipeline is active before deleting an incomplete, reproducible staging batch and restarting.

### Source volume disconnects

Stop the pipeline, remount the volume, confirm that the expected DNG sequence is readable, and resume with the same command. Never point the script at a partially copied substitute directory without verifying completeness.

### Disk becomes too full

The script stops before starting another batch when free space is below the threshold. An interrupted current batch can be removed because its TIFFs and JPEGs are reproducible. Preserve the DNG archive, manifest, verified movies, and production script.

### Sprocket failures or bad registration

Review the per-frame fields in the manifest:

- `detected`
- `accepted`
- `detector_score`
- `anchor_x`
- `anchor_y`
- `crop_left`
- `crop_top`

A small number of interpolated measurements is expected to be recoverable. Long runs of failures should be inspected visually before accepting the movie.

### Exposure or color seams

Confirm that all segments use the same `normalization.target_median_luma` recorded in the top-level manifest. Scene-by-scene grading is a later restoration stage and should not be confused with this restrained review normalization.

## What this production pass does not yet do

The current pipeline is a conservative review and registration pass. It does not yet perform:

- scene detection or scene-specific grading;
- temporal dust or scratch removal;
- advanced grain management;
- content-based stabilization;
- sharpening intended to invent missing focus detail;
- archival mezzanine encoding such as ProRes or FFV1;
- automated focus-defect or recapture-range reporting.

Those steps should be considered only after reviewing the full sprocket-stabilized movie. The DNG archive allows improved processing later without recapture, except where focus, clipping, or physical capture failure prevented detail from being recorded.

## Recommended long-term archive layout

```text
Reel_Name/
├── raw/                         # Original DNG sequence; immutable
├── documentation/
│   ├── GrokCam_RAW_postprocessing_guide.md
│   └── grokcam_raw_production.py
├── derivatives/
│   ├── processing_manifest.json
│   └── Reel_Name_review_16fps.mp4
└── checksums/
    └── raw_sha256.txt
```

Keep at least two independent copies of the DNG archive and checksum manifest. A review MP4 is convenient, but it is never the archival master.

## Final acceptance checklist

- DNG count matches the capture inventory.
- DNG checksum manifest has been retained and verified.
- Exactly one pipeline instance performed the run.
- Final movie frame count matches the selected DNG frame count.
- Final movie fully decodes without errors.
- Final checksum is present in the processing manifest.
- Sprocket detection/interpolation counts are reviewed.
- Orientation and crop are correct.
- No unacceptable batch-boundary exposure or color shifts are visible.
- Soft-focus or otherwise defective ranges are recorded for possible recapture.
- Production script, guide, manifest, and movie are copied beside the archived reel.
