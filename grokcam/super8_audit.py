"""Shared production RAW development and registration audit for Super 8."""

from __future__ import annotations

import concurrent.futures
import json
import shutil
import statistics
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .config import ProductionCalibration
from .encoding import concatenate_segments, encode_segment, file_sha256, verify_video
from .image_processing import registered_frame
from .models import CropGeometry
from .normalization import normalize_frames
from .raw_development import DarktableMatchedDeveloper
from .super8_registration import Super8Registration


KNOWN_DIFFICULT = {2626, 2643, 2850, 3059, 3060, 3433, 3448}
DIRECT_PROVENANCE = {"PRIMARY", "SECONDARY", "FALLBACK", "TEMPLATE_FALLBACK"}
PROGRESS_INTERVAL = 25


def _frame_number(path: Path) -> int:
    return int(path.stem.rsplit("_", 1)[-1])


def _stats(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None, "median": None,
                "mad": None, "p05": None, "p95": None}
    median = statistics.median(values)
    array = np.asarray(values, dtype=float)
    return {"count": len(values), "min": float(min(values)), "max": float(max(values)),
            "mean": float(statistics.mean(values)), "median": float(median),
            "mad": float(statistics.median(abs(value - median) for value in values)),
            "p05": float(np.percentile(array, 5)), "p95": float(np.percentile(array, 95))}


def _record_from_result(dng: Path, result, image_size: list[int]) -> dict:
    diagnostics = result.diagnostics
    p06 = diagnostics.get("p06", {})
    return {
        "frame": _frame_number(dng), "source": str(dng.resolve()), "source_name": dng.name,
        "image_size": image_size, "film_format": "super8",
        "detector_provenance": result.provenance, "fallback_level": result.fallback_level,
        "accepted": result.accepted, "raw_candidate_y": result.raw_candidate_y,
        "raw_candidate_x": result.anchor_x, "registration_y": result.registration_y,
        "final_registration_y": result.registration_y, "confidence": result.score,
        "score": result.score, "rejection_reasons": list(result.rejection_reasons),
        "interpolation_status": "direct" if result.accepted else "pending",
        "template_version": ("super8-template-bank-v1" if result.provenance == "TEMPLATE_FALLBACK" else None),
        "p06_rejection_reasons": p06.get("rejection_reasons", []),
        "p06": p06, "diagnostics": diagnostics,
    }


def _worker(task: tuple[Path, Path, ProductionCalibration]) -> dict:
    dng, match_report, calibration = task
    developer = DarktableMatchedDeveloper(match_report)
    detector = Super8Registration(calibration.super8_registration)
    with tempfile.TemporaryDirectory(prefix=f"grokcam-super8-production-{_frame_number(dng)}-") as temp:
        tiff = Path(temp) / "developed.tiff"
        developer.develop(dng, tiff)
        with Image.open(tiff) as image:
            result = detector.register(image)
            size = [image.width, image.height]
    return _record_from_result(dng, result, size)


def _is_direct(record: dict | None) -> bool:
    return bool(record and record.get("accepted") and
                record.get("detector_provenance") in DIRECT_PROVENANCE and
                record.get("final_registration_y") is not None)


def _resolve_records(records: list[dict], left: dict | None = None,
                     right: dict | None = None, defer_last: bool = False) -> None:
    """Resolve only immediately bracketed failures; never smooth trusted values."""
    for index, record in enumerate(records):
        if record.get("accepted"):
            continue
        previous = records[index - 1] if index else left
        following = records[index + 1] if index + 1 < len(records) else right
        bracketed = (_is_direct(previous) and _is_direct(following) and
                     previous["frame"] + 1 == record["frame"] == following["frame"] - 1)
        if bracketed:
            fraction = ((record["frame"] - previous["frame"]) /
                        (following["frame"] - previous["frame"]))
            value = previous["final_registration_y"] + fraction * (
                following["final_registration_y"] - previous["final_registration_y"])
            previous_x = previous.get("raw_candidate_x")
            following_x = following.get("raw_candidate_x")
            candidate_x = ((previous_x + following_x) / 2.0
                           if previous_x is not None and following_x is not None
                           else (previous_x if previous_x is not None else following_x))
            record.update({"final_registration_y": float(value), "registration_y": float(value),
                           "raw_candidate_x": candidate_x,
                           "detector_provenance": "INTERPOLATED", "fallback_level": "INTERPOLATED",
                           "interpolation_status": "INTERPOLATED", "accepted": True,
                           "temporal_information_required": True})
        elif defer_last and index == len(records) - 1 and right is None:
            continue
        else:
            record.update({"detector_provenance": "UNTRUSTED", "fallback_level": "UNTRUSTED",
                           "interpolation_status": "UNTRUSTED", "temporal_information_required": False,
                           "output_disposition": "excluded"})


