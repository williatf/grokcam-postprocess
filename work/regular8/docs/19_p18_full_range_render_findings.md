# P18 full-range render — Reel_46335 frames 2000–2350

The exact frozen P18 estimator was run independently on all 351 frames and a
continuous 16 fps movie was rendered. All frames were included; the movie has
351 decoded frames and a duration of 21.9375 seconds.

## Frozen register

```text
trusted detector X and initial Y
  -> fixed-X rigid-pair Y search, ±12 px at 0.25 px
  -> sum of the four frozen P07 signed horizontal-edge responses
  -> refined anchor Y - 412.990739695 px = crop top
```

The crop relationship consists of the frozen P18 anchor-to-lower-top offset
`+260.539051765 px` and the frozen P15 lower-top-to-crop-top offset
`-673.529791460 px`. P15 measurements were used only to label/evaluate the 284
valid frames, never as estimator input. The 67 missing frames received no P15
value.

## P15-missing-frame audit

The movie is suitable for continuous visual review, but the estimator does not
demonstrate reliable register on the P15-missing population:

| Population | n | Median Y shift | Shifts with absolute value >=10 px | At ±12 px boundary |
|---|---:|---:|---:|---:|
| P15 valid | 284 | 0.00 | 1 | 0 |
| P15 missing | 67 | -11.50 | 53 | 15 |

The missing-frame horizontal-evidence score is also materially weaker: its
5th/25th/50th/75th/95th percentiles are 0.264/0.792/2.354/3.148/3.434, versus
3.220/3.890/3.969/3.993/4.000 on P15-valid frames.

The 15 missing frames at the -12 px search boundary are:

```text
2011 2025 2027 2050 2055 2092 2136 2154 2217 2221 2225 2307 2311 2340 2342
```

This is a systematic observability warning, not merely a few outliers. P15 is
missing precisely where the lower-top edge meter lacks valid evidence, and the
four-edge P18 objective commonly drives to the negative search limit there.
The continuous render therefore shows what the exact estimator does, but it
must not be interpreted as validation of those 67 registers.

## Artifacts

- `work/regular8/Reel_46335_p18_full_range_2000_2350_20260829/Reel_46335_002000_002350_p18_register_16fps.mp4`
- `work/regular8/Reel_46335_p18_full_range_2000_2350_20260829/measurements.csv`
- `work/regular8/Reel_46335_p18_full_range_2000_2350_20260829/summary.json`
- `research/p18_full_range_render.py`

Movie SHA-256:
`3e29631d3d85408a74c5e17fe26cfa1f97f44c0e06af196f20365cf202e1bea8`.

