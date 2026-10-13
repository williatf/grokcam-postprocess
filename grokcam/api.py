"""GUI-neutral public API for source inspection and reel processing.

This module is intentionally a client-facing facade. The production pipeline
continues to own all image processing, registration, normalization, encoding,
verification, and manifest behavior.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable

import rawpy

from .batch import RunOptions
from .config import (Regular8CaptureGeometry, load_calibration,
                      load_capture_geometry)
from .events import EventEmitter, ProcessingProgressEvent
from .pipeline import ProductionPipeline


SUPPORTED_FILM_FORMATS = ("regular8", "super8")
DEFAULT_PROJECT_ROOT = Path("/mnt/SG1TB/GrokCam/projects")
_FRAME_PATTERN = re.compile(r"^frame_(\d+)\.dng$")
_DEFAULT_CALIBRATION_DIR = Path(__file__).resolve().parents[1] / "calibrations"


def _json_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _json_dict(value: Any) -> dict[str, Any]:
    return _json_value(asdict(value))


@dataclass(frozen=True)
class SourceInspection:
    source_path: Path
    raw_path: Path
    metadata_path: Path | None
    metadata: dict[str, Any] | None
    metadata_error: str | None
    project_name: str | None
    declared_film_format: str | None
    frame_count: int
    first_frame: int | None
    last_frame: int | None
    contiguous: bool
    missing_frames: tuple[int, ...] = ()
    sample_dimensions: tuple[int, int] | None = None
    capture_metadata_files: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()
    capture_geometry_present: bool = False
    capture_geometry_valid: bool = False
    capture_geometry_schema_version: int | None = None
    capture_geometry_frozen: bool | None = None
    capture_geometry_summary: dict[str, Any] = field(default_factory=dict)
    capture_geometry_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _json_dict(self)


@dataclass(frozen=True)
class CalibrationInfo:
    calibration_id: str
    display_name: str
    config_path: Path
    metadata_path: Path | None
    film_formats: tuple[str, ...]
    adoption_status: str | None
    available: bool
    unavailable_reason: str | None
    artifact_sha256: str | None
    resource_paths: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _json_dict(self)


@dataclass(frozen=True)
class ProjectInfo:
    """A capture project suitable for display in a post-processing picker."""

    project_name: str
    source_path: Path
    film_format: str | None
    frame_count: int
    first_frame: int | None
    last_frame: int | None
    contiguous: bool
    available: bool
    warnings: tuple[str, ...] = ()
    capture_geometry_present: bool = False
    capture_geometry_valid: bool = False
    capture_geometry_frozen: bool | None = None
    capture_geometry_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_dict(self)


@dataclass(frozen=True)
class ProcessingConfig:
    source_path: Path
    output_directory: Path
    calibration_id: str
    film_format: str
    first_frame: int | None = None
    last_frame: int | None = None
    fps: int = 16
    batch_frames: int = 960
    raw_jobs: int = 3
    output_name: str | None = None
    capture_geometry_path: Path | None = None

    def __post_init__(self) -> None:
        if self.source_path is None or not str(self.source_path).strip():
            raise ValueError("source_path is required")
        if self.output_directory is None or not str(self.output_directory).strip():
            raise ValueError("output_directory is required")
        source = Path(self.source_path).expanduser()
        output = Path(self.output_directory).expanduser()
        object.__setattr__(self, "source_path", source)
        object.__setattr__(self, "output_directory", output)
        if self.capture_geometry_path is not None:
            object.__setattr__(self, "capture_geometry_path",
                               Path(self.capture_geometry_path).expanduser())
        if not isinstance(self.calibration_id, str) or not self.calibration_id.strip():
            raise ValueError("calibration_id is required")
        if self.film_format not in SUPPORTED_FILM_FORMATS:
            raise ValueError("film_format must be regular8 or super8")
        if self.capture_geometry_path is not None and self.film_format != "regular8":
            raise ValueError("capture_geometry_path is only supported for regular8")
        for name, value in (("first_frame", self.first_frame), ("last_frame", self.last_frame)):
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
                raise ValueError(f"{name} must be a positive integer or None")
        if self.first_frame is not None and self.last_frame is not None and self.first_frame > self.last_frame:
            raise ValueError("first_frame must not be greater than last_frame")
        for name, value in (("fps", self.fps), ("batch_frames", self.batch_frames), ("raw_jobs", self.raw_jobs)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.output_name is not None:
            if not isinstance(self.output_name, str) or not self.output_name.strip():
                raise ValueError("output_name must be a non-empty filename or None")
            if self.output_name in {".", ".."} or Path(self.output_name).is_absolute():
                raise ValueError("output_name must be a filename inside output_directory")
            if "/" in self.output_name or "\\" in self.output_name:
                raise ValueError("output_name must be a filename, not a path")

    def to_dict(self) -> dict[str, Any]:
        return _json_dict(self)


@dataclass(frozen=True)
class ProcessingResult:
    protocol_version: int
    job_id: str
    status: str
    source: SourceInspection | None
    selected_frame_range: tuple[int, int] | None
    output_directory: Path
    movie_path: Path | None
    manifest_path: Path | None
    registration_summary: dict[str, Any] = field(default_factory=dict)
    batches: tuple[dict[str, Any], ...] = ()
    timing: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    error: dict[str, Any] | None = None
    capture_geometry_source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _json_dict(self)


class StructuredProcessingError(RuntimeError):
    """An operational error safe to expose at the public API boundary."""

    def __init__(self, code: str, message: str, *, stage: str | None = None,
                 retryable: bool = False, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage
        self.retryable = retryable
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "stage": self.stage,
            "retryable": self.retryable,
            "details": _json_value(self.details),
        }


def _resolve_source(path: Path) -> tuple[Path, Path]:
    source = path.expanduser().resolve()
    if not source.exists() or not source.is_dir():
        raise StructuredProcessingError("source_unavailable", f"Source directory does not exist: {source}",
                                        stage="source_validation")
    raw = source / "raw" if (source / "raw").is_dir() else source
    if raw.name == "raw":
        project = raw.parent
    else:
        project = raw
    return project, raw


def _sample_dimensions(path: Path) -> tuple[tuple[int, int] | None, str | None]:
    try:
        with rawpy.imread(str(path)) as raw:
            sizes = raw.sizes
            width = getattr(sizes, "width", None) or getattr(sizes, "raw_width", None)
            height = getattr(sizes, "height", None) or getattr(sizes, "raw_height", None)
            if width is None or height is None:
                return None, "sample DNG did not expose image dimensions"
            return (int(width), int(height)), None
    except Exception as error:  # DNG header inspection is best effort.
        return None, f"sample dimensions unavailable: {error}"


def inspect_source(path: Path | str, *, include_sample_dimensions: bool = True) -> SourceInspection:
    """Inspect a project or raw directory without modifying it."""
    project, raw = _resolve_source(Path(path))
    metadata_path = project / "metadata.json"
    metadata: dict[str, Any] | None = None
    metadata_error = None
    warnings: list[str] = []
    if metadata_path.is_file():
        try:
            value = json.loads(metadata_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                metadata = value
            else:
                metadata_error = "metadata.json does not contain a JSON object"
                warnings.append(metadata_error)
        except (OSError, json.JSONDecodeError) as error:
            metadata_error = str(error)
            warnings.append(f"metadata.json could not be read: {error}")

    dngs: list[tuple[int, Path]] = []
    unique_dngs: list[tuple[int, Path]] = []
    duplicate_frames: set[int] = set()
    seen: dict[int, Path] = {}
    try:
        entries = sorted(raw.iterdir(), key=lambda item: item.name)
    except OSError as error:
        raise StructuredProcessingError("source_unavailable", f"Could not list source directory: {error}",
                                        stage="source_validation") from error
    for entry in entries:
        match = _FRAME_PATTERN.match(entry.name)
        if not match or not entry.is_file():
            continue
        number = int(match.group(1))
        dngs.append((number, entry))
        if number in seen:
            duplicate_frames.add(number)
        else:
            seen[number] = entry
            unique_dngs.append((number, entry))
    dngs.sort(key=lambda item: item[0])
    unique_dngs.sort(key=lambda item: item[0])
    if duplicate_frames:
        warnings.append("duplicate frame numbers were found: " + ", ".join(map(str, sorted(duplicate_frames))))
    numbers = [number for number, _path in unique_dngs]
    first = numbers[0] if numbers else None
    last = numbers[-1] if numbers else None
    missing = tuple(number for number in range(first, last + 1) if number not in seen) if numbers else ()
    contiguous = bool(numbers) and not duplicate_frames and not missing
    if not dngs:
        warnings.append("no frame_<digits>.dng files were found")
    if missing:
        warnings.append(f"source sequence has {len(missing)} missing frame(s)")
    dimensions = None
    if unique_dngs and include_sample_dimensions:
        dimensions, dimension_warning = _sample_dimensions(unique_dngs[0][1])
        if dimension_warning:
            warnings.append(dimension_warning)

    raw_logs = tuple(sorted((project / "debug").glob("raw_capture_metadata_*.jsonl"))) if (project / "debug").is_dir() else ()
    declared = metadata.get("film_format") if metadata else None
    if declared is not None and not isinstance(declared, str):
        warnings.append("metadata.json film_format is not a string")
        declared = None
    # A capture that is still calibrating (or that could not freeze) records
    # status separately and may leave capture_geometry as null. Treat that as
    # absent so the established Regular 8 default remains usable; a non-null
    # malformed object is still surfaced as an explicit validation error.
    geometry_present = bool(metadata and metadata.get("capture_geometry") is not None)
    geometry_valid = False
    geometry_schema = None
    geometry_frozen = None
    geometry_summary: dict[str, Any] = {}
    geometry_error = None
    if geometry_present:
        raw_geometry = metadata.get("capture_geometry")
        if isinstance(raw_geometry, dict):
            geometry_schema = raw_geometry.get("schema_version")
            geometry_frozen = raw_geometry.get("frozen")
            try:
                geometry = Regular8CaptureGeometry.from_dict(raw_geometry)
                geometry_valid = True
                geometry_summary = {
                    "pitch_px": geometry.sprocket_pitch_px,
                    "pitch_mad_px": geometry.sprocket_pitch_mad_px,
                    "calibration_frames": len(geometry.calibration_frames),
                    "calibration_method": geometry.calibration_method,
                    "source": geometry.source,
                }
            except (TypeError, ValueError) as error:
                geometry_error = str(error)
                warnings.append(f"capture_geometry is invalid: {error}")
        else:
            geometry_error = "capture_geometry must be a JSON object"
            warnings.append(geometry_error)
    return SourceInspection(
        source_path=project,
        raw_path=raw,
        metadata_path=metadata_path if metadata_path.is_file() else None,
        metadata=metadata,
        metadata_error=metadata_error,
        project_name=metadata.get("project_name") if metadata else None,
        declared_film_format=declared,
        frame_count=len(dngs),
        first_frame=first,
        last_frame=last,
        contiguous=contiguous,
        missing_frames=missing,
        sample_dimensions=dimensions,
        capture_metadata_files=raw_logs,
        warnings=tuple(warnings),
        capture_geometry_present=geometry_present,
        capture_geometry_valid=geometry_valid,
        capture_geometry_schema_version=geometry_schema,
        capture_geometry_frozen=geometry_frozen,
        capture_geometry_summary=geometry_summary,
        capture_geometry_error=geometry_error,
    )


def list_projects(project_root: Path | str = DEFAULT_PROJECT_ROOT) -> list[ProjectInfo]:
    """Discover capture projects below *project_root* without modifying them.

    Existing GrokCam projects are identified by a ``metadata.json`` file or a
    ``raw`` directory. Each candidate is inspected independently so one bad
    project cannot hide the remaining projects.
    """
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        return []
    try:
        candidates = sorted((item for item in root.iterdir() if item.is_dir()),
                            key=lambda item: item.name.casefold())
    except OSError:
        return []

    projects: list[ProjectInfo] = []
    for candidate in candidates:
        metadata_path = candidate / "metadata.json"
        raw_path = candidate / "raw"
        try:
            metadata_exists = metadata_path.is_file()
            raw_exists = raw_path.is_dir()
            direct_frames = any(_FRAME_PATTERN.match(item.name) and item.is_file()
                                for item in candidate.iterdir())
        except OSError as error:
            projects.append(ProjectInfo(
                project_name=candidate.name,
                source_path=candidate.resolve(),
                film_format=None,
                frame_count=0,
                first_frame=None,
                last_frame=None,
                contiguous=False,
                available=False,
                warnings=(f"project could not be inspected: {error}",),
            ))
            continue
        if not (metadata_exists or raw_exists or direct_frames):
            continue
        warnings: list[str] = []
        try:
            source = inspect_source(candidate, include_sample_dimensions=False)
            project_name = source.project_name if isinstance(source.project_name, str) and source.project_name.strip() else candidate.name
            if project_name == candidate.name and source.project_name is None:
                warnings.append("metadata.json does not declare project_name")
            elif project_name == candidate.name and source.project_name is not None:
                warnings.append("metadata.json project_name is invalid; using directory name")
            film_format = source.declared_film_format if isinstance(source.declared_film_format, str) else None
            warnings.extend(source.warnings)
            if source.metadata_path is None:
                warnings.append("metadata.json not found")
            available = source.raw_path.is_dir() and source.frame_count > 0
            if not source.raw_path.is_dir():
                warnings.append("raw source directory is not present")
            elif source.frame_count == 0:
                warnings.append("no frame_<digits>.dng files were found")
            projects.append(ProjectInfo(
                project_name=project_name,
                source_path=source.source_path,
                film_format=film_format,
                frame_count=source.frame_count,
                first_frame=source.first_frame,
                last_frame=source.last_frame,
                contiguous=source.contiguous,
                available=available,
                warnings=tuple(dict.fromkeys(warnings)),
                capture_geometry_present=source.capture_geometry_present,
                capture_geometry_valid=source.capture_geometry_valid,
                capture_geometry_frozen=source.capture_geometry_frozen,
                capture_geometry_summary=source.capture_geometry_summary,
            ))
        except (OSError, StructuredProcessingError) as error:
            projects.append(ProjectInfo(
                project_name=candidate.name,
                source_path=candidate.resolve(),
                film_format=None,
                frame_count=0,
                first_frame=None,
                last_frame=None,
                contiguous=False,
                available=False,
                warnings=(f"project could not be inspected: {error}",),
            ))
    return sorted(projects, key=lambda item: (item.project_name.casefold(), str(item.source_path).casefold()))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _calibration_dirs(search_paths: Iterable[Path | str] | None) -> tuple[Path, ...]:
    values = (_DEFAULT_CALIBRATION_DIR,) if search_paths is None else tuple(Path(item).expanduser().resolve() for item in search_paths)
    return tuple(dict.fromkeys(values))


def _resource_path(base: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    return candidate if candidate.is_absolute() else (base / candidate).resolve()


def _discover_one(metadata_path: Path) -> CalibrationInfo | None:
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(metadata, dict) or not metadata.get("config"):
        return None
    config_path = _resource_path(metadata_path.parent, str(metadata["config"]))
    warnings: list[str] = []
    resources: list[Path] = []
    for value in metadata.get("requires", []):
        if isinstance(value, str):
            resources.append(_resource_path(metadata_path.parent, value))
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            if not isinstance(config, dict):
                warnings.append("configuration JSON is not an object")
            else:
                match = config.get("match", {})
                if isinstance(match, dict) and isinstance(match.get("report"), str):
                    resources.append(_resource_path(config_path.parent, match["report"]))
                super8 = config.get("super8_registration", {})
                if isinstance(super8, dict):
                    for key in ("template_bank", "template_metadata"):
                        if isinstance(super8.get(key), str):
                            resources.append(_resource_path(config_path.parent, super8[key]))
        except (OSError, json.JSONDecodeError) as error:
            warnings.append(f"configuration could not be read: {error}")
    resources = list(dict.fromkeys(resources))
    missing = [path for path in [config_path, *resources] if not path.exists()]
    available = not missing and not warnings
    reason = None if available else "; ".join(
        ([f"missing resource: {path}" for path in missing] + warnings)
    )
    artifact_hash = metadata.get("artifact_sha256")
    artifact = metadata.get("artifact", metadata.get("config"))
    if artifact_hash and isinstance(artifact, str):
        artifact_path = _resource_path(metadata_path.parent, artifact)
        if artifact_path.is_file() and _sha256(artifact_path) != artifact_hash:
            available = False
            reason = f"SHA-256 mismatch: {artifact_path}"
    formats = tuple(item for item in metadata.get("film_formats", []) if item in SUPPORTED_FILM_FORMATS)
    if not formats and config_path.is_file():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            value = config.get("film_format", "regular8")
            formats = (value,) if value in SUPPORTED_FILM_FORMATS else ()
        except (OSError, json.JSONDecodeError):
            pass
    calibration_id = str(metadata.get("calibration_id") or config_path.stem)
    return CalibrationInfo(
        calibration_id=calibration_id,
        display_name=str(metadata.get("display_name") or calibration_id),
        config_path=config_path,
        metadata_path=metadata_path,
        film_formats=formats,
        adoption_status=metadata.get("adoption_status"),
        available=available,
        unavailable_reason=reason,
        artifact_sha256=artifact_hash,
        resource_paths=tuple(resources),
        warnings=tuple(warnings),
    )


def list_calibrations(search_paths: Iterable[Path | str] | None = None) -> list[CalibrationInfo]:
    """Enumerate selectable production calibration descriptors."""
    found: list[CalibrationInfo] = []
    for directory in _calibration_dirs(search_paths):
        if not directory.is_dir():
            continue
        for metadata_path in sorted(directory.glob("*.metadata.json")):
            item = _discover_one(metadata_path)
            if item is not None:
                found.append(item)
    unique: dict[str, CalibrationInfo] = {}
    for item in found:
        unique.setdefault(item.calibration_id, item)
    return sorted(unique.values(), key=lambda item: item.calibration_id)


def _error_from_exception(error: BaseException, *, stage: str | None = None) -> dict[str, Any]:
    if isinstance(error, StructuredProcessingError):
        result = error.to_dict()
        if result["stage"] is None:
            result["stage"] = stage
        return result
    if isinstance(error, SystemExit):
        message = str(error) or "processing exited without a structured error"
    else:
        message = str(error) or type(error).__name__
    return {
        "code": "processing_failed",
        "message": message,
        "stage": stage,
        "retryable": False,
        "details": {"error_type": type(error).__name__},
    }


def _find_calibration(calibration_id: str) -> CalibrationInfo:
    for item in list_calibrations():
        if item.calibration_id == calibration_id:
            if not item.available:
                raise StructuredProcessingError("calibration_unavailable",
                                                item.unavailable_reason or calibration_id,
                                                stage="source_validation")
            return item
    raise StructuredProcessingError("calibration_unavailable",
                                    f"Unknown calibration_id: {calibration_id}",
                                    stage="source_validation")


def _validate_selection(source: SourceInspection, config: ProcessingConfig) -> tuple[int, int]:
    if not source.frame_count or source.first_frame is None or source.last_frame is None:
        raise StructuredProcessingError("source_empty", "Source contains no DNG frames",
                                        stage="source_validation")
    first = source.first_frame if config.first_frame is None else config.first_frame
    last = source.last_frame if config.last_frame is None else config.last_frame
    if first < source.first_frame or last > source.last_frame:
        raise StructuredProcessingError("frame_range_out_of_bounds",
                                        f"Requested range {first}-{last} is outside source range "
                                        f"{source.first_frame}-{source.last_frame}",
                                        stage="source_validation",
                                        details={"source_range": [source.first_frame, source.last_frame],
                                                 "requested_range": [first, last]})
    if not source.contiguous:
        missing = [number for number in source.missing_frames if first <= number <= last]
        if missing:
            raise StructuredProcessingError("source_non_contiguous",
                                            "Selected DNG sequence is not contiguous",
                                            stage="source_validation",
                                            details={"missing_frames": missing})
    return first, last


def _manifest_path(output_directory: Path) -> Path:
    return output_directory / "processing_manifest.json"


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StructuredProcessingError("result_unavailable", f"Could not read processing manifest: {error}") from error
    if not isinstance(value, dict):
        raise StructuredProcessingError("result_unavailable", "Processing manifest is not a JSON object")
    return value


def _result_from_manifest(output_directory: Path, manifest_path: Path, manifest: dict[str, Any],
                          *, job_id: str = "recovered") -> ProcessingResult:
    summary = manifest.get("summary") if isinstance(manifest.get("summary"), dict) else {}
    processing_summary = manifest.get("processing_summary") if isinstance(manifest.get("processing_summary"), dict) else {}
    render = summary.get("render") if isinstance(summary.get("render"), dict) else {}
    final = manifest.get("final") if isinstance(manifest.get("final"), dict) else {}
    movie_value = final.get("video") or render.get("output_video")
    movie = Path(movie_value) if isinstance(movie_value, str) else None
    if movie is not None and not movie.is_absolute():
        movie = output_directory / movie
    frame_range = manifest.get("frame_range")
    selected = tuple(frame_range) if isinstance(frame_range, list) and len(frame_range) == 2 else None
    raw_path = Path(manifest.get("raw_dir") or manifest.get("source_directory") or output_directory)
    try:
        source = inspect_source(raw_path)
    except StructuredProcessingError:
        source = SourceInspection(
            source_path=raw_path.parent if raw_path.name == "raw" else raw_path,
            raw_path=raw_path,
            metadata_path=None,
            metadata=None,
            metadata_error=None,
            project_name=None,
            declared_film_format=manifest.get("film_format"),
            frame_count=int(manifest.get("frame_count", 0)),
            first_frame=selected[0] if selected else None,
            last_frame=selected[1] if selected else None,
            contiguous=True,
            warnings=("source was unavailable; source information was recovered from the manifest",),
        )
    verified = bool(
        final.get("verified") or render.get("verified") or
        render.get("output_video_verification")
    )
    if movie is not None and movie.exists():
        verified = verified or bool(final.get("verified"))
    status = "succeeded" if verified and movie is not None else "failed"
    registration = (summary.get("processing_summary") or summary.get("provenance_counts") or
                    processing_summary or summary)
    batches = summary.get("batch_timings") or manifest.get("segments") or ()
    timing = (summary.get("scheduler") or summary.get("timing") or
              processing_summary.get("stage_total_seconds", {}))
    return ProcessingResult(
        protocol_version=1,
        job_id=job_id,
        status=status,
        source=source,
        selected_frame_range=selected,
        output_directory=output_directory,
        movie_path=movie if movie is not None and movie.exists() else None,
        manifest_path=manifest_path,
        registration_summary=registration if isinstance(registration, dict) else {},
        batches=tuple(item for item in batches if isinstance(item, dict)),
        timing=timing if isinstance(timing, dict) else {},
        warnings=tuple(manifest.get("warnings", ())),
        error=None if status == "succeeded" else {"code": "result_incomplete", "message": "No verified final movie was recorded"},
        capture_geometry_source=manifest.get("capture_geometry_source"),
    )


def read_result(output_path: Path | str) -> ProcessingResult:
    """Recover a result from a published output directory or manifest."""
    candidate = Path(output_path).expanduser().resolve()
    manifest_path = candidate if candidate.name == "processing_manifest.json" else candidate / "processing_manifest.json"
    if not manifest_path.is_file():
        raise StructuredProcessingError("result_unavailable", f"Processing manifest does not exist: {manifest_path}")
    return _result_from_manifest(manifest_path.parent, manifest_path, _read_manifest(manifest_path))


def process_reel(config: ProcessingConfig, event_sink: Callable[[ProcessingProgressEvent], None] | None = None) -> ProcessingResult:
    """Run the existing production pipeline through a stable public boundary."""
    job_id = uuid.uuid4().hex
    emitter = EventEmitter(job_id, event_sink)
    source: SourceInspection | None = None
    selected: tuple[int, int] | None = None
    output = Path(config.output_directory).expanduser().resolve()
    try:
        source = inspect_source(config.source_path)
        selected = _validate_selection(source, config)
        calibration_info = _find_calibration(config.calibration_id)
        if config.film_format not in calibration_info.film_formats:
            raise StructuredProcessingError(
                "calibration_incompatible",
                f"Calibration {config.calibration_id} does not support {config.film_format}",
                stage="source_validation",
                details={"film_formats": list(calibration_info.film_formats)},
            )
        calibration = load_calibration(calibration_info.config_path)
        capture_geometry_source = (
            "super8_default" if config.film_format == "super8" else "regular8_default"
        )
        if config.capture_geometry_path is not None:
            calibration = replace(
                calibration,
                capture_geometry=load_capture_geometry(config.capture_geometry_path),
            )
            capture_geometry_source = "explicit_override"
        elif config.film_format == "regular8" and source.capture_geometry_present:
            if not source.capture_geometry_valid:
                raise StructuredProcessingError(
                    "capture_geometry_invalid",
                    source.capture_geometry_error or "capture_geometry is invalid",
                    stage="source_validation",
                )
            calibration = replace(
                calibration,
                capture_geometry=Regular8CaptureGeometry.from_dict(
                    source.metadata["capture_geometry"]
                ),
            )
            capture_geometry_source = "project_metadata"
        calibration = replace(calibration, film_format=config.film_format)
        total = selected[1] - selected[0] + 1
        batches = (total + config.batch_frames - 1) // config.batch_frames
        emitter.emit("job_started", {
            "source_path": str(source.source_path),
            "selected_frame_range": list(selected),
            "total_source_frames": total,
            "total_batches": batches,
            "film_format": config.film_format,
            "calibration_id": config.calibration_id,
            "capture_geometry_path": (None if config.capture_geometry_path is None else
                                       str(config.capture_geometry_path)),
            "capture_geometry_source": capture_geometry_source,
            "capture_geometry_summary": source.capture_geometry_summary,
            "fps": config.fps,
            "batch_frames": config.batch_frames,
            "raw_jobs": config.raw_jobs,
        })
        ffmpeg = Path(shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg")
        ffprobe = Path(shutil.which("ffprobe") or "/usr/local/bin/ffprobe")
        options = RunOptions(
            raw_dir=source.raw_path,
            output_dir=output,
            first=selected[0],
            last=selected[1],
            batch_frames=config.batch_frames,
            fps=config.fps,
            jobs=config.raw_jobs,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            output_name=config.output_name,
            event_emitter=emitter,
            capture_geometry_source=capture_geometry_source,
        )
        raw_result = ProductionPipeline(calibration).process_reel(options)
        manifest_path = _manifest_path(output)
        manifest = _read_manifest(manifest_path) if manifest_path.is_file() else {}
        result = _result_from_manifest(output, manifest_path, manifest, job_id=job_id)
        if result.status != "succeeded" and isinstance(raw_result, dict):
            raw_final = raw_result.get("final") if isinstance(raw_result.get("final"), dict) else {}
            raw_render = raw_result.get("render") if isinstance(raw_result.get("render"), dict) else {}
            raw_movie = raw_final.get("video") or raw_render.get("output_video")
            raw_verified = raw_final.get("verified") or raw_render.get("verified") or raw_render.get("output_video_verification")
            if isinstance(raw_movie, str) and raw_verified and Path(raw_movie).is_file():
                result = replace(result, status="succeeded", error=None,
                                 movie_path=Path(raw_movie), selected_frame_range=selected,
                                 source=source)
        result = replace(result, selected_frame_range=selected, source=source)
        if isinstance(raw_result, dict):
            summary = raw_result.get("processing_summary") or raw_result.get("provenance_counts")
            if isinstance(summary, dict) and not result.registration_summary:
                result = replace(result, registration_summary=summary)
        emitter.emit("job_completed", result.to_dict())
        return result
    except (Exception, SystemExit) as error:
        error_info = _error_from_exception(error, stage="source_validation" if source is None else None)
        emitter.emit("job_failed", {
            "error": error_info,
            "selected_frame_range": list(selected) if selected else None,
            "output_directory": str(output),
        })
        return ProcessingResult(
            protocol_version=1,
            job_id=job_id,
            status="failed",
            source=source,
            selected_frame_range=selected,
            output_directory=output,
            movie_path=None,
            manifest_path=_manifest_path(output) if _manifest_path(output).exists() else None,
            warnings=source.warnings if source else (),
            error=error_info,
            capture_geometry_source=(
                capture_geometry_source if "capture_geometry_source" in locals() else None
            ),
        )


__all__ = [
    "CalibrationInfo", "DEFAULT_PROJECT_ROOT", "ProcessingConfig",
    "ProcessingProgressEvent", "ProcessingResult", "ProjectInfo", "SourceInspection",
    "StructuredProcessingError", "inspect_source", "list_calibrations", "list_projects",
    "process_reel", "read_result",
]
