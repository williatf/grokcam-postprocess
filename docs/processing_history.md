# Processing history

Experimental Darktable, rawpy, white-reference, color, and registration work
established the desired rendering and film geometry. The implementation named
`grokcam_raw_production_darktable_matched` became the golden reference after it
produced the approved result.

That wrapper was found to replace the RAW developer inside a separate timed
runner while relying on the runner for batching, detection, registration,
normalization, manifests, encoding, verification, and resume behavior. The
first consolidation made this composition explicit. The second extracted the
complete execution path into cohesive `grokcam/` modules, leaving the historical
entry points as non-load-bearing shims.

The selected detector uses two adjacent bright sprocket bands as the physical
film reference, validates their pitch and horizontal agreement, and interpolates
missing or rejected batch measurements. The approved loose crop remains anchored
at `(+159, -413)` with size `1133 × 900`, using fractional bicubic sampling,
rotation, and mirroring. Restrained reel normalization remains separate from RAW
development so genuine scene brightness and color are not erased.

Before cleanup, the learned Darktable match and its creation process were
audited. The adopted report was preserved byte-for-byte under `calibrations/`.
Permanent offline tools reproduced the sprocket-white correction, all 39 fitted
coefficients, and all 768 LUT entries exactly from the retained DNGs and fresh
Darktable references. Production reads this frozen artifact and never learns.

Finally, the obsolete production scripts and superseded learning POCs were
removed. The renderer/demosaic, normalization, and residual-cast investigations
remain under `research/` for future algorithm work. The canonical production
command is now exclusively `python -m grokcam.cli.process_reel`.
