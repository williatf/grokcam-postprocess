# P07 Production Integration and Performance Research

## Recommendation

**B — architecture is sound but further performance/equivalence research is
required before integration.**

The validated full-domain detector remains the authority. No production file,
frozen P07 file, calibration, manifest, DNG, or production output was changed.
No P08 was created.

## Frozen baseline

The implementation, configuration, and test hashes were verified as
`d78bc847...fd13d`, `334abf89...a1c6`, and `82bc6487...e4d`. They remained
unchanged after this work. Blind validation remains 67 correct accepts, zero
incorrect/uncertain accepts, and one conservative rejection (frame 4600).

## Current production path

The actual path is:

```text
DNG
  -> one Darktable-matched full-resolution 16-bit TIFF development
  -> full-resolution luminance-band pair detection
  -> five-frame local-median validation
  -> interpolation of rejected primary anchors
  -> primary crop from anchor + fixed offsets
  -> optional provisional registered 1133x900 JPEG in memory
  -> residual top edge / expanded top / bottom rescue
  -> residual interpolation only when same-frame evidence fails
  -> one final bicubic crop from the original developed TIFF
  -> normalization and encoding
```

Source references:

- `grokcam/batch.py:148-186`: one TIFF development and primary detection.
- `grokcam/sprocket_detection.py:24-53`: full-resolution RGB conversion,
  X=100-570 luminance ROI, percentile threshold, row bands, pitch/width score.
- `grokcam/sprocket_detection.py:56-76`: five-frame median outlier rejection and
  X/Y interpolation.
- `grokcam/registration.py:7-9`: anchor-to-crop offsets.
- `grokcam/batch.py:188-218`: provisional residual input and final TIFF crop.
- `grokcam/vertical_stabilization.py:138-210`: normal/expanded top measurement,
  bottom rescue, bounds checks, and last-resort interpolation.
- `grokcam/image_processing.py:11-18`: final bicubic extent crop and orientation.

Production imports no capture JSONL or capture boxes. It has the TIFF and PIL
image available when primary detection runs, but no persistent luminance,
gradient, polarity, or physical-hole candidate cache. The primary detector
creates float32 RGB and mean luminance; P07 separately creates uint8 RGB,
grayscale, Gaussian blur, and Sobel maps. Residual stabilization operates later
on a serialized in-memory JPEG of the provisional registered crop; that image
is not equivalent to P07's full-resolution evidence and cannot replace it.

P07 can consume the already-open developed TIFF. A second RAW development or a
second retained detector image is unnecessary. A future integration should
prepare P07 grayscale/gradients lazily only for fallback frames and reuse them
through all P07 candidate evaluations.

## Cost profile

On six difficult frames (42, 949, 2117, 3341, 4589, 4600), single-process
reference P07 search took 5.63 seconds median. Image conversion was about 6 ms
median and normal physical-hole evidence was milliseconds. The existing
production luminance-pair detector measured 16 ms median over 18 runs.

The six-frame cProfile contains 12,535 pair candidates and 25,070 template
evaluations. Of 35.63 cumulative seconds:

- `fit_pair`: 35.63 s;
- `_pair_candidate`: 35.49 s;
- `_template_evidence`: 34.83 s (97.8%);
- percentile/quantile calculation: 20.78 s;
- NumPy partition called by percentiles: 17.48 s (49.1%);
- corner evidence: 7.73 s;
- line evidence: 5.60 s.

Detector-image and Sobel preparation are negligible beside repeated feature
sampling and per-candidate percentile work. The blind run's production-like
parallel workload measured 11.30 seconds median detector time per frame and
277.30 seconds wall time for 68 frames. The difference from the isolated
single-process profile reflects worker contention and workload variation; both
figures are retained as lower/conservative cost bounds.

The profile does not expose independent coarse/fine timers without copying and
altering the frozen function. Candidate counts and cumulative evidence time
show that both search phases are dominated by the same template evaluator.
Diagnostics and overlays are not material (6.15 seconds total for 68 overlays).

## Measured cascade