def _interpolate(records: list[dict]) -> None:
    _resolve_records(records)


def _overlay(image: Image.Image, record: dict, path: Path, crop: dict | None = None,
             orientation: str = "native_capture", vertical_flip: bool = False) -> None:
    rendered = np.asarray(image.convert("RGB"))[:, :, ::-1].copy()
    y = record.get("final_registration_y")
    x = record.get("raw_candidate_x") or rendered.shape[1] / 2
    color = (0, 220, 0) if record["detector_provenance"] in {"PRIMARY", "SECONDARY", "FALLBACK", "TEMPLATE_FALLBACK"} else (0, 0, 255)
    if y is not None:
        cv2.line(rendered, (0, int(round(y))), (rendered.shape[1] - 1, int(round(y))), color, 3)
        cv2.drawMarker(rendered, (int(round(x)), int(round(y))), color, cv2.MARKER_CROSS, 36, 3)
    if crop is not None and y is not None:
        left = int(round(x + crop["x_offset"]))
        top = int(round(y + crop["y_offset"]))
        right, bottom = left + crop["width"], top + crop["height"]
        cv2.rectangle(rendered, (left, top), (right, bottom), (255, 0, 255), 4)
    if orientation == "final_viewing" and vertical_flip:
        rendered = cv2.flip(rendered, 0)
    displayed_y = (rendered.shape[0] - 1 - y) if y is not None and orientation == "final_viewing" and vertical_flip else y
    label = (f"frame={record['frame']} {record['detector_provenance']} "
             f"native_y={y} displayed_y={displayed_y} "
             f"orientation={orientation}")
    cv2.rectangle(rendered, (0, 0), (min(rendered.shape[1], 1500), 48), (0, 0, 0), -1)
    cv2.putText(rendered, label, (12, 32), cv2.FONT_HERSHEY_SIMPLEX, .65, (255, 255, 255), 2, cv2.LINE_AA)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), rendered)


def render_diagnostics(records: list[dict], calibration: ProductionCalibration,
                       output_dir: Path, diagnostic_frames: set[int] | None = None,
                       crop: dict | None = None) -> list[str]:
    diagnostic_frames = diagnostic_frames or set()
    output_dir.mkdir(parents=True, exist_ok=True)
    selected = [record for record in records if record["detector_provenance"] == "TEMPLATE_FALLBACK"
                or record["detector_provenance"] in {"INTERPOLATED", "UNTRUSTED"}
                or record["frame"] in diagnostic_frames]
    developer = DarktableMatchedDeveloper(calibration.match.report.expanduser().resolve())
    paths = []
    with tempfile.TemporaryDirectory(prefix="grokcam-super8-production-diagnostics-") as temp:
        tiff = Path(temp) / "developed.tiff"
        for record in selected:
            developer.develop(Path(record["source"]), tiff)
            with Image.open(tiff) as image:
                stem = f"frame_{record['frame']:06d}_{record['detector_provenance'].lower()}"
                native_path = output_dir / f"{stem}_native.png"
                final_path = output_dir / f"{stem}_final.png"
                _overlay(image, record, native_path, crop,
                         orientation="native_capture", vertical_flip=False)
                _overlay(image, record, final_path, crop,
                         orientation="final_viewing", vertical_flip=calibration.vertical_flip)
                paths.extend([str(native_path), str(final_path)])
    return paths


def _json_calibration(calibration: ProductionCalibration) -> dict:
    super8 = calibration.super8_registration.to_dict()
    return {
        "film_format": calibration.film_format,
        "vertical_flip": calibration.vertical_flip,
        "contrast": calibration.contrast,
        "super8_registration": super8,
        "match_report": str(calibration.match.report),
    }


