# Retained research

These scripts preserve useful experimental investigations but are not imported
or executed by the production pipeline:

- `grokcam_rawpy_quality_poc.py`: renderer, bit-depth, and demosaic comparisons.
- `grokcam_color_poc.py`: downstream normalization comparisons.
- `grokcam_residual_cast_poc.py`: scene/restoration cast experiments.

Run them from the repository root as modules, for example:

```bash
/home/todd/telecine/.venv/bin/python -m research.grokcam_rawpy_quality_poc --help
```

Their outputs remain disposable research data under `work/` or explicitly
chosen output directories. They do not change the frozen production calibration.
