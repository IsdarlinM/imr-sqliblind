from __future__ import annotations

import html
from collections.abc import Iterable, Sequence

from .models import DatabaseMap, Table

DEFAULT_MAX_COLUMN_WIDTH = 42
DEFAULT_MAX_TABLE_WIDTH = 180


def _flat_text(value: object) -> str:
    return " ".join(str(value).replace("\x00", "").split())


def _clip(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    if width <= 3:
        return value[:width]
    return value[: width - 3] + "..."


def _table_widths(
    headers: Sequence[str],
    rows: Sequence[Sequence[object]],
    *,
    max_column_width: int = DEFAULT_MAX_COLUMN_WIDTH,
    max_table_width: int = DEFAULT_MAX_TABLE_WIDTH,
) -> list[int]:
    columns = len(headers)
    normalized = [[_flat_text(cell) for cell in row] for row in rows]
    widths = []
    for index, header in enumerate(headers):
        values = [_flat_text(header)] + [
            row[index] if index < len(row) else "" for row in normalized
        ]
        widths.append(min(max(len(value) for value in values), max_column_width))

    minimums = [3] * columns
    while sum(widths) + 3 * columns + 1 > max_table_width:
        candidates = [
            index for index, width in enumerate(widths) if width > minimums[index]
        ]
        if not candidates:
            break
        selected = max(candidates, key=lambda index: widths[index] - minimums[index])
        widths[selected] -= 1
    return widths


def ascii_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[object]],
    *,
    max_column_width: int = DEFAULT_MAX_COLUMN_WIDTH,
    max_table_width: int = DEFAULT_MAX_TABLE_WIDTH,
) -> str:
    if not headers:
        return ""
    materialized = [list(row) for row in rows]
    widths = _table_widths(
        headers,
        materialized,
        max_column_width=max_column_width,
        max_table_width=max_table_width,
    )

    def border() -> str:
        return "+" + "+".join("-" * (width + 2) for width in widths) + "+"

    def line(values: Sequence[object]) -> str:
        cells = []
        for index, width in enumerate(widths):
            value = _flat_text(values[index]) if index < len(values) else ""
            cells.append(f" {_clip(value, width):<{width}} ")
        return "|" + "|".join(cells) + "|"

    output = [border(), line(headers), border()]
    output.extend(line(row) for row in materialized)
    output.append(border())
    return "\n".join(output)


def _data_columns(table: Table) -> list[str]:
    columns = list(table.columns)
    known = {column.casefold() for column in columns}
    for row in table.rows:
        for column in row:
            if column.casefold() not in known:
                known.add(column.casefold())
                columns.append(column)
    return columns


def render_ascii_tables(database: DatabaseMap) -> str:
    lines = ["DATABASE TABLE VIEW", ""]
    summary_rows = [
        ("Schemas", database.schema_count),
        ("Tables", database.table_count),
        ("Columns", database.column_count),
        ("Rows", database.row_count),
        ("Cells", database.cell_count),
        ("Relationships", database.relationship_count),
    ]
    lines.append(ascii_table(("Entity", "Count"), summary_rows, max_table_width=64))

    if not database.schemas:
        lines.extend(("", "(no schemas found)"))
        return "\n".join(lines)

    for schema in database.schemas:
        if not schema.tables:
            lines.extend(("", f"SCHEMA {schema.name}", "(no tables found)"))
            continue
        for table in schema.tables:
            qualified = f"{schema.name}.{table.name}"
            lines.extend(("", f"TABLE {qualified}"))
            column_rows = [
                (index, column) for index, column in enumerate(table.columns, 1)
            ]
            lines.append(
                ascii_table(
                    ("#", "Column"),
                    column_rows or [("-", "columns not enumerated")],
                    max_table_width=100,
                )
            )

            if table.rows:
                columns = _data_columns(table)
                data_rows = [
                    [index, *(row.get(column, "") for column in columns)]
                    for index, row in enumerate(table.rows, 1)
                ]
                lines.extend(
                    (
                        "DATA",
                        ascii_table(
                            ("Row", *columns),
                            data_rows,
                            max_column_width=32,
                            max_table_width=DEFAULT_MAX_TABLE_WIDTH,
                        ),
                    )
                )
            else:
                lines.append("DATA: rows not extracted")
    return "\n".join(lines)


def _html_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[object]],
    *,
    css_class: str = "",
) -> str:
    head = "".join(
        f'<th scope="col">{html.escape(_flat_text(value))}</th>'
        for value in headers
    )
    body_rows = []
    for row in rows:
        cells = "".join(
            f"<td>{html.escape(_flat_text(value))}</td>" for value in row
        )
        body_rows.append(f"<tr>{cells}</tr>")
    body = "".join(body_rows) or (
        f'<tr><td colspan="{max(1, len(headers))}" '
        'class="empty">No data.</td></tr>'
    )
    class_name = f' class="{html.escape(css_class)}"' if css_class else ""
    return (
        f'<div class="table-scroll"><table{class_name}>'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody>"
        "</table></div>"
    )


