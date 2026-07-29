from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Table:
    """In-memory table representation used by reports and future exporters."""

    name: str
    columns: list[str]
    rows: list[dict[str, Any]] = field(default_factory=list)

    def add_row(self, values: list[Any]) -> None:
        if len(values) != len(self.columns):
            raise ValueError(
                f"Expected {len(self.columns)} values, received {len(values)}."
            )
        self.rows.append(dict(zip(self.columns, values, strict=True)))


@dataclass(slots=True)
class Schema:
    name: str
    tables: list[Table] = field(default_factory=list)

    def add_table(self, table: Table) -> None:
        if any(existing.name.casefold() == table.name.casefold() for existing in self.tables):
            return
        self.tables.append(table)


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
