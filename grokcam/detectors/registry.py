"""Small explicit detector registry and state-checkpoint helpers."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Callable

from ..config import DetectorCalibration
from .adaptive import _factory as adaptive_factory
from .base import SprocketDetector

DetectorFactory = Callable[[DetectorCalibration, dict[str, Any]], SprocketDetector]
_FACTORIES: dict[str, DetectorFactory] = {"adaptive-v1": adaptive_factory}


def register_detector(name: str, factory: DetectorFactory) -> None:
    """Register a detector factory; duplicate identifiers are rejected."""
    if not name or not isinstance(name, str):
        raise ValueError("detector name must be a non-empty string")
    if name in _FACTORIES:
        raise ValueError(f"sprocket detector is already registered: {name}")
    _FACTORIES[name] = factory


def unregister_detector(name: str) -> None:
    """Remove a non-production registration (primarily useful to test plugins)."""
    if name == "adaptive-v1":
        raise ValueError("the built-in adaptive-v1 detector cannot be unregistered")
    _FACTORIES.pop(name, None)


def detector_registered(name: str) -> bool:
    return name in _FACTORIES


def registered_detectors() -> tuple[str, ...]:
    return tuple(sorted(_FACTORIES))


def create_detector(name: str, calibration: DetectorCalibration,
                    options: dict[str, Any] | None = None) -> SprocketDetector:
    try:
        factory = _FACTORIES[name]
    except KeyError as error:
        raise ValueError(f"unknown sprocket detector: {name}") from error
    detector = factory(calibration, dict(options or {}))
    if detector.name != name:
        raise ValueError(f"detector factory {name} created {detector.name}")
    return detector


def _canonical_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def detector_identity(detector: SprocketDetector) -> dict[str, Any]:
    configuration = detector.configuration()
    return {"name": detector.name, "version": detector.version,
            "configuration": configuration,
            "configuration_sha256": _canonical_hash(configuration),
            "stateful": bool(detector.stateful)}


def detector_checkpoint(detector: SprocketDetector) -> dict[str, Any]:
    identity = detector_identity(detector)
    state = deepcopy(detector.get_state())
    # Fail at the verified-segment boundary rather than writing a checkpoint
    # that cannot be safely resumed from JSON.
    json.dumps(state, allow_nan=False)
    return {**identity, "state": state}


def restore_detector_checkpoint(detector: SprocketDetector, checkpoint: dict[str, Any]) -> None:
    expected = detector_identity(detector)
    for key in ("name", "version", "configuration_sha256", "stateful"):
        if checkpoint.get(key) != expected[key]:
            raise RuntimeError(f"Cannot resume: detector checkpoint has different {key}")
    state = checkpoint.get("state")
    if not isinstance(state, dict):
        raise RuntimeError("Cannot resume: detector checkpoint state is missing or invalid")
    detector.restore_state(deepcopy(state))


def restore_state_before_frame(detector: SprocketDetector, manifest: dict,
                               first_frame: int, initial_state: dict[str, Any]) -> int | None:
    """Restore the nearest verified prior segment checkpoint, or initial state."""
    predecessors = [segment for segment in manifest.get("segments", [])
                    if segment.get("verified") and segment.get("last", first_frame) < first_frame]
    previous = max(predecessors, key=lambda segment: segment["last"], default=None)
    if previous is None:
        detector.restore_state(deepcopy(initial_state))
        return None
    checkpoint = previous.get("sprocket_detector_checkpoint")
    if checkpoint is None:
        if detector.stateful:
            raise RuntimeError(
                "Cannot resume stateful sprocket detector: prior verified segment "
                f"{previous.get('first')}-{previous.get('last')} has no detector checkpoint"
            )
        detector.restore_state(deepcopy(initial_state))
        return None
    restore_detector_checkpoint(detector, checkpoint)
    return int(previous["last"])
