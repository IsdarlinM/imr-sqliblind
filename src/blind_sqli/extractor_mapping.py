from __future__ import annotations

from .events import entity_id
from .extractor_common import ExtractionError, protect_sensitive_value
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

    @staticmethod
    def _require_complete_counts(
        values: dict[str, tuple[int, bool]],
        maximum: int,
        kind: str,
    ) -> dict[str, int]:
        complete: dict[str, int] = {}
        for key, (value, truncated) in values.items():
            if truncated:
                raise ExtractionError(
                    f"{kind} count exceeds configured maximum ({maximum}) for {key}."
                )
            complete[key] = value
        return complete

    def _discover_schema_tables(
        self,
        database: DatabaseMap,
        schema_name: str,
        table_count: int,
    ) -> tuple[Schema, list[tuple[ExtractionJob, Table]]]:
        schema = database.add_schema(Schema(schema_name))
        schema_identifier = entity_id("schema", schema_name)
        table_jobs = [
            ExtractionJob(
                f"table:{index}",
                self.dialect.table_name_expression(schema_name, index),
            )
            for index in range(table_count)
        ]

        def on_table(_job: ExtractionJob, table_name: str) -> None:
            self._emit_entity(
                kind="table",
                name=table_name,
                entity_key=(schema_name, table_name),
                parent_id=schema_identifier,
                data={"schema": schema_name, "table": table_name},
            )

        table_values = self.extract_many(table_jobs, on_result=on_table)
        tables: list[tuple[ExtractionJob, Table]] = []
        for job in table_jobs:
            table = schema.add_table(Table(table_values[job.key]))
            tables.append((job, table))
        return schema, tables

    def _discover_schema_columns(
        self,
        schema_name: str,
        tables: list[tuple[ExtractionJob, Table]],
    ) -> None:
        count_expressions = {
            job.key: self.dialect.column_count_expression(
                schema_name,
                table.name,
            )
            for job, table in tables
        }
        column_counts = self._require_complete_counts(
            self.infer_many_integers_capped(
                count_expressions,
                self.config.max_items,
            ),
            self.config.max_items,
            "column",
        )
        column_jobs: list[ExtractionJob] = []
        locations: dict[str, Table] = {}
        for table_job, table in tables:
            for column_index in range(column_counts[table_job.key]):
                key = f"{table_job.key}:column:{column_index}"
                column_jobs.append(
                    ExtractionJob(
                        key,
                        self.dialect.column_name_expression(
                            schema_name,
                            table.name,
                            column_index,
                        ),
                    )
                )
                locations[key] = table

        def on_column(job: ExtractionJob, column_name: str) -> None:
            table = locations[job.key]
            self._emit_entity(
                kind="column",
                name=column_name,
                entity_key=(schema_name, table.name, column_name),
                parent_id=entity_id("table", schema_name, table.name),
                data={
                    "schema": schema_name,
                    "table": table.name,
                    "column": column_name,
                },
            )

        values = self.extract_many(column_jobs, on_result=on_column)
        for job in column_jobs:
            locations[job.key].add_column(values[job.key])

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
        """Discover schemas smallest-first and finish each before continuing.

        Schema size is defined by its table count because that bounded metadata is
        available before any table name or contents must be extracted. All table
        names in a schema are resolved first; then all columns and bounded rows are
        completed before the next schema begins.
        """
        self._emit("phase.started", phase="schemas")
        schema_count = self.infer_integer(
            self.dialect.schema_count_expression(),
            self.config.max_items,
        )
        schema_jobs = [
            ExtractionJob(str(index), self.dialect.schema_name_expression(index))
            for index in range(schema_count)
        ]
        schema_names_by_key = self.extract_many(schema_jobs)
        schema_names = [schema_names_by_key[job.key] for job in schema_jobs]

        table_count_expressions = {
            schema_name: self.dialect.table_count_expression(schema_name)
            for schema_name in schema_names
        }
        table_counts = self._require_complete_counts(
            self.infer_many_integers_capped(
                table_count_expressions,
                self.config.max_items,
            ),
            self.config.max_items,
            "table",
        )
        ordered_schemas = sorted(
            schema_names,
            key=lambda name: (table_counts[name], name.casefold()),
        )
        database = DatabaseMap()
        for priority, schema_name in enumerate(ordered_schemas, 1):
            self._emit_entity(
                kind="schema",
                name=schema_name,
                entity_key=(schema_name,),
                data={
                    "schema": schema_name,
                    "table_count": table_counts[schema_name],
                    "discovery_priority": priority,
                },
            )
        self._emit(
            "phase.completed",
            phase="schemas",
            count=len(ordered_schemas),
            order=ordered_schemas,
        )

        selectors = {value.casefold() for value in data_tables or set()}
        remaining_bytes = max_data_bytes
        discover_columns = include_columns or include_data

        for priority, schema_name in enumerate(ordered_schemas, 1):
            self.control.checkpoint()
            table_count = table_counts[schema_name]
            phase = f"schema:{schema_name}"
            self._emit(
                "phase.started",
                phase=phase,
                schema=schema_name,
                priority=priority,
                table_count=table_count,
            )
            _schema, tables = self._discover_schema_tables(
                database,
                schema_name,
                table_count,
            )

            if discover_columns and tables:
                self._discover_schema_columns(schema_name, tables)

            rows_extracted = 0
            bytes_used = 0
            if include_data and remaining_bytes > 0:
                for _job, table in tables:
                    selector = f"{schema_name}.{table.name}".casefold()
                    if selectors and selector not in selectors:
                        continue
                    count, _truncated, used = self.extract_table_rows(
                        schema_name,
                        table,
                        max_rows=max_rows,
                        max_columns=max_data_columns,
                        max_value_length=max_value_length,
                        max_data_bytes=remaining_bytes,
                        reveal_sensitive_values=reveal_sensitive_values,
                    )
                    rows_extracted += count
                    bytes_used += used
                    remaining_bytes -= used
                    if remaining_bytes <= 0:
                        self._emit(
                            "data.budget_exhausted",
                            schema=schema_name,
                            table=table.name,
                            max_data_bytes=max_data_bytes,
                        )
                        break

            self._emit(
                "phase.completed",
                phase=phase,
                schema=schema_name,
                priority=priority,
                tables=len(tables),
                columns=sum(len(table.columns) for _job, table in tables),
                rows=rows_extracted,
                data_bytes=bytes_used,
            )
        return database
