"use strict";

function telemetryNumber(value, digits = 1) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? number.toFixed(digits) : "0.0";
}

function renderOperationalTelemetry() {
  const metrics = $("metrics");
  if (!metrics || !state.scan) return;
  let panel = $("operationalTelemetry");
  if (!panel) {
    panel = professionalElement("section", "professional-telemetry");
    panel.id = "operationalTelemetry";
    metrics.after(panel);
  }
  const stats = state.scan.stats || {};
  const elapsed = Number(stats.elapsed_seconds || state.scan.elapsed_seconds || 0);
  const requests = Number(stats.requests || 0);
  const rps = elapsed > 0 ? requests / elapsed : Number(stats.requests_per_second || 0);
  const failures = Number(stats.failures || stats.errors || 0);
  const concurrency = Number(stats.active_workers || stats.concurrency || state.scan.config?.workers || 0);
  const phase = $("activityPhase")?.textContent || "idle";
  const items = [
    ["RPS", telemetryNumber(rps, 2)],
    ["Effective workers", concurrency],
    ["Failures", failures],
    ["Backoff", stats.backoff_events || stats.rate_limit_events || 0],
    ["Elapsed", `${telemetryNumber(elapsed, 1)}s`],
    ["Phase", phase],
  ];
  panel.replaceChildren(...items.map(([label, value]) => {
    const card = professionalElement("div", "professional-telemetry-card");
    card.append(professionalElement("strong", "", value), professionalElement("span", "", label));
    return card;
  }));
}

const renderMetricsBeforeTelemetry = renderMetrics;
renderMetrics = function renderMetricsWithTelemetry() {
  renderMetricsBeforeTelemetry();
  renderOperationalTelemetry();
};

function graphAdvancedContext() {
  if (!graphRelationState.selectedId) return null;
  return directGraphContext(graphRelationState.selectedId);
}

function applyGraphTypeVisibility() {
  const hidden = new Set(
    [...document.querySelectorAll("[data-graph-type-toggle]:not(:checked)")].map((input) => input.value),
  );
  for (const entry of graphState.nodeElements.values()) {
    entry.group.classList.toggle("professional-graph-hidden", hidden.has(entry.entity.type));
  }
  for (const edge of graphState.edgeElements) {
    const source = graphState.nodeElements.get(edge.relation.source_id)?.entity;
    const target = graphState.nodeElements.get(edge.relation.target_id)?.entity;
    edge.path.classList.toggle(
      "professional-graph-hidden",
      hidden.has(source?.type) || hidden.has(target?.type),
    );
  }
}

function isolateSelectedGraphContext() {
  const context = graphAdvancedContext();
  if (!context) {
    toast("Select a graph node first.");
    return;
  }
  for (const [id, entry] of graphState.nodeElements.entries()) {
    entry.group.classList.toggle("professional-graph-hidden", id !== context.entity.id && !context.relatedIds.has(id));
  }
  for (const edge of graphState.edgeElements) {
    edge.path.classList.toggle("professional-graph-hidden", !context.relationIds.has(edge.relation.id));
  }
}

function centerSelectedGraphNode() {
  const id = graphRelationState.selectedId;
  const position = id && graphState.positions.get(id);
  const dimensions = id && graphState.dimensions.get(id);
  if (!position || !dimensions) {
    toast("Select a graph node first.");
    return;
  }
  const viewport = graphViewportSize();
  graphState.transform.x = viewport.width / 2 - (position.x + dimensions.width / 2) * graphState.transform.scale;
  graphState.transform.y = viewport.height / 2 - (position.y + dimensions.height / 2) * graphState.transform.scale;
  graphState.userTransformed = true;
  applyGraphTransform();
  persistProfessionalWorkspace();
}

function resetGraphVisibility() {
  graphState.nodeElements.forEach((entry) => entry.group.classList.remove("professional-graph-hidden"));
  graphState.edgeElements.forEach((entry) => entry.path.classList.remove("professional-graph-hidden"));
  applyGraphTypeVisibility();
}

