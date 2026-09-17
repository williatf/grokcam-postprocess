# Sprocket-registration research history

This document preserves the rationale for the production registration system
after removal of executable research POCs. The complete scripts, configurations,
and intermediate documents remain recoverable from Git history, principally
commits `9e0fbd9` (P01–P07 lineage), `83d2fd3` (P08–P23 and production
validation), and `fb3b5b3` (P24/P25 production promotion). No detector or
registration constant was changed by the cleanup that created this archive.

## Detection versus precision registration

The project ultimately separated two jobs that early experiments often mixed:

- **Detection/localization** finds a trustworthy rigid two-sprocket placement
  despite dirt, clipping, merged highlights, and partial holes.
- **Precision registration** measures the physical optical landmark used for
  the final crop. A detector coordinate is not automatically precise metrology.

P15 is authoritative Y metrology when its lower-sprocket top measurement
passes unchanged column-consensus checks. P07 is the robust rigid-pair fallback;
accepted P07 geometry is refined only by P22's same-frame sub-grid common-Y
search. No production branch uses temporal interpolation, temporal smoothing,
neighboring frames, historical coordinates, or residual vertical stabilization.

## Physical-pair recovery: P03–P07

- **P03** used an intact hole to constrain recovery of a damaged partner.
  Contour-derived boxes could move or deform with damage.
- **P04** froze calibrated hole size and pair geometry. A single misleading
  landmark could still translate the rigid model incorrectly.
- **P05** combined independent landmarks as votes for one rigid translation.
  Coherent but physically contradictory placements remained possible.
- **P06** predicted the partner from same-frame intact evidence and directly
  tested fixed-template pixel support in a bounded neighborhood.
- **P07** removed the intact-seed requirement and jointly searched the physical
  two-hole domain. It conservatively rejects weak, contradictory, or competing
  placements. Blind validation found no false accepts and one conservative
  false reject. Exact candidate memoization preserved all tested decisions and
  became the frozen production implementation.

This lineage and its original artifacts entered Git in `9e0fbd9`. P07 remains
unchanged in production; capture boxes, local physical holes, and P06 may supply
same-frame priors but cannot accept or veto P07.

## Precision-registration experiments: P08–P23

- **P08** searched a tiny same-frame Y neighborhood around the trusted pair.
  Boundary evidence was usually conflicting or uninformative; conservative
  acceptance produced essentially no useful correction. It was rejected.
- **P09–P13** explored individual sprocket boundaries, coverage, failure
  populations, transition behavior, and blinded landmark audits. They clarified
  the difference between geometric model coordinates and optical edges.
- **P10** showed that apparent broad coverage could conceal source-dependent
  failure modes and that missing/invalid measurements must remain explicit.
- **P14** established detector-guided narrow optical-edge measurement.
- **P15** simplified this to the top edge of the lower sprocket. When valid it
  provided precise physical Y and became authoritative production metrology.
- **P16** calibrated an upper-bottom fallback. It was accurate where present
  but recovered only a handful of missing P15 cases.
- **P17** tested four independently calibrated partial-edge segments. It found
  no safe useful recovery population and ended the edge-fallback line.
- **P18/P19** tested whether trusted anchors or residual evidence directly
  delivered precise register. Fixed offsets removed central bias but surviving
  detector evidence retained source/evidence-dependent tails; these approaches
  were not promoted.
- **P20** compared the rigid-model lower top directly with P15 truth.
- **P21** established P15-first with rigid P07 fallback.
- **P22** refined only accepted P07's common Y at 0.25 px spacing within ±3 px.
  It became the sole production refinement after P07.
- **P23** initially appeared to validate near-complete P15-first coverage. A
  later forensic review corrected that interpretation: P23 ran P07 first and
  used its coordinates to place P15's narrow ROI, so it was not independent
  validation of the cheap front end.

The P08–P23 implementations and reports entered Git in `83d2fd3`. Important
negative results—especially P08, P10, P17, and the P18/P19 limitations—prevented
unsafe smoothing, source-specific calibration, and proliferating edge finders.

## Capture-assisted registration: P24 and P25

Production data showed that most expensive fallbacks came from missing or
mislocalized preliminary P15 guides, not from P15 metrology itself.

**P24** evaluated transformed capture `pair_actual` geometry. Capture-only Y
guidance had useful central accuracy but an unsafe outlier tail. The promoted
gate therefore requires all frozen capture-geometry predicates plus agreement
with two successful, low-score local physical-hole measurements. Capture Y only
places P15; physical-hole Y only corroborates. Neither is final Y registration.

**P25** resolved the missing-X architectural question. The capture and P07
anchor conventions are both `mean(upper_x, lower_x) - 17.125`. On the exact 139
held-out P24/P15 rescues, development-calibrated capture X had 1.602 px MedAE,
3.333 px P95, 3.999 px maximum, and no error above 5 px. This justified
provisional local-production use of calibrated capture X when P24-guided P15
accepts. The production promotion is commit `fb3b5b3`.

## Frozen production architecture and constants

```text
primary localization -> P15
  success: primary X + measured P15 Y
  failure: frozen P24 corroborated capture guide -> P15
    success: calibrated capture X + measured P15 Y
    failure: frozen P07 -> accepted? -> P22 : preserve/debug/exclude
```

Frozen values:

- P24 capture-Y bias: `14.5` px, subtracted.
- P24 physical-Y bias: `23.0` px, subtracted for corroboration only.
- P25 capture-X bias: `1.3344210526315692` px, subtracted.
- P07-model to P15-optical Y offset: `4.178787846871160` px.
- P15 lower-top to crop-top offset: `-673.5297914597816` px.
- Capture pitch: `740 <= pitch <= 835`.
- Both capture widths: `>= 350` px.
- Both capture heights: `250 <= height <= 340` px.
- Capture height difference: `>= 20` px.
- Absolute capture X displacement: `<= 30` px.
- Calibrated capture/physical Y disagreement: `<= 8` px.
- Both physical-hole fit scores: `<= 0.30`.

The final image is always sampled once from the original developed TIFF using
the selected final crop.

## Two-full-reel production milestone

The `fb3b5b3` production architecture completed two full reels and both movies
were visually reviewed as very good:

| Reel | Input | Primary/P15 | P07 attempts | P07/P22 | Excluded |
|---|---:|---:|---:|---:|---:|
| Reel_28486 | 5,125 | 5,108 | 17 | 15 | 2 |
| Blue_Reel | 5,153 | 5,131 | 22 | 18 | 4 |

Neither transfer reel produced a P24/P25 rescue: the frozen P24 capture gate
rejected the small primary-failure population before admission. Thus these runs
strongly validate primary/P15 coverage, unchanged P07/P22 fallback, exclusion,
manifest attribution, and final rendering, but do not independently validate
capture-X transfer. The P24/P25 branch remains frozen and available rather than
being retuned during this milestone.

Known excluded/failure fixtures include Reel_28486 frames 5037 and 5094 and
Blue_Reel frames 86, 161, 2625, and 5116. They are retained in production
manifests/debug outputs, not copied into the repository.

## Historical recovery

Deleted research executables and generated artifacts are not production
dependencies. Tracked historical source can be inspected without restoring it,
for example:

```bash
git show 83d2fd3:research/p18_sprocket_detector_register_poc.py
git show 9e0fbd9:research/p07_joint_rigid_sprocket_pair_evidence_poc.py
```

Production code, tests, frozen constants, manifests, and the operational
deterministic P24 transfer-sample generator remain in the current tree.
