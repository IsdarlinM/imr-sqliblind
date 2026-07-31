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
