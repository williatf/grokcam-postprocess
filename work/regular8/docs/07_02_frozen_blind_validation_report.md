# P07 Frozen Blind Validation — Final Report

## Decision

**A — P07 passes blind validation and is suitable to proceed to
production-integration/optimization research.**

This validation did not modify or integrate production code, optimize P07,
change detector thresholds, or create P08.

## Freeze and audit trail

The exact reviewed files were verified before processing:

- implementation: `d78bc8478308451af69d37dc7485cb5c0a15cd7a59ccdb75ec86932a498fd13d`
- configuration: `334abf89ee43a0eb18c7f33e68eb8afb9f38556ff981136ac16f5d30b646a1c6`
- tests: `82bc6487ffd3d9bc8c9dc86a206355f4973202ed19b79f9c59a8cb1438558e4d`

All 68 detector outputs were locked before ground truth was opened. The final
pre-unblind package SHA-256 is
`60ff34e75e667abeb6f529e4979c9f3ef97e2f5db58995204888c665f9663231`.
The human CSV SHA-256 is
`b27fd14ece5c1ab8194227e014f8755813117ddd3adbb56da38c4e7ace3f2f37`.
The scorer reverified every locked file before reading the CSV.

Two UI-only lock revisions are recorded. They fixed JavaScript newline escaping
and enabled separate post-reveal marker editing. Each superseding lock verified
143 detector/audit artifacts byte-for-byte unchanged. Frames 247 and 3382 have
separate corrections; the original blind clicks remain preserved.

## Population and scoring

The unchanged 68-frame population contained seven questionable P03 recoveries,
40 stratified strong recoveries, 20 negative controls, and mandatory frame 3341.
All rows were submitted and both landmarks were marked measurable.

Before scoring, a correct acceptance was defined as two measurable landmarks
and pair-anchor error no greater than 25 px. Larger errors were incorrect;
acceptances without two measurable landmarks were uncertain. Raw outliers are
reported separately.

| Result | Count |
|---|---:|
| Frames | 68 |
| Accepted | 67 |
| Rejected | 1 |
| Correct accepts | 67 |
| Incorrect accepts | 0 |
| Uncertain accepts | 0 |
| Correct rejects | 0 |
| False rejects | 1 |
| False-accept rate | 0.00% |
| Acceptance rate | 98.53% |

All questionable recoveries, negative controls, and frame 3341 were correct.
Thirty-nine of 40 strong recoveries were accepted.

## Localization

| Measurement | Median | P95 | Maximum |
|---|---:|---:|---:|
| Upper center | 13.53 px | 19.36 px | 21.32 px |
| Lower center | 6.95 px | 12.60 px | 16.40 px |
| Pair anchor | 6.00 px | 9.88 px | 17.21 px |

Anchor bias was +2.34 px mean X (+1.49 median) and +5.01 px mean Y (+5.11
median). The larger upper Y offset is systematic: the clicked physical corner
and idealized template transition are not identical landmarks. Combining both
centers substantially cancels this asymmetry. Frame 4589 has the maximum anchor
error, 17.21 px.

## Evidence and special populations

Accepted support was 29 at 8+8 classes, 23 at 8+7, nine at 7+8, five at 7+7,
and one at 8+6. Every acceptance had zero contradictions. Geometry residual was
0 px median, 2 px P95, and 6 px maximum. Competitor margin was 2.502 median;
the accepted minimum was 0.873.

Frames 2117, 2170, 2199, and 2240 were accepted without a normal-detector seed.
All four were correct and all were P06 `both_holes_damaged_ambiguous` cases.
The reviewer labeled every frame `clean`, so there is no independent human
bridged-tear or capture-failure stratum; empty category sheets say `NONE`
rather than assigning categories after seeing results.

## Individual exception: frame 4600

Frame 4600 is the sole false reject. Both landmarks were measurable, but P07
reported `ambiguous_competing_pair_positions`: 4+4 support, eight missing
classes, 6 px geometry residual, joint score 6.344, and competitor margin
-0.103. Its rejected candidate was about 550 px from human truth. This is a
conservative failure, not a false registration, and should become an explicit
fallback test in integration research—not retrospective detector tuning.

## Safety regressions

Frame 3341 is a correct physical-pair acceptance with 7.25 px anchor error,
8+7 support, zero contradictions, zero geometry residual, and 2.326 competitor
margin. The erroneous capture prior is 1,283.9 px away; P07 follows physical
perforations rather than picture content.

Frame 42 remains correct at 7.79 px anchor error. Frame 4589 is correct at the
17.21 px validation maximum. Four members of the original 19-frame safety queue
occur in this blind population—2117, 2170, 2199, and 2240. Their classifications,
coordinates, scores, and margins exactly match the frozen 198-frame diagnostics,
and all four validate correctly. The other 15 frozen queue artifacts remain
unchanged and were not used for tuning.

## Performance and POC comparison

Total isolated wall time was 277.30 seconds. Parallel DNG preparation used
18.06 seconds. Incremental detector work summed to 754.40 worker-seconds, with
an 11.30-second median per frame; overlays summed to 6.15 seconds. No
optimization was performed.

The reviewed POC accepted 192/198 (96.97%) with zero contradictions, 2.498
median competitor margin, and 0 px median geometry residual. Blind validation
accepted 67/68 (98.53%), again with zero contradictions, 2.502 median margin,
and 0 px median geometry residual. Blind scoring found zero false accepts and
one conservative false reject.

## Artifacts

- `research/output/sprocket_xy/p07_frozen_blind_validation/lock_manifest.json`
- `research/output/sprocket_xy/p07_frozen_blind_validation/unblind_audit.json`
- `research/output/sprocket_xy/p07_frozen_blind_validation/blind_validation_summary.json`
- `research/output/sprocket_xy/p07_frozen_blind_validation/scored_diagnostics.csv`
- `research/output/sprocket_xy/p07_frozen_blind_validation/scored_diagnostics.json`
- `research/output/sprocket_xy/p07_frozen_blind_validation/scored_overlays/`
- contact sheets `20_incorrect_accepts` through `31_transport_capture_failures`
- `research/output/sprocket_xy/p07_frozen_blind_validation/partner_partial_blind_ground_truth.csv`

