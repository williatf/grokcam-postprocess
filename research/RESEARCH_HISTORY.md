# Sprocket-detection research history

This file records the retained rationale after the 2026-08-27 research cleanup.
All work was isolated from production code, calibration, DNGs, manifests, and
production outputs.

## P08 — cheap same-frame Y refinement

P08 held the trusted P07 pair and frozen geometry fixed and evaluated only
−5…+5 px using upper/lower horizontal-boundary polarity. Opposing upper/lower
peaks and boundary maxima forced 347/351 conservative no-op decisions; the four
accepted corrections did not materially change jitter statistics. Outcome C:
preserve the experiment, do not integrate or loosen it.

## Evolution of the design

1. **Residual edge and corrected-recrop POCs.** A visible upper sprocket edge
   proved that post-registration Y residuals could be measured and corrected
   with one final full-resolution bicubic crop. Large transport excursions were
   real, temporal smoothing was harmful, and interpolation had to remain a last
   resort. Fixed/global edge searches were vulnerable to dirt and missed frame
   3882 when the real boundary fell just outside the normal ROI.
2. **Expanded/bottom physical evidence.** Adaptive search recovered frame 3882;
   bottom-sprocket corroboration and physical candidate geometry protected
   known contaminated Blue frames 3615 and 3676. Confidence-only fusion and
   unconstrained multi-candidate pairing were rejected because they admitted
   plausible-looking wrong edges.
3. **Temporal candidate validation.** A physical detector plus temporal
   validation removed large false corrections on Reel_28486. Independent
   Reel_46335 validation exposed long low-visibility regions and substantial
   interpolation, showing that global ROI/brightness assumptions did not
   generalize fully.
4. **Adaptive visibility and OpenCV X/Y research.** Local visibility
   normalization improved candidates but could not safely solve all reels.
   Genuine blind Blue annotations (75 frames) and independent Reel_28486 and
   Reel_46335 annotations (50 each) established a 175-frame manual ground-truth
   set. Minimal/CV-specific DNG renders and the CV_C-native multi-peak detector
   improved understanding but did not beat the frozen production-derived
   detector safely enough to replace it. These paths were rejected as the main
   architecture; their findings remain in `docs/`.
5. **Capture-versus-production audit.** Capture detects 2-D full perforation
   boxes with temporal pitch/phase tracking; production independently detects
   threshold-defined full-resolution landmarks for crop registration. Capture
   Y maps closely, but X has a stable landmark-definition offset. The audit
   therefore recommended capture as a prior, never as the final crop answer.
6. **Bright-band hybrid POC.** Exact frame joins and `pair_actual` capture boxes
   seeded local full-resolution searches while unchanged broad production
   detection remained fallback. It was safe in review but recovered only 93 of
   Reel_46335's 1,294 production interpolation gaps. Phase-1 forensics found
   that 1,146 of 1,153 eligible failures were size/shape failures caused by
   bright film and hole merging into over-wide 1-D row bands.
7. **Current physical-hole hybrid.** Two independent 2-D contour detections
   inside capture-box-derived ROIs replaced the bright-band evidence. Parameters
   and the 25% ROI margin were frozen on Blue only. Full evaluation recovered
   1,013 of the 1,201 previous-hybrid Reel_46335 gaps, leaving 198 unresolved,
   while preserving all required Blue regressions and Reel_28486 coverage.
   Recommendation: proceed toward integration validation with a larger blind
   review of seeded-only acceptances; do not yet enable it in production.
8. **Partner-assisted partial-hole recovery (P03).** An independently detected
   intact hole supplied pitch/X constraints for searching the damaged partner,
   while same-frame boundary fragments remained mandatory. The approach showed
   partial holes were recoverable, but fitting a box to a torn contour allowed
   damage to alter the reconstructed geometry.
9. **Fixed calibrated geometry (P04).** Blue-frozen width, height, pitch, and X
   relationship prevented torn contours from changing model shape. It recovered
   62 of the frozen 198 problem frames, but choosing one landmark as the anchor
   could shift the otherwise-correct template; frame 42 exposed this failure.
10. **Rigid translation consensus (P05).** Every independently observed
    wall, edge, and corner votes for the translation of one immutable sprocket
    template. Robust consensus retains agreeing constraints and labels isolated
    conflicts as outliers; the frozen 198-frame result is documented in the P05
    findings report. Blind validation has not been restarted.
11. **Partner-predicted rigid-template evidence (P06).** P05 still placed frame
    42 too low and rejected visibly plausible
    damaged partners. P06 starts from an independently detected intact hole,
    predicts one immutable partner template, and directly scores supported,
    missing, and contradictory physical features over only a bounded translation
    grid. It recovers 75 of 198 frames and fixes frame 42's top-edge alignment,
    but large-translation and changed-population cases require review before any
    blind-validation freeze.
