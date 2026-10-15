"""FFmpeg encoding, verification, and checksum helpers."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


def run_command(command: list[str], capture: bool = True) -> subprocess.CompletedProcess:
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


def encode_segment(ffmpeg: Path, normalized: Path, temporary_video: Path,
                   first: int, frame_count: int, fps: int,
                   video_format: str = "h264_mp4") -> None:
    if video_format == "ffv1_mkv_16bit":
        run_command([str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
                     "-framerate", str(fps), "-start_number", str(first),
                     "-i", str(normalized / "frame_%06d.tif"),
                     "-frames:v", str(frame_count), "-c:v", "ffv1", "-level", "3",
                     "-coder", "1", "-context", "1", "-slicecrc", "1",
                     "-pix_fmt", "rgb48le", "-f", "matroska", str(temporary_video)])
    elif video_format == "h264_mp4":
        run_command([str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
                     "-framerate", str(fps), "-start_number", str(first),
                     "-i", str(normalized / "frame_%06d.jpg"), "-frames:v", str(frame_count),
                     "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-threads", "1",
                     "-preset", "fast", "-crf", "15", "-pix_fmt", "yuv420p", str(temporary_video)])
    else:
        raise ValueError(f"unsupported video format: {video_format}")


def verify_video(ffmpeg: Path, ffprobe: Path, video: Path, expected_frames: int) -> dict:
    probe = run_command([str(ffprobe), "-v", "error", "-count_frames", "-show_entries",
                         "format=duration,size,format_name:stream=width,height,nb_frames,nb_read_frames,r_frame_rate,codec_name,pix_fmt,bits_per_raw_sample,level",
                         "-of", "json", str(video)]).stdout
    info = json.loads(probe)
    stream = info["streams"][0]
    frames = 0
    for key in ("nb_frames", "nb_read_frames"):
        try:
            frames = int(stream.get(key, 0))
        except (TypeError, ValueError):
            continue
        if frames:
            break
    if frames != expected_frames:
        raise RuntimeError(f"Video verification failed: expected {expected_frames}, found {frames}")
    if stream.get("codec_name") == "ffv1" and stream.get("pix_fmt") != "rgb48le":
        raise RuntimeError(f"FFV1 verification failed: expected rgb48le, found {stream.get('pix_fmt')}")
    if stream.get("codec_name") == "ffv1":
        if stream.get("level") is not None and stream.get("level") not in {3, "3"}:
            raise RuntimeError(f"FFV1 verification failed: expected version 3, found {stream.get('level')}")
        if not info.get("format", {}).get("format_name", "").startswith("matroska"):
            raise RuntimeError("FFV1 verification failed: output container is not Matroska")
    run_command([str(ffmpeg), "-v", "error", "-i", str(video), "-f", "null", "-"])
    return info


def concatenate_segments(ffmpeg: Path, concat: Path, segment_paths: list[Path], temporary: Path) -> None:
    concat.write_text("".join(f"file '{path.as_posix()}'\n" for path in segment_paths), encoding="utf-8")
    run_command([str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
                 "-i", str(concat), "-c", "copy", str(temporary)])
