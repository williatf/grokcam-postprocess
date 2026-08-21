# Repository inventory

Inventory date: 2026-08-21. The dependency analysis preceded consolidation and
no source DNG, calibration report, or retained output was changed.

## Active production

- `grokcam/`: calibrated stage implementations, models, composition, resume and
  regression utilities, and canonical CLI.
- `scripts/grokcam_raw_production_with_timings.py`: proven batch lifecycle used
  by `grokcam.pipeline` in this compatibility-preserving release (selection,
  locking, normalization, encoding, verification, cleanup, and manifest).
- `scripts/grokcam_raw_production_darktable_matched.py`: compatibility shim.
- `pyproject.toml`, `README.md`: packaging and production operation.

## Tests and calibration

- `tests/test_production.py`: calibration, detector, fallback interpolation,
  crop geometry, transform, resume, and manifest regression tests.
- External `rawpy-darktable-match-poc/poc-report.json`: authoritative learned
  color calibration. It is retained outside the repository outputs and is not
  generated during production.
- `work/matched-timed-proof/`: disposable four-frame golden proof from the
  actual timed/matched execution path; ignored by Git.

## Documentation and research retained

- `docs/GrokCam_RAW_postprocessing_guide.md`: detailed historical operations
  guide (some commands predate the canonical CLI).
- `docs/color_poc_findings.md`, `docs/residual_cast_poc_findings.md`, and
  `docs/sprocket_white_poc_findings.md`: concise experiment conclusions.
- `docs/processing_history.md`: why the selected algorithms survived.

## Superseded or experimental candidates (retained pending exact deletion approval)

- `scripts/grokcam_raw_production.py`: original Darktable batch runner.
- `scripts/grokcam_color_poc.py`, `grokcam_rawpy_darktable_match_poc.py`,
  `grokcam_rawpy_quality_poc.py`, `grokcam_residual_cast_poc.py`, and
  `grokcam_sprocket_white_poc.py`: reproducible research scripts whose findings
  are already documented.
- The unused adaptive renderer and old Darktable development functions within
  `scripts/grokcam_raw_production_with_timings.py`: not on the composed
  production path, retained because the proven batch runner remains a staged
  dependency in this release.

## Generated artifacts

- Everything under `work/`, Python bytecode, `.DS_Store`, logs, images, videos,
  locks, and local Darktable databases is generated or machine-local and ignored.
- The two tracked root `.DS_Store` resource-fork files predate this consolidation.
  They are deletion candidates but were not removed without exact approval.

## Unknown

None among tracked files. Generated `work/` subtrees are purpose-labelled and
disposable, but remain untouched under the workspace retention rule.
