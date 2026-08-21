from __future__ import annotations

import argparse
import json
from pathlib import Path

from grokcam.regression import compare_images, compare_manifests


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare a production result with its golden reference")
    parser.add_argument("reference_manifest", type=Path)
    parser.add_argument("candidate_manifest", type=Path)
    parser.add_argument("--reference-image", type=Path)
    parser.add_argument("--candidate-image", type=Path)
    args = parser.parse_args()
    result = {"manifest": compare_manifests(args.reference_manifest, args.candidate_manifest)}
    if bool(args.reference_image) != bool(args.candidate_image):
        parser.error("both image arguments are required together")
    if args.reference_image:
        result["image"] = compare_images(args.reference_image, args.candidate_image)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