def _write_processing_manifest(output_dir: Path, dngs: list[Path],
                               calibration: ProductionCalibration,
                               summary: dict, options=None,
                               frame_records: list[dict] | None = None) -> None:
    manifest = {
        "pipeline": "grokcam_postprocess",
        "film_format": "super8",
        "source_policy": "read_only",
        "source_directory": str(dngs[0].parent.resolve()),
        "frame_range": [int(dngs[0].stem.rsplit("_", 1)[-1]),
                        int(dngs[-1].stem.rsplit("_", 1)[-1])],
        "valid_transport_frame_range": [1, 5638],
        "registration_coordinate_system": "developed_frame_pixels_native_capture_orientation",
        "render_orientation": {"vertical_flip": calibration.vertical_flip, "horizontal_flip": False},
        "calibration": _json_calibration(calibration),
        "template_bank_sha256": (file_sha256(calibration.super8_registration.template_bank)
                                  if calibration.super8_registration.template_bank.is_file() else None),
        "registration_audit": str((output_dir / "registration_audit.json").resolve()),
        "summary": summary,
    }
    if frame_records is not None:
        manifest["frame_records"] = frame_records
    if options is not None:
        manifest["fps"] = options.fps
        manifest["batch_frames"] = options.batch_frames
    (output_dir / "processing_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _render_super8_records(dngs: list[Path], records: list[dict], output_dir: Path,
                          calibration: ProductionCalibration, options) -> dict:
    crop = calibration.super8_registration
    if not crop.crop_validated:
        raise RuntimeError("Super 8 rendering requires crop_validated=true")
    output_dir.mkdir(parents=True, exist_ok=True)
    segments_dir = output_dir / "segments"
    staging = output_dir / ".super8-staging"
    segments_dir.mkdir(exist_ok=True)
    staging.mkdir(exist_ok=True)
    by_frame = {record["frame"]: record for record in records}
    included = [record for record in records if record.get("accepted") and
                record.get("output_disposition") != "excluded" and
                record.get("final_registration_y") is not None]
    target_luma = None
    encoded_before = 0
    segment_items = []
    source_index = {int(path.stem.rsplit("_", 1)[-1]): path for path in dngs}
    developer = DarktableMatchedDeveloper(calibration.match.report.expanduser().resolve())

    for batch_start in range(0, len(included), max(1, options.batch_frames)):
        batch = included[batch_start:batch_start + max(1, options.batch_frames)]
        first, last = batch[0]["frame"], batch[-1]["frame"]
        work = staging / f"segment_{first:06d}_{last:06d}"
        tiffs, registered, normalized = (work / name for name in ("tiff", "registered", "normalized"))
        for directory in (tiffs, registered, normalized):
            directory.mkdir(parents=True, exist_ok=True)
        registered_paths = []
        for record in batch:
            dng = source_index[record["frame"]]
            tiff = tiffs / f"{dng.stem}.tif"
            developer.develop(dng, tiff)
            with Image.open(tiff) as image:
                geometry = CropGeometry(
                    left=float(record["raw_candidate_x"] + crop.crop_x_offset),
                    top=float(record["final_registration_y"] + crop.crop_y_offset),
                    width=crop.crop_width, height=crop.crop_height)
                movie = registered_frame(image, geometry, calibration.contrast,
                                         vertical_flip=calibration.vertical_flip)
                path = registered / f"frame_{encoded_before + len(registered_paths) + 1:06d}.jpg"
                movie.save(path, quality=95, subsampling=0)
                registered_paths.append(path)
                record.update({
                    "crop_left": geometry.left, "crop_top": geometry.top,
                    "crop_width": geometry.width, "crop_height": geometry.height,
                    "crop_coordinate_system": "native_capture_orientation",
                    "vertical_flip_applied_after_crop": calibration.vertical_flip,
                    "horizontal_flip_applied": False,
                    "encoded_output_frame": encoded_before + len(registered_paths),
                    "output_disposition": "included",
                })
        corrections, target_luma = normalize_frames(registered_paths, normalized, target_luma)
        for record, correction in zip(batch, corrections):
            record["normalization"] = correction
        video = segments_dir / f"frames_{first:06d}_{last:06d}_{options.fps}fps.mp4"
        temporary = video.with_suffix(".tmp.mp4")
        encode_segment(options.ffmpeg, normalized, temporary, encoded_before + 1,
                       len(batch), options.fps)
        verification = verify_video(options.ffmpeg, options.ffprobe, temporary, len(batch))
        temporary.replace(video)
        segment_items.append({"first": first, "last": last, "frames": len(batch),
                              "source_frames": last - first + 1, "excluded": 0,
                              "video": str(video), "video_bytes": video.stat().st_size,
                              "video_sha256": file_sha256(video), "verified": True,
                              "verification": verification})
        encoded_before += len(batch)
        for directory in (tiffs, registered, normalized):
            for item in directory.iterdir():
                item.unlink()
            directory.rmdir()
        work.rmdir()

    concat = output_dir / "segments.txt"
    final = output_dir / f"Super8_REDO5_{dngs[0].stem.rsplit('_', 1)[-1]}_{dngs[-1].stem.rsplit('_', 1)[-1]}_{options.fps}fps.mp4"
    temporary = final.with_suffix(".tmp.mp4")
    concat.write_text("".join(f"file '{Path(item['video']).as_posix()}'\n" for item in segment_items), encoding="utf-8")
    from .encoding import concatenate_segments
    concatenate_segments(options.ffmpeg, concat, [Path(item["video"]) for item in segment_items], temporary)
    final_verification = verify_video(options.ffmpeg, options.ffprobe, temporary, encoded_before)
    temporary.replace(final)
    for item in segment_items:
        Path(item["video"]).unlink(missing_ok=True)
    concat.unlink(missing_ok=True)
    segments_dir.rmdir()
    staging.rmdir()
    summary = {
        "rendered_frames": encoded_before,
        "excluded_frames": len(records) - encoded_before,
        "output_video": str(final),
        "output_video_sha256": file_sha256(final),
        "output_video_verification": final_verification,
        "segments": segment_items,
    }
    return summary


