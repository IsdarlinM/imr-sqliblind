from __future__ import annotations

import shutil
import sys
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import TextIO

from .events import ScanEvent


_TERMINAL_ACTIVITY_STATES = {"completed", "failed", "cancelled"}
_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


@dataclass(slots=True)
class ActivityView:
    id: str
    operation: str
    target: str
    detail: str = "queued"
    status: str = "running"
    worker: str = "main"
    started_monotonic: float = field(default_factory=time.monotonic)
    updated_monotonic: float = field(default_factory=time.monotonic)
    elapsed_seconds: float = 0.0

    def merge(self, payload: dict[str, object]) -> None:
        self.operation = str(payload.get("operation", self.operation))
        self.target = str(payload.get("target", self.target))
        self.detail = str(payload.get("detail", self.detail))
        self.status = str(payload.get("status", self.status))
        self.worker = str(payload.get("worker", self.worker))
        if "elapsed_seconds" in payload:
            self.elapsed_seconds = float(payload["elapsed_seconds"])
        self.updated_monotonic = time.monotonic()

    @property
    def elapsed(self) -> float:
        if self.status in _TERMINAL_ACTIVITY_STATES:
            return self.elapsed_seconds
        return max(self.elapsed_seconds, time.monotonic() - self.started_monotonic)


class ActivityMonitor:
    """Render concurrent extraction activity without a misleading percentage."""

    def __init__(
        self,
        *,
        mode: str = "auto",
        workers: int = 1,
        stream: TextIO | None = None,
        max_lines: int = 8,
        refresh_interval: float = 0.12,
    ) -> None:
        if mode not in {"auto", "live", "plain", "off"}:
            raise ValueError("progress mode must be auto, live, plain, or off")
        self.stream = stream or sys.stderr
        if mode == "auto":
            mode = "live" if self._isatty(self.stream) else "off"
        self.mode = mode
        self.workers = workers
        self.max_lines = max(2, max_lines)
        self.refresh_interval = max(0.05, refresh_interval)
        self._activities: dict[str, ActivityView] = {}
        self._recent: deque[ActivityView] = deque(maxlen=3)
        self._findings: Counter[str] = Counter()
        self._phase = "starting"
        self._requests = 0
        self._started = time.monotonic()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._dirty = threading.Event()
        self._thread: threading.Thread | None = None
        self._rendered_lines = 0
        self._closed = False

    @staticmethod
    def _isatty(stream: TextIO) -> bool:
        try:
            return bool(stream.isatty())
        except (AttributeError, OSError):
            return False

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    def __enter__(self) -> "ActivityMonitor":
        if self.mode == "live":
            self._thread = threading.Thread(
                target=self._render_loop,
                name="sqliblind-progress",
                daemon=True,
            )
            self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def __call__(self, event: ScanEvent) -> None:
        if not self.enabled or self._closed:
            return
        with self._lock:
            if event.event_type == "request.completed":
                self._requests = int(event.payload.get("requests_used", self._requests))
            elif event.event_type == "phase.started":
                self._phase = str(event.payload.get("phase", "working"))
                self._plain(f"→ phase: {self._phase}")
            elif event.event_type == "phase.completed":
                phase = str(event.payload.get("phase", self._phase))
                count = event.payload.get("count")
                suffix = f" ({count} found)" if count is not None else ""
                self._plain(f"✓ phase: {phase}{suffix}")
            elif event.event_type.startswith("activity."):
                activity = event.payload.get("activity")
                if isinstance(activity, dict):
                    self._apply_activity(event.event_type, activity)
            elif event.event_type.endswith(".discovered"):
                entity = event.payload.get("entity")
                if isinstance(entity, dict):
                    self._findings[str(entity.get("type", "finding"))] += 1
            self._dirty.set()

    def _apply_activity(self, event_type: str, payload: dict[str, object]) -> None:
        identifier = str(payload.get("id", ""))
        if not identifier:
            return
        current = self._activities.get(identifier)
        if current is None:
            current = ActivityView(
                id=identifier,
                operation=str(payload.get("operation", "Working")),
                target=str(payload.get("target", "")),
                detail=str(payload.get("detail", "queued")),
                status=str(payload.get("status", "running")),
                worker=str(payload.get("worker", "main")),
            )
            self._activities[identifier] = current
        current.merge(payload)
        if event_type == "activity.started":
            self._plain(
                f"→ [{current.worker}] {current.operation}: {current.target}"
            )
        if current.status in _TERMINAL_ACTIVITY_STATES:
            self._activities.pop(identifier, None)
            self._recent.appendleft(current)
            symbol = "✓" if current.status == "completed" else "×"
            self._plain(
                f"{symbol} [{current.worker}] {current.operation}: "
                f"{current.target} · {current.detail} · {current.elapsed:.2f}s"
            )

    def _plain(self, text: str) -> None:
        if self.mode == "plain":
            self.stream.write(text + "\n")
            self.stream.flush()

    def _render_loop(self) -> None:
        while not self._stop.wait(self.refresh_interval):
            self.render()

    def render(self, *, final: bool = False) -> None:
        if self.mode != "live" or self._closed:
            return
        with self._lock:
            lines = self._build_lines(final=final)
            previous = self._rendered_lines
            if previous:
                self.stream.write(f"\x1b[{previous}F")
            total = max(previous, len(lines))
            for index in range(total):
                line = lines[index] if index < len(lines) else ""
                self.stream.write("\x1b[2K" + line + "\n")
            self.stream.flush()
            self._rendered_lines = len(lines)
            self._dirty.clear()

    def _build_lines(self, *, final: bool) -> list[str]:
        width = max(72, shutil.get_terminal_size((110, 24)).columns)
        elapsed = time.monotonic() - self._started
        active = sorted(
            self._activities.values(),
            key=lambda item: (item.worker, item.started_monotonic),
        )
        title = (
            f"SQLIBLIND ACTIVITY  phase={self._phase}  active={len(active)}  "
            f"requests={self._requests}  elapsed={elapsed:.1f}s  workers={self.workers}"
        )
        lines = [self._clip(title, width)]
        spinner = "✓" if final else _SPINNER[int(time.monotonic() * 10) % len(_SPINNER)]
        room = self.max_lines - 2
        for activity in active[:room]:
            line = (
                f" {spinner} [{activity.worker}] {activity.operation:<23} "
                f"{activity.target}  · {activity.detail}  · {activity.elapsed:.1f}s"
            )
            lines.append(self._clip(line, width))
        if len(active) > room:
            lines.append(f" … {len(active) - room} additional active tasks")
        elif not active and self._recent:
            recent = self._recent[0]
            symbol = "✓" if recent.status == "completed" else "×"
            lines.append(
                self._clip(
                    f" {symbol} [{recent.worker}] {recent.operation} "
                    f"{recent.target} · {recent.detail} · {recent.elapsed:.1f}s",
                    width,
                )
            )
        elif not active:
            lines.append(" · waiting for the next extraction activity")
        findings = "  ".join(
            f"{kind}={count}" for kind, count in sorted(self._findings.items())
        )
        lines.append(self._clip("Findings: " + (findings or "none yet"), width))
        return lines

    @staticmethod
    def _clip(value: str, width: int) -> str:
        if len(value) <= width:
            return value
        return value[: max(1, width - 1)] + "…"

    def close(self) -> None:
        if self._closed:
            return
        if self.mode == "live":
            self.render(final=True)
            self._stop.set()
            if self._thread is not None and self._thread is not threading.current_thread():
                self._thread.join(timeout=1.0)
            self.stream.write("\n")
            self.stream.flush()
        self._closed = True
