"""Disk-bounded, restartable production batch lifecycle."""

from __future__ import annotations

import concurrent.futures
import fcntl
import io
import os
import shutil
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .config import ProductionCalibration
from .encoding import (concatenate_segments, encode_segment, file_sha256,
                       verify_video)
from .image_processing import registered_frame
from .manifest import atomic_json, load_or_create, record_segment, utc_now
from .normalization import normalize_frames
from .raw_development import DarktableMatchedDeveloper
from .registration import crop_for_detection
from .resume import completed_frame_numbers, contiguous_batches
from .sprocket_detection import detect, validate_batch, validate_batch_with_physical
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
                          if item.get("verified") and Path(item["video"]).exists()]
    completed = completed_frame_numbers(completed_segments)
    remaining = [path for path in dngs if frame_number(path) not in completed]
    return completed_segments, contiguous_batches(remaining, frame_number, batch_frames)


def finalize_if_complete(options: RunOptions, dngs: list[Path], manifest: dict,
                         manifest_path: Path, segments_dir: Path) -> Path | None:
    numbers = [frame_number(path) for path in dngs]
    ordered = sorted([item for item in manifest["segments"]
                      if item.get("verified") and Path(item["video"]).exists()],
                     key=lambda item: item["first"])
    covered = [number for item in ordered for number in range(item["first"], item["last"] + 1)]
    if covered != numbers:
        return None
    segment_paths = [Path(item["video"]) for item in ordered]
    concat = options.output_dir / "segments.txt"
    final = options.output_dir / f"RAW_review_{numbers[0]:06d}_{numbers[-1]:06d}_{options.fps}fps.mp4"
    temporary = final.with_suffix(".tmp.mp4")
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


def run_reel(options: RunOptions, calibration: ProductionCalibration) -> None:
    raw_dir = options.raw_dir.expanduser().resolve()
    output_dir = options.output_dir.expanduser().resolve()
    options = RunOptions(**{**options.__dict__, "raw_dir": raw_dir, "output_dir": output_dir})
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

        with timed("rawpy_develop", timings):
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, options.jobs)) as pool:
                futures = [pool.submit(convert, path) for path in batch]
                for done, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                    future.result()
                    if done == 1 or done % 25 == 0 or done == len(batch):
                        print(f"  developed {done}/{len(batch)}; free {shutil.disk_usage(output_dir).free/2**30:.1f} GiB", flush=True)

        with timed("sprocket_detect", timings):
            measured = []
            for dng in batch:
                with Image.open(tiffs / f"{dng.stem}.tif") as image:
                    try:
                        measured.append(detect(image, calibration.detector))
                    except ValueError:
                        measured.append(None)
            physical_details = [{} for _ in measured]
            if calibration.sprocket_detector_mode == "physical-p07-v1":
                paths = [tiffs / f"{dng.stem}.tif" for dng in batch]
                detections, physical_details = validate_batch_with_physical(
                    lambda index: Image.open(paths[index]), measured, calibration.detector,
                    [capture_metadata.get(frame_number(dng)) for dng in batch],
                )
            else:
                detections = validate_batch(measured, calibration.detector)
            trusted = [item for item in detections if item is not None]
            reference_x = float(np.median([item.cx for item in trusted])) if trusted else None

        with timed("crop_register", timings):
            frame_records = []
            included = [(index, dng, detection) for index, (dng, detection) in
                        enumerate(zip(batch, detections)) if detection is not None]
            if not included:
                raise RuntimeError(f"No trustworthy registrations in source batch {first}-{last}")
            primary_crops = [crop_for_detection(item[2], calibration.crop) for item in included]
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
            excluded_dir = output_dir / "debug" / "excluded_frames"
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
                    }
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
                }
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

        registered_paths = sorted(registered.glob("frame_*.jpg"), key=frame_number)
        with timed("normalize", timings):
            corrections, target = normalize_frames(
                registered_paths, normalized, manifest["normalization"].get("target_median_luma"))
            if "target_median_luma" not in manifest["normalization"]:
                manifest["normalization"]["target_median_luma"] = target
            for record, correction in zip(included_records, corrections):
                record["normalization"] = correction

        with timed("ffmpeg_encode", timings):
            video = segments_dir / f"frames_{first:06d}_{last:06d}_16fps.mp4"
            temporary_video = video.with_suffix(".tmp.mp4")
            encode_segment(options.ffmpeg, normalized, temporary_video,
                           encoded_before + 1, len(included), options.fps)
        verification = verify_video(options.ffmpeg, options.ffprobe, temporary_video, len(included))
        os.replace(temporary_video, video)
        segment = {"first": first, "last": last, "frames": len(included),
                   "source_frames": len(batch), "excluded": len(batch) - len(included), "video": str(video),
                   "video_bytes": video.stat().st_size, "video_sha256": file_sha256(video),
                   "verified": True, "verification": verification, "reference_sprocket_x": reference_x,
                   "detected": sum(item.detected for item in trusted),
                   "accepted": len(trusted), "interpolated": 0,
                   "elapsed_seconds": round(time.time() - started, 2),
                   "completed": utc_now(), "frame_records": frame_records}
        record_segment(manifest_path, manifest, segment)

        total = sum(timings.values())
        print(f"  Timing breakdown for {first:06d}-{last:06d}:")
        for stage, seconds in sorted(timings.items(), key=lambda item: -item[1]):
            percent = 100 * seconds / total if total else 0
            print(f"    {stage:20s}  {seconds:7.1f}s  ({percent:5.1f}%)")
        shutil.rmtree(work)
        print(f"  verified and cleaned segment {first:06d}-{last:06d}; free {shutil.disk_usage(output_dir).free/2**30:.1f} GiB", flush=True)

    final = finalize_if_complete(options, dngs, manifest, manifest_path, segments_dir)
    if final is not None:
        print(f"Complete and verified: {final}", flush=True)