def run_super8_production(dngs: list[Path], output_dir: Path,
                          calibration: ProductionCalibration, options) -> dict:
    # Backward-compatible entry point; normal production uses the single-pass
    # batch implementation below.
    return run_super8_batch_production(dngs, output_dir, calibration, options)


def _resolve_batch(records: list[dict], left: dict | None = None,
                   right: dict | None = None, defer_last: bool = False) -> None:
    """Resolve same-frame failures using only immediate direct neighbors."""
    for index, record in enumerate(records):
        if record.get("accepted"):
            continue
        previous = records[index - 1] if index else left
        following = records[index + 1] if index + 1 < len(records) else right
        if (_is_direct(previous) and _is_direct(following) and
                previous["frame"] + 1 == record["frame"] == following["frame"] - 1):
            fraction = ((record["frame"] - previous["frame"]) /
                        (following["frame"] - previous["frame"]))
            record["final_registration_y"] = float(
                previous["final_registration_y"] + fraction *
                (following["final_registration_y"] - previous["final_registration_y"]))
            previous_x = previous.get("raw_candidate_x")
            following_x = following.get("raw_candidate_x")
            record["raw_candidate_x"] = (previous_x + following_x) / 2.0 \
                if previous_x is not None and following_x is not None else (previous_x or following_x)
            record.update({"registration_y": record["final_registration_y"],
                           "detector_provenance": "INTERPOLATED",
                           "fallback_level": "INTERPOLATED",
                           "interpolation_status": "INTERPOLATED",
                           "accepted": True, "temporal_information_required": True})
        elif defer_last and index == len(records) - 1 and right is None:
            continue
        else:
            record.update({"detector_provenance": "UNTRUSTED", "fallback_level": "UNTRUSTED",
                           "interpolation_status": "UNTRUSTED",
                           "temporal_information_required": False,
                           "output_disposition": "excluded"})


def _cleanup_staging(work: Path) -> None:
    shutil.rmtree(work)


def _progress_checkpoint(done: int, total: int) -> bool:
    return done == 1 or done % PROGRESS_INTERVAL == 0 or done == total


def _free_gib(path: Path) -> float:
    """Report free space for the filesystem holding active intermediates."""
    return shutil.disk_usage(path).free / 2**30


def _batch_report(state: dict, segment: dict) -> dict:
    timings = state["timings"]
    timing_report = {
        "raw_development_worker_seconds": timings.get("raw_development_worker_seconds", 0.0),
        "registration_main_thread_seconds": timings.get("registration_main_thread_seconds", 0.0),
        "develop_register_wall_seconds": timings.get("develop_register_wall_seconds", 0.0),
        "crop_render_wall_seconds": timings.get("crop_render_wall_seconds", 0.0),
        "normalization_wall_seconds": timings.get("normalization_wall_seconds", 0.0),
        "encoding_verification_wall_seconds": timings.get("encoding_verification_wall_seconds", 0.0),
    }
    timing_report["active_pipeline_wall_seconds"] = (
        timing_report["develop_register_wall_seconds"] +
        timing_report["crop_render_wall_seconds"] +
        timing_report["normalization_wall_seconds"] +
        timing_report["encoding_verification_wall_seconds"]
    )
    counts = Counter(record.get("detector_provenance", "UNTRUSTED")
                     for record in state["records"])
    print(f"  Timing breakdown for {state['first']:06d}-{state['last']:06d}:", flush=True)
    for label, seconds in timing_report.items():
        print(f"    {label:36s} {seconds:8.2f}s", flush=True)
    print("    worker/main-thread values are accumulated; "
          "development and registration may overlap", flush=True)
    print("  Registration counts: " + ", ".join(
        f"{name}={counts[name]}" for name in
        ("PRIMARY", "SECONDARY", "FALLBACK", "TEMPLATE_FALLBACK", "INTERPOLATED", "UNTRUSTED")),
        flush=True)
    return {
        "first": state["first"], "last": state["last"],
        "source_frames": len(state["records"]),
        "rendered_frames": int(segment.get("frames", 0)),
        "excluded_frames": int(segment.get("excluded", 0)),
        "timing_seconds": timing_report,
        "registration_counts": {name: counts[name] for name in
                                 ("PRIMARY", "SECONDARY", "FALLBACK",
                                  "TEMPLATE_FALLBACK", "INTERPOLATED", "UNTRUSTED")},
    }


