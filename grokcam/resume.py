"""Pure resume-planning helpers."""

from pathlib import Path


def completed_frame_numbers(segments: list[dict]) -> set[int]:
    completed: set[int] = set()
    for item in segments:
        retained = (item.get("excluded_only_segment") is True or
                    (item.get("video") and Path(item["video"]).exists()))
        if item.get("verified") and retained:
            completed.update(range(int(item["first"]), int(item["last"]) + 1))
    return completed


def contiguous_batches(paths: list[Path], frame_number, size: int) -> list[list[Path]]:
    if size < 1:
        raise ValueError("batch size must be positive")
    groups: list[list[Path]] = []
    for path in paths:
        if not groups or frame_number(path) != frame_number(groups[-1][-1]) + 1:
            groups.append([path])
        else:
            groups[-1].append(path)
    return [group[i:i + size] for group in groups for i in range(0, len(group), size)]
