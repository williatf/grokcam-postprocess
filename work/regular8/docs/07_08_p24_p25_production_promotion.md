# P24/P25 production promotion

The local `physical-p07-v1` production policy is:

1. Existing primary anchor guides unchanged P15. Success registers primary X
   and measured P15 Y (`primary_p15`).
2. Missing/rejected primary P15 enters the frozen P24 capture gate. Admission
   requires all frozen capture-geometry predicates and frozen local
   physical-hole corroboration.
3. An admitted capture guide positions unchanged P15. Success registers frozen
   P25-calibrated capture X and measured P15 Y (`p24_capture_p15`).
4. Gate or P15 rejection invokes unchanged P07, followed by P22 only after P07
   acceptance (`p07_p22`). P07 rejection preserves and excludes the frame.

Frozen production constants are recorded in every new manifest, including the
P24/P25 research hashes. No value is recalibrated per reel. Capture Y guides
P15 only; physical-hole evidence corroborates only. There is no temporal,
neighboring-frame, or historical registration path.

Every frame records `registration_x_source`, `registration_y_source`, primary
P15 diagnostics, P24 input geometry and individual predicates, physical-hole
diagnostics, P24-guided P15 outcome, and unchanged P07/P22 diagnostics when
invoked. Segment and run summaries contain separate counters and timings.

After a reel, create the predetermined retrospective-P07 sample without using
P07 outcomes to select frames:

```bash
/home/todd/telecine/.venv/bin/python research/generate_p24_transfer_sample.py \
  OUTPUT_DIR/processing_manifest.json \
  research/output/p24_p25_transfer/REEL_ID_validation_sample.json
```

The selector includes every tenth P24/P15 rescue plus three closest admitted
cases for each frozen gate boundary. It does not execute P07.