def _consecutive_exclusion_runs(records: list[dict]) -> list[dict]:
    runs = []
    for record in records:
        excluded = (record.get("detector_provenance") == "UNTRUSTED" or
                    record.get("output_disposition") == "excluded")
        if not excluded:
            continue
        frame = int(record["frame"])
        if not runs or frame != runs[-1]["last"] + 1:
            runs.append({"first": frame, "last": frame, "length": 1})
        else:
            runs[-1]["last"] = frame
            runs[-1]["length"] += 1
    return runs


def _write_records(output_dir: Path, records: list[dict]) -> None:
    with (output_dir / "registration_audit.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def _render_staged_batch(state: dict, output_dir: Path,
                         calibration: ProductionCalibration, options,
                         encoded_before: int, target_luma: float | None) -> tuple[dict, float | None, list[str]]:
    crop = calibration.super8_registration
    registered = state["work"] / "registered"
    normalized = state["work"] / "normalized"
    registered.mkdir()
    normalized.mkdir()
    registered_paths = []
    diagnostic_paths = []
    crop_started = time.perf_counter()
    for record in state["records"]:
        tiff = state["tiffs"] / f"{record['source_name'].rsplit('.', 1)[0]}.tif"
        if not record.get("accepted") or record.get("final_registration_y") is None:
            record["output_disposition"] = "excluded"
            continue
        with Image.open(tiff) as image:
            if (record["frame"] in KNOWN_DIFFICULT or
                    record["detector_provenance"] in {"TEMPLATE_FALLBACK", "INTERPOLATED", "UNTRUSTED"}):
                crop_overlay = {"x_offset": crop.crop_x_offset, "y_offset": crop.crop_y_offset,
                                "width": crop.crop_width, "height": crop.crop_height}
                stem = f"frame_{record['frame']:06d}_{record['detector_provenance'].lower()}"
                for orientation, flip in (("native_capture", False),
                                          ("final_viewing", calibration.vertical_flip)):
                    path = output_dir / "diagnostics" / f"{stem}_{orientation}.png"
                    _overlay(image, record, path, crop_overlay, orientation, flip)
                    diagnostic_paths.append(str(path))
            geometry = CropGeometry(
                left=float(record["raw_candidate_x"] + crop.crop_x_offset),
                top=float(record["final_registration_y"] + crop.crop_y_offset),
                width=crop.crop_width, height=crop.crop_height)
            movie = registered_frame(image, geometry, calibration.contrast,
                                     vertical_flip=calibration.vertical_flip)
            encoded_number = encoded_before + len(registered_paths) + 1
            path = registered / f"frame_{encoded_number:06d}.jpg"
            movie.save(path, quality=95, subsampling=0)
            registered_paths.append(path)
            record.update({"crop_left": geometry.left, "crop_top": geometry.top,
                           "crop_width": geometry.width, "crop_height": geometry.height,
                           "crop_coordinate_system": "native_capture_orientation",
                           "vertical_flip_applied_after_crop": calibration.vertical_flip,
                           "horizontal_flip_applied": False,
                           "encoded_output_frame": encoded_number,
                           "output_disposition": "included"})
    state["timings"]["crop_render_wall_seconds"] = time.perf_counter() - crop_started
    if not registered_paths:
        return ({"first": state["first"], "last": state["last"], "frames": 0,
                 "source_frames": len(state["records"]), "excluded": len(state["records"])},
                target_luma, diagnostic_paths)
    normalization_started = time.perf_counter()
    corrections, target_luma = normalize_frames(registered_paths, normalized, target_luma)
    state["timings"]["normalization_wall_seconds"] = time.perf_counter() - normalization_started
    included = [record for record in state["records"]
                if record.get("output_disposition") == "included"]
    for record, correction in zip(included, corrections):
        record["normalization"] = correction
    video = output_dir / "segments" / f"frames_{state['first']:06d}_{state['last']:06d}_{options.fps}fps.mp4"
    temporary = video.with_suffix(".tmp.mp4")
    encoding_started = time.perf_counter()
    encode_segment(options.ffmpeg, normalized, temporary, encoded_before + 1,
                   len(registered_paths), options.fps)
    verification = verify_video(options.ffmpeg, options.ffprobe, temporary, len(registered_paths))
    temporary.replace(video)
    state["timings"]["encoding_verification_wall_seconds"] = time.perf_counter() - encoding_started
    return ({"first": state["first"], "last": state["last"], "frames": len(registered_paths),
             "source_frames": len(state["records"]),
             "excluded": len(state["records"]) - len(registered_paths),
             "video": str(video), "video_bytes": video.stat().st_size,
             "video_sha256": file_sha256(video), "verified": True,
             "verification": verification}, target_luma, diagnostic_paths)


