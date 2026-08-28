# P07 Exact-Equivalence Template-Evaluation Optimization

## Recommendation

**A — an exact-equivalent evaluator optimization has been demonstrated and is
ready to be used in a production-integration implementation phase.**

This is a research result only. Production and frozen P07 were not changed.

## Frozen oracle and experimental variant

Verified frozen hashes:

- implementation: `d78bc8478308451af69d37dc7485cb5c0a15cd7a59ccdb75ec86932a498fd13d`
- configuration: `334abf89ee43a0eb18c7f33e68eb8afb9f38556ff981136ac16f5d30b646a1c6`
- tests: `82bc6487ffd3d9bc8c9dc86a206355f4973202ed19b79f9c59a8cb1438558e4d`

Exact-cache variant hashes:

- implementation: `459093853b1f4fb5843849ffd034d31984a89f554a0535b190ccbf4253d3899c`
- configuration record: `c3b5a2a7e554a48093a30278b1eebfd4b18621bfdd93df9a8958e06a545a86d5`
- tests: `137a74c5cdd999da8d6a95a62ae0516c383c6d406cbd82b3244ea882c627b8ee`

The variant copies the frozen `fit_pair` control flow and changes one concept:
an invocation-local dictionary memoizes an already-computed pair candidate by
the exact `(upper_x, upper_y, full_evidence_mode)` tuple. A hit returns a shallow
copy of that exact dictionary. It does not reuse nearby positions, persist
across images, change the grid, reorder candidates, change priors, or replace
any arithmetic. `full=False` and `full=True` are distinct keys.

## Frozen evaluator repeated work

The established six-frame reference profile evaluated 12,535 pair candidates
and 25,070 hole templates. Every non-full hole template executes two
percentiles: inside P60 and outer P30. Thus a pair performs four percentiles;
each frame also performs one P92 gradient-normalization percentile.

Reference cumulative profile (six frames):

| Operation | Calls | Cumulative time |
|---|---:|---:|
| `fit_pair` | 6 | 35.63 s |
| `_pair_candidate` | 12,535 | 35.49 s |
| `_template_evidence` | 25,070 | 34.83 s |
| percentile | 50,146 | 20.78 s |
| NumPy partition | 50,146 | 17.48 s |
| corner evidence | 100,280 | 7.73 s |
| line evidence | 101,480 | 5.60 s |

Each line call reconstructs a 31- or 41-sample `linspace`/constant coordinate
array. Each corner reconstructs a 13-angle arc, translated coordinates, normals,
and two gradient gathers. Every template constructs interior and outer slices;
typical unclipped arrays are approximately 32 thousand and 203 thousand float32
pixels. `np.percentile` may copy/partition these arrays. Grayscale and Sobel maps
are correctly computed once per `fit_pair`, but their pixels are gathered many
times by overlapping candidates.

Coarse and fine grids contain exact duplicate translations. Frozen P07
recomputes their line arrays, corner arrays, gradient gathers, large percentile
partitions, feature states, and pair score. The exact cache eliminates the whole
duplicate computation. Overlapping but non-identical windows are deliberately
not cached.

Across 198 frames:

- candidate calls: 488,417;
- exact duplicate hits: 30,329 (6.210%);
- misses/actual optimized evaluations: 458,088;
- hole-template evaluations avoided: 60,658;
- percentile calls avoided: 121,316.

The cache therefore attacks only measured exact repetition. It does not claim
to remove the much larger amount of merely overlapping sampling.

## Incremental experiments

### Exact candidate memoization — accepted

Two synthetic tests first required complete dictionary equality for a physical
pair and a rejection. The established six hard frames—42, 949, 2117, 3341,
4589, and 4600—were then run three times with alternating reference/optimized
order on the same resident TIFF arrays. All 18 comparisons were identical.

### Exact uint8 histogram percentile — rejected

The grayscale percentile arrays contain integer-valued float32 values derived
from uint8 grayscale, making a 256-bin histogram superficially attractive. An
isolated cumulative-histogram implementation was tested against NumPy's default
float32 percentile semantics for P30/P60 over 5,280 seeded comparisons,
including duplicate values, sizes 1-129, and representative large arrays. Six
exact mismatches occurred. Although a 203,000-element microbenchmark appeared
9.37x faster, the concept was rejected immediately and never inserted into a
detector. No mismatch-specific tuning was attempted.

Static geometry, batched gathering, and parallel candidates remain potential
future work. They were not combined with memoization in this POC because their
floating/index construction and reduction order require separate equivalence
proofs. Candidate threading was also not added; the production-like frame-level
benchmark already exposes contention, and changing completion order could affect
tie behavior if not carefully isolated.

## Strict equivalence

