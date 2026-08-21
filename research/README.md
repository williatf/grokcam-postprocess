# Retained research

These scripts preserve useful experimental investigations but are not imported
or executed by the production pipeline:

- `grokcam_rawpy_quality_poc.py`: renderer, bit-depth, and demosaic comparisons.
- `grokcam_color_poc.py`: downstream normalization comparisons.
- `grokcam_residual_cast_poc.py`: scene/restoration cast experiments.
- `grokcam_vertical_stabilization_poc.py`: isolated residual Y-only registration
  study using the visible upper sprocket remnant in the production loose crop.
- `analyze_vertical_stabilization_run.py`: research-only long-run statistics,
  correction-cap simulation, and large-event contact sheets for that POC.
- `analyze_vertical_recrop_validation.py`: final corrected-recrop diagnostics,
  target-aware verification, and shifted-versus-recrop quality metrics.
- `check_vertical_stabilization_regressions.py`: assertions for required large,
  primary-rejection, damaged-edge, bottom-rescue, and expanded-search cases.

Run them from the repository root as modules, for example:

```bash
/home/todd/telecine/.venv/bin/python -m research.grokcam_rawpy_quality_poc --help
```

Their outputs remain disposable research data under `work/` or explicitly
chosen output directories. They do not change the frozen production calibration.
