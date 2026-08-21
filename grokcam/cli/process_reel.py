"""Canonical GrokCam production command."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from grokcam.config import load_calibration
from grokcam.pipeline import run


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--match-report", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    known, remaining = parser.parse_known_args()
    calibration = load_calibration(known.calibration, known.match_report)
    if known.dry_run and "--plan-only" not in remaining:
        remaining.append("--plan-only")
    run(calibration, remaining)


if __name__ == "__main__":
    main()
