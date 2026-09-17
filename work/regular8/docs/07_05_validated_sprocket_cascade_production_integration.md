# P07 — Validated sprocket cascade production integration

## Outcome

`physical-p07-v1` is implemented as an opt-in production mode with `legacy` as
the rollback default. The cascade preserves the developed-TIFF evidence path:

1. unchanged production primary detector and local-median validation;
2. eligible capture `pair_actual` boxes used only as ROIs for full-resolution
   physical-hole measurement;
3. frozen P06 partner-template evidence only after one hole is independently
   measured;
4. exact cached full-domain P07;
5. isolated trusted-neighbor interpolation, otherwise an explicit stop for
   exclusion/review.

Capture coordinates never become an anchor. P07 always retains its full search
domain, including frame 3341's badly wrong capture prior case.

## Frozen references and equivalence

All required source hashes matched before implementation. The production port
was then run against the frozen Reel_46335 198-frame oracle using identical
developed image evidence and priors:

| Population | Identical |
|---|---:|
| Frozen population | 198 / 198 |
| Blind subset | 68 / 68 |
| Safety queue | 19 / 19 |

Mandatory results were unchanged: frames 42, 3341, 4589, 2117, 2170, 2199,
and 2240 were accepted; 2606 and 2608 retained insufficient-support
rejections; 4599 and 4600 retained competing/insufficient rejection behavior.
Frame 4600 remains `ambiguous_competing_pair_positions` and was not tuned.

The final production module SHA-256 is
`3badaa9a4a567c62d61ddac695cdfc421e629d3c1a3e44ac0dcd3d13d4e2437d`.
The manifest also records the frozen P07 implementation/configuration hashes
and exact-cache implementation hash. Resume checks both mode and production
module hash.

## Image path and residual stabilization

P06/P07 open the already-developed TIFF lazily and retain no cross-frame image
cache. The candidate cache is local to one `fit_pair` call. A recovered anchor
feeds the existing crop calculation and residual vertical measurement. The
residual correction modifies crop coordinates; `registered_frame` then makes
one bicubic `EXTENT` sample from the original developed TIFF. Tests assert the
P07-anchor sign convention and one final transform. No DNG redevelopment,
intermediate final-quality shift, or synthetic fill was added.

## Manifest diagnostics

Per-frame records identify the primary result, fallback stage, P06/P07 attempt
and decision, final registration source, rejection/interpolation reason, hole
centers and final anchor, supported/missing/contradicted states, joint score,
geometry residual, competitor score/margin, detector hashes, and exact-cache
counters. Temporary gradient arrays and candidate grids are not serialized.

## Validation runs

An isolated Blue 3449–3453 run developed five DNGs once, invoked P07 only for
primary-rejected frame 3451, recovered it from same-frame physical evidence,
applied residual stabilization, encoded five frames, and verified the final
movie. Sprocket detection took 3.6 seconds for the batch.

An isolated Reel_46335 4598–4602 run retained frame 4600's P07 ambiguity,
interpolated it between trustworthy registrations, recovered frame 4601 through
the physical-pair stage, encoded five frames, and verified the final movie.
Sprocket detection took 3.8 seconds for the batch.

An isolated Reel_46335 40–44 run exercised the P06 branch: clean frames 40,
41, and 44 stayed primary; frames 42 and 43 were recovered by independently
measured partner evidence plus the frozen P06 template; P07 was not invoked.
The five-frame movie encoded and verified successfully.

Existing full-reel evidence projects the following cascade populations without
overwriting or re-encoding historical outputs:

| Reel | Primary | capture/full-hole recovery | later physical/P06 | P07 | unresolved |
|---|---:|---:|---:|---:|---:|
| Blue_Reel | 5,128 | 20 | not fully modeled | not fully modeled | 5 before P06/P07 |
| Reel_28486 | 5,124 | 1 | 0 | 0 | 0 |
| Reel_46335 | 3,321 | 1,096 | 24 + 75 P06 | 95 | 4 |

The Reel_46335 downstream counts are the previously approved measured cascade
model over the frozen 198-frame remainder. A new full-reel production
detection-only run was not performed in this integration pass.

## Performance and rejected optimizations

The exact cache remains byte-for-byte equivalent and previously measured
198/198 identical, with a 1.066× aggregate three-worker speedup and 30,329
duplicate candidate computations avoided. Coarse spacing 24, coarse spacing
32, and the uint8 histogram percentile replacement remain rejected and are not
present in production.

## Tests and operational concern

`research/run_python.sh -m unittest discover -s tests` passes 27 tests with one
historical proof-manifest fixture skipped because it is unavailable. The direct
oracle report is under the Git-ignored production P07 equivalence output.

The existing `/home/todd/telecine/.venv` contains a GUI OpenCV installation
that fails to load because `libGL.so.1` is unavailable. `pyproject.toml` now
requires `opencv-python-headless>=4.12,<5`, and legacy mode remains import-safe,
but that production environment must be refreshed and a full representative
detection-only cascade run completed before an archival reel is started.

## Recommendation

**B — integration is structurally sound but the production environment and
full-reel cascade validation must be completed before using it on an archival
production reel.**

The subsequent trusted-registration-only policy and targeted validation are
documented in `07_06_trusted_registration_only_targeted_validation.md`. That
revision supersedes this document's interpolation policy without changing the
frozen detector.
