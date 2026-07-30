from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

from .events import ScanEvent
from .store import SessionStore


def _apply_batch(
    store: SessionStore,
    events: list[ScanEvent],
    stats_updates: dict[str, tuple[dict[str, Any], str]],
) -> None:
    """Use one SQLite transaction without expanding SessionStore's public API."""
    if not events and not stats_updates:
        return
    if not hasattr(store, "_lock"):
        store.apply_batch(events, stats_updates)
        return
    with store._lock:
        for event in events:
            cursor = store._connection.execute(
                "INSERT INTO events(scan_id,event_type,timestamp,payload_json) "
                "VALUES(?,?,?,?)",
                (
                    event.scan_id,
                    event.event_type,
                    event.timestamp,
                    store._dumps(event.payload),
                ),
            )
            del cursor
            entity = event.payload.get("entity")
            if isinstance(entity, dict):
                store._upsert_entity(event, entity)
            relationship = event.payload.get("relationship")
            if isinstance(relationship, dict):
                store._upsert_relationship(event, relationship)
            activity = event.payload.get("activity")
            if isinstance(activity, dict):
                store._upsert_activity(event, activity)
            store._connection.execute(
                "UPDATE scans SET updated_at=? WHERE id=?",
                (event.timestamp, event.scan_id),
            )
        for scan_id, (stats, timestamp) in stats_updates.items():
            current = store._connection.execute(
                "SELECT stats_json FROM scans WHERE id=?",
                (scan_id,),
            ).fetchone()
            if current is None:
                continue
            merged = store._loads(current["stats_json"])
            merged.update(stats)
            store._connection.execute(
                "UPDATE scans SET stats_json=?, updated_at=? WHERE id=?",
                (store._dumps(merged), timestamp, scan_id),
            )
        store._connection.commit()


@dataclass(slots=True)
class _Barrier:
    completed: threading.Event


class EventBatchWriter:
    """Batch SQLite writes and sample raw request events off worker threads."""

    def __init__(
        self,
        store: SessionStore,
        *,
        batch_size: int = 50,
        flush_interval: float = 0.1,
        request_sample: int = 20,
    ) -> None:
        self.store = store
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.request_sample = request_sample
        self._queue: queue.Queue[ScanEvent | _Barrier | None] = queue.Queue()
        self._request_counts: dict[str, int] = {}
        self._request_samples: dict[str, int] = {}
        self._settings_lock = threading.Lock()
        self._error: Exception | None = None
        self._stopped = False
        self._thread = threading.Thread(
            target=self._run,
            name="sqliblind-event-writer",
            daemon=True,
        )
        self._thread.start()

    def configure_scan(self, scan_id: str, *, request_sample: int) -> None:
        with self._settings_lock:
            self._request_samples[scan_id] = max(1, request_sample)
            self._request_counts[scan_id] = 0

    def remove_scan(self, scan_id: str) -> None:
        with self._settings_lock:
            self._request_samples.pop(scan_id, None)
            self._request_counts.pop(scan_id, None)

    def submit(self, event: ScanEvent) -> None:
        if self._stopped:
            raise RuntimeError("event writer is stopped")
        self._raise_if_failed()
        self._queue.put(event)

    def flush(self) -> None:
        self._raise_if_failed()
        barrier = _Barrier(threading.Event())
        self._queue.put(barrier)
        if not barrier.completed.wait(timeout=5.0):
            self._raise_if_failed()
            raise RuntimeError("event writer flush timed out")
        self._raise_if_failed()

    def stop(self) -> None:
        if self._stopped:
            return
        self.flush()
        self._stopped = True
        self._queue.put(None)
        self._thread.join(timeout=5.0)
        self._raise_if_failed()

    def _raise_if_failed(self) -> None:
        if self._error is not None:
            raise RuntimeError("event writer failed") from self._error

    def _sample_for(self, scan_id: str) -> tuple[int, int]:
        with self._settings_lock:
            count = self._request_counts.get(scan_id, 0) + 1
            self._request_counts[scan_id] = count
            sample = self._request_samples.get(scan_id, self.request_sample)
        return count, sample

    def _run(self) -> None:
        try:
            self._consume()
        except Exception as exc:  # pragma: no cover - defensive thread boundary
            self._error = exc
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if isinstance(item, _Barrier):
                    item.completed.set()

    def _consume(self) -> None:
        events: list[ScanEvent] = []
        stats: dict[str, tuple[dict[str, Any], str]] = {}
        last_flush = time.monotonic()

        def flush_batch() -> None:
            nonlocal events, stats, last_flush
            if events or stats:
                _apply_batch(self.store, events, stats)
                events = []
                stats = {}
            last_flush = time.monotonic()

        while True:
            elapsed = time.monotonic() - last_flush
            timeout = max(0.0, self.flush_interval - elapsed)
            try:
                item = self._queue.get(timeout=timeout)
            except queue.Empty:
                flush_batch()
                continue
            if item is None:
                flush_batch()
                return
            if isinstance(item, _Barrier):
                flush_batch()
                item.completed.set()
                continue

            event = item
            if event.event_type == "request.completed":
                count, sample = self._sample_for(event.scan_id)
                stats[event.scan_id] = (
                    {
                        "requests": event.payload.get("requests_used", count),
                        "last_request_seconds": event.payload.get(
                            "elapsed_seconds",
                            0,
                        ),
                    },
                    event.timestamp,
                )
                status = int(event.payload.get("status_code", 0) or 0)
                if count % sample == 0 or status == 429:
                    events.append(event)
            else:
                events.append(event)

            due = time.monotonic() - last_flush >= self.flush_interval
            if len(events) >= self.batch_size or due:
                flush_batch()
