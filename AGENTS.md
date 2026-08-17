# GrokCam Archival RAW Post-Processing

This workspace is the primary development and processing environment for the GrokCam 8 mm archival RAW post-processing project.

## Storage and retention

- Treat every DNG under `/mnt/GrokCam/projects/RAW_Test/raw` as immutable archival source material.
- Never edit, rename, move, or delete source DNG files.
- Never place temporary files in the archival source directory.
- Put disposable intermediate files under `/home/todd/telecine/grokcam-postprocess/work`.
- Put retained finished deliverables under `/mnt/GrokCam/projects/RAW_Test/outputs`.
- Avoid retaining intermediate files that can be recreated from the DNGs and manifest.
- Do not delete existing files unless the user explicitly approves the exact deletion.

## Processing practice

- Preserve processing settings and reproducibility information in manifests.
- Prefer processing in restartable batches.
- Check available disk space before large processing runs, on both the workspace filesystem and `/mnt/GrokCam` when relevant.
- Do not begin full-archive processing until a representative color-processing proof of concept has been reviewed and approved.
- Keep the archival RAW source read-only in all development, diagnostics, planning, and processing workflows.
