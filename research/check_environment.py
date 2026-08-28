#!/usr/bin/env python3
"""Verify the isolated computer-vision research environment."""

from __future__ import annotations

import importlib
import json
import platform


MODULES = {
    "numpy": "numpy",
    "opencv": "cv2",
    "scipy": "scipy",
    "scikit-image": "skimage",
    "pandas": "pandas",
    "matplotlib": "matplotlib",
    "pyav": "av",
}


def main() -> None:
    versions = {"python": platform.python_version()}
    for label, module_name in MODULES.items():
        module = importlib.import_module(module_name)
        versions[label] = getattr(module, "__version__", "unknown")

    cv2 = importlib.import_module("cv2")
    image = importlib.import_module("numpy").zeros((64, 64), dtype="uint8")
    edges = cv2.Canny(image, 50, 100)
    if edges.shape != image.shape:
        raise RuntimeError("OpenCV smoke test returned an unexpected shape")
    versions["opencv_smoke_test"] = "passed"
    print(json.dumps(versions, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

