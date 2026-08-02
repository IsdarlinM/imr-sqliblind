"use strict";

const professionalAdvancedState = {
  minimap: null,
  minimapFrame: null,
  resizeBound: false,
  workspacePane: null,
};

function professionalWorkspacePayload() {
  if (!state.scanId) return null;
  try {
    return JSON.parse(
      localStorage.getItem(`sqliblind.workspace.${state.scanId}`) || "null",
    );
  } catch {
    return null;
  }
}

const restoreWorkspaceBeforeAdvanced = restoreProfessionalWorkspace;
restoreProfessionalWorkspace = function restoreWorkspaceWithActivePane() {
  restoreWorkspaceBeforeAdvanced();
  const payload = professionalWorkspacePayload();
  const pane = payload?.activePane;
  if (
    pane &&
    pane !== state.activePane &&
    document.querySelector(`[data-pane="${pane}"]`)
  ) {
    requestAnimationFrame(() => {
      document.querySelector(`[data-pane="${pane}"]`)?.click();
    });
  }
};

function scheduleWorkspacePersistence() {
  requestAnimationFrame(() => persistProfessionalWorkspace());
}

$("filter")?.addEventListener("input", scheduleWorkspacePersistence);
document.querySelectorAll("[data-pane]").forEach((button) => {
  button.addEventListener("click", scheduleWorkspacePersistence);
});
$("graph")?.addEventListener("pointerup", scheduleWorkspacePersistence);
$("graph")?.addEventListener("wheel", scheduleWorkspacePersistence, {
  passive: true,
});
for (const id of ["graphZoomIn", "graphZoomOut", "graphFit", "graphReset"]) {
  $(id)?.addEventListener("click", scheduleWorkspacePersistence);
}

const tableViewHtmlReportBeforeCompleteExport = tableViewHtmlReport;
tableViewHtmlReport = function tableViewHtmlReportComplete() {
  renderTableView(true);
  const cards = [...document.querySelectorAll(".professional-table-card")];
  const stateBefore = cards.map((card) => card.open);
  cards.forEach((card) => {
    if (!card.open) {
      card.open = true;
      card.dispatchEvent(new Event("toggle"));
    }
  });
  try {
    return tableViewHtmlReportBeforeCompleteExport();
  } finally {
    cards.forEach((card, index) => {
      card.open = stateBefore[index];
    });
  }
};

function graphMinimapBounds(entities) {
  const bounds = graphBounds(entities);
  if (!bounds) return null;
  const width = Math.max(1, bounds.maxX - bounds.minX);
  const height = Math.max(1, bounds.maxY - bounds.minY);
  return { ...bounds, width, height };
}

function renderGraphMinimap() {
  const canvas = professionalAdvancedState.minimap;
  if (!canvas || state.activePane !== "graph") return;
  const context = canvas.getContext("2d");
  if (!context) return;
  const entities = visibleGraphEntities();
  const bounds = graphMinimapBounds(entities);
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || 180;
  const height = canvas.clientHeight || 112;
  if (canvas.width !== Math.round(width * ratio)) {
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
  }
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, width, height);
  context.fillStyle = "rgba(7,16,28,.92)";
  context.fillRect(0, 0, width, height);
  if (!bounds) return;

  const padding = 7;
  const scale = Math.min(
    (width - padding * 2) / bounds.width,
    (height - padding * 2) / bounds.height,
  );
  const project = (x, y) => ({
    x: padding + (x - bounds.minX) * scale,
    y: padding + (y - bounds.minY) * scale,
  });

  context.globalAlpha = 0.66;
  for (const entity of entities) {
    const position = graphState.positions.get(entity.id);
    const dimensions = graphState.dimensions.get(entity.id);
    if (!position || !dimensions) continue;
    const point = project(
      position.x + dimensions.width / 2,
      position.y + dimensions.height / 2,
    );
    context.beginPath();
    context.arc(point.x, point.y, entity.type === "schema" ? 3 : 1.8, 0, Math.PI * 2);
    context.fillStyle = graphFill(entity.type);
    context.fill();
  }
  context.globalAlpha = 1;

  const viewport = graphViewportSize();
  const transform = graphState.transform;
  const worldLeft = -transform.x / transform.scale;
  const worldTop = -transform.y / transform.scale;
  const worldRight = (viewport.width - transform.x) / transform.scale;
  const worldBottom = (viewport.height - transform.y) / transform.scale;
  const start = project(worldLeft, worldTop);
  const end = project(worldRight, worldBottom);
  context.strokeStyle = "#4fd1a1";
  context.lineWidth = 1.5;
  context.strokeRect(
    start.x,
    start.y,
    Math.max(4, end.x - start.x),
    Math.max(4, end.y - start.y),
  );
  canvas.dataset.bounds = JSON.stringify(bounds);
}

