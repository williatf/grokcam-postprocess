"""Typed progress events shared by the public API and CLI adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable


EVENT_PROTOCOL = "grokcam.postprocess.events"
EVENT_SCHEMA_VERSION = 1


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class ProcessingProgressEvent:
    """One immutable, JSON-serializable progress notification."""

    protocol: str
    schema_version: int
    sequence: int
    event: str
    job_id: str
    emitted_at: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventEmitter:
    """Assign protocol envelope fields before invoking a client callback."""

    def __init__(self, job_id: str, sink: Callable[[ProcessingProgressEvent], None] | None):
        self.job_id = job_id
        self.sink = sink
        self.sequence = 0

    def emit(self, event: str, payload: dict[str, Any] | None = None) -> ProcessingProgressEvent:
        self.sequence += 1
        value = ProcessingProgressEvent(
            protocol=EVENT_PROTOCOL,
            schema_version=EVENT_SCHEMA_VERSION,
            sequence=self.sequence,
            event=event,
            job_id=self.job_id,
            emitted_at=utc_timestamp(),
            payload=payload or {},
        )
        if self.sink is not None:
            self.sink(value)
        return value
