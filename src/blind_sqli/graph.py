from __future__ import annotations

import html
import os
import tempfile
from pathlib import Path

from .models import DatabaseMap


FORMATS = {"tree", "relations", "mermaid", "html"}


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
    lines.extend(
        [
            "",
            f"Relationships: {database.relationship_count}",
            f"Schemas: {database.schema_count}",
            f"Tables: {database.table_count}",
            f"Columns: {database.column_count}",
        ]
    )
    return "\n".join(lines)


def _mermaid_label(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
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
                lines.append(f'  {column_id}["column: {_mermaid_label(column)}"]')
                lines.append(f"  {table_id} --> {column_id}")
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
            if table.columns:
                columns = "".join(
                    '<li class="column"><span class="kind">COLUMN</span>'
                    f"<code>{html.escape(column)}</code></li>"
                    for column in table.columns
                )
            else:
                columns = '<li class="empty small">Columns not enumerated.</li>'
            tables.append(
                '<details class="table node" open>'
                '<summary><span class="kind">TABLE</span>'
                f"<code>{html.escape(table.name)}</code>"
                f'<span class="count">{len(table.columns)} columns</span></summary>'
                f'<ul class="columns">{columns}</ul></details>'
            )
        if not tables:
            tables.append('<p class="empty small">No tables found.</p>')
        sections.append(
            '<details class="schema node" open>'
            '<summary><span class="kind">SCHEMA</span>'
            f"<code>{html.escape(schema.name)}</code>"
            f'<span class="count">{len(schema.tables)} tables</span></summary>'
            f'<div class="tables">{"".join(tables)}</div></details>'
        )
    return "".join(sections)


def render_html(database: DatabaseMap, *, title: str = "blind-sqli schema map") -> str:
    safe_title = html.escape(title)
    graph = _render_html_schemas(database)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:">
<title>{safe_title}</title>
<style>
:root {{ color-scheme: dark; --bg:#07111f; --panel:#0d1b2d; --line:#29415f; --text:#e5edf7; --muted:#8fa5bf; --accent:#54d2a0; --schema:#76b7ff; --table:#e8bd68; }}
* {{ box-sizing:border-box }}
body {{ margin:0; font:14px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace; background:var(--bg); color:var(--text) }}
header {{ position:sticky; top:0; z-index:2; padding:22px clamp(16px,4vw,48px); background:rgba(7,17,31,.96); border-bottom:1px solid var(--line) }}
h1 {{ margin:0 0 12px; font-size:clamp(22px,4vw,36px) }}
.controls {{ display:flex; gap:10px; flex-wrap:wrap }}
input,button {{ border:1px solid var(--line); background:var(--panel); color:var(--text); border-radius:8px; padding:9px 12px; font:inherit }}
input {{ min-width:min(420px,100%); flex:1 }} button {{ cursor:pointer }} button:hover {{ border-color:var(--accent) }}
main {{ padding:24px clamp(16px,4vw,48px) 48px; max-width:1400px; margin:auto }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:24px }}
.stat {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px }}
.stat strong {{ display:block; font-size:24px; color:var(--accent) }}
.node {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; margin:12px 0; overflow:hidden }}
.node > summary {{ display:flex; align-items:center; gap:10px; cursor:pointer; padding:13px 16px; list-style:none }}
.node > summary::-webkit-details-marker {{ display:none }}
.node > summary::before {{ content:'▸'; color:var(--muted) }} .node[open] > summary::before {{ content:'▾' }}
.schema > summary {{ border-left:4px solid var(--schema) }} .table > summary {{ border-left:4px solid var(--table) }}
.kind {{ color:var(--muted); font-size:11px; letter-spacing:.08em }} .count {{ margin-left:auto; color:var(--muted); font-size:12px }}
.tables {{ margin:0 14px 14px 30px; padding-left:18px; border-left:1px solid var(--line) }}
.columns {{ list-style:none; margin:0 14px 14px 30px; padding:4px 0 4px 18px; border-left:1px solid var(--line) }}
.column {{ display:flex; gap:10px; align-items:center; padding:7px 10px; margin:4px 0; border-radius:7px; background:#091728 }}
.empty {{ color:var(--muted); padding:16px }} .small {{ padding:8px 12px }}
.hidden {{ display:none !important }}
footer {{ color:var(--muted); padding-top:24px; text-align:center }}
@media (max-width:600px) {{ .count {{ display:none }} .tables,.columns {{ margin-left:14px }} }}
</style>
</head>
<body>
<header>
<h1>{safe_title}</h1>
<div class="controls">
<input id="search" type="search" placeholder="Filter schemas, tables, or columns" autocomplete="off">
<button id="expand" type="button">Expand all</button>
<button id="collapse" type="button">Collapse all</button>
</div>
</header>
<main>
<section class="stats" aria-label="Summary">
<div class="stat"><strong>{database.schema_count}</strong>Schemas</div>
<div class="stat"><strong>{database.table_count}</strong>Tables</div>
<div class="stat"><strong>{database.column_count}</strong>Columns</div>
<div class="stat"><strong>{database.relationship_count}</strong>Relationships</div>
</section>
<section id="graph" aria-label="Database graph">{graph}</section>
<footer>Generated by blind-sqli. Self-contained report; No external resources.</footer>
</main>
<script>
const all = [...document.querySelectorAll('details.node')];
document.getElementById('expand').addEventListener('click', () => all.forEach(x => x.open = true));
document.getElementById('collapse').addEventListener('click', () => all.forEach(x => x.open = false));
document.getElementById('search').addEventListener('input', event => {{
  const query = event.target.value.trim().toLowerCase();
  document.querySelectorAll('details.schema').forEach(schema => {{
    const match = !query || schema.textContent.toLowerCase().includes(query);
    schema.classList.toggle('hidden', !match);
    if (query && match) schema.open = true;
  }});
}});
</script>
</body>
</html>
"""


def render_database_map(
    database: DatabaseMap,
    *,
    output_format: str = "tree",
    ascii_only: bool = False,
    title: str = "blind-sqli schema map",
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
    return render_html(database, title=title)


def write_report(
    path: str | Path, content: str, *, default_suffix: str = ".txt"
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
