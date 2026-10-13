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

`adaptive-v1` wraps the existing `grokcam.sprocket_detection.detect` function;
the algorithm and its returned coordinates are unchanged. It is currently the
only production registration. To register a future stateful detector, its
factory would be added to `detectors.registry`, for example:

```python
from grokcam.detectors.registry import register_detector
from grokcam.detectors.rolling_geometry import RollingGeometryV1

register_detector("rolling-geometry-v1", RollingGeometryV1)
```

The factory receives the common `DetectorCalibration` and the optional
`sprocket.options` mapping. A future config could select it as follows:

```json
{
  "sprocket": {
    "detector": "rolling-geometry-v1",
    "registration": "physical-p07-v1",
    "options": {"bootstrap_pairs": 12, "history_size": 25}
  }
}
```

The rolling-geometry implementation is not present or enabled in this phase.

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
