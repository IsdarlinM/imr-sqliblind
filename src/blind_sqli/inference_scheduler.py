from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import TypeVar

from .extractor_common import job_activity
from .models import ExtractionJob, ProbeResult

T = TypeVar("T")
R = TypeVar("R")


class InferenceSchedulingMixin:
    """Global entity/position scheduler shared by all inference modes."""

    def _start_batch_activity(
        self,
        job: ExtractionJob,
        index: int,
    ) -> dict[str, object]:
        operation, target = job_activity(job)
        with self._activity_lock:
            identifier = (
                f"activity:{self.events.scan_id}:{next(self._activity_counter)}"
            )
        value: dict[str, object] = {
            "id": identifier,
            "operation": operation,
            "target": target,
            "detail": "queued for extraction",
            "kind": "batch",
            "status": "queued",
            "active": False,
            "worker": f"scheduler-{index + 1}",
            "requests_used": self.client.requests_used,
            "_started_monotonic": time.monotonic(),
        }
        self._emit("activity.queued", activity=self._activity_payload(value))
        return value

    def _update_batch_activity(
        self,
        value: dict[str, object],
        current: int,
        maximum: int,
    ) -> None:
        value.update(
            detail=f"extracted character {current}/{maximum}",
            current=current,
            maximum=maximum,
            unit="characters",
            requests_used=self.client.requests_used,
        )
        self._emit("activity.updated", activity=self._activity_payload(value))

    def _finish_batch_activity(
        self,
        value: dict[str, object],
        *,
        failed: str | None = None,
    ) -> None:
        started = float(value.pop("_started_monotonic", time.monotonic()))
        value.update(
            status="failed" if failed else "completed",
            active=False,
            detail=failed[:240] if failed else "extraction complete",
            elapsed_seconds=round(time.monotonic() - started, 6),
            requests_used=self.client.requests_used,
        )
        event = "activity.failed" if failed else "activity.completed"
        self._emit(event, activity=self._activity_payload(value))

    def _worker_activity_store(self) -> dict[str, dict[str, object]]:
        with self._activity_lock:
            value = getattr(self, "_live_worker_activities", None)
            if value is None:
                value = {}
                self._live_worker_activities = value
            return value

    def _activate_worker_activity(
        self,
        operation: str,
        target: str,
        detail: str,
    ) -> str:
        thread = threading.current_thread()
        identifier = (
            f"worker:{self.events.scan_id}:{thread.ident or threading.get_ident()}"
        )
        now = time.monotonic()
        with self._activity_lock:
            workers = getattr(self, "_live_worker_activities", None)
            if workers is None:
                workers = {}
                self._live_worker_activities = workers
            value = workers.get(identifier)
            if value is None:
                value = {
                    "id": identifier,
                    "operation": operation,
                    "target": target,
                    "detail": detail,
                    "kind": "worker",
                    "status": "running",
                    "active": True,
                    "worker": thread.name,
                    "requests_used": self.client.requests_used,
                    "_started_monotonic": now,
                    "_last_emit": 0.0,
                }
                workers[identifier] = value
                event = "activity.started"
            else:
                value.update(
                    operation=operation,
                    target=target,
                    detail=detail,
                    kind="worker",
                    status="running",
                    active=True,
                    worker=thread.name,
                    requests_used=self.client.requests_used,
                )
                event = "activity.updated"

            should_emit = (
                event == "activity.started"
                or now - float(value.get("_last_emit", 0.0)) >= 0.04
            )
            if should_emit:
                value["_last_emit"] = now
                payload = self._activity_payload(value)
            else:
                payload = None

        if payload is not None:
            self._emit(event, activity=payload)
        return identifier

    def _finish_worker_activities(
        self,
        identifiers: set[str],
        *,
        failed: str | None = None,
    ) -> None:
        for identifier in sorted(identifiers):
            with self._activity_lock:
                workers = getattr(self, "_live_worker_activities", None)
                if not workers:
                    continue
                value = workers.pop(identifier, None)
                if value is None:
                    continue
                started = float(
                    value.pop("_started_monotonic", time.monotonic())
                )
                value.update(
                    status="failed" if failed else "completed",
                    active=False,
                    detail=failed[:240] if failed else "worker idle",
                    elapsed_seconds=round(time.monotonic() - started, 6),
                    requests_used=self.client.requests_used,
                )
                payload = self._activity_payload(value)
            event = "activity.failed" if failed else "activity.completed"
            self._emit(event, activity=payload)

    def _execute_worker_task(
        self,
        used_workers: set[str],
        used_lock: threading.Lock,
        operation: str,
        target: str,
        detail: str,
        function: Callable[..., R],
        *args: object,
    ) -> R:
        identifier = self._activate_worker_activity(
            operation,
            target,
            detail,
        )
        with used_lock:
            used_workers.add(identifier)
        try:
            return function(*args)
        except Exception as exc:
            self._finish_worker_activities(
                {identifier},
                failed=str(exc),
            )
            raise

    def _parallel_map(
        self,
        items: Sequence[T],
        function: Callable[[T], R],
        on_result: Callable[[T, R], None] | None = None,
        activity_factory: Callable[[T, int], tuple[str, str, str]] | None = None,
    ) -> list[R]:
        if not items:
            return []
        workers = min(self.config.workers, len(items))
        values: list[R | None] = [None] * len(items)

        def tracked(index: int, item: T) -> R:
            if activity_factory is None:
                operation, target = job_activity(item)
                detail = "running on worker"
            else:
                operation, target, detail = activity_factory(item, index)
            with self.activity(operation, target, detail=detail):
                return function(item)

        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="sqliblind",
        ) as executor:
            futures = {
                executor.submit(tracked, index, item): (index, item)
                for index, item in enumerate(items)
            }
            try:
                for future in as_completed(futures):
                    index, item = futures[future]
                    result = future.result()
                    values[index] = result
                    if on_result is not None:
                        on_result(item, result)
            except Exception:
                for future in futures:
                    future.cancel()
                raise
        return [value for value in values if value is not None]

    def _measure_job_lengths(
        self,
        jobs: list[ExtractionJob],
        maximum_length: int,
        activities: list[dict[str, object]],
    ) -> list[tuple[int, bool]]:
        lengths: list[tuple[int, bool] | None] = [None] * len(jobs)
        workers = min(self.config.workers, max(1, len(jobs)))
        used_workers: set[str] = set()
        used_lock = threading.Lock()

        def measure(index: int, job: ExtractionJob) -> tuple[int, bool]:
            operation, target = job_activity(job)
            return self._execute_worker_task(
                used_workers,
                used_lock,
                operation,
                target,
                "measuring value length",
                self.infer_integer_capped,
                self.dialect.length_expression(job.expression),
                maximum_length,
            )

        try:
            with ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="sqliblind-length",
            ) as executor:
                future_map = {
                    executor.submit(measure, index, job): index
                    for index, job in enumerate(jobs)
                }
                for future in as_completed(future_map):
                    index = future_map[future]
                    lengths[index] = future.result()
                    activities[index]["detail"] = (
                        f"length resolved: {lengths[index][0]}"
                    )
                    self._emit(
                        "activity.updated",
                        activity=self._activity_payload(activities[index]),
                    )
        finally:
            self._finish_worker_activities(used_workers)

        return [
            value if value is not None else (0, False)
            for value in lengths
        ]

    def _extract_jobs(
        self,
        jobs: list[ExtractionJob],
        *,
        maximum_length: int,
        on_result: Callable[[ExtractionJob, str], None] | None,
    ) -> dict[str, str]:
        if not jobs:
            return {}
        activities = [
            self._start_batch_activity(job, index)
            for index, job in enumerate(jobs)
        ]

        try:
            resolved_lengths = self._measure_job_lengths(
                jobs,
                maximum_length,
                activities,
            )
            char_results: list[list[str | None]] = [
                [None] * length for length, _ in resolved_lengths
            ]
            remaining = [len(values) for values in char_results]
            completed_callbacks: set[int] = set()

            def complete_if_ready(index: int) -> None:
                if remaining[index] != 0 or index in completed_callbacks:
                    return
                value = "".join(
                    char for char in char_results[index] if char is not None
                )
                if resolved_lengths[index][1]:
                    value += "…"
                completed_callbacks.add(index)
                if on_result is not None:
                    on_result(jobs[index], value)

            total_positions = sum(remaining)
            if total_positions == 0:
                for index in range(len(jobs)):
                    complete_if_ready(index)
            elif not self.parallel_characters:
                self._extract_positions_serial(
                    jobs,
                    char_results,
                    remaining,
                    activities,
                    complete_if_ready,
                )
            elif self.inference_mode == "bitwise":
                self._extract_positions_bitwise(
                    jobs,
                    char_results,
                    remaining,
                    activities,
                    complete_if_ready,
                )
            else:
                self._extract_positions_parallel(
                    jobs,
                    char_results,
                    remaining,
                    activities,
                    complete_if_ready,
                )

            results: dict[str, str] = {}
            for index, job in enumerate(jobs):
                value = "".join(
                    char for char in char_results[index] if char is not None
                )
                if resolved_lengths[index][1]:
                    value += "…"
                results[job.key] = value
                self._finish_batch_activity(activities[index])
            return results
        except Exception as exc:
            for activity in activities:
                if activity.get("status") not in {"completed", "failed"}:
                    self._finish_batch_activity(activity, failed=str(exc))
            raise

    def _extract_positions_serial(
        self,
        jobs: list[ExtractionJob],
        results: list[list[str | None]],
        remaining: list[int],
        activities: list[dict[str, object]],
        complete: Callable[[int], None],
    ) -> None:
        used_workers: set[str] = set()
        used_lock = threading.Lock()
        try:
            for index, job in enumerate(jobs):
                maximum = len(results[index])
                operation, target = job_activity(job)
                for offset in range(maximum):
                    expression = self.dialect.char_code_expression(
                        job.expression,
                        offset + 1,
                    )
                    code = self._execute_worker_task(
                        used_workers,
                        used_lock,
                        operation,
                        target,
                        f"character {offset + 1}/{maximum}",
                        self._infer_character_code,
                        expression,
                        offset + 1,
                    )
                    results[index][offset] = chr(code)
                    self._update_batch_activity(
                        activities[index],
                        offset + 1,
                        maximum,
                    )
                remaining[index] = 0
                complete(index)
        finally:
            self._finish_worker_activities(used_workers)

    def _extract_positions_parallel(
        self,
        jobs: list[ExtractionJob],
        results: list[list[str | None]],
        remaining: list[int],
        activities: list[dict[str, object]],
        complete: Callable[[int], None],
    ) -> None:
        total = sum(remaining)
        pool_size = min(self.config.workers, max(1, total))
        used_workers: set[str] = set()
        used_lock = threading.Lock()

        def infer_position(
            index: int,
            offset: int,
            expression: str,
        ) -> int:
            operation, target = job_activity(jobs[index])
            return self._execute_worker_task(
                used_workers,
                used_lock,
                operation,
                target,
                f"character {offset + 1}/{len(results[index])}",
                self._infer_character_code,
                expression,
                offset + 1,
            )

        try:
            with ThreadPoolExecutor(
                max_workers=pool_size,
                thread_name_prefix="sqliblind-char",
            ) as executor:
                futures: dict[Future[int], tuple[int, int]] = {}
                for index, job in enumerate(jobs):
                    for offset in range(len(results[index])):
                        expression = self.dialect.char_code_expression(
                            job.expression,
                            offset + 1,
                        )
                        future = executor.submit(
                            infer_position,
                            index,
                            offset,
                            expression,
                        )
                        futures[future] = index, offset
                for future in as_completed(futures):
                    index, offset = futures[future]
                    results[index][offset] = chr(future.result())
                    remaining[index] -= 1
                    completed = len(results[index]) - remaining[index]
                    self._update_batch_activity(
                        activities[index],
                        completed,
                        len(results[index]),
                    )
                    complete(index)
        finally:
            self._finish_worker_activities(used_workers)

    def _extract_positions_bitwise(
        self,
        jobs: list[ExtractionJob],
        results: list[list[str | None]],
        remaining: list[int],
        activities: list[dict[str, object]],
        complete: Callable[[int], None],
    ) -> None:
        bits = max(1, self.config.max_char_code.bit_length())
        candidates = [[0] * len(values) for values in results]
        task_count = sum(remaining) * bits
        pool_size = min(self.config.workers, max(1, task_count))
        used_workers: set[str] = set()
        used_lock = threading.Lock()

        def probe_bit(
            index: int,
            offset: int,
            bit: int,
            condition: str,
        ) -> ProbeResult:
            operation, target = job_activity(jobs[index])
            return self._execute_worker_task(
                used_workers,
                used_lock,
                operation,
                target,
                (
                    f"character {offset + 1}/{len(results[index])} · "
                    f"bit {bit + 1}/{bits}"
                ),
                self.probe_condition,
                condition,
            )

        def confirm_candidate(
            index: int,
            offset: int,
            code_expression: str,
            candidate: int,
        ) -> bool:
            operation, target = job_activity(jobs[index])
            return self._execute_worker_task(
                used_workers,
                used_lock,
                operation,
                target,
                (
                    f"confirm character {offset + 1}/{len(results[index])} "
                    f"as code {candidate}"
                ),
                self._confirm_candidate,
                code_expression,
                candidate,
            )

        def recover_candidate(
            index: int,
            offset: int,
            code_expression: str,
        ) -> int:
            operation, target = job_activity(jobs[index])
            return self._execute_worker_task(
                used_workers,
                used_lock,
                operation,
                target,
                f"recover character {offset + 1}/{len(results[index])}",
                self._recover_character,
                code_expression,
                offset + 1,
            )

        try:
            with ThreadPoolExecutor(
                max_workers=pool_size,
                thread_name_prefix="sqliblind-bit",
            ) as executor:
                bit_futures: dict[
                    Future[ProbeResult],
                    tuple[int, int, int],
                ] = {}
                for index, job in enumerate(jobs):
                    for offset in range(len(results[index])):
                        code_expression = self.dialect.char_code_expression(
                            job.expression,
                            offset + 1,
                        )
                        for bit in range(bits):
                            mask = 1 << bit
                            condition = f"(({code_expression}) & {mask}) <> 0"
                            future = executor.submit(
                                probe_bit,
                                index,
                                offset,
                                bit,
                                condition,
                            )
                            bit_futures[future] = index, offset, mask

                for future in as_completed(bit_futures):
                    index, offset, mask = bit_futures[future]
                    self._metric("bit_probes")
                    if future.result().matched:
                        candidates[index][offset] |= mask

                confirm_futures: dict[
                    Future[bool],
                    tuple[int, int, str],
                ] = {}
                recover_futures: dict[
                    Future[int],
                    tuple[int, int],
                ] = {}
                for index, job in enumerate(jobs):
                    for offset, candidate in enumerate(candidates[index]):
                        code_expression = self.dialect.char_code_expression(
                            job.expression,
                            offset + 1,
                        )
                        in_range = (
                            self.config.min_char_code
                            <= candidate
                            <= self.config.max_char_code
                        )
                        if not in_range:
                            future = executor.submit(
                                recover_candidate,
                                index,
                                offset,
                                code_expression,
                            )
                            recover_futures[future] = index, offset
                            continue
                        future = executor.submit(
                            confirm_candidate,
                            index,
                            offset,
                            code_expression,
                            candidate,
                        )
                        confirm_futures[future] = (
                            index,
                            offset,
                            code_expression,
                        )

                for future in as_completed(recover_futures):
                    index, offset = recover_futures[future]
                    self._complete_bitwise_position(
                        index,
                        offset,
                        future.result(),
                        results,
                        remaining,
                        activities,
                        complete,
                    )

                for future in as_completed(confirm_futures):
                    index, offset, code_expression = confirm_futures[future]
                    candidate = candidates[index][offset]
                    if future.result():
                        self._record_code(candidate)
                        self._metric("characters")
                    else:
                        candidate = recover_candidate(
                            index,
                            offset,
                            code_expression,
                        )
                    self._complete_bitwise_position(
                        index,
                        offset,
                        candidate,
                        results,
                        remaining,
                        activities,
                        complete,
                    )
        finally:
            self._finish_worker_activities(used_workers)

    def _complete_bitwise_position(
        self,
        index: int,
        offset: int,
        candidate: int,
        results: list[list[str | None]],
        remaining: list[int],
        activities: list[dict[str, object]],
        complete: Callable[[int], None],
    ) -> None:
        results[index][offset] = chr(candidate)
        remaining[index] -= 1
        completed = len(results[index]) - remaining[index]
        self._update_batch_activity(
            activities[index],
            completed,
            len(results[index]),
        )
        complete(index)

    def extract_string(
        self,
        expression: str,
        *,
        maximum_length: int | None = None,
    ) -> str:
        key = "scalar"
        values = self._extract_jobs(
            [ExtractionJob(key, expression)],
            maximum_length=maximum_length or self.config.max_length,
            on_result=None,
        )
        return values[key]

    def extract_many(
        self,
        jobs: list[ExtractionJob],
        *,
        maximum_length: int | None = None,
        on_result: Callable[[ExtractionJob, str], None] | None = None,
        activity_operation: str | None = None,
        activity_target: Callable[[ExtractionJob, int], str] | None = None,
    ) -> dict[str, str]:
        # Retained for API compatibility. Batch activities derive better names
        # directly from each SQL expression.
        del activity_operation, activity_target
        return self._extract_jobs(
            jobs,
            maximum_length=maximum_length or self.config.max_length,
            on_result=on_result,
        )