12. **Joint rigid sprocket-pair evidence (P07, current freeze candidate).** P06
    could not proceed when neither damaged hole passed as an intact seed. P07
    searches the frozen physical domain for two independently evidenced rigid
    templates and scores them jointly; it accepts 192 of 198 frames, leaves six
    ambiguous/insufficient cases unresolved, and shows no obvious false physical
    registration in the generated review sheets. A new blind validation remains
    the required next gate.
13. **P07 frozen blind validation (passed).** The unchanged P07 hashes were
    verified and all 68 reserved frames were evaluated and locked before any
    protected answer was opened. Final scoring found 67 correct accepts, zero
    incorrect or uncertain accepts, and one conservative false reject; P07 is
    suitable to proceed to production-integration/optimization research.
14. **P07 production integration/performance research.** Production can reuse
    its single developed TIFF, and the measured normal -> P06 -> P07 cascade
    limits expensive P07 calls to 99 of 4,615 Reel_46335 frames. Profiling found
    repeated template percentiles dominate cost. Experimental coarse step 32
    changed frozen behavior on three of 198 frames, so it was rejected and
    further equivalence research is required before implementation.
15. **P07 exact-equivalence evaluator optimization.** Invocation-local caching
    eliminates only byte-for-byte identical candidate computations repeated by
    coarse and fine search. All 198 outputs, 68 blind subset rows, 19 safety
    cases, and mandatory regressions are identical; three-worker throughput
    improves 1.066x. An apparently faster uint8 histogram percentile was
    rejected after six exact mismatches in 5,280 micro-tests.
16. **P07 validated production cascade integration.** The frozen physical-hole,
    P06, and exact-cache P07 stages were ported behind `physical-p07-v1` while
    retaining `legacy` rollback, one development/one final crop, audit-grade
    provenance, and conservative unresolved handling. Direct P07 equivalence
    passed 198/198; controlled use remains gated on the headless OpenCV runtime
    and full-reel cascade validation.

## Current reproducible research path

The later precision-registration metrology path is intentionally separate from
detector development. P14 tested upper-bottom and lower-top as interchangeable
canonical edges, but found a stable optical interval near 519.94 px rather than
the nominal 513 px. P15 therefore uses the frozen lower-top meter directly with
one Primary-only crop offset. It recovered known several-pixel anchor errors on
matched frames, but its 80.9% coverage leaves missing-edge fallback as a
separate future problem; production was not changed.

P16 tested that missing-edge fallback without nominal geometry. A frozen
Primary-calibrated upper-bottom optical offset validated well but added only
four frames (82.1% combined coverage). A separately calibrated lower-bottom
check added no safe coverage and showed errors up to 8.40 px on held-out P07,
so P16 stopped with 63 unresolved frames and no production change.

P17 asked whether short surviving fragments from any of four horizontal edges
could recover those 63 frames. Only lower-bottom passed a substantial held-out
validation population safely, and it recovered zero unresolved frames;
upper-top showed a 21.4% >3 px false rate. The physical-edge fallback approach
was stopped with no production change.

P18–P20 isolated the registration question from detector identity. Trusted
anchors and residual estimators were not themselves precise enough, while the
frozen P07 rigid geometry did contain a useful lower-top coordinate with one
global optical offset. P21 established the simple P15-first/P07-fallback policy;
P22 refined only the already-accepted rigid pair's common Y translation on a
frozen ±3 px, 0.25 px grid and froze the model-to-P15 offset at
4.178787846871160 px.

P23 independently evaluated the frozen policy on 450 predeclared frames from
Reel_46335, Reel_28486, and Blue_Reel. P15 succeeded on 449/450, P07 accepted
450/450, and overlap MedAE/P95 were 0.520/1.459 px. Eleven errors exceeded 2 px
and six exceeded 3 px, with a 4.698 px maximum. Audit showed correct P15 edges
and correct P07 pair identity; the residual limitation is occasional P22 local-Y
imprecision. P23 therefore recorded Decision B. The project subsequently chose
to promote this exact architecture, explicitly accepting that tail as a known
production limitation and prohibiting retuning or per-reel calibration.

Retained active implementations:

- `p01_hybrid_capture_prior_poc.py` and its tests: baseline bright-band hybrid,
  shared exact-join/broad-fallback infrastructure, and documented predecessor.
- `p02_physical_hole_capture_prior_poc.py` and its tests: current 2-D physical-hole
  hybrid baseline.
