# Processing history and retained lessons

The original production script used Darktable directly. Later rawpy trials were
faster but their default/adaptive rendering did not reproduce the approved
Darktable appearance. The retained solution fits a quadratic RGB transform plus
monotonic per-channel LUTs and a four-value white-balance correction to reference
Darktable renders. Production validates that model and applies it after AHD,
linear 16-bit sRGB rawpy development.

Sprocket registration remained preferable to generic visual stabilization
because the perforations are the physical film reference. The selected detector
looks for two adjacent high-luminance bands in the calibrated left region,
validates their size, pitch, and horizontal agreement, and uses their midpoint.
Batch-local median rejection removes implausible transport jumps; missing or
rejected measurements are linearly interpolated. There is no separate fast
detector in the golden matched execution path, so inventing one would change
behavior.

The successful loose crop is anchored directly to the sprocket midpoint at
`(+159, -413)` with size `1133 x 900`. Fractional bicubic sampling avoids
one-pixel stepping. Rotation and mirroring follow the crop. Restrained reel-wide
normalization was retained because stronger residual-cast and sprocket-white
experiments could erase legitimate scene color or react to non-picture content.

Long-reel safety developed around bounded batches, verified/resumable segments,
free-space gates, a per-output lock, atomic manifests, and full-decode checks.
Only reproducible intermediates are removed after verification.