function scheduleGraphMinimap() {
  if (professionalAdvancedState.minimapFrame !== null) return;
  professionalAdvancedState.minimapFrame = requestAnimationFrame(() => {
    professionalAdvancedState.minimapFrame = null;
    renderGraphMinimap();
  });
}

function installGraphMinimap() {
  const viewport = $("graphViewport");
  if (!viewport || $("graphMinimap")) return;
  const canvas = document.createElement("canvas");
  canvas.id = "graphMinimap";
  canvas.className = "professional-graph-minimap";
  canvas.setAttribute("aria-label", "Graph minimap");
  canvas.title = "Click to center the graph";
  canvas.addEventListener("pointerdown", (event) => {
    const raw = canvas.dataset.bounds;
    if (!raw) return;
    const bounds = JSON.parse(raw);
    const rectangle = canvas.getBoundingClientRect();
    const xRatio = (event.clientX - rectangle.left) / Math.max(1, rectangle.width);
    const yRatio = (event.clientY - rectangle.top) / Math.max(1, rectangle.height);
    const worldX = bounds.minX + xRatio * bounds.width;
    const worldY = bounds.minY + yRatio * bounds.height;
    const viewportSize = graphViewportSize();
    graphState.transform.x =
      viewportSize.width / 2 - worldX * graphState.transform.scale;
    graphState.transform.y =
      viewportSize.height / 2 - worldY * graphState.transform.scale;
    graphState.userTransformed = true;
    applyGraphTransform();
    renderGraphMinimap();
    persistProfessionalWorkspace();
  });
  viewport.append(canvas);
  professionalAdvancedState.minimap = canvas;
}

const renderGraphBeforeMinimap = renderGraph;
renderGraph = function renderGraphWithMinimap() {
  renderGraphBeforeMinimap();
  installGraphMinimap();
  scheduleGraphMinimap();
};

$("graph")?.addEventListener("pointermove", scheduleGraphMinimap, {
  passive: true,
});
$("graph")?.addEventListener("wheel", scheduleGraphMinimap, {
  passive: true,
});

function telemetryEstimate(activities) {
  const measurable = activities.filter(
    (item) =>
      Number.isFinite(Number(item.current)) &&
      Number.isFinite(Number(item.maximum)) &&
      Number(item.maximum) > 0,
  );
  if (!measurable.length) return "—";
  const current = measurable.reduce(
    (total, item) => total + Math.min(Number(item.current), Number(item.maximum)),
    0,
  );
  const maximum = measurable.reduce(
    (total, item) => total + Number(item.maximum),
    0,
  );
  const elapsed = Math.max(
    0,
    ...measurable.map((item) => Number(item.elapsed_seconds || 0)),
  );
  const progress = maximum ? current / maximum : 0;
  if (progress < 0.02 || progress >= 1 || elapsed <= 0) return "—";
  const remaining = Math.max(0, (elapsed / progress) * (1 - progress));
  return remaining < 90
    ? `~${Math.ceil(remaining)}s`
    : `~${Math.ceil(remaining / 60)}m`;
}