def _production_summary(records: list[dict], diagnostic_paths: list[str],
                        calibration: ProductionCalibration) -> dict:
    direct = [record for record in records if record["detector_provenance"] in DIRECT_PROVENANCE]
    positioned = [(record, float(record["final_registration_y"])) for record in records
                  if record.get("final_registration_y") is not None]
    y_values = [value for _record, value in positioned]
    deltas = [second_y - first_y for (first, first_y), (second, second_y)
              in zip(positioned, positioned[1:])
              if second["frame"] == first["frame"] + 1]
    counts = Counter(record["detector_provenance"] for record in records)
    p06_rejections = [{"frame": record["frame"], "reasons": record["p06_rejection_reasons"],
                       "best_score": record.get("p06", {}).get("best", {}).get("score"),
                       "margin": record.get("p06", {}).get("margin"),
                       "physical_candidates": len(record.get("p06", {}).get("physical_candidates", []))}
                      for record in records if record.get("p06_rejection_reasons")]
    return {
        "film_format": "super8", "first_frame": records[0]["frame"],
        "last_frame": records[-1]["frame"], "total_valid_input_frames": len(records),
        "provenance_counts": dict(counts), "direct_same_frame_count": len(direct),
        "direct_same_frame_percentage": len(direct) / len(records) * 100,
        "interpolated_count": counts["INTERPOLATED"], "untrusted_count": counts["UNTRUSTED"],
        "excluded_count": sum(record.get("output_disposition") == "excluded" for record in records),
        "p06_rejections": p06_rejections,
        "candidate_ambiguity_count": sum(
            "multiple_distinct_physical_candidates" in item["reasons"] for item in p06_rejections),
        "registration_coordinate_distribution": _stats(y_values),
        "frame_to_frame_delta_distribution": _stats(deltas),
        "obvious_discontinuities_over_100px": [
            second["frame"] for (first, first_y), (second, second_y) in zip(positioned, positioned[1:])
            if second["frame"] == first["frame"] + 1 and abs(second_y - first_y) > 100],
        "difficult_frame_audit": [
            {"frame": record["frame"], "provenance": record["detector_provenance"],
             "registration_y": record.get("final_registration_y"),
             "rejection_reasons": record.get("rejection_reasons", [])}
            for record in records if record["frame"] in KNOWN_DIFFICULT],
        "diagnostic_overlays": diagnostic_paths,
        "crop_calibration": {"validated": calibration.super8_registration.crop_validated,
                              "version": calibration.super8_registration.crop_version,
                              "coordinate_system": "native_capture_orientation",
                              "x_offset": calibration.super8_registration.crop_x_offset,
                              "y_offset": calibration.super8_registration.crop_y_offset,
                              "width": calibration.super8_registration.crop_width,
                              "height": calibration.super8_registration.crop_height},
        "orientation": {"vertical_flip": calibration.vertical_flip, "horizontal_flip": False},
        "capture_metadata_used_at_runtime": False,
        "source_policy": "mounted REDO5 source is read-only; valid transport frames only",
    }


