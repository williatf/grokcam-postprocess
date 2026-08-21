#!/usr/bin/env python3
"""Assert required regression outcomes in an isolated POC diagnostics file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("diagnostics", type=Path)
    args = parser.parse_args()
    records = {int(item["frame"]): item for item in json.loads(args.diagnostics.read_text())}

    expected_sources = {
        3260: "residual",
        3451: "residual",
        3615: "bottom_rescue",
        3676: "bottom_rescue",
        3754: "residual",
        3846: "residual",
        3882: "expanded_residual",
    }
    for frame, source in expected_sources.items():
        record = records[frame]
        assert record["correction_source"] == source, (frame, record["correction_source"], source)
        assert record["post_correction_residual_y"] is not None, frame

    assert records[3260]["applied_correction_y"] > 10
    for frame in (3451, 3754, 3846):
        assert records[frame]["primary_accepted"] is False
        assert abs(records[frame]["post_correction_residual_y"]) < 2
    for frame in (3615, 3676):
        assert records[frame]["residual_measurement_valid"] is False
        assert abs(records[frame]["applied_correction_y"]) < 5
    assert records[3882]["primary_accepted"] is False
    assert records[3882]["residual_search_mode"] == "expanded"
    assert records[3882]["applied_correction_y"] > 75
    assert abs(records[3882]["post_correction_residual_y"]) < 2
    print("Vertical-stabilization POC regression cases passed")


if __name__ == "__main__":
    main()