def render_html_tables(
    database: DatabaseMap,
    *,
    title: str = "imr-sqliblind table map",
) -> str:
    safe_title = html.escape(title)
    summary = _html_table(
        ("Entity", "Count"),
        (
            ("Schemas", database.schema_count),
            ("Tables", database.table_count),
            ("Columns", database.column_count),
            ("Rows", database.row_count),
            ("Cells", database.cell_count),
            ("Relationships", database.relationship_count),
        ),
        css_class="summary-table",
    )
    cards = []
    for schema in database.schemas:
        if not schema.tables:
            cards.append(
                '<article class="db-table-card" data-search="'
                + html.escape(schema.name.casefold(), quote=True)
                + '"><h2>'
                + html.escape(schema.name)
                + '</h2><p class="empty">No tables found.</p></article>'
            )
            continue
        for table in schema.tables:
            qualified = f"{schema.name}.{table.name}"
            columns = _html_table(
                ("#", "Column"),
                ((index, column) for index, column in enumerate(table.columns, 1)),
                css_class="columns-table",
            )
            data = '<p class="empty">Rows not extracted.</p>'
            if table.rows:
                data_columns = _data_columns(table)
                data = _html_table(
                    ("Row", *data_columns),
                    (
                        (index, *(row.get(column, "") for column in data_columns))
                        for index, row in enumerate(table.rows, 1)
                    ),
                    css_class="data-table",
                )
            search_text = " ".join(
                [
                    qualified,
                    *table.columns,
                    *(
                        str(value)
                        for row in table.rows
                        for value in row.values()
                    ),
                ]
            ).casefold()
            cards.append(
                '<article class="db-table-card" data-search="'
                + html.escape(search_text, quote=True)
                + '"><header><div><span class="kind">TABLE</span><h2>'
                + html.escape(qualified)
                + '</h2></div><span class="counts">'
                + f"{len(table.columns)} columns · {len(table.rows)} rows"
                + "</span></header><h3>Columns</h3>"
                + columns
                + "<h3>Data</h3>"
                + data
                + "</article>"
            )

    content = "".join(cards) or '<p class="empty">No schemas found.</p>'
    style = """
:root {
  color-scheme: dark;
  --bg: #07101c;
  --panel: #0d1a2a;
  --line: #29415f;
  --text: #e7eef8;
  --muted: #91a5bd;
  --accent: #4fd1a1;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 14px/1.5 ui-monospace, Consolas, monospace;
}
header.page {
  position: sticky;
  z-index: 5;
  top: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  padding: 16px clamp(12px, 4vw, 42px);
  background: rgb(7 16 28 / 0.96);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(10px);
}
main { padding: 18px clamp(12px, 4vw, 42px); }
input {
  min-width: min(340px, 100%);
  padding: 9px 10px;
  color: var(--text);
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
}
.db-table-card {
  margin: 14px 0;
  padding: 14px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
}
.db-table-card > header {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
}
.db-table-card h2,
.db-table-card h3 { margin: 0; }
.db-table-card h3 {
  margin-top: 14px;
  color: var(--muted);
  font-size: 12px;
}
.kind,
.counts,
.empty { color: var(--muted); }
.kind { font-size: 10px; }
.counts { font-size: 12px; }
.table-scroll {
  max-width: 100%;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 9px;
}
table {
  width: 100%;
  border-collapse: collapse;
  white-space: nowrap;
}
th,
td {
  padding: 8px 10px;
  text-align: left;
  border-right: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}
th {
  position: sticky;
  top: 0;
  background: #11243a;
  color: var(--accent);
}
tr:last-child td { border-bottom: 0; }
th:last-child,
td:last-child { border-right: 0; }
.summary { max-width: 520px; }
.hidden { display: none !important; }
@media (max-width: 620px) {
  header.page { align-items: stretch; }
  input { min-width: 0; width: 100%; }
  .db-table-card { padding: 10px; }
  th,
  td { padding: 7px 8px; }
}
"""
    script = """
const search = document.getElementById('search');
search.addEventListener('input', () => {
  const query = search.value.trim().toLowerCase();
  document.querySelectorAll('.db-table-card').forEach((card) => {
    card.classList.toggle(
      'hidden',
      Boolean(query) && !card.dataset.search.includes(query),
    );
  });
});
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
<header class="page">
<div>
<strong>{safe_title}</strong>
<div class="empty">Self-contained tabular database map</div>
</div>
<input id="search" type="search"
       placeholder="Filter schema, table, column or value">
</header>
<main>
<section class="summary"><h2>Summary</h2>{summary}</section>
<section id="tables">{content}</section>
<footer class="empty">
Generated by imr-sqliblind. No external resources.
</footer>
</main>
<script>{script}</script>
</body>
</html>"""
