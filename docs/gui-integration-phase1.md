# GrokCamGUI Phase 1 interface

Phase 1 exposes a Python API and SSH-friendly JSON/JSONL commands. It does not
include cancellation, a daemon, an HTTP server, or Swift code.

## Public Python API

```python
from grokcam.api import (
    ProcessingConfig,
    inspect_source,
    list_calibrations,
    list_projects,
    process_reel,
    read_result,
)

source = inspect_source("/mnt/SG1TB/GrokCam/projects/Farmington_YW_Reel_REDO5")
calibrations = list_calibrations()
config = ProcessingConfig(
    source_path=source.source_path,
    output_directory="/mnt/SG1TB/GrokCam/projects/Farmington_YW_Reel_REDO5/outputs/gui-v1",
    calibration_id="grokcam-super8-redo5-v1",
    film_format="super8",
    first_frame=1,
    last_frame=5638,
    fps=12,
    batch_frames=960,
    raw_jobs=3,
    output_name="farmington-redo5-12fps.mp4",
)
result = process_reel(config, event_sink=lambda event: print(event.to_dict()))
```

The public models are `SourceInspection`, `CalibrationInfo`,
`ProjectInfo`, `ProcessingConfig`, `ProcessingResult`, and
`ProcessingProgressEvent`. Every model has `to_dict()` for JSON serialization.
`RunOptions` remains an internal engine type.

`list_projects()` defaults to `/mnt/SG1TB/GrokCam/projects`. It identifies
capture projects using the existing conventions: a child directory must have a
`metadata.json`, a `raw` directory, or directly stored `frame_<digits>.dng`
files. Each candidate is independently passed through `inspect_source`, so a
malformed project is returned with `available: false` and warnings without
preventing other projects from being listed.

The exact project discovery response is:

```json
{
  "projects": [
    {
      "project_name": "Farmington YW Reel REDO5",
      "source_path": "/mnt/SG1TB/GrokCam/projects/Farmington_YW_Reel_REDO5",
      "film_format": "super8",
      "frame_count": 6000,
      "first_frame": 1,
      "last_frame": 6000,
      "contiguous": true,
      "available": true,
      "warnings": []
    }
  ]
}
```

`film_format` may be `null` when it is not declared in metadata. A project
with readable frames but gaps remains `available: true` and reports
`contiguous: false` plus warnings. A project with malformed metadata, no raw
frames, or an inspection failure is retained with `available: false` and a
reason in `warnings`. Unrelated directories are omitted.

`process_reel` validates the source range, calibration ID, film format,
numeric settings, and output filename before starting. `output_name` is a
filename only; path separators and absolute paths are rejected. Omitting it
preserves the existing generated movie name.

## Source inspection

`inspect_source` accepts either a project directory or its `raw` directory.
It reads `metadata.json`, enumerates `frame_<digits>.dng`, reports gaps and
contiguity, makes a best-effort one-DNG dimension inspection, and reports
available `debug/raw_capture_metadata_*.jsonl` files. It never writes to the
source. Missing project metadata, valid-frame ranges, stationary-tail data, or
dimensions are represented as `null` or warnings.

Representative JSON:

```json
{
  "source_path": "/mnt/SG1TB/GrokCam/projects/Farmington_YW_Reel_REDO5",
  "raw_path": "/mnt/SG1TB/GrokCam/projects/Farmington_YW_Reel_REDO5/raw",
  "metadata_path": "/mnt/SG1TB/GrokCam/projects/Farmington_YW_Reel_REDO5/metadata.json",
  "metadata": {"project_name": "Farmington YW", "film_format": "super8"},
  "metadata_error": null,
  "project_name": "Farmington YW",
  "declared_film_format": "super8",
  "frame_count": 5638,
  "first_frame": 1,
  "last_frame": 5638,
  "contiguous": true,
  "missing_frames": [],
  "sample_dimensions": [2028, 1520],
  "capture_metadata_files": [],
  "warnings": []
}
```

## Calibration discovery

```python
for calibration in list_calibrations():
    print(calibration.to_dict())
```

The current selectable production descriptors are:

- `grokcam-regular8-default-v1`
- `grokcam-super8-redo5-v1`

The GUI must use the returned `calibration_id` and must not embed calibration
filenames. Discovery reads production `*.metadata.json` sidecars, verifies the
configuration and required resources, and excludes component-only metadata
such as the template-bank descriptor. An unavailable calibration is returned
with `available: false` and `unavailable_reason` rather than being silently
selectable.

Representative JSON:

```json
{
  "calibration_id": "grokcam-super8-redo5-v1",
  "display_name": "Super 8 REDO5 production",
  "config_path": "/home/todd/telecine/grokcam-postprocess/calibrations/super8_redo5.json",
  "metadata_path": "/home/todd/telecine/grokcam-postprocess/calibrations/super8_redo5.metadata.json",
  "film_formats": ["super8"],
  "adoption_status": "golden_production",
  "available": true,
  "unavailable_reason": null,
  "resource_paths": [
    "/home/todd/telecine/grokcam-postprocess/calibrations/darktable_match_v1.json",
    "/home/todd/telecine/grokcam-postprocess/calibrations/super8_template_bank_v1.json",
    "/home/todd/telecine/grokcam-postprocess/calibrations/super8_template_bank_v1.npz"
  ]
}
```

## Progress protocol

`ProcessingProgressEvent.to_dict()` produces one envelope per event:

```json
{
  "protocol": "grokcam.postprocess.events",
  "schema_version": 1,
  "sequence": 2,
  "event": "stage_progress",
  "job_id": "4b6f...",
  "emitted_at": "2026-09-22T14:00:00.123Z",
  "payload": {
    "batch_index": 1,
    "stage": "raw_development",
    "completed": 25,
    "total": 960,
    "unit": "frames"
  }
}
```

The event names are `job_started`, `batch_started`, `stage_progress`,
`registration_progress`, `registration_summary`, `batch_verified`,
`job_completed`, and `job_failed`. Regular 8 emits one `registration_progress`
event per registered source frame while the registration loop is running:

```json
{
  "event": "registration_progress",
  "payload": {
    "batch_index": 1,
    "frame": 906,
    "completed": 906,
    "total": 960,
    "unit": "frames",
    "provenance": "p15_direct",
    "counts": {
      "p15_direct": 905,
      "p24_recovery": 1,
      "p07_p22": 0,
      "interpolation": 0,
      "unresolved": 0
    }
  }
}
```

`provenance` is one of `p15_direct`, `p24_recovery`, `p07_p22`, or
`unresolved`. The cumulative counts are batch-local and do not require the GUI
to wait for the final manifest.

Stage values are `source_validation`, `raw_development`, `registration`,
`boundary_resolution`, `crop_render`, `normalization`, `encoding`,
`verification`, `finalization`, and `publication`. Sequences start at 1 and
increase monotonically for one job. The engine emits only progress checkpoints
it genuinely knows; it does not synthesize smooth progress.

Successful completion is represented by both a `job_completed` event and a
`ProcessingResult` like:

```json
{
  "status": "succeeded",
  "job_id": "4b6f...",
  "movie_path": "/mnt/.../outputs/gui-v1/farmington-redo5-12fps.mp4",
  "manifest_path": "/mnt/.../outputs/gui-v1/processing_manifest.json",
  "selected_frame_range": [1, 5638],
  "registration_summary": {"provenance_counts": {"PRIMARY": 5600, "UNTRUSTED": 38}},
  "timing": {"core_process_wall_seconds": 2170.33},
  "error": null
}
```

Failure is returned as a structured result and emitted as `job_failed`:

```json
{
  "status": "failed",
  "movie_path": null,
  "error": {
    "code": "source_non_contiguous",
    "message": "Selected DNG sequence is not contiguous",
    "stage": "source_validation",
    "retryable": false,
    "details": {"missing_frames": [172, 173]}
  }
}
```

The public API catches operational `SystemExit` values from the legacy core
and converts them to structured failures. The normal CLI still reports and
exits in its existing style.

## CLI commands

All commands use the installed environment on the telecine VM:

```bash
PY=/home/todd/telecine/.venv/bin/python
cd /home/todd/telecine/grokcam-postprocess
```

Inspect a source:

```bash
$PY -m grokcam.cli.gui inspect-source \
  /mnt/SG1TB/GrokCam/projects/Farmington_YW_Reel_REDO5
```

List selectable production calibrations:

```bash
$PY -m grokcam.cli.gui list-calibrations
```

List capture projects for the GUI picker:

```bash
$PY -m grokcam.cli.gui list-projects
```

An alternate project root may be supplied for testing or another mounted
volume:

```bash
$PY -m grokcam.cli.gui list-projects /mnt/SG1TB/GrokCam/projects
```

This command emits the project response envelope as JSON only on stdout and
does not modify any project files.

Start a production job with JSONL stdout:

```bash
$PY -m grokcam.cli.process_reel \
  /mnt/SG1TB/GrokCam/projects/Farmington_YW_Reel_REDO5 \
  /mnt/SG1TB/GrokCam/projects/Farmington_YW_Reel_REDO5/outputs/gui-v1 \
  --event-stream jsonl \
  --calibration-id grokcam-super8-redo5-v1 \
  --film-format super8 \
  --first 1 --last 5638 \
  --batch-frames 960 --fps 12 --jobs 3 \
  --output-name farmington-redo5-12fps.mp4
```

In event-stream mode stdout is JSONL only and is flushed after every event.
Human engine diagnostics remain on stderr. The process exits zero only when a
verified result is returned; failures exit nonzero after emitting
`job_failed`.

Recover a result after an SSH disconnect:

```bash
$PY -m grokcam.cli.gui read-result \
  /mnt/SG1TB/GrokCam/projects/Farmington_YW_Reel_REDO5/outputs/gui-v1
```

The ordinary `grokcam-process-reel` command remains available without
`--event-stream jsonl` and retains human-readable output. Phase 1 still has
CLI coupling in the compatibility path: the existing core prints human logs
directly. Machine mode isolates those logs by redirecting them to stderr; the
next cleanup phase can replace those prints with an injected logger.

## Automatic Regular 8 capture geometry

For Regular 8, `metadata.json.capture_geometry` is consumed automatically when
it is a non-null, frozen schema-1 object. The processing API reports the source
selection as `capture_geometry_source` with one of:

- `explicit_override` — `ProcessingConfig.capture_geometry_path` was supplied;
- `project_metadata` — the frozen object came from the selected capture project;
- `regular8_default` — the project has no frozen geometry;
- `super8_default` — Super 8, which does not use capture geometry.

The explicit override wins over project metadata. A malformed non-null project
object produces `capture_geometry_invalid` at `source_validation`; it is not
silently ignored. `inspect-source` and `list-projects` expose compact geometry
presence/validity/frozen status and a pitch/sample summary so a GUI can explain
why automatic geometry is or is not active. The full geometry object is kept in
the project metadata and processing manifest, not duplicated into Swift.
