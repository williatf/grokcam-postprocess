"""Disk-bounded, restartable production batch lifecycle."""

from __future__ import annotations

import concurrent.futures
import fcntl
import io
import json
import os
import shutil
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from PIL import Image

from .config import DEFAULT_STAGING_DIR, ProductionCalibration
from .encoding import (concatenate_segments, encode_segment, file_sha256,
                       verify_video)
from .image_processing import registered_frame
from .manifest import atomic_json, load_or_create, record_segment, utc_now
from .models import SprocketDetection
from .normalization import normalize_frames
from .precision_registration import register_precisely
from .raw_development import DarktableMatchedDeveloper
from .registration import crop_for_detection
from .resume import completed_frame_numbers, contiguous_batches
from .sprocket_detection import detect, validate_batch
from .timing import timed
from .vertical_stabilization import (measure_frame, measurement_details,
                                     resolve_batch, verify_post_crop)


@dataclass(frozen=True)
class RunOptions:
    raw_dir: Path
    output_dir: Path
    first: int | None = None
    last: int | None = None
    batch_frames: int = 960
    fps: int = 16
    jobs: int = 3
    ffmpeg: Path = Path("/usr/local/bin/ffmpeg")
    ffprobe: Path = Path("/usr/local/bin/ffprobe")
    minimum_free_gib: float = 22.0
    plan_only: bool = False
    registration_only: bool = False
    staging_dir: Path | None = None


def frame_number(path: Path) -> int:
    return int(path.stem.rsplit("_", 1)[-1])


def preserve_excluded_tiff(source: Path, output_dir: Path) -> Path:
    destination = output_dir / "debug" / "excluded_frames" / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def select_dngs(options: RunOptions) -> list[Path]:
    dngs = sorted(options.raw_dir.glob("frame_*.dng"), key=frame_number)
    if options.first is not None:
        dngs = [path for path in dngs if frame_number(path) >= options.first]
    if options.last is not None:
        dngs = [path for path in dngs if frame_number(path) <= options.last]
    if not dngs:
        raise SystemExit("No DNG frames selected")
    numbers = [frame_number(path) for path in dngs]
    if numbers != list(range(numbers[0], numbers[-1] + 1)):
        raise SystemExit("Selected DNG sequence is not contiguous")
    return dngs


def remaining_batches(dngs: list[Path], manifest: dict, batch_frames: int) -> tuple[list[dict], list[list[Path]]]:
    completed_segments = [item for item in manifest["segments"]
                          if item.get("verified") and
                          (item.get("excluded_only_segment") is True or
                           (item.get("video") and Path(item["video"]).exists()))]
    completed = completed_frame_numbers(completed_segments)
    remaining = [path for path in dngs if frame_number(path) not in completed]
    return completed_segments, contiguous_batches(remaining, frame_number, batch_frames)


