# GrokCamGUI integration design

Status: architecture proposal. This document intentionally does not add the
GUI or a second processing implementation.

## Recommendation

Add one small, GUI-neutral Python boundary above the existing pipeline:

```text
GrokCamGUI / CLI / automation
              |
       grokcam.api
              |
       ProductionPipeline
              |
       existing batch and Super 8 scheduler
```

The boundary should own four operations:

```python
inspect_source(path) -> SourceInspection
list_calibrations(search_paths=None) -> list[CalibrationInfo]
process_reel(config, event_sink=None, cancellation=None) -> ProcessingResult
read_result(output_path) -> ProcessingResult
```

The API should use dataclasses or similarly typed Python values internally.
The JSONL adapter should serialize those values; the processing engine should
not know about Swift, SSH, JSONL, or macOS.

## What exists today

The current composition point is already close to the desired job boundary:

- `ProductionPipeline` accepts a `ProductionCalibration` and delegates to
  `run_reel` (`grokcam/pipeline.py`).
- `RunOptions` contains the production inputs: source, output, frame range,
  batch size, FPS, worker count, FFmpeg paths, staging, and production-mode
  flags (`grokcam/batch.py`).
- The outer `run_reel` owns output locking, local staging, publication, and
  failed-run staging preservation.
- The Super 8 path already records per-batch scheduler timing, stage timing,
  registration provenance, exclusion counts, diagnostic paths, and final video
  verification in `registration_audit.json` and `processing_manifest.json`.
- Calibration files are loaded by `load_calibration`; the production defaults
  and format-specific overrides remain in Python rather than in the GUI.

The boundary is not yet suitable as a public API:

- `ProductionPipeline.process_reel` is annotated as returning `None`, while
  the staged runner actually returns a result for some paths and the regular 8
  path currently does not return a useful result.
- Operational validation and lock errors use `SystemExit` in the core path.
- Progress and completion information is printed directly from batch and
  scheduler code. It is not structured and would corrupt a JSON-only stdout.
- The Super 8 scheduler has an internal `stop_event`, but it is not externally
  controllable and is only used to stop queue production after an exception.
- FFmpeg is invoked with `subprocess.run`, so there is no process handle that
  can be asked to terminate during cancellation.
- Super 8 movie naming is currently hard-coded to `Super8_REDO5_...`; regular 8
  naming is also generated internally. The public API therefore needs an
  optional output name if the GUI is to control it.

These are interface and plumbing changes, not a rewrite of registration or
rendering.

## Public API shape

Names below are proposed names. They deliberately keep the current internal
`RunOptions` private to the engine.

### Source inspection

```python
@dataclass(frozen=True)
class SourceInspection:
    source_path: Path
    raw_path: Path
    metadata_path: Path | None
    metadata: dict[str, object] | None
    metadata_error: str | None
    project_name: str | None
    declared_film_format: str | None
    frame_count: int
    first_frame: int | None
    last_frame: int | None
    contiguous: bool
    missing_frames: tuple[int, ...]
    sample_dimensions: tuple[int, int] | None
    capture_metadata_files: tuple[Path, ...]
    warnings: tuple[str, ...]
```

`inspect_source` should accept either a project directory or its `raw`
subdirectory. It should resolve the same `project/raw` convention used by
`_run_reel_core`, but must not modify the source.

The first implementation should:

1. Read `metadata.json` when present and preserve its decoded object.
2. Enumerate only files matching `frame_<digits>.dng`.
3. Report the observed count, inclusive range, gaps, and whether the sequence
   meets the engine’s contiguous-frame requirement.
4. Read dimensions from one DNG header when possible. If that inspection is
   unavailable, return `null` plus a warning; do not infer dimensions from the
   capture calibration file.
5. Report optional `debug/raw_capture_metadata_*.jsonl` files as available
   capture logs. They are not a substitute for source-frame validation.

The capture application currently writes project name, safe folder name,
project paths, and declared film format to `metadata.json`. It also writes
transport observations and per-frame capture records, but there is no general
authoritative stationary-tail or valid-frame-range field. Inspection should
therefore return those fields only when they are actually present in source
metadata and otherwise use `null`/`unknown`.

The inspection response should include a validation warning when a requested
range would be non-contiguous, outside the observed range, or empty. The
processing job must repeat this validation immediately before starting because
the source is mounted storage and may change between the GUI’s inspection and
the job.

### Calibration discovery

```python
@dataclass(frozen=True)
class CalibrationInfo:
    calibration_id: str
    display_name: str
    config_path: Path
    metadata_path: Path | None
    film_formats: tuple[str, ...]
    adoption_status: str | None
    available: bool
    unavailable_reason: str | None
    artifact_sha256: str | None
    resource_paths: tuple[Path, ...]
    warnings: tuple[str, ...]
```

