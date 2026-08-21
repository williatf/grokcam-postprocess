"""Canonical GrokCam production command."""

from __future__ import annotations

import argparse
import shutil
from dataclasses import replace
from pathlib import Path

from grokcam.batch import RunOptions
from grokcam.config import load_calibration
from grokcam.pipeline import ProductionPipeline


def parser() -> argparse.ArgumentParser:
    ffmpeg = shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg"
    ffprobe = shutil.which("ffprobe") or "/usr/local/bin/ffprobe"
    result = argparse.ArgumentParser(description="Disk-bounded, resumable GrokCam production processing")
    result.add_argument("raw_dir", type=Path)
    result.add_argument("output_dir", type=Path)
    result.add_argument("--first", type=int)
    result.add_argument("--last", type=int)
    result.add_argument("--batch-frames", type=int, default=960)
    result.add_argument("--fps", type=int, default=16)
    result.add_argument("--jobs", type=int, default=3)
    result.add_argument("--crop-preset", choices=["loose"], default="loose")
    result.add_argument("--ffmpeg", type=Path, default=Path(ffmpeg))
    result.add_argument("--ffprobe", type=Path, default=Path(ffprobe))
    result.add_argument("--minimum-free-gib", type=float, default=22.0)
    result.add_argument("--plan-only", action="store_true", help="show the restart plan without processing")
    result.add_argument("--dry-run", action="store_true", help="alias for --plan-only")
    result.add_argument("--calibration", type=Path, help="optional JSON calibration overrides")
    result.add_argument("--match-report", type=Path, help="override the learned color-match report")
    result.add_argument("--vertical-stabilization", action="store_true",
                        help="enable second-stage physical vertical registration")
    return result


def main() -> None:
    args = parser().parse_args()
    calibration = load_calibration(args.calibration, args.match_report)
    if args.vertical_stabilization:
        calibration = replace(
            calibration,
            vertical_stabilization=replace(calibration.vertical_stabilization, enabled=True),
        )
    options = RunOptions(
        raw_dir=args.raw_dir, output_dir=args.output_dir, first=args.first, last=args.last,
        batch_frames=args.batch_frames, fps=args.fps, jobs=args.jobs,
        ffmpeg=args.ffmpeg, ffprobe=args.ffprobe, minimum_free_gib=args.minimum_free_gib,
        plan_only=args.plan_only or args.dry_run,
    )
    ProductionPipeline(calibration).process_reel(options)


if __name__ == "__main__":
    main()
