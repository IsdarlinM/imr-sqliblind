"use strict";

const tableViewState = {
  initialized: false,
};

function tableViewElement(name, className = "", text = null) {
  const element = document.createElement(name);
  if (className) {
    element.className = className;
  }
  if (text !== null) {
    element.textContent = String(text);
  }
  return element;
}

function tableViewChildren(parentId, type = null) {
  return [...state.entities.values()]
    .filter(
      (entity) =>
        entity.parent_id === parentId && (!type || entity.type === type),
    )
    .sort((left, right) =>
      String(left.name).localeCompare(String(right.name)),
    );
}

function tableViewRowValues(row) {
  const values = row?.data?.values;
  if (values && typeof values === "object" && !Array.isArray(values)) {
    return { ...values };
  }
  const result = {};
  for (const cell of tableViewChildren(row.id, "cell")) {
    const column = cell?.data?.column || cell.name;
    result[column] = cell?.data?.value ?? "";
  }
  return result;
}

function tableViewColumns(table, rows) {
  const columns = tableViewChildren(table.id, "column").map(
    (column) => column.name,
  );
  const known = new Set(columns.map((column) => column.toLocaleLowerCase()));
  for (const row of rows) {
    for (const column of Object.keys(tableViewRowValues(row))) {
      const normalized = column.toLocaleLowerCase();
      if (!known.has(normalized)) {
        known.add(normalized);
        columns.push(column);
      }
    }
  }
  return columns;
}

function appendTableViewCell(row, name, value, header = false) {
  const cell = tableViewElement(header ? "th" : "td", "", value);
  if (header) {
    cell.scope = "col";
  }
  cell.dataset.column = name;
  row.append(cell);
}

function tableViewTable(headers, rows, className) {
  const scroll = tableViewElement("div", "entity-table-scroll");
  const table = tableViewElement("table", className);
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  headers.forEach((header) =>
    appendTableViewCell(headRow, header, header, true),
  );
  head.append(headRow);

  const body = document.createElement("tbody");
  if (!rows.length) {
    const emptyRow = document.createElement("tr");
    const empty = tableViewElement("td", "entity-table-empty", "No data.");
    empty.colSpan = Math.max(1, headers.length);
    emptyRow.append(empty);
    body.append(emptyRow);
  } else {
    for (const values of rows) {
      const row = document.createElement("tr");
      headers.forEach((header, index) =>
        appendTableViewCell(row, header, values[index] ?? ""),
      );
      body.append(row);
    }
  }
  table.append(head, body);
  scroll.append(table);
  return scroll;
}

function tableViewSearchText(schema, table, columns, rows) {
  const values = rows.flatMap((row) => Object.values(tableViewRowValues(row)));
  return [schema.name, table.name, ...columns, ...values]
    .map((value) => String(value).toLocaleLowerCase())
    .join(" ");
}

function buildTableEntityCard(schema, table) {
  const rows = tableViewChildren(table.id, "row");
  const columns = tableViewColumns(table, rows);
  const article = tableViewElement("article", "entity-table-card");
  article.dataset.search = tableViewSearchText(schema, table, columns, rows);

  const heading = tableViewElement("header", "entity-table-card-head");
  const identity = tableViewElement("div");
  identity.append(
    tableViewElement("span", "entity-table-kind", "TABLE"),
    tableViewElement("h3", "", `${schema.name}.${table.name}`),
  );
  const counts = tableViewElement(
    "span",
    "entity-table-counts",
    `${columns.length} columns · ${rows.length} rows · ${
      table.status || "unknown"
    }`,
  );
  heading.append(identity, counts);

  const columnRows = columns.map((column, index) => [index + 1, column]);
  const columnTitle = tableViewElement("h4", "", "Columns");
  const columnTable = tableViewTable(
    ["#", "Column"],
    columnRows,
    "entity-table entity-table-columns",
  );

  const dataTitle = tableViewElement("h4", "", "Data");
  let data;
  if (!rows.length) {
    data = tableViewElement(
      "p",
      "entity-table-empty",
      "Rows were not extracted for this table.",
    );
  } else {
    const dataRows = rows.map((row, index) => {
      const values = tableViewRowValues(row);
      return [index + 1, ...columns.map((column) => values[column] ?? "")];
    });
    data = tableViewTable(
      ["Row", ...columns],
      dataRows,
      "entity-table entity-table-data",
    );
  }

  article.append(heading, columnTitle, columnTable, dataTitle, data);
  article.addEventListener("click", (event) => {
    if (event.target.closest?.("button, input, a")) {
      return;
    }
    openDrawer(table);
  });
  return article;
}

