#!/usr/bin/env python3
"""Disk-bounded, resumable GrokCam archival RAW post-processing pipeline."""

from __future__ import annotations

import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance

VERSION = "1.1.0"
PRESETS = {
    # Coordinates are relative to the full-resolution midpoint of a sprocket pair.
    # This deliberately retains some film edge/adjacent-frame character.
    "loose": {"x_offset": 159.0, "y_offset": -413.0, "width": 1133, "height": 900},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def run(command: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(command, text=True, capture_output=capture)
    if result.returncode:
        detail = result.stderr.strip() if capture else ""
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command)}\n{detail}")
    return result


def tool_version(path: Path) -> str:
    result = subprocess.run([str(path), "--version"], text=True, capture_output=True)
    return (result.stdout or result.stderr).splitlines()[0].strip()


def file_sha256(path: Path, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def frame_number(path: Path) -> int:
    return int(path.stem.rsplit("_", 1)[-1])


def runs(mask: np.ndarray) -> list[tuple[int, int]]:
    result, start = [], None
    for index, value in enumerate(mask):
        if value and start is None:
            start = index
        if start is not None and (not value or index == len(mask) - 1):
            result.append((start, index if not value else index + 1))
            start = None
    return result


def detect_anchor(image: Image.Image) -> tuple[float, float, float]:
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    x0, x1 = 100, 570
    luminance = rgb[:, x0:x1].mean(axis=2)
    threshold = float(np.percentile(luminance, 99.0) * 0.90)
    bright = luminance > threshold
    bands = [(a, b) for a, b in runs(bright.sum(axis=1) > 130) if 180 <= b - a <= 330]
    candidates = []
    for upper, lower in zip(bands, bands[1:]):
        uy, ly = (sum(upper) / 2.0), (sum(lower) / 2.0)
        pitch_error = abs((ly - uy) - 785.0)
        if pitch_error > 100:
            continue
        centers, widths = [], []
        for top, bottom in (upper, lower):
            columns = np.flatnonzero(bright[top:bottom].sum(axis=0) > (bottom - top) * 0.55)
            if len(columns) < 200:
                break
            left, right = int(columns[0]), int(columns[-1])
            centers.append((left + right) / 2.0 + x0)
            widths.append(right - left + 1)
        if len(centers) == 2:
            score = pitch_error + abs(centers[0] - centers[1]) * 2 + abs(np.mean(widths) - 365) * .2
            candidates.append((score, float(np.mean(centers)), (uy + ly) / 2.0))
    if not candidates:
        raise ValueError("no reliable sprocket pair")
    return min(candidates)


def robust_anchors(raw: np.ndarray, detected: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    accepted = detected.copy()
    for axis, limit in ((0, 12.0), (1, 45.0)):
        series = raw[:, axis]
        safe = np.where(np.isfinite(series), series, np.nanmedian(series))
        padded = np.pad(safe, 2, mode="edge")
        local = np.array([np.median(padded[i:i + 5]) for i in range(len(series))])
        accepted &= np.isfinite(series) & (np.abs(series - local) < limit)
    positions = np.arange(len(raw))
    output = raw.copy()
    for axis in range(2):
        good = accepted & np.isfinite(output[:, axis])
        if not good.any():
            raise RuntimeError("No usable sprocket measurements in batch")
        output[:, axis] = np.interp(positions, positions[good], output[good, axis])
    return output, accepted


def develop_one(darktable: Path, dng: Path, tiff: Path, config_root: Path) -> None:
    config = Path(tempfile.mkdtemp(prefix=f"dt_{dng.stem}_", dir=config_root))
    command = [
        str(darktable), str(dng), str(tiff), "--core", "--configdir", str(config),
        "--conf", "plugins/imageio/format/tiff/bpp=16",
        "--conf", "plugins/imageio/format/tiff/compress=1",
    ]
    try:
        last_error = ""
        for attempt in range(1, 4):
            result = subprocess.run(command, text=True, capture_output=True)
            if result.returncode == 0 and tiff.exists() and tiff.stat().st_size > 1_000_000:
                return
            last_error = result.stderr.strip()
            tiff.unlink(missing_ok=True)
            time.sleep(attempt)
        raise RuntimeError(f"Darktable failed for {dng.name}: {last_error}")
    finally:
        shutil.rmtree(config, ignore_errors=True)


def subpixel_crop(image: Image.Image, left: float, top: float, width: int, height: int) -> Image.Image:
    return image.transform(
        (width, height), Image.Transform.EXTENT,
        (left, top, left + width, top + height), resample=Image.Resampling.BICUBIC,
    )


def analyze_picture(path: Path) -> tuple[float, np.ndarray]:
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0
    h, w = rgb.shape[:2]
    roi = rgb[int(h * .12):int(h * .88), int(w * .15):int(w * .92)].reshape(-1, 3)
    luma = roi @ np.array([.2126, .7152, .0722], dtype=np.float32)
    usable = roi[(luma > .03) & (luma < .96)]
    if len(usable) < 100:
        usable = roi
    return float(np.median(usable @ np.array([.2126, .7152, .0722]))), np.median(usable, axis=0)


def rolling_median(values: np.ndarray, radius: int = 4) -> np.ndarray:
    return np.array([np.median(values[max(0, i-radius):min(len(values), i+radius+1)], axis=0)
                     for i in range(len(values))])


def normalize_frames(
    paths: list[Path], output_dir: Path, target_luma: float | None = None
) -> tuple[list[dict], float]:
    measurements = [analyze_picture(path) for path in paths]
    luma = np.array([value[0] for value in measurements])
    channels = np.array([value[1] for value in measurements])
    # The first segment establishes one reel-wide target. Reusing it prevents
    # visible exposure seams while still allowing each segment to be cleaned up.
    target = float(np.median(luma)) if target_luma is None else float(target_luma)
    exposure = np.clip(target / np.maximum(luma, .03), 2 ** -.65, 2 ** .65)
    neutral = np.exp(np.mean(np.log(np.maximum(channels, .02)), axis=1))
    gains = np.clip(neutral[:, None] / np.maximum(channels, .02), .78, 1.28)
    gains = 1 + (gains - 1) * .25
    exposure = rolling_median(exposure[:, None])[:, 0]
    gains = rolling_median(gains)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for path, exp, gain, measured in zip(paths, exposure, gains, measurements):
        rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0
        corrected = rgb * exp * gain.reshape(1, 1, 3)
        corrected = np.clip(corrected / (1 + .12 * corrected), 0, 1)
        destination = output_dir / path.name
        Image.fromarray(np.uint8(corrected * 255 + .5), "RGB").save(destination, quality=95, subsampling=0)
        results.append({"median_luma": measured[0], "channel_median": measured[1].tolist(),
                        "exposure_gain": float(exp), "channel_gains_rgb": gain.tolist()})
    return results, target


def verify_video(ffmpeg: Path, ffprobe: Path, video: Path, expected_frames: int) -> dict:
    probe = run([str(ffprobe), "-v", "error", "-show_entries",
                 "format=duration,size:stream=width,height,nb_frames,r_frame_rate",
                 "-of", "json", str(video)]).stdout
    info = json.loads(probe)
    frames = int(info["streams"][0]["nb_frames"])
    if frames != expected_frames:
        raise RuntimeError(f"Video verification failed: expected {expected_frames}, found {frames}")
    run([str(ffmpeg), "-v", "error", "-i", str(video), "-f", "null", "-"])
    return info


def parse_args() -> argparse.Namespace:
    darktable_default = shutil.which("darktable-cli") or "/Applications/darktable.app/Contents/MacOS/darktable-cli"
    ffmpeg_default = shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg"
    ffprobe_default = shutil.which("ffprobe") or "/usr/local/bin/ffprobe"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--first", type=int)
    parser.add_argument("--last", type=int)
    parser.add_argument("--batch-frames", type=int, default=960)
    parser.add_argument("--fps", type=int, default=16)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--crop-preset", choices=sorted(PRESETS), default="loose")
    parser.add_argument("--darktable", type=Path, default=Path(darktable_default))
    parser.add_argument("--ffmpeg", type=Path, default=Path(ffmpeg_default))
    parser.add_argument("--ffprobe", type=Path, default=Path(ffprobe_default))
    parser.add_argument("--minimum-free-gib", type=float, default=22.0)
    parser.add_argument("--plan-only", action="store_true", help="Print resume plan without processing")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.raw_dir = args.raw_dir.expanduser().resolve()
    args.output_dir = args.output_dir.expanduser().resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    lock_handle = (args.output_dir / ".pipeline.lock").open("w")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(f"Another pipeline process is already using {args.output_dir}")
    lock_handle.write(f"pid={os.getpid()} started={utc_now()}\n")
    lock_handle.flush()
    staging = args.output_dir / ".staging"
    staging.mkdir(exist_ok=True)
    segments_dir = args.output_dir / "segments"
    segments_dir.mkdir(exist_ok=True)
    dngs = sorted(args.raw_dir.glob("frame_*.dng"), key=frame_number)
    if args.first is not None:
        dngs = [p for p in dngs if frame_number(p) >= args.first]
    if args.last is not None:
        dngs = [p for p in dngs if frame_number(p) <= args.last]
    if not dngs:
        raise SystemExit("No DNG frames selected")
    numbers = [frame_number(path) for path in dngs]
    if numbers != list(range(numbers[0], numbers[-1] + 1)):
        raise SystemExit("Selected DNG sequence is not contiguous")
    free_gib = shutil.disk_usage(args.output_dir).free / 2**30
    if free_gib < args.minimum_free_gib:
        raise SystemExit(f"Only {free_gib:.1f} GiB free; need {args.minimum_free_gib:.1f} GiB")

    manifest_path = args.output_dir / "processing_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.setdefault("batch_history", []).append(
            {"started": utc_now(), "batch_frames": args.batch_frames}
        )
    else:
        manifest = {
            "pipeline": "grokcam_raw_production", "version": VERSION,
            "created": utc_now(), "raw_dir": str(args.raw_dir), "source_policy": "read_only",
            "frame_range": [numbers[0], numbers[-1]], "frame_count": len(numbers),
            "fps": args.fps, "batch_frames": args.batch_frames,
            "crop_preset": args.crop_preset, "crop": PRESETS[args.crop_preset],
            "normalization": {"picture_aperture": {"x": [.15, .92], "y": [.12, .88]},
                              "exposure_limit_stops": .65, "white_balance_blend": .25},
            "tools": {"python": platform.python_version(), "pillow": Image.__version__,
                      "darktable": tool_version(args.darktable), "ffmpeg": tool_version(args.ffmpeg)},
            "segments": [],
        }
        atomic_json(manifest_path, manifest)

    completed_segments = [
        item for item in manifest["segments"]
        if item.get("verified") and Path(item["video"]).exists()
    ]
    completed_numbers: set[int] = set()
    for item in completed_segments:
        completed_numbers.update(range(int(item["first"]), int(item["last"]) + 1))
    remaining = [path for path in dngs if frame_number(path) not in completed_numbers]
    # Form batches only across contiguous unprocessed ranges. This permits a
    # smaller batch size on resume without reprocessing verified earlier work.
    runs_of_dngs: list[list[Path]] = []
    for path in remaining:
        if not runs_of_dngs or frame_number(path) != frame_number(runs_of_dngs[-1][-1]) + 1:
            runs_of_dngs.append([path])
        else:
            runs_of_dngs[-1].append(path)
    batches = [run_group[i:i + args.batch_frames]
               for run_group in runs_of_dngs
               for i in range(0, len(run_group), args.batch_frames)]
    if completed_segments:
        print("Preserving verified segments: " + ", ".join(
            f"{item['first']:06d}-{item['last']:06d}" for item in completed_segments
        ), flush=True)
    print(f"Remaining plan: {len(remaining)} frames in {len(batches)} batches", flush=True)
    for batch in batches:
        print(f"  {frame_number(batch[0]):06d}-{frame_number(batch[-1]):06d} ({len(batch)} frames)", flush=True)
    if args.plan_only:
        return
    for batch_index, batch in enumerate(batches, start=1):
        first, last = frame_number(batch[0]), frame_number(batch[-1])
        free_gib = shutil.disk_usage(args.output_dir).free / 2**30
        if free_gib < args.minimum_free_gib:
            raise RuntimeError(f"Stopping safely: only {free_gib:.1f} GiB free")
        work = staging / f"segment_{first:06d}_{last:06d}"
        if work.exists():
            shutil.rmtree(work)
        tiffs, registered, normalized, configs = (work / name for name in ("tiff", "registered", "normalized", "dt_config"))
        for directory in (tiffs, registered, normalized, configs):
            directory.mkdir(parents=True)
        started = time.time()
        print(f"[{batch_index}/{len(batches)}] developing {len(batch)} frames ({first:06d}-{last:06d})", flush=True)
        def convert(path: Path) -> Path:
            target = tiffs / f"{path.stem}.tif"
            develop_one(args.darktable, path, target, configs)
            return target
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            futures = [pool.submit(convert, path) for path in batch]
            for done, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                future.result()
                if done == 1 or done % 25 == 0 or done == len(batch):
                    print(f"  developed {done}/{len(batch)}; free {shutil.disk_usage(args.output_dir).free/2**30:.1f} GiB", flush=True)

        raw_anchors = np.full((len(batch), 2), np.nan)
        scores = np.full(len(batch), np.nan)
        detected = np.zeros(len(batch), dtype=bool)
        for index, dng in enumerate(batch):
            with Image.open(tiffs / f"{dng.stem}.tif") as image:
                try:
                    score, x, y = detect_anchor(image)
                    raw_anchors[index], scores[index], detected[index] = (x, y), score, True
                except ValueError:
                    pass
        anchors, accepted = robust_anchors(raw_anchors, detected)
        reference_x = float(np.median(anchors[:, 0]))
        crop = PRESETS[args.crop_preset]
        frame_records = []
        for index, dng in enumerate(batch):
            x, y = anchors[index]
            left, top = x + crop["x_offset"], y + crop["y_offset"]
            with Image.open(tiffs / f"{dng.stem}.tif") as image:
                movie = subpixel_crop(image.convert("RGB"), left, top, crop["width"], crop["height"])
            movie = movie.rotate(180, expand=False).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            movie = ImageEnhance.Contrast(movie).enhance(1.04)
            destination = registered / f"{dng.stem}.jpg"
            movie.save(destination, quality=95, subsampling=0)
            frame_records.append({"frame": frame_number(dng), "source_name": dng.name,
                                  "source_bytes": dng.stat().st_size, "anchor_x": float(x), "anchor_y": float(y),
                                  "detected": bool(detected[index]), "accepted": bool(accepted[index]),
                                  "detector_score": None if not np.isfinite(scores[index]) else float(scores[index]),
                                  "crop_left": float(left), "crop_top": float(top)})
        # TIFFs and all Darktable databases are now fully reproducible.
        shutil.rmtree(tiffs)
        shutil.rmtree(configs, ignore_errors=True)

        registered_paths = sorted(registered.glob("frame_*.jpg"), key=frame_number)
        corrections, normalization_target = normalize_frames(
            registered_paths, normalized, manifest["normalization"].get("target_median_luma")
        )
        if "target_median_luma" not in manifest["normalization"]:
            manifest["normalization"]["target_median_luma"] = normalization_target
        for record, correction in zip(frame_records, corrections):
            record["normalization"] = correction
        video = segments_dir / f"frames_{first:06d}_{last:06d}_16fps.mp4"
        temporary_video = video.with_suffix(".tmp.mp4")
        run([str(args.ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
             "-framerate", str(args.fps), "-start_number", str(first),
             "-i", str(normalized / "frame_%06d.jpg"), "-frames:v", str(len(batch)),
             "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-threads", "1",
             "-preset", "fast", "-crf", "15", "-pix_fmt", "yuv420p", str(temporary_video)])
        verification = verify_video(args.ffmpeg, args.ffprobe, temporary_video, len(batch))
        os.replace(temporary_video, video)
        segment = {"first": first, "last": last, "frames": len(batch), "video": str(video),
                   "video_bytes": video.stat().st_size, "video_sha256": file_sha256(video),
                   "verified": True, "verification": verification, "reference_sprocket_x": reference_x,
                   "detected": int(detected.sum()), "accepted": int(accepted.sum()),
                   "interpolated": int((~accepted).sum()), "elapsed_seconds": round(time.time() - started, 2),
                   "completed": utc_now(), "frame_records": frame_records}
        manifest["segments"] = [item for item in manifest["segments"]
                                if (item.get("first"), item.get("last")) != (first, last)] + [segment]
        manifest["segments"].sort(key=lambda item: item["first"])
        atomic_json(manifest_path, manifest)
        # Both JPEG sequences can be recreated from DNG + manifest.
        shutil.rmtree(work)
        print(f"  verified and cleaned segment {first:06d}-{last:06d}; free {shutil.disk_usage(args.output_dir).free/2**30:.1f} GiB", flush=True)

    # Losslessly concatenate the independently verified, codec-identical segments.
    ordered_segments = sorted(
        [item for item in manifest["segments"] if item.get("verified") and Path(item["video"]).exists()],
        key=lambda item: item["first"],
    )
    covered = [number for item in ordered_segments for number in range(item["first"], item["last"] + 1)]
    segment_paths = [Path(item["video"]) for item in ordered_segments]
    if covered == numbers:
        concat = args.output_dir / "segments.txt"
        concat.write_text("".join(f"file '{path.as_posix()}'\n" for path in segment_paths), encoding="utf-8")
        final = args.output_dir / f"RAW_review_{numbers[0]:06d}_{numbers[-1]:06d}_{args.fps}fps.mp4"
        temporary = final.with_suffix(".tmp.mp4")
        run([str(args.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", str(concat), "-c", "copy", str(temporary)])
        final_verification = verify_video(args.ffmpeg, args.ffprobe, temporary, len(dngs))
        os.replace(temporary, final)
        manifest["final"] = {"video": str(final), "video_bytes": final.stat().st_size,
                             "video_sha256": file_sha256(final), "verified": True,
                             "verification": final_verification, "completed": utc_now()}
        # Once the joined movie is independently decoded and verified, its
        # component videos are redundant and reproducible from DNG + manifest.
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
        print(f"Complete and verified: {final}", flush=True)


if __name__ == "__main__":
    main()
