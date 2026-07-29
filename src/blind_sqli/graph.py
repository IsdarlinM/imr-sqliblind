from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .models import DatabaseMap


FORMATS = {"tree", "relations", "mermaid"}


def render_tree(database: DatabaseMap, *, ascii_only: bool = False) -> str:
    branch, last, vertical, blank = (
        ("|-- ", "`-- ", "|   ", "    ")
        if ascii_only
        else ("├── ", "└── ", "│   ", "    ")
    )
    lines = ["DATABASE STRUCTURE"]
    if not database.schemas:
        lines.append("(no schemas found)")

    for schema_index, schema in enumerate(database.schemas):
        schema_last = schema_index == len(database.schemas) - 1
        lines.append(f"{last if schema_last else branch}[SCHEMA] {schema.name}")
        schema_prefix = blank if schema_last else vertical
        if not schema.tables:
            lines.append(f"{schema_prefix}{last}(no tables found)")
            continue

        for table_index, table in enumerate(schema.tables):
            table_last = table_index == len(schema.tables) - 1
            lines.append(
                f"{schema_prefix}{last if table_last else branch}[TABLE] {table.name}"
            )
            table_prefix = schema_prefix + (blank if table_last else vertical)
            if not table.columns:
                lines.append(f"{table_prefix}{last}(columns not enumerated)")
                continue
            for column_index, column in enumerate(table.columns):
                connector = last if column_index == len(table.columns) - 1 else branch
                lines.append(f"{table_prefix}{connector}[COLUMN] {column}")

    lines.extend(
        [
            "",
            "SUMMARY",
            f"Schemas: {database.schema_count}",
            f"Tables: {database.table_count}",
            f"Columns: {database.column_count}",
            f"Relationships: {database.relationship_count}",
        ]
    )
    return "\n".join(lines)


def render_relations(database: DatabaseMap) -> str:
    lines = ["DATABASE RELATIONSHIPS"]
    for schema in database.schemas:
        for table in schema.tables:
            lines.append(f'[SCHEMA] "{schema.name}" -> [TABLE] "{table.name}"')
            lines.extend(
                f'[TABLE] "{schema.name}.{table.name}" -> [COLUMN] "{column}"'
                for column in table.columns
            )
    if len(lines) == 1:
        lines.append("(no relationships found)")
    lines.extend(["", f"Relationships: {database.relationship_count}"])
    return "\n".join(lines)


def _mermaid_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', "&quot;").replace("\n", " ")


def render_mermaid(database: DatabaseMap) -> str:
    lines = ["flowchart LR"]
    node = 0
    for schema in database.schemas:
        schema_id = f"n{node}"
        node += 1
        lines.append(f'  {schema_id}["schema: {_mermaid_label(schema.name)}"]')
        for table in schema.tables:
            table_id = f"n{node}"
            node += 1
            lines.append(f'  {table_id}["table: {_mermaid_label(table.name)}"]')
            lines.append(f"  {schema_id} --> {table_id}")
            for column in table.columns:
                column_id = f"n{node}"
                node += 1
                lines.append(f'  {column_id}["column: {_mermaid_label(column)}"]')
                lines.append(f"  {table_id} --> {column_id}")
    if node == 0:
        lines.append('  empty["no findings"]')
    return "\n".join(lines)


def render_database_map(
    database: DatabaseMap, *, output_format: str = "tree", ascii_only: bool = False
) -> str:
    selected = output_format.casefold()
    if selected not in FORMATS:
        raise ValueError(f"Unsupported graph format: {output_format!r}")
    if selected == "tree":
        return render_tree(database, ascii_only=ascii_only)
    if selected == "relations":
        return render_relations(database)
    return render_mermaid(database)


def write_text_report(path: str | Path, content: str) -> Path:
    destination = Path(path).expanduser()
    if not destination.suffix:
        destination = destination.with_suffix(".txt")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=destination.parent, delete=False
        ) as handle:
            handle.write(content.rstrip("\n") + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return destination