def run_super8_batch_production(dngs: list[Path], output_dir: Path,
                                calibration: ProductionCalibration, options) -> dict:
    """Normal Super 8 production: one RAW development per DNG."""
    if not calibration.super8_registration.crop_validated:
        raise RuntimeError("Super 8 rendering requires crop_validated=true")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "segments").mkdir(exist_ok=True)
    staging = output_dir / ".super8-staging"
    staging.mkdir(exist_ok=True)
    developer = DarktableMatchedDeveloper(calibration.match.report.expanduser().resolve())
    registrar = Super8Registration(calibration.super8_registration)
    batch_size = max(1, options.batch_frames)
    batches = [dngs[start:start + batch_size] for start in range(0, len(dngs), batch_size)]
    print(f"Remaining plan: {len(dngs)} frames in {len(batches)} batches", flush=True)
    for planned in batches:
        print(f"  {_frame_number(planned[0]):06d}-{_frame_number(planned[-1]):06d} "
              f"({len(planned)} frames)", flush=True)
    previous = None
    target_luma = None
    encoded_before = 0
    segments, records, diagnostic_paths, batch_timings = [], [], [], []
    last_frame = _frame_number(dngs[-1])
    for batch_index, paths in enumerate(batches, start=1):
        first, last = _frame_number(paths[0]), _frame_number(paths[-1])
        work = staging / f"segment_{first:06d}_{last:06d}"
        tiffs = work / "tiff"
        tiffs.mkdir(parents=True)
        batch_records = []
        timings = {}
        phase_started = time.perf_counter()
        print(f"[{batch_index}/{len(batches)}] developing and registering "
              f"{len(paths)} frames ({first:06d}-{last:06d})", flush=True)

        progress_lock = threading.Lock()
        developed_count = 0

        def develop(path: Path) -> tuple[Path, float]:
            tiff = tiffs / path.name.replace(".dng", ".tif")
            started = time.perf_counter()
            developer.develop(path, tiff)
            return tiff, time.perf_counter() - started

        def report_development(future) -> None:
            nonlocal developed_count
            try:
                _tiff, worker_seconds = future.result()
            except BaseException:
                return
            with progress_lock:
                developed_count += 1
                timings["raw_development_worker_seconds"] = (
                    timings.get("raw_development_worker_seconds", 0.0) + worker_seconds)
                if _progress_checkpoint(developed_count, len(paths)):
                    print(f"  developed {developed_count}/{len(paths)}; "
                          f"free {_free_gib(output_dir):.1f} GiB", flush=True)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, options.jobs)) as pool:
            developed = {}
            for path in paths:
                future = pool.submit(develop, path)
                future.add_done_callback(report_development)
                developed[path] = future
            registered_count = 0
            for dng in paths:
                tiff, _worker_seconds = developed[dng].result()
                register_started = time.perf_counter()
                with Image.open(tiff) as image:
                    result = registrar.register(image)
                    batch_records.append(_record_from_result(dng, result, [image.width, image.height]))
                timings["registration_main_thread_seconds"] = (
                    timings.get("registration_main_thread_seconds", 0.0) +
                    time.perf_counter() - register_started)
                registered_count += 1
                if _progress_checkpoint(registered_count, len(paths)):
                    print(f"  registered {registered_count}/{len(paths)}", flush=True)
            timings["develop_register_wall_seconds"] = time.perf_counter() - phase_started
        current = {"first": first, "last": last, "records": batch_records,
                   "tiffs": tiffs, "work": work, "timings": timings}
        if previous is not None:
            _resolve_batch(previous["records"], right=batch_records[0])
            _resolve_batch(batch_records, left=previous["records"][-1], defer_last=True)
            segment, target_luma, paths_written = _render_staged_batch(
                previous, output_dir, calibration, options, encoded_before, target_luma)
            segments.append(segment)
            encoded_before += segment["frames"]
            records.extend(previous["records"])
            diagnostic_paths.extend(paths_written)
            batch_timings.append(_batch_report(previous, segment))
            _cleanup_staging(previous["work"])
            print(f"  verified and cleaned segment {previous['first']:06d}-{previous['last']:06d}; "
                  f"free {_free_gib(output_dir):.1f} GiB", flush=True)
        previous = current
        print(f"super8 production {last:06d}/{last_frame:06d}", flush=True)
    if previous is not None:
        _resolve_batch(previous["records"])
        segment, target_luma, paths_written = _render_staged_batch(
            previous, output_dir, calibration, options, encoded_before, target_luma)
        segments.append(segment)
        encoded_before += segment["frames"]
        records.extend(previous["records"])
        diagnostic_paths.extend(paths_written)
        batch_timings.append(_batch_report(previous, segment))
        _cleanup_staging(previous["work"])
        print(f"  verified and cleaned segment {previous['first']:06d}-{previous['last']:06d}; "
              f"free {_free_gib(output_dir):.1f} GiB", flush=True)

    concat = output_dir / "segments.txt"
    final = output_dir / f"Super8_REDO5_{dngs[0].stem.rsplit('_', 1)[-1]}_{dngs[-1].stem.rsplit('_', 1)[-1]}_{options.fps}fps.mp4"
    temporary = final.with_suffix(".tmp.mp4")
    concatenate_segments(options.ffmpeg, concat, [Path(item["video"]) for item in segments], temporary)
    final_verification = verify_video(options.ffmpeg, options.ffprobe, temporary, encoded_before)
    temporary.replace(final)
    for item in segments:
        Path(item["video"]).unlink(missing_ok=True)
    concat.unlink(missing_ok=True)
    (output_dir / "segments").rmdir()
    staging.rmdir()
    records.sort(key=lambda record: record["frame"])
    summary = _production_summary(records, diagnostic_paths, calibration)
    summary["batch_timings"] = batch_timings
    summary["consecutive_exclusion_untrusted_runs"] = _consecutive_exclusion_runs(records)
    summary["render"] = {"rendered_frames": encoded_before,
                          "excluded_frames": len(records) - encoded_before,
                          "output_video": str(final),
                          "output_video_sha256": file_sha256(final),
                          "output_video_verification": final_verification,
                          "segments": segments}
    _write_records(output_dir, records)
    (output_dir / "registration_audit.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_processing_manifest(output_dir, dngs, calibration, summary, options, records)
    return summary


def run_registration_audit(dngs: list[Path], output_dir: Path,
                           calibration: ProductionCalibration, jobs: int = 3,
                           diagnostic_frames: set[int] | None = None,
                           crop: dict | None = None) -> dict:
    if not dngs:
        raise ValueError("Super 8 registration audit requires at least one DNG")
    match_report = calibration.match.report.expanduser().resolve()
    tasks = [(path, match_report, calibration) for path in dngs]
    records = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = [pool.submit(_worker, task) for task in tasks]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            records.append(future.result())
            if index == 1 or index % 50 == 0 or index == len(futures):
                print(f"super8 registration {index}/{len(futures)}", flush=True)
    records.sort(key=lambda record: record["frame"])
    _interpolate(records)
    if crop is None and calibration.super8_registration.crop_validated:
        crop = {
            "x_offset": calibration.super8_registration.crop_x_offset,
            "y_offset": calibration.super8_registration.crop_y_offset,
            "width": calibration.super8_registration.crop_width,
            "height": calibration.super8_registration.crop_height,
            "coordinate_system": "native_capture_orientation",
            "vertical_flip_applied_after_crop": calibration.vertical_flip,
        }
    diagnostic_paths = render_diagnostics(records, calibration, output_dir / "diagnostics",
                                          diagnostic_frames or KNOWN_DIFFICULT, crop)
    direct = [record for record in records if record["detector_provenance"] in
              {"PRIMARY", "SECONDARY", "FALLBACK", "TEMPLATE_FALLBACK"}]
    positioned = [(record, float(record["final_registration_y"])) for record in records
                  if record.get("final_registration_y") is not None]
    y_values = [value for _record, value in positioned]
    deltas = [second_y - first_y for (first, first_y), (second, second_y) in zip(positioned, positioned[1:])
              if second["frame"] == first["frame"] + 1]
    provenance_counts = Counter(record["detector_provenance"] for record in records)
    p06_rejections = [{"frame": record["frame"], "reasons": record["p06_rejection_reasons"],
                       "best_score": record.get("p06", {}).get("best", {}).get("score"),
                       "margin": record.get("p06", {}).get("margin"),
                       "physical_candidates": len(record.get("p06", {}).get("physical_candidates", []))}
                      for record in records if record.get("p06_rejection_reasons")]
    summary = {
        "film_format": "super8", "first_frame": records[0]["frame"], "last_frame": records[-1]["frame"],
        "total_valid_input_frames": len(records), "provenance_counts": dict(provenance_counts),
        "direct_same_frame_count": len(direct), "direct_same_frame_percentage": len(direct) / len(records) * 100,
        "interpolated_count": provenance_counts["INTERPOLATED"], "untrusted_count": provenance_counts["UNTRUSTED"],
        "excluded_count": sum(record.get("output_disposition") == "excluded" for record in records),
        "p06_rejections": p06_rejections,
        "candidate_ambiguity_count": sum("multiple_distinct_physical_candidates" in item["reasons"] for item in p06_rejections),
        "registration_coordinate_distribution": _stats(y_values),
        "frame_to_frame_delta_distribution": _stats(deltas),
        "obvious_discontinuities_over_100px": [second["frame"] for (first, first_y), (second, second_y) in zip(positioned, positioned[1:])
                                                if second["frame"] == first["frame"] + 1 and abs(second_y - first_y) > 100],
        "diagnostic_overlays": diagnostic_paths,
        "crop_calibration": {"validated": crop is not None, "geometry": crop,
                              "movie_rendering": "enabled only when crop calibration is supplied"},
        "capture_metadata_used_at_runtime": False,
        "source_policy": "mounted REDO5 source is read-only; valid transport frames only",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "registration_audit.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    (output_dir / "registration_audit.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_processing_manifest(output_dir, dngs, calibration, summary)
    return summary