def finalize_if_complete(options: RunOptions, dngs: list[Path], manifest: dict,
                         manifest_path: Path, segments_dir: Path) -> Path | None:
    numbers = [frame_number(path) for path in dngs]
    ordered = sorted([item for item in manifest["segments"]
                      if item.get("verified") and
                      (item.get("excluded_only_segment") is True or
                       (item.get("video") and Path(item["video"]).exists()))],
                     key=lambda item: item["first"])
    covered = [number for item in ordered for number in range(item["first"], item["last"] + 1)]
    if covered != numbers:
        return None
    segment_paths = [Path(item["video"]) for item in ordered if item.get("video")]
    if not segment_paths:
        raise RuntimeError("All selected source frames were excluded; no movie can be encoded")
    concat = options.output_dir / "segments.txt"
    final = options.output_dir / f"RAW_review_{numbers[0]:06d}_{numbers[-1]:06d}_{options.fps}fps.mp4"
    temporary = final.with_suffix(".tmp.mp4")
    finalization_started = time.perf_counter()
    concatenate_segments(options.ffmpeg, concat, segment_paths, temporary)
    encoded_frames = sum(int(item.get("frames", 0)) for item in ordered)
    verification = verify_video(options.ffmpeg, options.ffprobe, temporary, encoded_frames)
    os.replace(temporary, final)
    manifest["final"] = {"video": str(final), "video_bytes": final.stat().st_size,
                         "video_sha256": file_sha256(final), "verified": True,
                         "verification": verification, "completed": utc_now()}
    records = sorted([record for item in ordered for record in item.get("frame_records", [])],
                     key=lambda record: record["frame"])
    excluded = [record for record in records if record.get("output_disposition") == "excluded"]
    runs = []
    for record in excluded:
        if not runs or record["frame"] != runs[-1]["last"] + 1:
            runs.append({"first": record["frame"], "last": record["frame"],
                         "frames": [record["frame"]], "reasons": [record.get("exclusion_reason")],
                         "debug_artifacts": [record.get("debug_developed_image")]})
        else:
            run = runs[-1]; run["last"] = record["frame"]; run["frames"].append(record["frame"])
            run["reasons"].append(record.get("exclusion_reason")); run["debug_artifacts"].append(record.get("debug_developed_image"))
    by_frame = {record["frame"]: record for record in records}
    for run in runs:
        run["length"] = len(run["frames"]); run["duration_seconds"] = run["length"] / options.fps
        run["preceding_trusted_frame"] = max((n for n, r in by_frame.items() if n < run["first"] and r.get("output_disposition") == "included"), default=None)
        run["following_trusted_frame"] = min((n for n, r in by_frame.items() if n > run["last"] and r.get("output_disposition") == "included"), default=None)
    manifest["frame_mapping"] = {"source_frames": len(records), "included_frames": encoded_frames,
                                 "excluded_frames": len(excluded), "encoded_frames": encoded_frames,
                                 "invariants_valid": (len(records) == encoded_frames + len(excluded))}
    manifest["exclusion_runs"] = runs
    stage_totals: dict[str, float] = defaultdict(float)
    count_totals: dict[str, int] = defaultdict(int)
    for item in ordered:
        for key, value in item.get("stage_timings_seconds", {}).items():
            stage_totals[key] += float(value)
        for key, value in item.get("registration_counts", {}).items():
            count_totals[key] += int(value)
    stage_totals["final_concatenation_verification"] += time.perf_counter() - finalization_started
    manifest["processing_summary"] = {
        "total_input_frames": len(records),
        "p15_registrations": count_totals["p15_successes"],
        "p07_fallback_attempts": count_totals["p07_attempts"],
        "p07_fallback_successes": count_totals["p07_successes"],
        "p07_failures": count_totals["p07_failures"],
        "primary_p15_attempts": count_totals["primary_p15_attempts"],
        "primary_p15_successes": count_totals["primary_p15_successes"],
        "p24_branch_entries": count_totals["p24_attempts"],
        "p24_capture_pairs_available": count_totals["p24_capture_pairs_available"],
        "p24_capture_geometry_passes": count_totals["p24_capture_geometry_passes"],
        "p24_physical_corroborator_available": count_totals["p24_physical_corroborator_available"],
        "p24_corroborated_gate_passes": count_totals["p24_corroborated_gate_passes"],
        "p24_guided_p15_attempts": count_totals["p24_guided_p15_attempts"],
        "p24_guided_p15_successes": count_totals["p24_guided_p15_successes"],
        "p24_guided_p15_failures": count_totals["p24_guided_p15_failures"],
        "p22_invocations": count_totals["p22_invocations"],
        "registration_source_counts": {
            "primary_p15": count_totals["primary_p15_successes"],
            "p24_capture_p15": count_totals["p24_guided_p15_successes"],
            "p07_p22": count_totals["p07_successes"],
            "excluded": len(excluded)},
        "excluded_frames": len(excluded), "encoded_frames": encoded_frames,
        "consecutive_exclusion_runs": [{"first": run["first"], "last": run["last"],
                                         "length": run["length"]} for run in runs],
        "stage_total_seconds": dict(stage_totals),
        "registration_timing": {
            "p15": {"attempts": count_totals["p15_attempts"],
                    "successes": count_totals["p15_successes"],
                    "total_seconds": stage_totals["p15_measurement"],
                    "mean_seconds_per_attempt": (stage_totals["p15_measurement"] / count_totals["p15_attempts"]
                                                 if count_totals["p15_attempts"] else 0)},
            "p07": {"invocations": count_totals["p07_attempts"],
                    "total_seconds": stage_totals["p07_fallback_detection"],
                    "mean_seconds_per_invocation": (stage_totals["p07_fallback_detection"] / count_totals["p07_attempts"]
                                                    if count_totals["p07_attempts"] else 0)},
            "p22": {"invocations": count_totals["p22_invocations"],
                    "total_seconds": stage_totals["p22_refinement"],
                    "mean_seconds_per_invocation": (stage_totals["p22_refinement"] / count_totals["p22_invocations"]
                                                    if count_totals["p22_invocations"] else 0)},
            "primary_p15": {"calls": count_totals["primary_p15_attempts"],
                "total_seconds": stage_totals["primary_p15_measurement"],
                "mean_seconds_per_call": stage_totals["primary_p15_measurement"] / count_totals["primary_p15_attempts"] if count_totals["primary_p15_attempts"] else 0},
            "p24_capture_gate": {"calls": count_totals["p24_attempts"],
                "total_seconds": stage_totals["p24_capture_transform_gate"],
                "mean_seconds_per_call": stage_totals["p24_capture_transform_gate"] / count_totals["p24_attempts"] if count_totals["p24_attempts"] else 0},
            "p24_physical_corroboration": {"calls": count_totals["p24_capture_geometry_passes"],
                "total_seconds": stage_totals["p24_physical_hole_corroboration"],
                "mean_seconds_per_call": stage_totals["p24_physical_hole_corroboration"] / count_totals["p24_capture_geometry_passes"] if count_totals["p24_capture_geometry_passes"] else 0},
            "p24_guided_p15": {"calls": count_totals["p24_guided_p15_attempts"],
                "total_seconds": stage_totals["p24_guided_p15_measurement"],
                "mean_seconds_per_call": stage_totals["p24_guided_p15_measurement"] / count_totals["p24_guided_p15_attempts"] if count_totals["p24_guided_p15_attempts"] else 0},
        },
    }
    for path in segment_paths:
        path.unlink(missing_ok=True)
    concat.unlink(missing_ok=True)
    try:
        segments_dir.rmdir()
    except OSError:
        pass
    for item in manifest["segments"]:
        item["retained"] = False
    manifest["retention"] = {
        "retained": ["source DNG archive (in place)", "verified joined movie", "processing manifest"],
        "removed": ["16-bit TIFF cache", "Darktable databases", "registered JPEGs",
                    "normalized JPEGs", "verified component videos"],
    }
    atomic_json(manifest_path, manifest)
    return final