`list_calibrations` should discover JSON calibration descriptors from the
configured calibration directories and group any referenced resources. The
GUI must receive IDs and display metadata from this operation; it must not
hard-code names such as `super8_redo5`.

There are two kinds of JSON in the current directory:

- `super8_redo5.json` is a production configuration override.
- `darktable_match_v1.metadata.json` and
  `super8_template_bank_v1.json` describe individual artifacts/resources.

The minimum durable change is to add a sidecar for each selectable production
configuration, for example `super8_redo5.metadata.json`, containing:

```json
{
  "schema_version": 1,
  "calibration_id": "grokcam-super8-redo5-v1",
  "display_name": "Super 8 REDO5 production",
  "film_formats": ["super8"],
  "config": "super8_redo5.json",
  "requires": [
    "darktable_match_v1.json",
    "super8_template_bank_v1.npz"
  ],
  "adoption_status": "golden_production"
}
```

The exact file names are examples, not API identifiers. Discovery must verify
that the config, match report, template bank, and any other required resource
exist and that recorded hashes match when hashes are supplied. The existing
`*.metadata.json` artifact descriptors can be reused rather than duplicated.

The returned `CalibrationInfo` should also state that the current Super 8
production configuration requires validated crop geometry. A registration-only
calibration such as the unvalidated template-bank artifact must not appear as
a selectable movie-production calibration unless the descriptor explicitly
marks it as such.

### Processing configuration and result

```python
@dataclass(frozen=True)
class ProcessingConfig:
    source_path: Path
    output_directory: Path
    calibration_id: str
    film_format: str
    first_frame: int
    last_frame: int
    fps: int
    batch_frames: int = 960
    raw_jobs: int = 3
    output_name: str | None = None

@dataclass(frozen=True)
class ProcessingResult:
    protocol_version: str
    job_id: str
    status: str                 # succeeded, failed, or cancelled
    source: SourceInspection
    selected_frame_range: tuple[int, int]
    output_directory: Path
    movie_path: Path | None
    manifest_path: Path | None
    registration_summary: dict[str, object]
    batches: tuple[dict[str, object], ...]
    timing: dict[str, object]
    warnings: tuple[str, ...]
    error: dict[str, object] | None
    cancellation: dict[str, object] | None
```

The API resolves the calibration ID, builds the existing
`ProductionCalibration`, maps the safe public settings to `RunOptions`, and
invokes the existing pipeline. It should reject unknown calibration IDs,
invalid ranges, unsupported film formats, invalid FPS/batch/job values, and
output names that escape the selected output directory before processing.

`output_name` should be optional for compatibility. When supplied, it should
be a file name (not an arbitrary path) and be used by the common finalization
code for both film formats. If omitted, preserve the current generated name.
The manifest must record the actual final path, not merely the requested name.

`read_result(output_path)` should be a read-only convenience that loads the
published manifest and derives the movie path from its verified final/render
record. This lets the GUI recover after an SSH disconnect without rerunning a
job.

## JSONL event protocol

Use one JSON object per line with this envelope:

```json
{
  "protocol": "grokcam.postprocess.events",
  "schema_version": 1,
  "sequence": 42,
  "event": "stage_progress",
  "job_id": "01J...",
  "emitted_at": "2026-09-22T14:00:00Z",
  "payload": {}
}
```

`sequence` is monotonically increasing within a job. `emitted_at` is an
RFC3339 UTC timestamp. Event names and payload keys are stable snake_case
names. Unknown payload keys may be added, but existing keys must not change
meaning within schema version 1.

The initial event set should be:

| Event | Required payload |
|---|---|
| `job_started` | source path, selected range, total source frames, total batches, film format, calibration ID, FPS, batch size, jobs |
| `batch_started` | batch index/count, source first/last, source frame count, current stage |
| `stage_progress` | batch index, stage, completed, total, unit, current frame if known, elapsed seconds if known |
| `registration_summary` | batch index, counts by provenance/disposition, included frames, excluded frames, warnings |
| `batch_verified` | batch index, source range, verified segment path if retained, stage timings, total elapsed seconds |
| `job_completed` | verified movie path, manifest path, selected range, registration summary, batch summaries, timing, warnings |
| `job_failed` | structured error, current stage/batch, staging path if preserved, recoverability, cancellation state |
| `job_cancelled` | cancellation request time, acknowledged time, current stage/batch, preserved staging path, published movie path (`null`) |

`stage` values should be a closed list for version 1:

```text
source_validation, raw_development, registration, boundary_resolution,
crop_render, normalization, encoding, verification, finalization, publication
```

