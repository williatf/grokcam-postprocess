# GrokCam sprocket-hole white-reference findings

## Conclusion

The empty sprocket holes contain a valid, unclipped linear-RAW reference in the
tested later capture range. All 48 holes from 24 frames were usable. The holes
look white/clipped in Darktable JPEGs because of rendered tone mapping, but no
CFA population had any samples at or above the defined 98% near-clip threshold.

After subtracting black level 256 from the 12-bit white level 4095, median hole
responses relative to mean green were:

```text
R     0.372270
G1    0.999215
G2    1.000785
B     0.549178
```

The robust MAD-derived sigma of those ratios was 0.00263 for red, 0.00190 for
each green population, and 0.01200 for blue. The green populations agree to
about 0.16% around their mean. Across holes, median usable-range placement was
approximately 27.0% red, 72.5% green, and 39.5% blue. Thus the reference is
comfortably below clipping; green is already near the requested 75–85% target.

Conventional RGB gains, normalized to green, are:

```text
sprocket-derived: 2.68622 : 1 : 1.82090
embedded DNG:     2.51090 : 1 : 1.65660
```

Because `AsShotNeutral` is a camera-neutral response vector rather than a gain
vector, the correction to apply ahead of the existing D65 `ColorMatrix1`
interpretation is only `1.06984 : 1 : 1.09921`. `ColorMatrix1 × D65` reproduces
the recorded `AsShotNeutral` to rounding precision, confirming that the DNG
metadata describes a D65 interpretation rather than the measured LED/diffuser
illumination precisely.

## Sampling and masks

Frames 1400–1403, 1598–1601, 1798–1801, 2198–2201, 2798–2801, and 3398–3401
were measured. Geometry was detected from the RAW CFA itself. Each hole used a
200 × 140 rectangle centered well inside the detected hole; measurement cells
were further screened by robust central brightness. Rounded edges, film base,
writing, gate, adjacent frames, and picture content were excluded. Mask overlays
and per-hole RAW visualizations are retained for manual audit.

## Visual interpretation

The fixed calibration is visibly subtle: it adds roughly 7% red and 10% blue
relative to the embedded D65 interpretation. It reduces the capture-system
green bias, but strong green/yellow casts remain in affected film scenes. Those
remaining casts therefore cannot be attributed solely to the LED/diffuser/lens/
camera white point; film fading, scene illumination, and downstream rendering
remain significant.

No new calibration capture is required to recover a fixed reference from this
archive. For a future dedicated capture, use empty gate illumination with the
same LED, diffuser, lens, focus, aperture, sensor mode, gain, and DNG path, and
adjust exposure until the brightest CFA median is 75–85% of `(white-black)`;
record multiple frames and a dark frame without changing settings.

The Darktable-default column is retained as a reference. The embedded and fixed
columns use the same bilinear demosaic, matrix, exposure, and tone curve so only
the calibration differs. Darktable necessarily includes its own default RAW
history and is not used to derive the gains.
