# Retained research

## Computer-vision environment

Sprocket-detection research uses an isolated environment so OpenCV and the
larger analysis stack never become production runtime dependencies:

```bash
research/setup_environment.sh
source work/research-venv/bin/activate
research/run_python.sh research/check_environment.py
```

The environment is disposable and Git-ignored under `work/`. Direct dependency
ranges are recorded in `research/requirements.txt`, while
`research/requirements-lock.txt` freezes the environment currently under test.
Record a per-run snapshot with
`python -m pip freeze > research/output/<run>/environment-freeze.txt`.

Use `research/run_python.sh` for new sprocket research. It selects the isolated
Python and places library caches under ignored `work/research-cache/`. The
intended two-axis path is:

```text
locally normalized sprocket ROI
    -> connected components / contour candidates
    -> physical hole geometry and edge validation
    -> same-frame top/bottom or multi-hole agreement
    -> temporal validation
    -> exact X/Y measurement (no smoothing at measurement time)
```

OpenCV is for fast candidate generation and geometry measurement. It does not
replace the established physical or temporal rejection safeguards.

The current sprocket-recovery lineage is deliberately numbered because each
stage preserves the safety architecture of its predecessor:

```text
P01 capture prior
    ↓
P02 full-resolution physical-hole detection
    ↓
P03 partner-assisted partial-hole recovery
    ↓
P04 fixed calibrated geometry
    ↓
P05 rigid-geometry consensus translation
    ↓
P06 partner-predicted rigid-template evidence
    ↓
P07 joint rigid sprocket-pair evidence (current freeze candidate)
    ↓
P07 frozen blind validation (passed: 0 false accepts, 1 conservative false reject)
    ↓
P07 production integration/performance research (architecture sound; equivalence work remains)
    ↓
P07 exact-equivalence candidate memoization (198/198 identical; ready for integration implementation)
```

The P07 documents follow that progression explicitly:

1. `docs/07_01_joint_rigid_sprocket_pair_evidence_poc_findings.md`
2. `docs/07_02_frozen_blind_validation_report.md`
3. `docs/07_03_production_integration_performance_research.md`
4. `docs/07_04_exact_equivalence_template_optimization.md`

- `p01_hybrid_capture_prior_poc.py` tested capture boxes as search priors while
  remeasuring full-resolution pixels. Its 1-D bright-band evidence was safe but
  missed merged/bright holes, motivating physical 2-D detection.
- `p02_physical_hole_capture_prior_poc.py` identifies actual 2-D perforations
  inside capture-predicted ROIs. It dramatically reduced interpolation, but
  damaged or partial partner holes remained unresolved.
- `p03_partner_assisted_partial_hole_poc.py` used an intact hole to constrain a
  partial partner search. Contour-derived box fitting could be displaced or
  distorted by damage, motivating immutable geometry.
- `p04_calibrated_geometry_partial_hole_poc.py` fixed width and height to
  Blue-frozen geometry. A single selected landmark could still translate the
  entire model incorrectly, as demonstrated by frame 42.
- `p05_rigid_consensus_partial_hole_poc.py` is the immediate isolated predecessor.
  Every independently observed landmark votes for the translation of one rigid
  template; robust consensus rejects inconsistent landmarks as outliers.
- `p06_partner_predicted_rigid_template_evidence_poc.py` starts from the intact
  same-frame sprocket, predicts one immutable partner template, and directly
  tests physical pixel support over a small translation neighborhood. It was
  needed because P05 could still choose a geometrically coherent translation
  that contradicted a strong physical boundary, notably frame 42.
- `p07_joint_rigid_sprocket_pair_evidence_poc.py` removes the intact-hole seed
  requirement. It jointly searches for two independently evidenced immutable
  templates over the physical X domain and conservatively rejects competing
  pair positions.

Run the current POC with:

```bash
research/run_python.sh research/p07_joint_rigid_sprocket_pair_evidence_poc.py --help
```

The separate blind-validation package is under
`research/output/sprocket_xy/p07_frozen_blind_validation/`. Its detector output
was locked before the annotation CSV was exported. Final scoring found 67
correct accepts, no incorrect or uncertain accepts, and one conservative false
reject. See `docs/07_02_frozen_blind_validation_report.md`.

Integration/performance research is documented in
`docs/07_03_production_integration_performance_research.md`. It preserves the
frozen detector and makes no production change. A coarse-step optimization
retained decisions but changed frozen behavior on three of 198 frames, so no
optimization is approved for integration yet.

The next isolated performance POC is documented in
`docs/07_04_exact_equivalence_template_optimization.md`. Exact memoization of
duplicate coarse/fine candidate evaluations produces 198/198 identical outputs
and a 1.066x production-like speedup. It is approved as an implementation
candidate; production remains unchanged.

The numbered frozen configurations and tests use the same `p01`–`p07` stage
prefixes. Existing generated output directories retain their historical names
so evidence and protected validation packages are not disturbed. See
`RESEARCH_HISTORY.md` for results and transition rationale.

The earlier measurement-only X/Y benchmark remains in
`opencv_sprocket_xy_poc.py`; its frozen configuration and manual-annotation
tooling are retained because the 175 reviewed frames are irreplaceable research
ground truth.

These older tracked scripts preserve useful non-sprocket or foundational
investigations and are not imported or executed by the production pipeline:

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
