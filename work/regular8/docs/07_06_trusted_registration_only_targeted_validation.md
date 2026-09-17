# P07 — Trusted-registration-only targeted production validation

## Policy revision

`physical-p07-v1` now accepts only same-frame anchors from the primary,
capture-seeded physical-pair, P06, or full-domain P07 stages. An unresolved
frame receives no anchor and is omitted from encoded output; its exact
already-developed full-resolution TIFF is retained under
`debug/excluded_frames/`. The `legacy` rollback mode keeps its historical
interpolation behavior. No P06/P07 detector constants or semantics changed.

The manifest identifies this as `failure_policy: exclude_unresolved`, records
capture ROI coordinates and rejected primary coordinates independently, maps
source frames to encoded frames, and summarizes consecutive exclusion runs.
Resume checks the mode, module hash, failure policy, and vertical stabilization
setting.

## Tests and frozen references

The production suite passes 30 tests with one historical missing-fixture skip.
The frozen P07 implementation/configuration/exact-cache hashes remain
`d78bc847...`, `334abf89...`, and `459093853...`. The production module hash for
this policy revision is
`31152f8bc0d3e91276a2ce15f5d518e2a066bd8ec46e707ded133b136355361d`.

## Reel_46335 frames 2000–2350

Residual vertical stabilization was disabled. All 351 source frames received
trusted same-frame anchors and all 351 were encoded: 259 primary, 36 physical
pairs, 29 P06, and 27 P07. There was no interpolation or exclusion. Frames
2117, 2170, 2199, and 2240 were accepted by full-domain P07. In every retained
record `crop_top == anchor_y - 413`, so frames 2199 and 2240 received no former
bottom-rescue residual movement. The verified H.264 movie is 1134×900, 16 fps,
351 frames, and 21.9375 seconds.

## Reel_46335 frames 2604–2610

Seven source frames produced four encoded frames. Frames 2604 and 2605 were
trusted P07 recoveries; 2609 and 2610 were trusted primary registrations.
Frames 2606–2608 remained rejected as `insufficient_joint_support`, received no
anchor or output-frame number, and were preserved as uncropped TIFFs. The
three-frame run represents 187.5 ms at 16 fps; processing resumed normally at
2609. Both source/count invariants hold.

## Stop gate

These targeted results support the new production mechanics, but the movies
still require human visual review before another full-reel validation. No
full-reel or archival processing was started.