Progress should be emitted at the granularity the engine naturally knows:
Super 8 currently reports development and registration checkpoints every 25
frames (plus first and last), and batch-level crop, normalization, encoding,
and verification timing. The API should expose those checkpoints rather than
pretend to know per-pixel or per-process progress. A later protocol version can
add finer-grained progress if it becomes available.

Registration counts should use the existing Super 8 provenance names:
`PRIMARY`, `SECONDARY`, `FALLBACK`, `TEMPLATE_FALLBACK`, `INTERPOLATED`, and
`UNTRUSTED`, plus explicit `included` and `excluded` totals. Regular 8 should
use the same disposition vocabulary where applicable and retain its existing
P15/P07/P22 count fields as additional payload values. The final manifest and
the final event remain the authoritative complete record; live events are
progress snapshots.

### Transport rules

The processing API receives a callback such as
`event_sink(ProcessingProgressEvent)`. The JSONL CLI adapter serializes each
event and writes only JSON objects to stdout, flushing after every line. Human
diagnostics go to stderr. The engine must never write human-readable messages
to the event stream.

Keep the existing human CLI as the default for compatibility. Add an explicit
machine mode, for example `--event-stream jsonl`, whose stdout is reserved for
this protocol. Do not make the GUI parse the existing completion text.

## Cancellation design

Cancellation should be exposed as a small thread-safe token:

```python
class CancellationToken:
    def request(self, reason: str = "user_requested") -> None: ...
    @property
    def requested(self) -> bool: ...
    def raise_if_requested(self) -> None: ...
```

The safest boundary in the current producer/consumer scheduler is between
DNGs and between batches:

1. Check before starting a batch and before accepting a batch into the queue.
2. Check between RAW development tasks and before each registration task.
3. Cancel queued executor futures; allow an active `rawpy` operation to return
   before joining the executor. Python threads cannot safely kill an active
   `rawpy` call.
4. Check before crop/render, normalization, encoding, verification, and final
   concatenation.
5. Replace `subprocess.run` for FFmpeg with a small cancellable process helper:
   send SIGTERM, wait a bounded interval, then SIGKILL only if necessary; reap
   the process and remove only its incomplete temporary output.
6. On cancellation, set the producer stop event, drain/close the queue without
   leaving the producer blocked, join the producer, and preserve the current
   local staging directory.

The existing queue capacity of one and the producer’s timed `put` loop are the
right ownership model. External cancellation should set that same stop event;
it should not have the GUI manipulate the queue or worker threads directly.

Publication must remain after successful final verification. A cancelled job
must never call `_publish_staged_output`, must never publish a new final movie,
and must return `movie_path: null`. If an older verified movie already exists
in the destination, the result must identify it as pre-existing rather than
claim it as the cancelled job’s output. The existing failed-staging pointer is
useful, but it should gain `status: "cancelled"`, `job_id`, and a structured
error/cancellation object.

This behavior should be implemented and tested before exposing a GUI Cancel
button. Until then, a process-level SSH termination is not an equivalent safe
cancellation API.

## Error model

The public API should use structured exceptions internally and convert them to
`ProcessingResult.error` at the API boundary:

```json
{
  "code": "source_non_contiguous",
  "message": "Selected DNG sequence is not contiguous",
  "stage": "source_validation",
  "batch_index": null,
  "retryable": false,
  "details": {"missing_frames": [17, 18]}
}
```

At minimum, distinguish `invalid_request`, `source_unavailable`,
`source_non_contiguous`, `calibration_unavailable`, `insufficient_disk_space`,
`output_locked`, `processing_failed`, `verification_failed`, and
`cancelled`. The CLI can map these to a nonzero exit status; the processing
engine must not call `sys.exit()`.

## Smallest implementation sequence

1. Add the typed API models, source inspection, calibration discovery, and
   JSON serialization tests. This is read-only and does not alter processing.
2. Make the existing pipeline return a normalized result for every format;
   replace core `SystemExit` cases with structured exceptions. Add optional
   output naming and record it in the manifest.
3. Thread an internal event/log context through the existing batch and Super 8
   scheduler. Preserve existing human CLI output through a stderr logger and
   add the explicit JSONL CLI mode.
4. Add cooperative cancellation and cancellable FFmpeg process ownership.
   Test cancellation while producing, while the queue is full, during
   rendering, and during finalization; assert no new movie is published.
5. Only then build the Swift client. It should call source inspection and
   calibration discovery, send a `ProcessingConfig`, consume the JSONL event
   stream, and use `ProcessingResult`/the manifest for completion and recovery.

No Swift-specific type, SSH behavior, or GUI state should be added to the
Python processing package.