The paired full audit developed each of the frozen 198 frames once, held the
same RGB array resident, and ran both implementations. Execution order alternated
by frame parity. Equality required the entire returned nested dictionary to be
equal and separately checked decision, centers, score, margin, and feature states
against the stored frozen oracle.

| Population | Identical | Behavioral changes |
|---|---:|---:|
| Complete frozen population | 198/198 | 0 |
| Blind-validation subset | 68/68 | 0 |
| Safety queue | 19/19 | 0 |
| Mandatory regression/unresolved set | 11/11 | 0 |

Mandatory coverage includes 42, 3341, 4589, 4600; no-normal-seed frames 2117,
2170, 2199, 2240; and unresolved frames 2606, 2608, 4599, 4600. The full
population also contains lowest margins, maximum residuals, P06 both-damaged
cases, and capture/ROI failures. Human ground truth was not used; frozen P07
outputs alone defined equivalence.

There were no numerical-only differences to enumerate: **198/198 IDENTICAL**.

## Performance

### Single-process matched six-frame benchmark

Eighteen alternating comparisons after warm-up:

| Metric | Frozen reference | Exact cache |
|---|---:|---:|
| Median/frame | 4.484 s | 4.251 s |
| Mean/frame | 4.724 s | 4.461 s |
| P95 | 6.418 s | 5.916 s |
| Maximum | 6.427 s | 5.919 s |
| Sum | 85.04 s | 80.30 s |

Aggregate speedup: **1.059x**. The six-frame cache hit rate was 5.529%.

### Production-like three-worker full benchmark

| Metric | Frozen reference | Exact cache |
|---|---:|---:|
| Median/frame | 11.334 s | 10.673 s |
| Mean/frame | 11.046 s | 10.365 s |
| P95 | 12.755 s | 11.941 s |
| Maximum | 14.306 s | 12.596 s |
| Worker-time sum | 2,187.19 s | 2,052.23 s |

Aggregate speedup: **1.066x**. Complete paired wall time, including development
and both detectors, was 1,494.62 s. Reference throughput was about 223.3 pair
candidates/worker-second; optimized effective throughput was about 238.0.

The optimized six-frame profile fell from 50,146 to 47,374 percentile calls,
with partition cumulative time falling from 17.48 to 16.42 s. `_template_evidence`
calls fell from 25,070 to 23,684. The remaining evaluator cost per actual
candidate is unchanged, as required.

Process peak RSS during the three-worker audit was 1,762,120 KiB. This includes
three developed images, both sequential detector runs, OpenCV/NumPy storage, and
Python state; it is not an incremental cache-only allocation figure. The cache
contains at most one dictionary per unique candidate within one invocation and
is released afterward. Python allocation counts would omit NumPy native buffers,
so no misleading byte claim is made.

Environment: Python 3.14.4, NumPy 2.5.2, OpenCV 4.14.0, Linux 7.0.0-29, eight
logical CPUs, three frame workers, and no explicit OMP/OpenBLAS/MKL/NumExpr
thread environment overrides.

## Whole-reel impact

The measured Reel_46335 cascade invokes P07 99 times out of 4,615 frames
(2.145%). Using the production-like median improvement of 0.661 s/call, exact
memoization saves approximately 65.5 seconds on that reel and 2.36 minutes per
10,000 frames at the same fallback rate. Estimated savings for the earlier
capacity assumptions are approximately 0.95 minutes for a 4,000-frame 3-inch
reel, 3.78 minutes for 16,000 frames, and 7.57 minutes for 32,000 frames.

The optimization is deliberately modest. Its value is that the saved work is
proven redundant and the behavior is exact, not that it solves P07's entire
performance cost. Further gains should target exact percentile/window reuse or
static feature geometry in separate frozen-equivalence POCs.

## Artifacts

- `research/p07_exact_cached_candidate_poc.py`
- `research/p07_exact_cached_candidate_blue_frozen.json`
- `research/test_p07_exact_cached_candidate_poc.py`
- `research/output/sprocket_xy/p07_exact_template_optimization/equivalence_audit.json`
- `research/output/sprocket_xy/p07_exact_template_optimization/full_198_equivalence.csv`
- `research/output/sprocket_xy/p07_exact_template_optimization/six_frame_benchmark.json`
- `research/output/sprocket_xy/p07_exact_template_optimization/six_frame_benchmark.csv`
- `research/output/sprocket_xy/p07_exact_template_optimization/optimized_profile.txt`
- `research/output/sprocket_xy/p07_exact_template_optimization/optimized_profile.pstats`
- `research/output/sprocket_xy/p07_exact_template_optimization/optimized_profile_metrics.json`
- `research/output/sprocket_xy/p07_exact_template_optimization/uint8_histogram_quantile_probe.json`