For the frozen 198-frame Reel_46335 problem population:

| Stage | Stops successfully | Percent of 198 | Remaining |
|---|---:|---:|---:|
| normal full-hole evidence | 24 | 12.12% | 174 |
| P06 partner template | 75 | 37.88% | 99 |
| P07 joint pair | 95 | 47.98% | 4 |
| unresolved | 4 | 2.02% | — |

The unresolved frames are 2606, 2608, 4599, and 4600. P07 alone after the
normal stage would receive 174 frames and accept 169, versus only 99 P07 calls
when P06 remains. P06 therefore avoids 75 expensive P07 invocations and is not
redundant. P07 adds 95 same-frame measurements after the cheaper stages.

The recommended cascade is:

1. unchanged production primary detection and batch validation;
2. capture-seeded full-resolution physical-hole evidence where eligible;
3. P06 only when an independently trustworthy same-frame partner exists;
4. exact frozen full-domain P07 for remaining frames;
5. flagged conservative downstream handling when P07 rejects.

Capture, normal, P06, and temporal positions may order candidate work but must
not veto the full physical domain or become the answer. P07 remains the source
of accepted coordinates at stage 4.

## Search-order research

Likely-region-first search cannot safely stop merely because it finds a strong
local result: competitor margin is defined against separated alternatives, so
the remaining physical domain must either be searched or excluded by a proven
upper bound. No such bound exists in the reference. Adding previous/neighbor
priors would also alter current candidate density and the weak-prior score,
making it a behavioral change unless carefully isolated from scoring.

Frame 3341 demonstrates the requirement. Its capture prior is 1,283.9 px wrong,
but full-domain P07 finds the physical holes. Any prior-limited cascade would
reintroduce the picture-content hazard. The proposed architecture may search
that prior first, but it must expand to the frozen X/Y domain before rejecting
or accepting unless equivalence is certified.

## Coarse-to-fine experiment and equivalence

Experimental coarse steps 24 and 32 were first tested on six hard frames.
Step 24 changed frame 4589 by 1.5 px and changed feature states. Step 32 was
identical on those six, so it was run over all 198 frames.

Full step-32 result:

| Classification | Frames |
|---|---:|
| IDENTICAL | 158 |
| NUMERICALLY EQUIVALENT | 37 |
| BEHAVIORAL CHANGE | 3 |
| accept/reject decision changes | 0 |

Frames 1007 and 1666 moved 4.28 and 5.08 px. Frame 2606 selected a different
rejected hypothesis 193.49 px away and changed evidence states and competitor
margin. Thirty-seven other frames moved up to 3.16 px or changed scores,
margins, or evidence states. Therefore step 32 is not production-equivalent and
is rejected despite retaining decisions. It also cannot claim a controlled
full-population speedup because reference and variant full runs were not timed
under identical contention; the small probe's apparent speedup is only a lead.

No vectorized, cached-percentile, integral-image, or batched evaluator was
implemented. The profile identifies these as appropriate next research, but
mathematical equivalence must be demonstrated across all 198 frames, the 68
blind frames, the 19-frame queue, and mandatory regressions before integration.

## Required regressions

- Frame 42: unchanged correct physical pair.
- Frame 3341: unchanged correct physical pair despite the wrong capture prior.
- Frame 4589: unchanged reference; step 24 was non-identical.
- Frame 4600: unchanged conservative `ambiguous_competing_pair_positions`.
- All four blind no-normal-seed successes remain represented in the 198-frame
  comparison.
- All 19 safety-queue frames are included in the 198-frame comparison.
- P06 capture/ROI failures, both-damaged cases, and low-margin cases are present
  in the same frozen population.

The 68 blind frames are a subset of this frozen 198-frame population; all are
therefore covered by the full equivalence comparison without using their human
answers to tune behavior.

## Frame 4600 and true failure policy

