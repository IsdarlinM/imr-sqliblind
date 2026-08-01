"use strict";

const resetScanBeforeProfessionalUi = resetScan;
resetScan = function resetProfessionalWorkspace() {
  professionalUiState.treeExpanded.clear();
  professionalUiState.tableExpanded.clear();
  professionalUiState.elastic = null;
  if (professionalUiState.elasticFrame !== null) {
    cancelAnimationFrame(professionalUiState.elasticFrame);
    professionalUiState.elasticFrame = null;
  }
  clearProfessionalElasticClasses();
  resetScanBeforeProfessionalUi();
};

const renderGraphBeforeElasticGuard = renderGraph;
renderGraph = function renderGraphWithoutInterruptingElasticDrag() {
  if (professionalUiState.elastic) {
    updateGraphEdges();
    updateProfessionalElasticVisuals();
    return;
  }
  renderGraphBeforeElasticGuard();
};

const tableViewHtmlReportBeforeProfessionalUi = tableViewHtmlReport;
tableViewHtmlReport = function tableViewCompleteProfessionalHtmlReport() {
  const previous = new Set(professionalUiState.tableExpanded);
  for (const entity of state.entities.values()) {
    if (entity.type === "table") {
      professionalUiState.tableExpanded.add(entity.id);
    }
  }
  try {
    return tableViewHtmlReportBeforeProfessionalUi();
  } finally {
    professionalUiState.tableExpanded = previous;
    if (state.activePane === "tables") {
      renderTableView(true);
    }
  }
};
