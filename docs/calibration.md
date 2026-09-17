# Darktable-match calibration

## Why calibration exists

The approved appearance was originally produced by Darktable. Rawpy is faster
and easier to run in bounded concurrent batches, but its direct output did not
match that appearance. The calibration learns a fixed display transform from
paired renders of the same representative DNG frames.

Production inference and offline calibration are intentionally separate:

```text
production: DNG + frozen versioned calibration -> deterministic rawpy renderer
research:   DNG + Darktable references -> fit candidate -> independent review
```

Production never fits, updates, or writes calibration values.

## Golden production artifact

The adopted calibration is `calibrations/darktable_match_v1.json`; its identity
and provenance are in `darktable_match_v1.metadata.json`. The artifact is an
exact copy of the report created on 2026-08-20 and has SHA-256:

```text
d5a4526b6b5e38fd9d7b37876b0ec39cb37a370d066419433db38f978cb3dc96
```

It contains:

- RGBG white-balance correction `[1.06982421875, 1.0,
  1.0991804599761963, 1.0]`;
- a 13-feature by 3-channel least-squares coefficient matrix;
- three monotonic 256-entry per-channel LUTs;
- 24 training and 8 holdout frame identifiers;
- per-frame reference/match metrics.

The 13 features are a constant, linear RGB, square-root RGB, squared RGB, and
the three cross-channel products. Inference clips the matrix result to `[0,1]`,
linearly interpolates each LUT, and clips again.

Before that transform, rawpy uses AHD demosaicing, the DNG camera white balance
multiplied by the frozen correction, 16-bit output, no automatic brightening,
linear gamma `(1,1)`, and sRGB output color. The matched float image is rounded
to a 16-bit TIFF. Subsequent sprocket registration, contrast, and reel
normalization are production stages, not learned calibration parameters.

## Determinism

The renderer is frozen and deterministic for fixed:

- DNG bytes and embedded metadata/camera white balance;
- calibration artifact bytes;
- production code;
- rawpy/LibRaw, NumPy, and tifffile versions/builds;
- platform floating-point behavior.

It does not use random sampling during inference. The offline fitter uses a
frame-number seed for deterministic sample selection. Exact output across
different rawpy/LibRaw versions is not promised; version changes require
regression testing and may justify recalibration.

## Required source data

Calibration DNGs stay in the archival source directory and are never copied
into Git. The current workflow expects:

- sprocket-white frames: 1400–1403, 1598–1601, 1798–1801, 2198–2201,
  2798–2801, and 3398–3401;
- additional match frames: 120–123 and 1000–1003;
- match training: the first six four-frame groups;
- match holdout: 2798–2801 and 3398–3401.

The current DNG layout is 2028×1520, uncompressed packed 12-bit BGGR with black
level 256 and white level 4095. The sprocket tool's direct CFA reader is specific
to this layout. A different camera or packing requires reviewing that reader.

## Recalibration workflow

Use the project environment. Write candidates only under `work/` or a separate
review output directory.

For a changed camera or illumination, first derive a candidate white-balance
report from the sprocket illumination:

```bash
/home/todd/telecine/.venv/bin/python -m tools.calibrate_sprocket_white \
  --raw-dir /mnt/GrokCam/projects/RAW_Test/raw \
  --work-dir work/regular8/sprocket-white-calibration \
  --output-dir work/regular8/sprocket-white-candidate
```

Then fit a new Darktable-match candidate:

```bash
/home/todd/telecine/.venv/bin/python -m tools.calibrate_darktable_match \
  --raw-dir /mnt/GrokCam/projects/RAW_Test/raw \
  --darktable /usr/bin/darktable-cli \
  --wb-report work/regular8/sprocket-white-candidate/poc-report.json \
  --work-dir work/regular8/darktable-match-calibration \
  --output work/regular8/darktable-match-candidate.json \
  --calibration-id grokcam-darktable-match-candidate-YYYYMMDD \
  --jobs 3
```

To reproduce the current fit with its already frozen white-balance seed, omit
`--wb-report`. The command reads the seed from the golden repository artifact.

Compare learned values with the golden artifact:

```bash
/home/todd/telecine/.venv/bin/python -m tools.compare_darktable_calibrations \
  calibrations/darktable_match_v1.json \
  work/regular8/darktable-match-candidate.json \
  --require-exact-fit
```

## Historical script audit

| Historical script | Calibration classification | Reason |
|---|---|---|
| `grokcam_rawpy_darktable_match_poc.py` | Superseded by current calibration tooling | It uniquely generated paired Darktable/rawpy crops, deterministic samples, the least-squares matrix, monotonic LUTs, holdout metrics, and the report. That behavior now lives in `tools/calibrate_darktable_match.py` and `grokcam.calibration.match_model`. |
| `grokcam_sprocket_white_poc.py` | Superseded by current calibration tooling | It uniquely decoded the packed CFA, measured unclipped sprocket illumination, and derived the initial WB correction. Its capability is preserved as `tools/calibrate_sprocket_white.py`. |
| `grokcam_rawpy_quality_poc.py` | Historically useful only | It compared AHD/AMaZE, 16-bit handling, and an earlier adaptive filmic renderer. It informed choices but does not fit the adopted match. |
| `grokcam_color_poc.py` | Historically useful only | It compared downstream normalization strategies using Darktable output; it does not create renderer calibration. |
| `grokcam_residual_cast_poc.py` | Historically useful only | It evaluates scene/restoration casts and candidate grading, not rawpy-to-Darktable calibration. |

The old direct Darktable production script can render references, but its batch
implementation is neither required nor used by the permanent calibration tools.

## Validation and adoption

A calibration command always emits `adoption_status:
candidate_not_approved`. It never replaces the configured production artifact.
Review training and holdout MAE, contact/reference imagery where appropriate,
dark/bright/color-diverse scenes, and then run the full frames 120–123 production
regression. Geometry must remain exact and the current calibration must retain
movie SHA-256 `bc13e671530a3483dce0f510c1420ad32cf481c942956a8221197297541c5f76`.

Adopting a deliberately different calibration is a separate, explicit change:
give it a new ID, retain its JSON and metadata, change the production default,
and record reviewed regression results. Never overwrite version 1 in place.

## When recalibration is appropriate

- Camera, sensor, CFA layout, or RAW packing changes
- Capture illumination changes
- The desired Darktable rendering changes
- Rawpy or LibRaw behavior changes
- Poor matching is discovered in important exposure/color conditions
- New source material is substantially broader than the original groups