Frame 4600 contains two human-measurable holes, but frozen P07 cannot separate
competing positions. Production must preserve that rejection. For an isolated
interior failure, the safest default is temporal interpolation from trustworthy
same-frame neighbors, explicitly marked `interpolated_after_p07_ambiguity`.
Capture or a single hole may be logged as diagnostics but must not override the
rejection. At a segment boundary or across a discontinuity, do not interpolate
blindly; flag for review and compare exclusion against a provisional crop.

Policy classes:

- A, two evidenced holes: use the accepted P07 anchor.
- B, only one captured hole: unresolved; no new extrapolation in this stage.
- C, capture/transport failure: flag; prefer dropping when interpolation is not
  locally trustworthy. One frame at 16 fps is 62.5 ms.
- D, competing physical pairs: preserve rejection; interpolate only across
  trustworthy neighbors, otherwise flag/drop.

This policy needs visual validation before implementation. No automatic frame
dropping or new single-hole recovery was added.

## Whole-reel cost model

Reel_46335 has 4,615 frames and the measured cascade would invoke P07 99 times
(2.145%). At 5.626 seconds isolated median, this adds about 9.28 detector minutes;
at the blind-run 11.30-second conservative median, 18.65 minutes. Per 10,000
frames at the same failure mix: 214.5 P07 calls and 20.1-40.4 added minutes.

No reliable reel-diameter metadata exists in current manifests. Using clearly
labeled 8 mm capacity estimates of 80 frames/foot—3-inch 50 ft/4,000 frames,
5-inch 200 ft/16,000 frames, 7-inch 400 ft/32,000 frames—the added P07 time is:

| Reel estimate | Frames | P07 calls | Added minutes, 5.626-11.30 s/call |
|---|---:|---:|---:|
| 3-inch | 4,000 | 85.8 | 8.0-16.2 |
| 5-inch | 16,000 | 343.2 | 32.2-64.6 |
| 7-inch | 32,000 | 686.5 | 64.4-129.3 |

These estimates assume Reel_46335's unusually difficult fallback rate. Blue
Reel currently interpolates 25/5,153 primary frames and Reel_28486 1/5,125, so
their P07 invocation rates and costs should be far lower. Exact cascade runs on
those reels are still required before using a single fleet-wide estimate.

## Proposed future production architecture

Do not copy research imports directly into production. A future implementation
phase should:

- add a production-owned physical evidence module containing a line-for-line,
  hash-documented port of frozen P06/P07 primitives;
- lazily prepare one full-resolution grayscale/gradient context from the
  already-open TIFF;
- retain the normal detector first and run P06/P07 only for unresolved anchors;
- keep full-domain P07 authoritative until an optimization is proven equivalent;
- preserve per-frame source, evidence states, scores, competitor margin, and
  interpolation reason in the manifest;
- keep final cropping as the existing single bicubic sample from the TIFF.

Files expected to change in a later authorized implementation:

- new `grokcam/physical_sprocket.py` for frozen physical evidence/P06/P07;
- `grokcam/sprocket_detection.py` for the cascade interface;
- `grokcam/batch.py` for capture metadata loading, lazy fallback invocation,
  batch resolution, diagnostics, and failure policy;
- `grokcam/config.py` for an immutable versioned detector configuration;
- `grokcam/models.py` for measurement source and P07 diagnostics;
- `grokcam/manifest.py` for detector version/hash and cascade policy records;
- `tests/test_production.py` plus new equivalence fixtures/tests.

Required tests include frozen hash/config checks, all 198 reference rows, all 68
blind rows, exact frame 42/3341/4589/4600 assertions, all 19 queue cases,
capture-prior corruption, no-seed/both-damaged evidence, batch-boundary
interpolation, out-of-bounds crop rejection, restart/manifest compatibility,
and proof that each DNG is developed and finally sampled once.

Risks are semantic drift while porting P06/P07, hidden prior vetoes, excessive
runtime, memory pressure from concurrent full-resolution arrays, and manifest
resume incompatibility. Rollback must be a versioned feature flag/config mode
that leaves the existing detector/crop path intact, forbids mixed detector
versions within one output directory, and permits restarting from source DNGs
without altering archival input.

