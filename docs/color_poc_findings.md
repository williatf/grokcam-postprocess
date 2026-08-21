# GrokCam representative color POC findings

## Existing processing path

`grokcam_raw_production.py` asks Darktable CLI 5.4.x to export each DNG as a
16-bit TIFF from an empty, per-frame configuration directory. No XMP or style is
supplied, so Darktable chooses its default RAW history and interprets the
embedded DNG camera profile and as-shot white balance. The script then detects a
sprocket pair in the full 2028 × 1520 development, crops 1133 × 900 relative to
that anchor, rotates 180 degrees, mirrors horizontally, adds 1.04 contrast, and
converts to an 8-bit registered JPEG.

Color normalization is therefore downstream of Darktable and downstream of the
8-bit conversion. It measures the central x=15–92%, y=12–88% aperture, rejects
very dark/bright pixels, forces the median luminance toward the reel target
0.801 with ±0.65-stop bounds, applies a 25% gray-world channel correction, uses
a radius-four rolling median, and maps `x` to `x/(1+0.12x)` before JPEG export.

## DNG interpretation and likely cast causes

Checked frames 1, 1400, 2400, and 3400 are Raspberry Pi `PiDNG / PiCamera2`
DNG 1.4 files, 2028 × 1520, 12-bit, with BGGR CFA, black level 256, white level
4095, normal orientation, D65 ColorMatrix1, embedded profile name
`PiDNG / PiCamera2 Profile`, and constant AsShotNeutral
`0.3982635708 1 0.603646022`. Exposure changes from 1/293 s and ISO 100 in the
early experiment to 1/915 s and ISO 102 later. No embedded raster preview was
reported by ExifTool.

The constant capture white balance across materially different film scenes is
the main upstream risk. Darktable is not neutral pass-through: a fresh config
still applies its default RAW development plus the embedded matrix/as-shot
values. Downstream, gray-world assumptions can confuse genuine scene color with
a cast, and the inherited 0.801 target is too bright for many later scenes. The
baseline POC reached a worst picture-aperture highlight fraction of roughly
26%, versus roughly 6–10% for the alternatives. Processing after an 8-bit
registered JPEG also limits recovery of information already compressed or
clipped by Darktable/default conversion.

## POC design and recommendation

The sample is eight deterministic groups of four adjacent frames: 120–123,
1000–1003, 1400–1403, 1598–1601, 1798–1801, 2198–2201, 2798–2801, and
3398–3401. Reasons and source paths are in `poc-report.json`. These cover early
capture behavior, bright outdoor/landscape material, green and faded interiors,
skin, white clothing, saturated objects, deep shadows, strong highlights,
sprockets/edges, and later dark holiday footage.

Four approaches are shown: exact current-production baseline, one conservative
global correction, per-frame film-aware correction (included to expose pumping
risk), and one correction shared by every four-frame scene group. All POC color
statistics use the registered picture inset x=10–90%, y=10–90%; sprockets,
edges, black gate, and adjacent frames remain visible in the loose review crop
but do not affect color estimation.

The scene-aware result is the recommended direction for review. It removes much
of the green bias while preserving one parameter set across adjacent frames.
It should not yet be promoted to production: four-frame groups are deliberately
short, scene boundaries need a deterministic detector plus handles, and a
future version should keep color work in 16-bit/linear or scene-referred data
until final output rather than normalizing an 8-bit JPEG. The global correction
is the safest fallback. The per-frame result is useful diagnostically but is not
recommended because longer runs may pump even where this sample looks stable.

Review materials are under
`/mnt/GrokCam/projects/RAW_Test/outputs/color-poc`; start with `index.md`.