- `p02_physical_hole_capture_prior_blue_frozen.json`: Blue-frozen configuration.
- `p03_partner_assisted_partial_hole_poc.py` and its tests: first damaged-partner
  recovery experiment.
- `p04_calibrated_geometry_partial_hole_poc.py`, its tests, and frozen config:
  immutable geometry with the superseded single-landmark translation.
- `p05_rigid_consensus_partial_hole_poc.py`, its tests, and frozen config:
  immutable-geometry consensus predecessor.
- `p06_partner_predicted_rigid_template_evidence_poc.py`, its tests, and frozen
  config: direct rigid-template evidence predecessor.
- `p07_joint_rigid_sprocket_pair_evidence_poc.py`, its tests, and frozen config:
  current joint-pair freeze candidate.
- `diagnose_bright_band_failures.py`: reproducible phase-1 failure classifier.

The isolated OpenCV environment is retained through `requirements*.txt`,
`setup_environment.sh`, `run_python.sh`, and `check_environment.py`. The copied
capture source remains under `research/input/GrokCam_capture_source/` so source
line comparisons do not depend on an external machine path.

## Protected manual and expensive data

Never delete or overwrite without an explicit new review:

- `output/sprocket_xy/opencv_ground_truth_benchmark/blue_ground_truth.csv`
- `output/sprocket_xy/opencv_ground_truth_benchmark/reel_28486_validation_ground_truth.csv`
- `output/sprocket_xy/opencv_ground_truth_benchmark/reel_46335_validation_ground_truth.csv`
- the 75 Blue and two 50-frame validation annotation packages and ROI images
  under `output/sprocket_xy/opencv_ground_truth_benchmark/ground_truth/`
- the frozen inference/configuration records adjacent to that ground truth
- any completed browser/local-storage answers and package files under
  `output/sprocket_xy/partner_partial_hole_blind_validation/`; these are protected
  evaluation data and were not inspected while developing P04 or P05

The Blue set is genuine blind manual calibration truth. Reel_28486 and
Reel_46335 remain independent human-reviewed validation truth.

## Retained conclusions and representative evidence

Detailed final reports are under `docs/`, particularly:

- `vertical_stabilization_poc_findings.md`
- `physical_sprocket_detector_poc_findings.md`
- `physical_sprocket_temporal_validation_poc_findings.md`
- `reel_46335_temporal_validation_findings.md`
- `adaptive_visibility_normalization_poc_findings.md`
- `opencv_sprocket_xy_ground_truth_benchmark.md`
- `capture_vs_production_sprocket_detection.md`
- `01_hybrid_capture_prior_poc_findings.md`
- `02_physical_hole_capture_prior_poc_findings.md`
- `03_partner_assisted_partial_hole_poc_findings.md`
- `04_calibrated_geometry_partial_hole_poc_findings.md`
- `05_rigid_consensus_partial_hole_poc_findings.md`
- `06_partner_predicted_rigid_template_evidence_poc_findings.md`
- `07_01_joint_rigid_sprocket_pair_evidence_poc_findings.md`
- `07_02_frozen_blind_validation_report.md`
- `07_03_production_integration_performance_research.md`
- `07_04_exact_equivalence_template_optimization.md`
- `07_05_validated_sprocket_cascade_production_integration.md`

Retained generated evidence is intentionally small: final JSON/CSV summaries,
current contact sheets, three current Reel_46335 recovery clips, the prior
hybrid's long-region clips/safety sheets, and a few historically important Blue
failure/rescue clips. Everything remains Git-ignored and regenerable except the
protected manual annotations.

## Cleanup decision record

Kept because it is active, irreplaceable, expensive/manual, or concise:

- current and immediately preceding hybrid implementations, tests, configs;
- environment/setup files and copied capture source;
- all manual annotation CSVs, pages, selected ROI images, and frozen inference;
- final findings documents and compact validation/summary reports;
- current diagnostics, phase-1 classifications, contact sheets, and three
  representative event clips;
- a small curated set of older clips/contact sheets documenting large-motion
  rescue, false-edge rejection, temporal rejection, and long-region recovery.

Deleted because conclusions are documented and files can be regenerated:

- superseded untracked sprocket/temporal/CV POC and rendering scripts plus tests;
- Python caches, nested capture-source caches, `.DS_Store`, and editor swap data;
- full-frame JPEG/TIFF dumps and duplicated render/segment directories;
- full-reel and duplicate before/after/comparison movies;
- parameter-sweep experiment trees, raw profiles, large candidate-score tables,
  intermediate plots/contact sheets, and duplicate CSV/JSON diagnostics;
- smoke-run and failed/interrupted output directories.

No production path is in the cleanup set.
