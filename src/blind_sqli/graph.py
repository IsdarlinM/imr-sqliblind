from __future__ import annotations

import html
import os
import tempfile
from pathlib import Path

from .models import DatabaseMap
from .table_reports import render_ascii_tables, render_html_tables

FORMATS = {"tree", "relations", "mermaid", "html", "tables", "html-tables"}


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
        for table_index, table in enumerate(schema.tables):
            table_last = table_index == len(schema.tables) - 1
            lines.append(
                f"{schema_prefix}{last if table_last else branch}"
                f"[TABLE] {table.name}"
            )
            table_prefix = schema_prefix + (blank if table_last else vertical)
            children: list[tuple[str, str]] = [
                ("COLUMN", column) for column in table.columns
            ] + [("ROW", f"row {index + 1}") for index in range(len(table.rows))]
            if not children:
                lines.append(
                    f"{table_prefix}{last}"
                    "(columns not enumerated; no rows extracted)"
                )
            for child_index, (kind, value) in enumerate(children):
                child_last = child_index == len(children) - 1
                connector = last if child_last else branch
                lines.append(f"{table_prefix}{connector}[{kind}] {value}")
                if kind == "ROW":
                    row = table.rows[int(value.split()[-1]) - 1]
                    row_prefix = table_prefix + (blank if child_last else vertical)
                    cells = list(row.items())
                    for cell_index, (column, cell_value) in enumerate(cells):
                        cell_connector = (
                            last if cell_index == len(cells) - 1 else branch
                        )
                        lines.append(
                            f"{row_prefix}{cell_connector}[CELL] "
                            f"{column}={cell_value}"
                        )
    lines.extend(
        [
            "",
            "SUMMARY",
            f"Schemas: {database.schema_count}",
            f"Tables: {database.table_count}",
            f"Columns: {database.column_count}",
            f"Rows: {database.row_count}",
            f"Cells: {database.cell_count}",
            f"Relationships: {database.relationship_count}",
        ]
    )
    return "\n".join(lines)


def render_relations(database: DatabaseMap) -> str:
    lines = ["DATABASE RELATIONSHIPS"]
    for schema in database.schemas:
        for table in schema.tables:
            lines.append(f'[SCHEMA] "{schema.name}" -> [TABLE] "{table.name}"')
            for column in table.columns:
                lines.append(
                    f'[TABLE] "{schema.name}.{table.name}" '
                    f'-> [COLUMN] "{column}"'
                )
            for row_index, row in enumerate(table.rows):
                row_name = f"row {row_index + 1}"
                lines.append(
                    f'[TABLE] "{schema.name}.{table.name}" '
                    f'-> [ROW] "{row_name}"'
                )
                for column, value in row.items():
                    lines.append(
                        f'[ROW] "{schema.name}.{table.name}.{row_name}" -> '
                        f'[CELL] "{column}={value}"'
                    )
    if len(lines) == 1:
        lines.append("(no relationships found)")
    lines.extend(
        [
            "",
            f"Relationships: {database.relationship_count}",
            f"Schemas: {database.schema_count}",
            f"Tables: {database.table_count}",
            f"Columns: {database.column_count}",
            f"Rows: {database.row_count}",
            f"Cells: {database.cell_count}",
        ]
    )
    return "\n".join(lines)


def _mermaid_label(value: object) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', "&quot;")
        .replace("\r", " ")
        .replace("\n", " ")
    )


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
                lines.append(
                    f'  {column_id}["column: {_mermaid_label(column)}"]'
                )
                lines.append(f"  {table_id} --> {column_id}")
            for row_index, row in enumerate(table.rows):
                row_id = f"n{node}"
                node += 1
                lines.append(f'  {row_id}["row: {row_index + 1}"]')
                lines.append(f"  {table_id} --> {row_id}")
                for column, value in row.items():
                    cell_id = f"n{node}"
                    node += 1
                    label = _mermaid_label(f"{column}={value}")
                    lines.append(f'  {cell_id}["cell: {label}"]')
                    lines.append(f"  {row_id} --> {cell_id}")
    if node == 0:
        lines.append('  empty["no findings"]')
    return "\n".join(lines)


def _render_html_schemas(database: DatabaseMap) -> str:
    if not database.schemas:
        return '<p class="empty">No schemas found.</p>'
    sections: list[str] = []
    for schema in database.schemas:
        tables: list[str] = []
        for table in schema.tables:
            columns = "".join(
                '<li><span class="kind">COLUMN</span>'
                f"<code>{html.escape(column)}</code></li>"
                for column in table.columns
            ) or '<li class="empty">Columns not enumerated.</li>'
            rows: list[str] = []
            for index, row in enumerate(table.rows):
                cells = "".join(
                    '<li><span class="kind">CELL</span>'
                    f"<code>{html.escape(column)}="
                    f"{html.escape(str(value))}</code></li>"
                    for column, value in row.items()
                )
                rows.append(
                    '<details class="row" open><summary>'
                    f"ROW {index + 1}</summary><ul>{cells}</ul></details>"
                )
            row_html = "".join(rows) or '<p class="empty">Rows not extracted.</p>'
            tables.append(
                '<details class="table" open><summary>'
                '<span class="kind">TABLE</span>'
                f"<code>{html.escape(table.name)}</code></summary>"
                f'<ul class="columns">{columns}</ul>'
                f'<div class="rows">{row_html}</div></details>'
            )
        tables_html = "".join(tables) or '<p class="empty">No tables.</p>'
        sections.append(
            '<details class="schema" open><summary>'
            '<span class="kind">SCHEMA</span>'
            f"<code>{html.escape(schema.name)}</code></summary>"
            f'<div class="tables">{tables_html}</div></details>'
        )
    return "".join(sections)


