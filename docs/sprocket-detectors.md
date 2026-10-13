# Sprocket detector architecture

Primary sprocket detection and downstream registration are selected separately.
The existing registration setting and CLI option remain supported:

```json
{
  "sprocket": {
    "detector": "adaptive-v1",
    "registration": "physical-p07-v1"
  }
}
```

For compatibility, old calibration files with `sprocket_detector_mode` still
load, and `--sprocket-detector-mode` still selects registration. The new
`--sprocket-detector` option selects the primary detector. The programmatic
`ProcessingConfig.sprocket_detector` field provides the same selection at the
processing API boundary. Both default to the existing behavior: detector
`adaptive-v1`, registration `physical-p07-v1`.

## Available detectors

### `adaptive-v1`

This remains the default detector. It wraps the existing
`grokcam.sprocket_detection.detect` implementation without changing its
calculation or coordinates.

### `rolling-geometry-v1`

This optional, stateful Regular 8 detector preserves the behavior of the
500-frame rolling-geometry experiment. It uses the fixed X strip `[240, 660)`,
a per-frame p99 luminance threshold multiplied by `0.96`, and an initial
minimum row count of 130. It bootstraps from accepted geometry, begins its
tighter rolling geometry gate after five accepted pairs, and keeps medians over
up to 25 accepted pairs. The dynamic row minimum is `max(130, round(0.65 ×
rolling median plateau row count))`. Its profile-transition fallback runs only
when the fast candidate path has no accepted pair. Accepted pairs alone update
the rolling model.

The detector keeps the original experiment's `pair_bands()` and `band_edges()`
calculations. Their source and the original trial script are preserved under
`work/registration-walkthrough/Reel_46335_REDO1/`; see
[`rolling-geometry-reference.md`](rolling-geometry-reference.md) for the
reference inputs and reproduction procedure. The experimental thresholds and
geometry gates are fixed; detector options are not accepted.

Select the detector in calibration while leaving registration selection
independent:

```json
{
  "sprocket": {
    "detector": "rolling-geometry-v1",
    "registration": "physical-p07-v1"
  }
}
```

Or use the CLI:

```sh
grokcam-process-reel --sprocket-detector rolling-geometry-v1 \
  --raw-dir /path/to/capture --output-dir /path/to/output
```

Diagnostics include fast or profile-fallback method, accepted/recovered/
fallback-only/unresolved status, fallback attempt and recovery flags, geometry
gate rejection reason, rolling pitch/height/width/aspect/center, dynamic row
minimum, bootstrap progress, threshold measurements, candidate counts, and the
selected pair geometry. Diagnostics are observational and do not feed back
into detection.

The detector is stateful. Its checkpoints include the rolling accepted-pair
history and the first 12 bootstrap measurements. Verified segment checkpoints
are restored before later pending batches. A detector version or effective
configuration mismatch prevents resume; a missing checkpoint for a preceding
verified segment also prevents a stateful resume. The unresolved trial frame
4576 demonstrates a current limitation: a sprocket whose expected band
extends beyond the image cannot be recovered by the profile fallback.

## Detector contract

Detector implementations live under `grokcam.detectors`. A per-reel instance
implements `SprocketDetector` from `detectors.base`:

- `detect(image)` returns a `DetectorResult` containing a `SprocketDetection`
  (or `None`) and structured optional diagnostics.
- `configuration()` returns JSON-compatible effective settings. They are
  hashed and compared when resuming a job.
- `get_state()` and `restore_state()` serialize sequential detector history.
- `name`, `version`, and `stateful` identify compatibility and checkpoint
  requirements.

The factory receives the common `DetectorCalibration` and the optional
`sprocket.options` mapping. `rolling-geometry-v1` rejects options so its
experimentally evaluated parameters cannot be changed accidentally.

## Resume behavior

One detector instance is created for a reel and receives frames sequentially
within each processing batch. Once a segment has been verified, its manifest
record stores the detector's JSON state and identity. Before a later pending
batch, the pipeline restores the checkpoint from the nearest earlier verified
segment. If detector name, version, effective configuration, or statefulness
does not match, resume stops with an error. A stateful detector also refuses
to resume past a verified segment that lacks a checkpoint. The built-in
`adaptive-v1` is stateless, so historical manifests without detector metadata
remain resumable and are upgraded with its identity.

Each frame record stores detector diagnostics separately from the geometric
detection and registration diagnostics.
