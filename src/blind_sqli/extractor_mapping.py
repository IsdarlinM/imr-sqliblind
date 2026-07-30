from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor

from .events import entity_id
from .extractor_common import protect_sensitive_value
from .extractor_inference import InferenceExtractor
from .models import DatabaseMap, ExtractionJob, Schema, Table


class BlindExtractor(InferenceExtractor):
    """Schema/table/column pipeline built on the optimized inference engine."""

    def enumerate_schemas(self) -> list[str]:
        self._emit("phase.started", phase="schemas")
        count = self.infer_integer(
            self.dialect.schema_count_expression(),
            self.config.max_items,
        )
        jobs = [
            ExtractionJob(str(index), self.dialect.schema_name_expression(index))
            for index in range(count)
        ]
        values = self.extract_many(
            jobs,
            on_result=lambda _job, name: self._emit_entity(
                kind="schema",
                name=name,
                entity_key=(name,),
                data={"schema": name},
            ),
        )
        self._emit("phase.completed", phase="schemas", count=len(values))
        return list(values.values())

    def enumerate_tables(self, schema: str) -> list[str]:
        count = self.infer_integer(
            self.dialect.table_count_expression(schema),
            self.config.max_items,
        )
        schema_identifier = entity_id("schema", schema)
        jobs = [
            ExtractionJob(
                str(index),
                self.dialect.table_name_expression(schema, index),
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
        count = self.infer_integer(
            self.dialect.column_count_expression(schema, table),
            self.config.max_items,
        )
        table_identifier = entity_id("table", schema, table)
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

        with self.activity(
            "Extract bounded rows",
            f"{schema}.{table.name}",
            detail="counting rows and selected columns",
            kind="data",
        ):
            selected_columns = table.columns[:max_columns]
            count, truncated = self.infer_integer_capped(
                self.dialect.row_count_expression(schema, table.name),
                max_rows,
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
                remaining_bytes = max_data_bytes - bytes_used
                if remaining_bytes <= 0:
                    truncated = True
                    break

                jobs = [
                    ExtractionJob(
                        column,
                        self.dialect.cell_value_expression(
                            schema,
                            table.name,
                            column,
                            row_index,
                            selected_columns[0],
                        ),
                    )
                    for column in selected_columns
                ]
                values = self.extract_many(
                    jobs,
                    maximum_length=min(max_value_length, remaining_bytes),
                )

                for column in selected_columns:
                    remaining_bytes = max_data_bytes - bytes_used
                    if remaining_bytes <= 0:
                        truncated = True
                        row_truncated = True
                        break
                    value = values[column]
                    encoded = value.encode("utf-8")
                    if len(encoded) > remaining_bytes:
                        value = encoded[:remaining_bytes].decode(
                            "utf-8",
                            errors="ignore",
                        )
                        encoded = value.encode("utf-8")
                        truncated = True
                        row_truncated = True
                    if value.endswith("…"):
                        truncated = True
                        row_truncated = True
                    bytes_used += len(encoded)
                    display_value = protect_sensitive_value(
                        column,
                        value,
                        reveal=reveal_sensitive_values,
                    )
                    row_values[column] = display_value
                    self._emit_entity(
                        kind="cell",
                        name=column,
                        entity_key=(
                            schema,
                            table.name,
                            str(row_index),
                            column,
                        ),
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
                    break

            self._activity_update(
                f"stored {len(table.rows)} rows, {bytes_used} bytes",
                force=True,
                current=len(table.rows),
                unit="rows",
            )
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
        """Pipeline schema names, table counts, names, and column counts."""
        schema_count = self.infer_integer(
            self.dialect.schema_count_expression(),
            self.config.max_items,
        )
        schema_jobs = [
            ExtractionJob(str(index), self.dialect.schema_name_expression(index))
            for index in range(schema_count)
        ]
        table_count_futures: dict[str, Future[int]] = {}
        count_workers = min(max(1, self.config.workers // 3), 4)

        with ThreadPoolExecutor(
            max_workers=count_workers,
            thread_name_prefix="sqliblind-pipeline",
        ) as count_pool:

            def on_schema(_job: ExtractionJob, schema_name: str) -> None:
                self._emit_entity(
                    kind="schema",
                    name=schema_name,
                    entity_key=(schema_name,),
                    data={"schema": schema_name},
                )
                table_count_futures[schema_name] = count_pool.submit(
                    self.infer_integer,
                    self.dialect.table_count_expression(schema_name),
                    self.config.max_items,
                )

            schema_names = list(
                self.extract_many(schema_jobs, on_result=on_schema).values()
            )
            database = DatabaseMap([Schema(name) for name in schema_names])
            table_jobs: list[ExtractionJob] = []
            table_locations: dict[str, tuple[int, str]] = {}
            for schema_index, schema_name in enumerate(schema_names):
                count = table_count_futures[schema_name].result()
                for table_index in range(count):
                    key = f"s{schema_index}:t{table_index}"
                    table_jobs.append(
                        ExtractionJob(
                            key,
                            self.dialect.table_name_expression(
                                schema_name,
                                table_index,
                            ),
                        )
                    )
                    table_locations[key] = schema_index, schema_name

            column_count_futures: dict[str, Future[int]] = {}

            def on_table(job: ExtractionJob, table_name: str) -> None:
                _, schema_name = table_locations[job.key]
                self._emit_entity(
                    kind="table",
                    name=table_name,
                    entity_key=(schema_name, table_name),
                    parent_id=entity_id("schema", schema_name),
                    data={"schema": schema_name, "table": table_name},
                )
                if include_columns:
                    column_count_futures[job.key] = count_pool.submit(
                        self.infer_integer,
                        self.dialect.column_count_expression(
                            schema_name,
                            table_name,
                        ),
                        self.config.max_items,
                    )

            table_values = self.extract_many(table_jobs, on_result=on_table)
            table_objects: dict[str, Table] = {}
            for job in table_jobs:
                schema_index, _ = table_locations[job.key]
                table_objects[job.key] = database.schemas[
                    schema_index
                ].add_table(Table(table_values[job.key]))

            if include_columns:
                column_jobs: list[ExtractionJob] = []
                column_locations: dict[str, tuple[str, str, Table]] = {}
                for table_job in table_jobs:
                    _, schema_name = table_locations[table_job.key]
                    table_name = table_values[table_job.key]
                    count = column_count_futures[table_job.key].result()
                    for column_index in range(count):
                        key = f"{table_job.key}:c{column_index}"
                        column_jobs.append(
                            ExtractionJob(
                                key,
                                self.dialect.column_name_expression(
                                    schema_name,
                                    table_name,
                                    column_index,
                                ),
                            )
                        )
                        column_locations[key] = (
                            schema_name,
                            table_name,
                            table_objects[table_job.key],
                        )

                def on_column(job: ExtractionJob, column_name: str) -> None:
                    schema_name, table_name, _ = column_locations[job.key]
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

                column_values = self.extract_many(
                    column_jobs,
                    on_result=on_column,
                )
                for job in column_jobs:
                    _, _, table = column_locations[job.key]
                    table.add_column(column_values[job.key])

        if include_data:
            selectors = {value.casefold() for value in data_tables or set()}
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