_STAGING_TRANSIENT_NAMES = {
    ".pipeline.lock", ".staging", ".super8-staging", "segments", "segments.txt",
}


def _validated_staging_root(options: RunOptions) -> Path:
    staging_root = (options.staging_dir if options.staging_dir is not None
                    else DEFAULT_STAGING_DIR).expanduser().resolve()
    if not staging_root.exists():
        raise RuntimeError(f"Configured staging directory does not exist: {staging_root}")
    if not staging_root.is_dir():
        raise RuntimeError(f"Configured staging path is not a directory: {staging_root}")
    if not os.access(staging_root, os.W_OK | os.X_OK):
        raise RuntimeError(f"Configured staging directory is not writable: {staging_root}")
    return staging_root


def _replace_path_prefix(value, source: str, destination: str):
    if isinstance(value, str):
        return value.replace(source, destination)
    if isinstance(value, list):
        return [_replace_path_prefix(item, source, destination) for item in value]
    if isinstance(value, dict):
        return {key: _replace_path_prefix(item, source, destination)
                for key, item in value.items()}
    return value


def _publish_staged_output(work_dir: Path, output_dir: Path,
                           staging_parent: Path) -> None:
    """Publish persistent results from a local run directory.

    The production stages intentionally continue to write their normal output
    names.  This boundary is the only place that knows a run was staged, so
    the normal no-staging path remains unchanged.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    for source in work_dir.iterdir():
        if source.name in _STAGING_TRANSIENT_NAMES:
            continue
        destination = output_dir / source.name
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(source, destination)

    source_prefix = str(work_dir)
    destination_prefix = str(output_dir)
    for relative in (path.relative_to(work_dir) for path in work_dir.rglob("*")):
        if relative.parts and relative.parts[0] in _STAGING_TRANSIENT_NAMES:
            continue
        destination = output_dir / relative
        if destination.suffix not in {".json", ".jsonl"} or not destination.is_file():
            continue
        if destination.suffix == ".json":
            data = json.loads(destination.read_text(encoding="utf-8"))
            data = _replace_path_prefix(data, source_prefix, destination_prefix)
            destination.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        else:
            text = destination.read_text(encoding="utf-8")
            destination.write_text(text.replace(source_prefix, destination_prefix),
                                   encoding="utf-8")

    manifest = output_dir / "processing_manifest.json"
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["staging_root"] = str(staging_parent)
        data["staging_directory"] = str(work_dir)
        data["output_directory"] = str(output_dir)
        data["staging"] = {
            "mode": "local_internal",
            "parent": str(staging_parent),
            "cleaned_after_success": True,
        }
        manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _write_staging_failure(output_dir: Path, work_dir: Path,
                           error: BaseException) -> None:
    """Leave a small NFS-visible pointer while preserving local failed work."""
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / ".staging-failure.json").write_text(
            json.dumps({
                "staging_root": str(work_dir.parent),
                "staging_directory": str(work_dir),
                "output_directory": str(output_dir),
                "error_type": type(error).__name__,
                "error": str(error),
                "preserved_for_diagnosis": True,
            }, indent=2) + "\n", encoding="utf-8")
    except OSError:
        print(f"Could not write staging failure marker in {output_dir}; "
              f"preserved local staging at {work_dir}", file=sys.stderr)


def _print_super8_completion(summary: dict) -> None:
    render = summary.get("render", {})
    print(f"Complete and verified: {render.get('output_video')}", flush=True)
    counts = summary.get("provenance_counts", {})
    print("Registration summary: " + ", ".join(
        f"{name}={counts.get(name, 0)}" for name in
        ("PRIMARY", "SECONDARY", "FALLBACK", "TEMPLATE_FALLBACK",
         "INTERPOLATED", "UNTRUSTED")), flush=True)
    print("Consecutive exclusion/untrusted runs: " +
          str(summary.get("consecutive_exclusion_untrusted_runs", [])), flush=True)


def run_reel(options: RunOptions, calibration: ProductionCalibration) -> None:
    """Run production, optionally isolating all transient output locally."""
    staging_parent = _validated_staging_root(options)
    output_dir = options.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    final_lock = (output_dir / ".pipeline.lock").open("a")
    try:
        try:
            fcntl.flock(final_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(f"Another pipeline process is already using {output_dir}")
        work_dir = Path(tempfile.mkdtemp(
            prefix=f"grokcam-{calibration.film_format}-", dir=staging_parent))
        succeeded = False
        working_options = replace(
            options, raw_dir=options.raw_dir, output_dir=work_dir, staging_dir=None)
        result = _run_reel_core(working_options, calibration)
        _publish_staged_output(work_dir, output_dir, staging_parent)
        succeeded = True
        published_result = _replace_path_prefix(result, str(work_dir), str(output_dir))
        if calibration.film_format == "super8" and not options.registration_only:
            _print_super8_completion(published_result)
        return published_result
    except BaseException as error:
        if "work_dir" in locals():
            _write_staging_failure(output_dir, work_dir, error)
            print(f"Preserving failed local staging at {work_dir}", file=sys.stderr)
        raise
    finally:
        if "work_dir" in locals() and succeeded and work_dir.exists():
            shutil.rmtree(work_dir)
        final_lock.close()


def _run_reel_core(options: RunOptions, calibration: ProductionCalibration) -> None:
    raw_dir = options.raw_dir.expanduser().resolve()
    if (raw_dir / "raw").is_dir():
        raw_dir = raw_dir / "raw"
    output_dir = options.output_dir.expanduser().resolve()
    options = RunOptions(**{**options.__dict__, "raw_dir": raw_dir, "output_dir": output_dir})
    if calibration.film_format == "super8":
        output_dir.mkdir(parents=True, exist_ok=True)
        if options.registration_only:
            dngs = select_dngs(options)
            free_gib = shutil.disk_usage(output_dir).free / 2**30
            if free_gib < options.minimum_free_gib:
                raise RuntimeError(f"Stopping safely: only {free_gib:.1f} GiB free")
            from .super8_audit import run_registration_audit
            return run_registration_audit(dngs, output_dir, calibration, options.jobs)
        if not calibration.super8_registration.crop_validated:
            raise RuntimeError(
                "Super 8 movie rendering requires an empirically validated crop calibration; "
                "run with --registration-only until calibration is reviewed"
            )
        dngs = select_dngs(options)
        free_gib = shutil.disk_usage(output_dir).free / 2**30
        if free_gib < options.minimum_free_gib:
            raise RuntimeError(f"Stopping safely: only {free_gib:.1f} GiB free")
        from .super8_audit import run_super8_batch_production
        return run_super8_batch_production(dngs, output_dir, calibration, options)
    if (calibration.sprocket_detector_mode == "physical-p07-v1" and
            calibration.vertical_stabilization.enabled):
        raise SystemExit("physical-p07-v1 uses frozen P15/P07/P22 registration and cannot enable residual vertical stabilization")
    output_dir.mkdir(parents=True, exist_ok=True)
    lock_handle = (output_dir / ".pipeline.lock").open("w")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(f"Another pipeline process is already using {output_dir}")
    lock_handle.write(f"pid={os.getpid()} started={utc_now()}\n")
    lock_handle.flush()

    staging = output_dir / ".staging"
    staging.mkdir(exist_ok=True)
    segments_dir = output_dir / "segments"
    segments_dir.mkdir(exist_ok=True)
    dngs = select_dngs(options)
    numbers = [frame_number(path) for path in dngs]
    free_gib = shutil.disk_usage(output_dir).free / 2**30
    if free_gib < options.minimum_free_gib:
        raise SystemExit(f"Only {free_gib:.1f} GiB free; need {options.minimum_free_gib:.1f} GiB")

    manifest_path = output_dir / "processing_manifest.json"
    manifest = load_or_create(manifest_path, raw_dir, numbers, options.fps,
                              options.batch_frames, calibration, options.ffmpeg)
    completed_segments, batches = remaining_batches(dngs, manifest, options.batch_frames)
    remaining_count = sum(len(batch) for batch in batches)
    if completed_segments:
        print("Preserving verified segments: " + ", ".join(
            f"{item['first']:06d}-{item['last']:06d}" for item in completed_segments), flush=True)
    print(f"Remaining plan: {remaining_count} frames in {len(batches)} batches", flush=True)
    for batch in batches:
        print(f"  {frame_number(batch[0]):06d}-{frame_number(batch[-1]):06d} ({len(batch)} frames)", flush=True)
    if options.plan_only:
        return

    developer = DarktableMatchedDeveloper(calibration.match.report.expanduser().resolve())
    capture_metadata = {}
    if calibration.sprocket_detector_mode == "physical-p07-v1":
        from .physical_sprocket import load_capture_metadata
        capture_metadata = load_capture_metadata(raw_dir)
    for batch_index, batch in enumerate(batches, start=1):
        timings: dict[str, float] = defaultdict(float)
        registration_counts: dict[str, int] = defaultdict(int)
        first, last = frame_number(batch[0]), frame_number(batch[-1])
        free_gib = shutil.disk_usage(output_dir).free / 2**30
        if free_gib < options.minimum_free_gib:
            raise RuntimeError(f"Stopping safely: only {free_gib:.1f} GiB free")
        work = staging / f"segment_{first:06d}_{last:06d}"
        if work.exists():
            shutil.rmtree(work)
        tiffs, registered, normalized = (work / name for name in ("tiff", "registered", "normalized"))
        for directory in (tiffs, registered, normalized):
            directory.mkdir(parents=True)
        started = time.time()
        print(f"[{batch_index}/{len(batches)}] developing {len(batch)} frames ({first:06d}-{last:06d})", flush=True)

        def convert(path: Path) -> Path:
            target = tiffs / f"{path.stem}.tif"
            developer.develop(path, target)
            return target

        with timed("raw_development", timings):
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, options.jobs)) as pool:
                futures = [pool.submit(convert, path) for path in batch]
                for done, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                    future.result()
                    if done == 1 or done % 25 == 0 or done == len(batch):
                        print(f"  developed {done}/{len(batch)}; free {shutil.disk_usage(output_dir).free/2**30:.1f} GiB", flush=True)

        with timed("primary_roi_detection", timings):
            measured = []
            for dng in batch:
                with Image.open(tiffs / f"{dng.stem}.tif") as image:
                    try:
                        measured.append(detect(image, calibration.detector))
                    except ValueError:
                        measured.append(None)
        physical_details = [{} for _ in measured]
        precise_results = None
        if calibration.sprocket_detector_mode == "physical-p07-v1":
            precise_results = []
            for index, dng in enumerate(batch):
                with Image.open(tiffs / f"{dng.stem}.tif") as image:
                    result = register_precisely(
                        image, measured[index], capture_metadata.get(frame_number(dng)),
                        timings, registration_counts,
                    )
                precise_results.append(result)
                physical_details[index] = result.diagnostics
            detections = [None if result.crop is None else SprocketDetection(
                float(result.anchor_x), float(result.optical_lower_top_y), None,
                detector=result.source, detected=True, accepted=True, interpolated=False,
            ) for result in precise_results]
        else:
            with timed("legacy_batch_validation", timings):
                detections = validate_batch(measured, calibration.detector)
        trusted = [item for item in detections if item is not None]
        reference_x = float(np.median([item.cx for item in trusted])) if trusted else None

        with timed("crop_register", timings):
            frame_records = []
            included = [(index, dng, detection) for index, (dng, detection) in
                        enumerate(zip(batch, detections)) if detection is not None]
            primary_crops = ([precise_results[item[0]].crop for item in included]
                             if precise_results is not None else
                             [crop_for_detection(item[2], calibration.crop) for item in included])
            stabilization = None
            if calibration.vertical_stabilization.enabled:
                residual_measured = []
                developed_heights = []
                for (_, dng, detection), crop in zip(included, primary_crops):
                    with Image.open(tiffs / f"{dng.stem}.tif") as image:
                        developed_heights.append(image.height)
                        provisional = registered_frame(image, crop, calibration.contrast)
                    # Match the validated detector input without retaining a
                    # second crop or reading/developing the DNG again.
                    serialized = io.BytesIO()
                    provisional.save(serialized, format="JPEG", quality=95, subsampling=0)
                    serialized.seek(0)
                    with Image.open(serialized) as detector_image:
                        residual_measured.append(measure_frame(
                            detector_image, detection, calibration.vertical_stabilization
                        ))
                stabilization = resolve_batch(
                    residual_measured, primary_crops, developed_heights,
                    calibration.vertical_stabilization,
                )

            encoded_before = sum(int(item.get("frames", 0)) for item in manifest["segments"])
            included_records = []
            included_position = {source_index: position for position, (source_index, _, _) in enumerate(included)}
            for index, (dng, detection) in enumerate(zip(batch, detections)):
                if detection is None:
                    debug_path = preserve_excluded_tiff(tiffs / f"{dng.stem}.tif", output_dir)
                    record = {
                        "frame": frame_number(dng), "source_name": dng.name,
                        "source_bytes": dng.stat().st_size, "anchor_x": None,
                        "anchor_y": None, "detected": physical_details[index].get("primary_detected", False),
                        "accepted": False, "detector_score": None,
                        "crop_left": None, "crop_top": None,
                        "vertical_stabilization_enabled": False,
                        "output_disposition": "excluded", "encoded_output_frame": None,
                        "debug_developed_image": str(debug_path),
                        "raw_source_reference": str(dng.resolve()),
                        "final_registration_source": None,
                        "final_disposition": "excluded",
                    }
                    if precise_results is not None:
                        p15 = physical_details[index].get("p15", {})
                        p07 = physical_details[index].get("p07", {})
                        record.update({
                            "exclusion_reason": p07.get("classification", "p07_rejected"),
                            "p15_failure_reason": p15.get("reason"),
                            "p15_measurements": p15,
                            "p07_rejection_reason": p07.get("classification"),
                            "p07_best_candidate_coordinates": {
                                "upper_center": p07.get("upper_center"),
                                "lower_center": p07.get("lower_center")},
                            "p07_best_score": p07.get("joint_score"),
                            "p07_competitor_score": p07.get("competitor_score"),
                            "p07_competitor_margin": p07.get("competitor_margin"),
                            "p07_supported": p07.get("supported"),
                            "p07_missing": p07.get("missing"),
                            "p07_contradicted": p07.get("contradicted"),
                        })
                    record.update(physical_details[index])
                    frame_records.append(record)
                    continue
                position = included_position[index]
                primary_crop = primary_crops[position]
                result = None if stabilization is None else stabilization[position]
                crop = primary_crop if result is None else result.corrected_crop
                with Image.open(tiffs / f"{dng.stem}.tif") as image:
                    movie = registered_frame(image, crop, calibration.contrast)
                encoded_number = encoded_before + position + 1
                destination = registered / f"frame_{encoded_number:06d}.jpg"
                movie.save(destination, quality=95, subsampling=0)
                record = {
                    "frame": frame_number(dng), "source_name": dng.name,
                    "source_bytes": dng.stat().st_size, "anchor_x": detection.cx,
                    "anchor_y": detection.cy, "detected": detection.detected,
                    "accepted": detection.accepted, "detector_score": detection.score,
                    "crop_left": crop.left, "crop_top": crop.top,
                    "vertical_stabilization_enabled": result is not None,
                    "output_disposition": "included", "encoded_output_frame": encoded_number,
                    "final_registration_source": detection.detector,
                }
                if precise_results is not None:
                    registration = precise_results[index]
                    record.update({"optical_lower_top_y": registration.optical_lower_top_y,
                                   "registration_diagnostics": registration.diagnostics})
                record.update(physical_details[index])
                if result is not None:
                    record.update(result.diagnostics)
                    record["normal_residual_measurement"] = measurement_details(residual_measured[position].normal)
                    record["expanded_residual_measurement"] = measurement_details(residual_measured[position].expanded)
                    with Image.open(destination) as serialized_movie:
                        record.update(verify_post_crop(
                            serialized_movie, calibration.vertical_stabilization
                        ))
                frame_records.append(record)
                included_records.append(record)
        shutil.rmtree(tiffs)

        video = None
        verification = {"excluded_only_segment": True}
        if included:
            registered_paths = sorted(registered.glob("frame_*.jpg"), key=frame_number)
            with timed("normalization", timings):
                corrections, target = normalize_frames(
                    registered_paths, normalized, manifest["normalization"].get("target_median_luma"))
                if "target_median_luma" not in manifest["normalization"]:
                    manifest["normalization"]["target_median_luma"] = target
                for record, correction in zip(included_records, corrections):
                    record["normalization"] = correction

            with timed("encoding_output", timings):
                video = segments_dir / f"frames_{first:06d}_{last:06d}_16fps.mp4"
                temporary_video = video.with_suffix(".tmp.mp4")
                encode_segment(options.ffmpeg, normalized, temporary_video,
                               encoded_before + 1, len(included), options.fps)
            verification = verify_video(options.ffmpeg, options.ffprobe,
                                        temporary_video, len(included))
            os.replace(temporary_video, video)
        for key in ("frames","primary_p15_attempts","primary_p15_successes","p24_attempts",
                    "p24_capture_pairs_available","p24_capture_geometry_passes",
                    "p24_physical_corroborator_available","p24_corroborated_gate_passes",
                    "p24_guided_p15_attempts","p24_guided_p15_successes",
                    "p24_guided_p15_failures","p07_attempts","p07_successes",
                    "p07_failures","p22_invocations","excluded_frames"):
            registration_counts[key] += 0
        segment = {"first": first, "last": last, "frames": len(included),
                   "source_frames": len(batch), "excluded": len(batch) - len(included),
                   "video": None if video is None else str(video),
                   "video_bytes": 0 if video is None else video.stat().st_size,
                   "video_sha256": None if video is None else file_sha256(video),
                   "excluded_only_segment": video is None,
                   "verified": True, "verification": verification, "reference_sprocket_x": reference_x,
                   "detected": sum(item.detected for item in trusted),
                   "accepted": len(trusted), "interpolated": 0,
                   "elapsed_seconds": round(time.time() - started, 2),
                   "completed": utc_now(), "frame_records": frame_records,
                   "stage_timings_seconds": dict(timings),
                   "registration_counts": dict(registration_counts)}
        record_segment(manifest_path, manifest, segment)

        total = sum(timings.values())
        print(f"  Timing breakdown for {first:06d}-{last:06d}:")
        for stage, seconds in sorted(timings.items(), key=lambda item: -item[1]):
            percent = 100 * seconds / total if total else 0
            print(f"    {stage:20s}  {seconds:7.1f}s  ({percent:5.1f}%)")
        if calibration.sprocket_detector_mode == "physical-p07-v1":
            for stage, count_key in (("primary_p15_measurement", "primary_p15_attempts"),
                                     ("p24_capture_transform_gate", "p24_attempts"),
                                     ("p24_physical_hole_corroboration", "p24_capture_geometry_passes"),
                                     ("p24_guided_p15_measurement", "p24_guided_p15_attempts"),
                                     ("p07_fallback_detection", "p07_attempts"),
                                     ("p22_refinement", "p22_invocations")):
                count = registration_counts[count_key]; seconds = timings[stage]
                print(f"    {stage:20s}  calls={count:5d}  mean={seconds/count if count else 0:.4f}s")
            print("    registration counts  " + ", ".join(
                f"{key}={registration_counts[key]}" for key in
                ("primary_p15_attempts", "primary_p15_successes", "p24_attempts",
                 "p24_capture_pairs_available", "p24_capture_geometry_passes",
                 "p24_physical_corroborator_available", "p24_corroborated_gate_passes",
                 "p24_guided_p15_attempts", "p24_guided_p15_successes",
                 "p24_guided_p15_failures", "p07_attempts", "p07_successes",
                 "p07_failures", "p22_invocations", "excluded_frames")))
        shutil.rmtree(work)
        print(f"  verified and cleaned segment {first:06d}-{last:06d}; free {shutil.disk_usage(output_dir).free/2**30:.1f} GiB", flush=True)

    final = finalize_if_complete(options, dngs, manifest, manifest_path, segments_dir)
    if final is not None:
        print(f"Complete and verified: {final}", flush=True)
        summary = manifest.get("processing_summary", {})
        print("Registration summary: " + ", ".join(
            f"{key}={summary.get(key, 0)}" for key in
            ("total_input_frames", "p15_registrations", "p07_fallback_attempts",
             "p07_fallback_successes", "p07_failures", "excluded_frames", "encoded_frames")),
            flush=True)
        print(f"Consecutive exclusion runs: {summary.get('consecutive_exclusion_runs', [])}", flush=True)