function renderTableView() {
  const root = $("tableEntityGrid");
  const summary = $("tableViewSummary");
  if (!root || !summary) {
    return;
  }

  const schemas = [...state.entities.values()]
    .filter((entity) => entity.type === "schema")
    .sort((left, right) =>
      String(left.name).localeCompare(String(right.name)),
    );
  const cards = [];
  for (const schema of schemas) {
    for (const table of tableViewChildren(schema.id, "table")) {
      cards.push(buildTableEntityCard(schema, table));
    }
  }

  const query = String(state.filter || "").trim().toLocaleLowerCase();
  const visible = cards.filter(
    (card) => !query || card.dataset.search.includes(query),
  );
  summary.textContent = `${visible.length}/${cards.length} tables · ${
    schemas.length
  } schemas`;

  if (!visible.length) {
    root.replaceChildren(
      tableViewElement(
        "div",
        "empty",
        cards.length
          ? "No tables match the current filter."
          : "No table entities discovered yet.",
      ),
    );
    return;
  }
  const fragment = document.createDocumentFragment();
  visible.forEach((card) => fragment.append(card));
  root.replaceChildren(fragment);
}

function activateTablePane() {
  state.activePane = "tables";
  document.querySelectorAll("[data-pane]").forEach((button) => {
    button.classList.toggle("active", button.dataset.pane === "tables");
  });
  for (const name of ["tree", "graph", "entities", "events"]) {
    $(`${name}Pane`)?.classList.add("hidden");
  }
  $("tablesPane")?.classList.remove("hidden");
  renderTableView();
}

function buildTableView() {
  if (tableViewState.initialized) {
    return;
  }
  const tabs = document.querySelector(".tabs");
  const graphButton = document.querySelector('[data-pane="graph"]');
  const entitiesPane = $("entitiesPane");
  if (!tabs || !graphButton || !entitiesPane) {
    return;
  }
  tableViewState.initialized = true;

  const button = tableViewElement("button", "", "Tables");
  button.type = "button";
  button.dataset.pane = "tables";
  button.addEventListener("click", activateTablePane);
  graphButton.after(button);

  const pane = tableViewElement(
    "section",
    "panel pane hidden entity-tables-pane",
  );
  pane.id = "tablesPane";
  pane.setAttribute("aria-label", "Tabular database map");
  const head = tableViewElement("div", "section-head");
  const title = tableViewElement("div");
  title.append(
    tableViewElement("h2", "", "Database tables"),
    tableViewElement(
      "p",
      "",
      "Schemas, columns and extracted rows represented as native HTML tables.",
    ),
  );
  const summary = tableViewElement("span", "muted", "0 tables");
  summary.id = "tableViewSummary";
  head.append(title, summary);
  const grid = tableViewElement("div", "entity-table-grid");
  grid.id = "tableEntityGrid";
  pane.append(head, grid);
  entitiesPane.before(pane);

  document
    .querySelectorAll('[data-pane]:not([data-pane="tables"])')
    .forEach((tab) => {
      tab.addEventListener("click", () => pane.classList.add("hidden"));
    });

  const exportFormat = $("exportFormat");
  if (exportFormat) {
    for (const [value, label] of [
      ["tables", "tables · ASCII text"],
      ["html-tables", "html-tables · HTML table report"],
    ]) {
      if (!exportFormat.querySelector(`option[value="${value}"]`)) {
        const option = tableViewElement("option", "", label);
        option.value = value;
        exportFormat.append(option);
      }
    }
  }
}

buildTableView();
const renderAllBeforeTableView = renderAll;
renderAll = function renderAllWithTables() {
  renderAllBeforeTableView();
  renderTableView();
};
renderTableView();

function tableViewClip(value, width) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  if (text.length <= width) {
    return text;
  }
  return width <= 3 ? text.slice(0, width) : `${text.slice(0, width - 3)}...`;
}

function tableViewAsciiTable(headers, rows, maxWidth = 180) {
  const normalized = rows.map((row) => row.map((value) => String(value ?? "")));
  const widths = headers.map((header, index) =>
    Math.min(
      42,
      Math.max(
        String(header).length,
        ...normalized.map((row) => String(row[index] ?? "").length),
      ),
    ),
  );
  const minimums = headers.map((header) =>
    Math.min(12, Math.max(3, String(header).length)),
  );
  while (
    widths.reduce(
      (total, width) => total + width,
      1 + 3 * widths.length,
    ) > maxWidth
  ) {
    const candidates = widths
      .map((width, index) => ({ width, index }))
      .filter(({ width, index }) => width > minimums[index]);
    if (!candidates.length) {
      break;
    }
    candidates.sort((left, right) => right.width - left.width);
    widths[candidates[0].index] -= 1;
  }
  const border = `+${widths
    .map((width) => "-".repeat(width + 2))
    .join("+")}+`;
  const line = (values) =>
    `|${widths
      .map((width, index) => {
        const value = tableViewClip(values[index] ?? "", width);
        return ` ${value.padEnd(width)} `;
      })
      .join("|")}|`;
  return [border, line(headers), border, ...normalized.map(line), border].join(
    "\n",
  );
}

