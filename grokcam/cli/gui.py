"""Machine-readable inspection and result-recovery commands for GrokCamGUI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from grokcam.api import DEFAULT_PROJECT_ROOT, inspect_source, list_calibrations, list_projects, read_result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="GrokCamGUI machine-readable API helpers")
    commands = result.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect-source", help="inspect a project or raw directory")
    inspect.add_argument("path", type=Path)
    calibrations = commands.add_parser("list-calibrations", help="list selectable production calibrations")
    calibrations.add_argument("search_paths", nargs="*", type=Path)
    projects = commands.add_parser("list-projects", help="list capture projects available for post-processing")
    projects.add_argument("project_root", nargs="?", type=Path, default=DEFAULT_PROJECT_ROOT)
    recovered = commands.add_parser("read-result", help="recover a published processing result")
    recovered.add_argument("output_path", type=Path)
    return result


def main() -> None:
    args = parser().parse_args()
    if args.command == "inspect-source":
        value = inspect_source(args.path).to_dict()
    elif args.command == "list-calibrations":
        value = {"calibrations": [item.to_dict() for item in
                                   list_calibrations(args.search_paths or None)]}
    elif args.command == "list-projects":
        value = {"projects": [item.to_dict() for item in list_projects(args.project_root)]}
    else:
        value = read_result(args.output_path).to_dict()
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
