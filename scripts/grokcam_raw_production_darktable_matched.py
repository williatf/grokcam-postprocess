#!/usr/bin/env python3
"""Compatibility entry point; use ``python -m grokcam.cli.process_reel``."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grokcam.cli.process_reel import main


if __name__ == "__main__":
    main()