function tableViewAsciiReport() {
  const schemas = [...state.entities.values()]
    .filter((entity) => entity.type === "schema")
    .sort((left, right) =>
      String(left.name).localeCompare(String(right.name)),
    );
  const tables = schemas.flatMap((schema) =>
    tableViewChildren(schema.id, "table").map((table) => ({ schema, table })),
  );
  const entityCounts = { schema: 0, table: 0, column: 0, row: 0, cell: 0 };
  for (const entity of state.entities.values()) {
    if (entity.type in entityCounts) {
      entityCounts[entity.type] += 1;
    }
  }
  const output = [
    "DATABASE TABLE VIEW",
    "",
    tableViewAsciiTable(
      ["Entity", "Count"],
      Object.entries(entityCounts).map(([name, count]) => [name, count]),
      64,
    ),
  ];
  for (const { schema, table } of tables) {
    const rows = tableViewChildren(table.id, "row");
    const columns = tableViewColumns(table, rows);
    output.push(
      "",
      `TABLE ${schema.name}.${table.name}`,
      tableViewAsciiTable(
        ["#", "Column"],
        columns.length
          ? columns.map((column, index) => [index + 1, column])
          : [["-", "columns not enumerated"]],
        100,
      ),
    );
    if (rows.length) {
      output.push(
        "DATA",
        tableViewAsciiTable(
          ["Row", ...columns],
          rows.map((row, index) => {
            const values = tableViewRowValues(row);
            return [
              index + 1,
              ...columns.map((column) => values[column] ?? ""),
            ];
          }),
        ),
      );
    } else {
      output.push("DATA: rows not extracted");
    }
  }
  return output.join("\n");
}

function tableViewHtmlReport() {
  renderTableView();
  const pane = $("tablesPane")?.cloneNode(true);
  if (!pane) {
    throw new Error("Table view is not available.");
  }
  pane.classList.remove("hidden", "panel", "pane");
  pane.querySelectorAll("[id]").forEach((node) => node.removeAttribute("id"));
  const content = new XMLSerializer().serializeToString(pane);
  const title = `imr-sqliblind table map ${
    state.scanId?.slice(0, 8) || "scan"
  }`;
  const style = `
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
  padding: 20px;
  background: var(--bg);
  color: var(--text);
  font: 14px/1.5 ui-monospace, Consolas, monospace;
}
.entity-table-grid { display: grid; gap: 12px; }
.entity-table-card {
  padding: 12px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 11px;
}
.entity-table-card-head {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: space-between;
}
.entity-table-kind,
.entity-table-counts,
.entity-table-empty { color: var(--muted); }
.entity-table-scroll {
  max-width: 100%;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 9px;
}
.entity-table {
  width: 100%;
  border-collapse: collapse;
  white-space: nowrap;
}
th,
td {
  padding: 7px 9px;
  text-align: left;
  border-right: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}
th { color: var(--accent); background: #10243a; }
h2,
h3,
h4 { overflow-wrap: anywhere; }
@media (max-width: 620px) {
  body { padding: 10px; }
  .entity-table-card { padding: 9px; }
}
`;
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; style-src 'unsafe-inline'; img-src data:">
<title>${title}</title>
<style>${style}</style>
</head>
<body>
<h1>${title}</h1>
${content}
<footer>Generated by imr-sqliblind. No external resources.</footer>
</body>
</html>`;
}

function downloadTableView(content, filename, mediaType) {
  const blob = new Blob([content], { type: `${mediaType};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$("exportBtn")?.addEventListener(
  "click",
  (event) => {
    const format = $("exportFormat")?.value;
    if (!state.scanId || !["tables", "html-tables"].includes(format)) {
      return;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
    const prefix = `sqliblind-${state.scanId.slice(0, 8)}-tables`;
    if (format === "tables") {
      downloadTableView(
        tableViewAsciiReport(),
        `${prefix}.txt`,
        "text/plain",
      );
    } else {
      downloadTableView(
        tableViewHtmlReport(),
        `${prefix}.html`,
        "text/html",
      );
    }
    toast(`Exported ${format}.`);
  },
  true,
);