renderOperationalTelemetry = function renderLiveOperationalTelemetry() {
  const metrics = $("metrics");
  if (!metrics || !state.scan) return;
  let panel = $("operationalTelemetry");
  if (!panel) {
    panel = professionalElement("section", "professional-telemetry");
    panel.id = "operationalTelemetry";
    metrics.after(panel);
  }
  const stats = state.scan.stats || {};
  const running = [...state.activities.values()].filter(
    (activity) => activity.status === "running" && activity.active !== false,
  );
  const liveRequests = Math.max(
    Number(stats.requests || 0),
    ...running.map((item) => Number(item.requests_used || 0)),
  );
  const liveElapsed = Math.max(
    Number(stats.elapsed_seconds || state.scan.elapsed_seconds || 0),
    ...running.map((item) => Number(item.elapsed_seconds || 0)),
  );
  const rps =
    liveElapsed > 0
      ? liveRequests / liveElapsed
      : Number(stats.requests_per_second || 0);
  const failures = state.events.filter((item) =>
    /(failed|error|transport)/i.test(item.event),
  ).length;
  const backoff = state.events.filter(
    (item) =>
      /(backoff|rate.?limit|concurrency)/i.test(item.event) ||
      Number(item.payload?.status_code) === 429,
  ).length;
  const items = [
    ["RPS", telemetryNumber(rps, 2)],
    ["Effective workers", running.length || Number(stats.active_workers || 0)],
    ["Requests", liveRequests],
    ["Failures", failures],
    ["Backoff", backoff],
    ["ETA", telemetryEstimate(running)],
    ["Elapsed", `${telemetryNumber(liveElapsed, 1)}s`],
    ["Phase", $("activityPhase")?.textContent || "idle"],
  ];
  panel.replaceChildren(
    ...items.map(([label, value]) => {
      const card = professionalElement("div", "professional-telemetry-card");
      card.append(
        professionalElement("strong", "", value),
        professionalElement("span", "", label),
      );
      return card;
    }),
  );
};

function bindVerticalResize(target, property, minimum, maximumRatio) {
  if (!target || target.dataset.professionalResizeBound === "true") return;
  target.dataset.professionalResizeBound = "true";
  const handle = professionalElement("button", "professional-vertical-resizer");
  handle.type = "button";
  handle.setAttribute("aria-label", `Resize ${property}`);
  target.append(handle);
  handle.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = target.getBoundingClientRect().height;
    handle.setPointerCapture(event.pointerId);
    const move = (next) => {
      const height = Math.max(
        minimum,
        Math.min(window.innerHeight * maximumRatio, startHeight + next.clientY - startY),
      );
      document.documentElement.style.setProperty(property, `${height}px`);
    };
    const finish = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", finish);
      persistProfessionalWorkspace();
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", finish);
  });
}

function installAdvancedPanelResizers() {
  bindVerticalResize(
    document.querySelector(".activity-panel"),
    "--activity-panel-height",
    160,
    0.72,
  );
  bindVerticalResize($("graphViewport"), "--graph-height", 320, 0.88);
}

function enhanceComparisonPanel() {
  const pane = $("sessionComparePane");
  if (!pane || pane.dataset.collapsible === "true") return;
  pane.dataset.collapsible = "true";
  const head = pane.querySelector(".section-head");
  const results = $("sessionDiffResults");
  if (!head || !results) return;
  const toggle = professionalElement("button", "", "Hide comparison");
  toggle.type = "button";
  toggle.addEventListener("click", () => {
    const hidden = !results.hidden;
    results.hidden = hidden;
    const controls = pane.querySelector(".professional-compare-controls");
    if (controls) controls.hidden = hidden;
    toggle.textContent = hidden ? "Show comparison" : "Hide comparison";
  });
  head.append(toggle);
}

const renderAllBeforeAdvancedUi = renderAll;
renderAll = function renderAllAdvancedUi() {
  renderAllBeforeAdvancedUi();
  installAdvancedPanelResizers();
  enhanceComparisonPanel();
  scheduleGraphMinimap();
};

installGraphMinimap();
installAdvancedPanelResizers();
enhanceComparisonPanel();
