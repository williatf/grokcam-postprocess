# Rolling-geometry experiment reference

The production `rolling-geometry-v1` detector is checked against the original
study implementation and report. These reference files are tracked verbatim:

- `work/registration-walkthrough/Reel_46335_REDO1/primary_detector_500/run_rolling_calibration_trial.py`
- `work/registration-walkthrough/Reel_46335_REDO1/first_frames/annotate_primary_strip.py`
- `work/registration-walkthrough/Reel_46335_REDO1/primary_detector_500/adaptive_report.json`
- `work/registration-walkthrough/Reel_46335_REDO1/primary_detector_500/adaptive_frames.csv`
- `work/registration-walkthrough/Reel_46335_REDO1/primary_detector_500/rolling_calibration_trial/rolling_calibration_report.json`
- `work/registration-walkthrough/Reel_46335_REDO1/primary_detector_500/rolling_calibration_trial/rolling_calibration_frames.csv`

The 500 TIFF inputs remain in the same `primary_detector_500/frames/`
directory and are not modified or committed. Reproduction also reads the
the tracked study reference files and the repository's default detector
calibration. Python dependencies are listed in `pyproject.toml`.

To run the original script without replacing its saved report and annotations,
redirect its output directory in memory:

```python
import runpy
from pathlib import Path

script = Path("work/registration-walkthrough/Reel_46335_REDO1/primary_detector_500/run_rolling_calibration_trial.py").resolve()
namespace = runpy.run_path(str(script), run_name="rolling_geometry_reference")
namespace["main"].__globals__["OUT"] = Path("/tmp/rolling_geometry_reference_run")
namespace["main"]()
```

Compare that run's `rolling_calibration_report.json` frame records and summary
against the tracked report. `runtime_seconds` naturally varies by run.

The trial's confirmed reference outcome is 499 accepted pairs out of 500:
455 fast detections, 44 fallback recoveries, and unresolved frame 4576. The
first 12 bootstrap frames are 1, 10, 19, 28, 38, 47, 56, 66, 75, 84, 94, and
103. The report is a candidate-yield evaluation; agreement with the prior
adaptive detector is not a ground-truth accuracy measure.

## Integration validation

The integrated detector was run sequentially over the same 500 TIFFs. All 500
records matched the reference for selected method and status, fallback choice,
gate reason, row minimum, pair bands, per-sprocket edges and dimensions,
pitch, width, aspect, center, plateau count, and returned detection anchor.
There were zero frame-level mismatches; the unresolved frame remained 4576.

Deterministic resume was checked by restoring verified-state checkpoints after
frames 1, 103, 1851, and 298. These exercise an incomplete bootstrap, completed
bootstrap, normal rolling operation, and the first fallback recovery. The
resumed suffixes contained 499, 488, 300, and 467 frames respectively. Every
detection and the final serialized state matched uninterrupted processing.
