# GrokCam residual-cast POC findings

## Controlled base

All six frames use black-level-subtracted 12-bit BGGR data, bilinear demosaic,
the fixed sprocket correction `R×1.06984, G×1, B×1.09921`, embedded
`ColorMatrix1`, the established loose registered crop, floating-point processing,
and one common `x/(1+x)` plus sRGB display transform. No gray-world, per-frame
automatic white balance, luminance target, automatic contrast, or saturation is
used. Lossless float base arrays remain in the POC workspace.

Reference rectangles are deliberately hypotheses, not asserted ground truth.
The report records coordinates and limitations for papers, fabric, gray/dark
surfaces, skin, wood, green flooring, and saturated red/blue controls. Each
region includes linear and display RGB, luminance, xy chromaticity, clipping,
variation, and separate shadow/midtone/highlight measurements.

## Diagnosis

The residual is a mixture. A broad green component responds to fixed RGB
WB/tint changes, but the apparent correction required varies with density in the
most affected frames. Smooth, restrained per-channel tonal correction improves
their midtones more than a single gain set. This supports age-related dye
crossover/fading in addition to the objectively calibrated capture-system
white point. The tested near-identity 3×3 matrix adds little and is not justified
by the available non-colorimetric scene patches; it also creates unnecessary
risk to skin and saturated red/blue controls.

## Least-aggressive plausible candidates

- Frame 1400: `combined_strong`; severe yellow-green with tonal crossover.
- Frame 1598: `combined_mild`; preserve warm wood and indoor illumination.
- Frame 1798: `combined_strong`; WB alone leaves green midtones.
- Frame 2198: `combined_strong`; WB alone leaves crossover in shirt/trousers.
- Frame 2798: `combined_mild`; saturated controls argue against stronger work.
- Frame 3398: `wb_none`; plausible warm control and no correction is safest.

`combined_strong` is `wb_medium = [1.10, 0.88, 1.06]` followed by 75% of
the smooth curve. The full curve peaks in midtones at approximately
`[+13%, -11%, +10%]` for RGB and in shadows at `[+4%, -3%, +3%]`.
`combined_mild` is `wb_mild = [1.05, 0.94, 1.03]` followed by 55% of that
curve. Exact formulas and the tested matrix are in the JSON report.

Frames 1400, 1798, and 2198 can share `combined_strong` as a diagnostic model.
That does not establish one historically correct grade: papers and fabrics may
be aged or colored, indoor illumination may be warm, and there is no chart in
the photographed scenes. Frame 1598 needs a gentler grade, while 2798 and 3398
show that the strong grade should not be applied universally.

The verified review package currently resides in
`work/residual-cast-poc/review`. Copying it to the designated retained mount was
blocked by the environment's elevated-action usage quota; no workaround or
source mutation was attempted.
