"use strict";

const renderTableViewImmediately = renderTableView;
renderTableView = function renderTableViewWhenVisible(force = false) {
  if (!force && state.activePane !== "tables") {
    return;
  }
  renderTableViewImmediately();
};

const tableViewHtmlReportBeforeLazyRender = tableViewHtmlReport;
tableViewHtmlReport = function tableViewHtmlReportWithFreshContent() {
  renderTableViewImmediately();
  return tableViewHtmlReportBeforeLazyRender();
};

// Keep every ASCII row within the requested width, including schemas with the
// maximum supported number of columns. Long headers are clipped like values.
tableViewAsciiTable = function boundedTableViewAsciiTable(
  headers,
  rows,
  maxWidth = 180,
) {
  const normalized = rows.map((row) =>
    row.map((value) => String(value ?? "")),
  );
  const widths = headers.map((header, index) =>
    Math.min(
      42,
      Math.max(
        String(header).length,
        ...normalized.map((row) => String(row[index] ?? "").length),
      ),
    ),
  );
  const minimums = headers.map(() => 3);
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
    candidates.sort(
      (left, right) =>
        right.width - minimums[right.index] -
        (left.width - minimums[left.index]),
    );
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
  return [
    border,
    line(headers),
    border,
    ...normalized.map(line),
    border,
  ].join("\n");
};
