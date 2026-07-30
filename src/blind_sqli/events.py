from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


class ScanCancelled(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ScanEvent:
    event_type: str
    scan_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event_type,
            "scan_id": self.scan_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }


EventCallback = Callable[[ScanEvent], None]


def entity_id(kind: str, *parts: str) -> str:
    digest = hashlib.sha256("\x00".join((kind, *parts)).encode("utf-8")).hexdigest()
    return f"{kind}:{digest[:20]}"


def relationship_id(source_id: str, target_id: str, kind: str) -> str:
    return entity_id("rel", source_id, target_id, kind)


class ScanControl:
    """Cooperative pause/resume/cancel control shared by extractor workers."""

    def __init__(self) -> None:
        self._resume = threading.Event()
        self._resume.set()
        self._stop = threading.Event()

    def pause(self) -> None:
        self._resume.clear()

    def resume(self) -> None:
        self._resume.set()

    def stop(self) -> None:
        self._stop.set()
        self._resume.set()

    @property
    def paused(self) -> bool:
        return not self._resume.is_set() and not self._stop.is_set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def checkpoint(self) -> None:
        if self._stop.is_set():
            raise ScanCancelled("Scan cancelled by user")
        while not self._resume.wait(timeout=0.1):
            if self._stop.is_set():
                raise ScanCancelled("Scan cancelled by user")
            time.sleep(0)
        if self._stop.is_set():
            raise ScanCancelled("Scan cancelled by user")


class EventEmitter:
    def __init__(
        self,
        scan_id: str = "cli",
        callback: EventCallback | None = None,
    ) -> None:
        self.scan_id = scan_id
        self.callback = callback

    def emit(self, event_type: str, **payload: Any) -> ScanEvent:
        event = ScanEvent(event_type=event_type, scan_id=self.scan_id, payload=payload)
        if self.callback is not None:
            self.callback(event)
        return event
