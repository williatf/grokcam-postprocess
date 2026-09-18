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

## UI Independence and Future GUI

GrokCam post-processing is currently operated primarily through the CLI, but
a graphical user interface is planned.

Treat the CLI as a client of the processing system, not as the processing
architecture itself.

When adding or modifying production functionality:

- Keep core processing logic independent of `argparse`, terminal input, and
  other CLI-specific behavior.
- Represent processing options and film-format configuration as structured
  program data rather than CLI-only state.
- Core processing code should report failures through structured results or
  exceptions rather than terminating the process with `sys.exit()`.
- Processing progress and status should be capable of being exposed
  programmatically rather than existing only as console output.
- Registration diagnostics should remain available as structured data,
  including where applicable:
  - sprocket detections
  - trusted/untrusted status
  - interpolated/fallback positions
  - registration coordinates
  - crop coordinates
  - stabilization measurements
  - diagnostic artifacts
- Film-format selection and format-specific registration behavior belong
  below the user-interface layer.
- Core processing must not require an interactive terminal.
- Prefer a shared processing API that can ultimately support:

      CLI ─┐
           ├─> Processing API ─> Processing Pipeline
      GUI ─┘

Do not implement GUI functionality unless the task specifically calls for it.
These requirements are architectural constraints intended to keep future GUI
integration straightforward.