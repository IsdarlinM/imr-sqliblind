from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Table:
    """In-memory table representation used by reports and exporters."""

    name: str
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)

    def add_column(self, column: str) -> None:
        if not column:
            raise ValueError("column cannot be empty")
        if any(existing.casefold() == column.casefold() for existing in self.columns):
            return
        self.columns.append(column)

    def add_row(self, values: list[Any]) -> None:
        if len(values) != len(self.columns):
            raise ValueError(
                f"Expected {len(self.columns)} values, received {len(values)}."
            )
        self.rows.append(dict(zip(self.columns, values, strict=True)))

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "columns": list(self.columns),
            "rows": list(self.rows),
        }


@dataclass(slots=True)
class Schema:
    name: str
    tables: list[Table] = field(default_factory=list)

    def add_table(self, table: Table) -> Table:
        for existing in self.tables:
            if existing.name.casefold() == table.name.casefold():
                for column in table.columns:
                    existing.add_column(column)
                return existing
        self.tables.append(table)
        return table

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "tables": [table.to_dict() for table in self.tables],
        }


@dataclass(slots=True)
class DatabaseMap:
    schemas: list[Schema] = field(default_factory=list)

    def add_schema(self, schema: Schema) -> Schema:
        for existing in self.schemas:
            if existing.name.casefold() == schema.name.casefold():
                for table in schema.tables:
                    existing.add_table(table)
                return existing
        self.schemas.append(schema)
        return schema

    @property
    def schema_count(self) -> int:
        return len(self.schemas)

    @property
    def table_count(self) -> int:
        return sum(len(schema.tables) for schema in self.schemas)

    @property
    def column_count(self) -> int:
        return sum(
            len(table.columns)
            for schema in self.schemas
            for table in schema.tables
        )

    @property
    def row_count(self) -> int:
        return sum(
            len(table.rows)
            for schema in self.schemas
            for table in schema.tables
        )

    @property
    def cell_count(self) -> int:
        return sum(
            len(row)
            for schema in self.schemas
            for table in schema.tables
            for row in table.rows
        )

    @property
    def relationship_count(self) -> int:
        return self.table_count + self.column_count + self.row_count + self.cell_count

    def to_dict(self) -> dict[str, object]:
        return {
            "schemas": [schema.to_dict() for schema in self.schemas],
            "summary": {
                "schemas": self.schema_count,
                "tables": self.table_count,
                "columns": self.column_count,
                "rows": self.row_count,
                "cells": self.cell_count,
                "relationships": self.relationship_count,
            },
        }


@dataclass(frozen=True, slots=True)
class ExtractionJob:
    key: str
    expression: str


@dataclass(frozen=True, slots=True)
class ProbeResult:
    matched: bool
    status_code: int
    body_length: int
    elapsed_seconds: float
    final_url: str
