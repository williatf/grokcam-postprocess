# Repository inventory

Post-cleanup inventory date: 2026-08-21.

## Production

- `grokcam/batch.py`: disk-bounded frame selection, restart planning, staging,
  stage orchestration, cleanup, and finalization.
- `grokcam/raw_development.py`: frozen Darktable-matched rawpy inference.
- `grokcam/sprocket_detection.py`, `registration.py`, and
  `image_processing.py`: physical film detection, geometry, and registered crop.
- `grokcam/normalization.py`: approved restrained reel normalization.
- `grokcam/encoding.py`: FFmpeg encoding, concatenation, verification, and hashes.
- `grokcam/manifest.py`, `models.py`, `resume.py`, and `timing.py`: production
  records and lifecycle support.
- `grokcam/pipeline.py` and `grokcam/cli/process_reel.py`: canonical composition
  and sole production entry point.

No production module imports a historical script or offline calibration fitter.

## Calibration tooling

- `calibrations/darktable_match_v1.json`: exact frozen production artifact.
- `calibrations/darktable_match_v1.metadata.json`: identity, provenance, source
  frames, software versions, and validation record.
- `grokcam/calibration/match_model.py`: permanent fitting mathematics.
- `tools/calibrate_sprocket_white.py`: candidate RGBG correction derivation.
- `tools/calibrate_darktable_match.py`: paired reference generation and candidate
  model fitting.
- `tools/compare_darktable_calibrations.py`: candidate/reference comparison.
- `docs/calibration.md`: complete offline workflow and adoption boundary.

Calibration tools write candidate artifacts only. Production reads the frozen
artifact and never retrains or approves a candidate.

## Research

- `research/grokcam_rawpy_quality_poc.py`: renderer/demosaic investigation.
- `research/grokcam_color_poc.py`: downstream normalization investigation.
- `research/grokcam_residual_cast_poc.py`: restoration-grade investigation.
- `research/_legacy_geometry.py`: production-equivalent geometry adapter shared
  by those retained scripts.

Research is retained for future investigation and is not a production or
calibration dependency.

## Tests

- `tests/test_production.py`: calibration identity/loading, detector and
  interpolation behavior, crop geometry, resume/segment planning, manifests,
  finalization, transform behavior, and golden regression snapshots.

## Documentation

- `README.md`: current production workflow and canonical command.
- `docs/calibration.md`: frozen inference and offline recalibration.
- `docs/processing_history.md`: concise architectural and algorithm history.
- `docs/*_findings.md`: retained research conclusions.
- `docs/GrokCam_RAW_postprocessing_guide.md`: clearly labelled historical notes.

## Generated / ignored

- `work/`: disposable proof, calibration-audit, and processing intermediates.
- Python/test caches, logs, images, videos, temporary manifests, locks, and local
  Darktable databases are ignored.
- Archival DNGs and retained project outputs live outside the repository and are
  never cleanup targets.

The repository has no remaining tracked cleanup candidates or uncertain files.
No retained manifest currently contains a real missed/rejected/interpolated
sprocket case, so that non-happy path uses a small synthetic test fixture.