function installAdvancedGraphControls() {
  const actions = document.querySelector(".graph-actions");
  if (!actions || $("graphAdvancedControls")) return;
  const controls = professionalElement("div", "professional-graph-controls");
  controls.id = "graphAdvancedControls";
  for (const type of ["schema", "table", "column", "row", "cell"]) {
    const label = professionalElement("label", "professional-graph-toggle");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = type;
    input.checked = type !== "cell";
    input.dataset.graphTypeToggle = type;
    input.addEventListener("change", applyGraphTypeVisibility);
    label.append(input, document.createTextNode(type));
    controls.append(label);
  }
  const buttons = [
    ["Center", centerSelectedGraphNode],
    ["Isolate", isolateSelectedGraphContext],
    ["Show all", resetGraphVisibility],
  ];
  buttons.forEach(([label, action]) => {
    const button = professionalElement("button", "", label);
    button.type = "button";
    button.addEventListener("click", action);
    controls.append(button);
  });
  actions.after(controls);
}

const renderGraphBeforeAdvancedControls = renderGraph;
renderGraph = function renderGraphWithAdvancedControls() {
  renderGraphBeforeAdvancedControls();
  installAdvancedGraphControls();
  applyGraphTypeVisibility();
};

function sessionEntitySignature(entity, all) {
  const parts = [];
  let current = entity;
  const seen = new Set();
  while (current && !seen.has(current.id)) {
    seen.add(current.id);
    parts.unshift(`${current.type}:${current.name}`);
    current = current.parent_id ? all.get(current.parent_id) : null;
  }
  return parts.join("/");
}

function snapshotSignatureMap(snapshot) {
  const entities = new Map((snapshot.entities || []).map((entity) => [entity.id, entity]));
  const result = new Map();
  for (const entity of entities.values()) result.set(sessionEntitySignature(entity, entities), entity);
  return result;
}

async function loadSessionSnapshot(id) {
  return (await (await api(`/api/scans/${id}/snapshot`)).json());
}

function renderSessionDiff(leftSnapshot, rightSnapshot) {
  const left = snapshotSignatureMap(leftSnapshot);
  const right = snapshotSignatureMap(rightSnapshot);
  const added = [...right.keys()].filter((key) => !left.has(key));
  const removed = [...left.keys()].filter((key) => !right.has(key));
  const changed = [...right.keys()].filter((key) =>
    left.has(key) && JSON.stringify(left.get(key)?.data || {}) !== JSON.stringify(right.get(key)?.data || {}),
  );
  const root = $("sessionDiffResults");
  const section = (title, values, kind) => {
    const block = professionalElement("section", `professional-diff-group diff-${kind}`);
    block.append(professionalElement("h3", "", `${title} (${values.length})`));
    const list = professionalElement("div", "professional-diff-list");
    values.slice(0, 1000).forEach((value) => list.append(professionalElement("code", "", value)));
    block.append(list);
    return block;
  };
  root.replaceChildren(
    section("Added", added, "added"),
    section("Removed", removed, "removed"),
    section("Changed", changed, "changed"),
  );
}

async function runSessionComparison() {
  const left = $("compareLeft")?.value;
  const right = $("compareRight")?.value;
  if (!left || !right || left === right) {
    toast("Choose two different sessions.");
    return;
  }
  const [leftSnapshot, rightSnapshot] = await Promise.all([loadSessionSnapshot(left), loadSessionSnapshot(right)]);
  renderSessionDiff(leftSnapshot, rightSnapshot);
}

async function installSessionComparison() {
  const workspace = document.querySelector(".workspace");
  if (!workspace || $("sessionComparePane")) return;
  const pane = professionalElement("section", "panel professional-compare");
  pane.id = "sessionComparePane";
  const head = professionalElement("div", "section-head");
  head.append(professionalElement("h2", "", "Compare sessions"));
  const controls = professionalElement("div", "professional-compare-controls");
  const left = professionalElement("select"); left.id = "compareLeft";
  const right = professionalElement("select"); right.id = "compareRight";
  const run = professionalElement("button", "", "Compare");
  run.type = "button";
  run.addEventListener("click", () => runSessionComparison().catch((error) => toast(error.message)));
  const scans = await (await api("/api/scans")).json();
  for (const scan of scans) {
    for (const select of [left, right]) {
      const option = professionalElement("option", "", `${scan.id.slice(0, 8)} · ${scan.status}`);
      option.value = scan.id;
      select.append(option);
    }
  }
  if (right.options.length > 1) right.selectedIndex = 1;
  controls.append(left, right, run);
  const results = professionalElement("div", "professional-diff-results");
  results.id = "sessionDiffResults";
  pane.append(head, controls, results);
  workspace.append(pane);
}

installAdvancedGraphControls();
installSessionComparison().catch(() => {});