def render_html(
    database: DatabaseMap,
    *,
    title: str = "imr-sqliblind schema map",
) -> str:
    safe_title = html.escape(title)
    graph = _render_html_schemas(database)
    style = """
:root {
  color-scheme: dark;
  --bg: #07111f;
  --panel: #0d1b2d;
  --line: #29415f;
  --text: #e5edf7;
  --muted: #8fa5bf;
  --accent: #54d2a0;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 14px/1.5 ui-monospace, Consolas, monospace;
}
header, main { padding: 20px clamp(14px, 4vw, 48px); }
header {
  position: sticky;
  top: 0;
  background: var(--bg);
  border-bottom: 1px solid var(--line);
}
input, button {
  background: var(--panel);
  border: 1px solid var(--line);
  color: var(--text);
  padding: 8px;
  border-radius: 8px;
}
details {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 10px;
  margin: 9px 0;
  padding: 8px;
}
summary { cursor: pointer; }
.tables, .rows, .columns, ul {
  margin-left: 20px;
  border-left: 1px solid var(--line);
  padding-left: 16px;
}
li { list-style: none; padding: 5px; }
.kind { color: var(--muted); font-size: 10px; margin-right: 8px; }
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 8px;
}
.stat {
  background: var(--panel);
  border: 1px solid var(--line);
  padding: 12px;
  border-radius: 10px;
}
.stat strong { display: block; color: var(--accent); font-size: 22px; }
.hidden { display: none; }
.empty { color: var(--muted); }
"""
    script = """
const all = [...document.querySelectorAll('details')];
document.getElementById('expand').onclick = () => {
  all.forEach((node) => { node.open = true; });
};
document.getElementById('collapse').onclick = () => {
  all.forEach((node) => { node.open = false; });
};
document.getElementById('search').oninput = (event) => {
  const query = event.target.value.toLowerCase();
  document.querySelectorAll('details.schema').forEach((node) => {
    node.classList.toggle(
      'hidden',
      Boolean(query) && !node.textContent.toLowerCase().includes(query),
    );
  });
};
"""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; style-src 'unsafe-inline';
               script-src 'unsafe-inline'; img-src data:">
<title>{safe_title}</title>
<style>{style}</style>
</head>
<body>
<header>
<h1>{safe_title}</h1>
<input id="search" type="search" placeholder="Filter">
<button id="expand" type="button">Expand all</button>
<button id="collapse" type="button">Collapse all</button>
</header>
<main>
<section class="stats">
<div class="stat"><strong>{database.schema_count}</strong>Schemas</div>
<div class="stat"><strong>{database.table_count}</strong>Tables</div>
<div class="stat"><strong>{database.column_count}</strong>Columns</div>
<div class="stat"><strong>{database.row_count}</strong>Rows</div>
<div class="stat"><strong>{database.cell_count}</strong>Cells</div>
</section>
<section id="graph">{graph}</section>
<footer class="empty">
Generated by imr-sqliblind. Self-contained report; No external resources.
</footer>
</main>
<script>{script}</script>
</body>
</html>"""


def render_database_map(
    database: DatabaseMap,
    *,
    output_format: str = "tree",
    ascii_only: bool = False,
    title: str = "imr-sqliblind schema map",
) -> str:
    selected = output_format.casefold()
    if selected not in FORMATS:
        raise ValueError(
            f"Unsupported graph format: {output_format!r}. "
            f"Choose one of: {', '.join(sorted(FORMATS))}."
        )
    if selected == "tree":
        return render_tree(database, ascii_only=ascii_only)
    if selected == "relations":
        return render_relations(database)
    if selected == "mermaid":
        return render_mermaid(database)
    if selected == "tables":
        return render_ascii_tables(database)
    if selected == "html-tables":
        return render_html_tables(database, title=title)
    return render_html(database, title=title)


def write_report(
    path: str | Path,
    content: str,
    *,
    default_suffix: str = ".txt",
) -> Path:
    destination = Path(path).expanduser()
    if not destination.suffix:
        destination = destination.with_suffix(default_suffix)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
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


def write_text_report(path: str | Path, content: str) -> Path:
    return write_report(path, content, default_suffix=".txt")
