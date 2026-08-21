"""Compare learned values and validation metrics in two calibration artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--require-exact-fit", action="store_true")
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    result = {"fit": {}, "metrics": {}}
    exact = True
    for key in ("coefficients", "luts", "white_balance_correction"):
        left = np.asarray(reference["fit"][key], dtype=np.float64)
        right = np.asarray(candidate["fit"][key], dtype=np.float64)
        same_shape = left.shape == right.shape
        array_equal = same_shape and np.array_equal(left, right)
        exact &= array_equal
        result["fit"][key] = {"shape": list(left.shape), "same_shape": same_shape,
                              "array_equal": array_equal,
                              "maximum_absolute_difference": None if not same_shape else
                              float(np.max(np.abs(left - right)))}
    left_metrics = {int(row["frame"]): row for row in reference.get("metrics", [])}
    right_metrics = {int(row["frame"]): row for row in candidate.get("metrics", [])}
    common = sorted(set(left_metrics) & set(right_metrics))
    differences = [abs(left_metrics[n]["mean_absolute_rgb_error"] -
                       right_metrics[n]["mean_absolute_rgb_error"]) for n in common]
    result["metrics"] = {"compared_frames": len(common),
                         "maximum_mae_difference": max(differences, default=0.0)}
    print(json.dumps(result, indent=2))
    if args.require_exact_fit and not exact:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
