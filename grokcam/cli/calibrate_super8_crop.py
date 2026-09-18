"""Develop/register a distributed REDO5 crop-calibration sample."""

from __future__ import annotations

import argparse
from pathlib import Path

from grokcam.config import load_calibration
from grokcam.super8_audit import run_registration_audit


DEFAULT_FRAMES = (1, 300, 600, 900, 1200, 1500, 1800, 2100, 2400,
                  2626, 2850, 3059, 3060, 3433, 3448, 4000, 4500, 5000,
                  5500, 5638)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--frames", help="comma-separated source frame numbers")
    parser.add_argument("--count", type=int,
                        help="number of evenly distributed valid REDO5 frames (1..5638)")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--crop", help="native-coordinate crop x_offset,y_offset,width,height")
    args = parser.parse_args()
    calibration = load_calibration(args.calibration)
    if calibration.film_format != "super8":
        raise SystemExit("crop calibration sample requires film_format=super8")
    source = args.raw_dir / "raw" if (args.raw_dir / "raw").is_dir() else args.raw_dir
    if args.frames and args.count:
        raise SystemExit("use only one of --frames or --count")
    if args.frames:
        numbers = tuple(int(value) for value in args.frames.split(","))
    elif args.count:
        if args.count < 2:
            raise SystemExit("--count must be at least 2")
        numbers = tuple(sorted({round(1 + index * (5638 - 1) / (args.count - 1))
                                for index in range(args.count)} |
                               {frame for frame in (2626, 2643, 2850, 3059, 3060, 3433, 3448)
                                if 1 <= frame <= 5638}))
    else:
        numbers = DEFAULT_FRAMES
    paths = [source / f"frame_{number:06d}.dng" for number in numbers]
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing sample DNGs: {missing[:3]}")
    crop = None
    if args.crop:
        x_offset, y_offset, width, height = (float(value) for value in args.crop.split(","))
        crop = {"x_offset": x_offset, "y_offset": y_offset,
                "width": int(width), "height": int(height),
                "coordinate_system": "native_capture_orientation",
                "vertical_flip_applied_after_crop": calibration.film_format == "super8" and calibration.vertical_flip}
    summary = run_registration_audit(paths, args.output_dir, calibration, args.jobs,
                                     diagnostic_frames=set(numbers), crop=crop)
    print(summary)


if __name__ == "__main__":
    main()
