"use strict";

const professionalUiState = {
  treeExpanded: new Set(),
  tableExpanded: new Set(),
  density: localStorage.getItem("sqliblind.ui.density") || "compact",
  elastic: null,
  elasticFrame: null,
  cleanupTimer: null,
  initialized: false,
};

const ELASTIC_GRAPH = Object.freeze({
  maxDepth: 4,
  maxNodes: 120,
  weights: Object.freeze([1, 0.58, 0.34, 0.2, 0.12]),
  settleMilliseconds: 1100,
});

function professionalElement(name, className = "", text = null) {
  const element = document.createElement(name);
  if (className) {
    element.className = className;
  }
  if (text !== null) {
    element.textContent = String(text);
  }
  return element;
}

function professionalChildrenMap() {
  const result = new Map();
  for (const entity of state.entities.values()) {
    const parent = entity.parent_id || null;
    if (!result.has(parent)) {
      result.set(parent, []);
    }
    result.get(parent).push(entity);
  }
  for (const values of result.values()) {
    values.sort(
      (left, right) =>
        String(left.type).localeCompare(String(right.type)) ||
        String(left.name).localeCompare(String(right.name)),
    );
  }
  return result;
}

function professionalEntityPath(entity) {
  const parts = [entity.name];
  const seen = new Set([entity.id]);
  let current = entity;
  while (current?.parent_id && !seen.has(current.parent_id)) {
    seen.add(current.parent_id);
    current = state.entities.get(current.parent_id);
    if (current) {
      parts.unshift(current.name);
    }
  }
  return parts.join(".");
}

function professionalBranchMatcher(childMap) {
  const query = String(state.filter || "").trim().toLocaleLowerCase();
  const cache = new Map();
  const matches = (entity, visiting = new Set()) => {
    if (!query) {
      return true;
    }
    if (cache.has(entity.id)) {
      return cache.get(entity.id);
    }
    if (visiting.has(entity.id)) {
      return false;
    }
    visiting.add(entity.id);
    const direct = `${entity.type} ${entity.name} ${professionalEntityPath(
      entity,
    )} ${JSON.stringify(entity.data || {})}`
      .toLocaleLowerCase()
      .includes(query);
    const nested = (childMap.get(entity.id) || []).some((child) =>
      matches(child, visiting),
    );
    visiting.delete(entity.id);
    cache.set(entity.id, direct || nested);
    return direct || nested;
  };
  return { query, matches };
}

function professionalTreeOpen(entity, query) {
  if (query) {
    return true;
  }
  if (professionalUiState.treeExpanded.has(entity.id)) {
    return true;
  }
  return entity.type === "schema";
}

function professionalTreeRow(entity, childCount, expandable = false) {
  const row = professionalElement("div", "professional-tree-row");
  const type = professionalElement(
    "span",
    `professional-kind professional-kind--${entity.type}`,
    entity.type,
  );
  const name = professionalElement(
    "span",
    "professional-tree-name",
    entity.name,
  );
  name.title = professionalEntityPath(entity);
  const meta = professionalElement(
    "span",
    "professional-tree-meta",
    expandable ? `${childCount}` : entity.status || "",
  );
  const details = professionalElement("button", "tree-details-button", "Details");
  details.type = "button";
  details.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    openDrawer(entity);
  });
  row.append(type, name, meta, details);
  return row;
}

function professionalTreeNode(entity, childMap, matcher) {
  const descendants = (childMap.get(entity.id) || []).filter(matcher.matches);
  if (!descendants.length) {
    const leaf = professionalElement("div", "professional-tree-leaf");
    leaf.append(professionalTreeRow(entity, 0, false));
    return leaf;
  }

  const branch = document.createElement("details");
  branch.className = "professional-tree-branch";
  branch.dataset.entityId = entity.id;
  branch.open = professionalTreeOpen(entity, matcher.query);

  const summary = document.createElement("summary");
  summary.append(professionalTreeRow(entity, descendants.length, true));
  branch.append(summary);

  if (branch.open) {
    const childrenRoot = professionalElement("div", "professional-tree-children");
    for (const child of descendants) {
      childrenRoot.append(professionalTreeNode(child, childMap, matcher));
    }
    branch.append(childrenRoot);
  }

  branch.addEventListener("toggle", () => {
    if (branch.open) {
      professionalUiState.treeExpanded.add(entity.id);
    } else {
      professionalUiState.treeExpanded.delete(entity.id);
    }
    if (!matcher.query) {
      scheduleRender();
    }
  });
  return branch;
}

function setProfessionalTreeExpansion(mode) {
  professionalUiState.treeExpanded.clear();
  if (mode !== "none") {
    for (const entity of state.entities.values()) {
      if (mode === "all" || entity.type === "schema") {
        professionalUiState.treeExpanded.add(entity.id);
      }
    }
  }
  scheduleRender();
}

function professionalTreeToolbar(visibleRoots) {
  const toolbar = professionalElement("div", "professional-tree-toolbar");
  const summary = professionalElement(
    "div",
    "professional-view-summary",
    `${visibleRoots.length} roots · ${state.entities.size} objects`,
  );
  const actions = professionalElement("div", "professional-view-actions");
  for (const [label, mode] of [
    ["Schemas", "schemas"],
    ["Expand all", "all"],
    ["Collapse", "none"],
  ]) {
    const button = professionalElement("button", "", label);
    button.type = "button";
    button.addEventListener("click", () => setProfessionalTreeExpansion(mode));
    actions.append(button);
  }
  toolbar.append(summary, actions);
  return toolbar;
}

renderTree = function renderProfessionalTree() {
  const root = $("treePane");
  const childMap = professionalChildrenMap();
  const matcher = professionalBranchMatcher(childMap);
  const roots = (childMap.get(null) || []).filter(matcher.matches);
  const fragment = document.createDocumentFragment();
  fragment.append(professionalTreeToolbar(roots));

  if (!roots.length) {
    fragment.append(
      professionalElement("div", "empty", "No matching database objects."),
    );
    root.replaceChildren(fragment);
    return;
  }

  const forest = professionalElement("div", "professional-tree-forest");
  for (const entity of roots) {
    forest.append(professionalTreeNode(entity, childMap, matcher));
  }
  fragment.append(forest);
  root.replaceChildren(fragment);
};

function professionalTableBody(schema, table, rows, columns) {
  const body = professionalElement("div", "entity-table-details");
  const columnsSection = professionalElement("section", "entity-table-section");
  const columnsHead = professionalElement("div", "entity-table-section-head");
  columnsHead.append(
    professionalElement("h4", "", "Columns"),
    professionalElement("span", "muted", `${columns.length}`),
  );
  const chips = professionalElement("div", "entity-column-chips");
  if (columns.length) {
    columns.forEach((column, index) => {
      const chip = professionalElement(
        "button",
        "entity-column-chip",
        `${index + 1} · ${column}`,
      );
      chip.type = "button";
      chip.title = `${schema.name}.${table.name}.${column}`;
      chip.addEventListener("click", (event) => event.stopPropagation());
      chips.append(chip);
    });
  } else {
    chips.append(professionalElement("span", "muted", "No columns discovered."));
  }
  columnsSection.append(columnsHead, chips);

  const dataSection = professionalElement("section", "entity-table-section");
  const dataHead = professionalElement("div", "entity-table-section-head");
  dataHead.append(
    professionalElement("h4", "", "Rows"),
    professionalElement("span", "muted", `${rows.length}`),
  );
  dataSection.append(dataHead);
  if (!rows.length) {
    dataSection.append(
      professionalElement(
        "p",
        "entity-table-empty",
        "Rows were not extracted for this table.",
      ),
    );
  } else {
    const values = rows.map((row, index) => {
      const rowValues = tableViewRowValues(row);
      return [index + 1, ...columns.map((column) => rowValues[column] ?? "")];
    });
    dataSection.append(
      tableViewTable(
        ["Row", ...columns],
        values,
        "entity-table entity-table-data",
      ),
    );
  }

  body.append(columnsSection, dataSection);
  return body;
}

buildTableEntityCard = function buildProfessionalTableCard(schema, table) {
  const rows = tableViewChildren(table.id, "row");
  const columns = tableViewColumns(table, rows);
  const card = document.createElement("details");
  card.className = "entity-table-card professional-table-card";
  card.dataset.search = tableViewSearchText(schema, table, columns, rows);
  card.dataset.tableId = table.id;
  card.open = professionalUiState.tableExpanded.has(table.id);

  const summary = document.createElement("summary");
  summary.className = "professional-table-summary";
  const identity = professionalElement("div", "professional-table-identity");
  identity.append(
    professionalElement("span", "entity-table-kind", "TABLE"),
    professionalElement("strong", "", `${schema.name}.${table.name}`),
  );
  const counts = professionalElement("div", "professional-table-counts");
  counts.append(
    professionalElement("span", "", `${columns.length} columns`),
    professionalElement("span", "", `${rows.length} rows`),
    professionalElement("span", "", table.status || "unknown"),
  );
  const details = professionalElement("button", "tree-details-button", "Details");
  details.type = "button";
  details.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    openDrawer(table);
  });
  summary.append(identity, counts, details);
  card.append(summary);

  const ensureBody = () => {
    if (card.dataset.loaded === "true") {
      return;
    }
    card.dataset.loaded = "true";
    card.append(professionalTableBody(schema, table, rows, columns));
  };
  if (card.open) {
    ensureBody();
  }
  card.addEventListener("toggle", () => {
    if (card.open) {
      professionalUiState.tableExpanded.add(table.id);
      ensureBody();
    } else {
      professionalUiState.tableExpanded.delete(table.id);
    }
  });
  return card;
};

function setVisibleTablesExpanded(expanded) {
  const cards = [...document.querySelectorAll(".professional-table-card")];
  for (const card of cards) {
    card.open = expanded;
    const id = card.dataset.tableId;
    if (expanded && id) {
      professionalUiState.tableExpanded.add(id);
    } else if (id) {
      professionalUiState.tableExpanded.delete(id);
    }
  }
}

function ensureProfessionalTableToolbar() {
  const pane = $("tablesPane");
  const head = pane?.querySelector(":scope > .section-head");
  if (!pane || !head || $("professionalTableActions")) {
    return;
  }
  const actions = professionalElement("div", "professional-view-actions");
  actions.id = "professionalTableActions";
  const expand = professionalElement("button", "", "Expand visible");
  expand.type = "button";
  expand.addEventListener("click", () => setVisibleTablesExpanded(true));
  const collapse = professionalElement("button", "", "Collapse all");
  collapse.type = "button";
  collapse.addEventListener("click", () => setVisibleTablesExpanded(false));
  actions.append(expand, collapse);
  head.append(actions);
}

const renderTableViewBeforeProfessionalUi = renderTableView;
renderTableView = function renderProfessionalTables(force = false) {
  renderTableViewBeforeProfessionalUi(force);
  ensureProfessionalTableToolbar();
};

function professionalGraphAdjacency() {
  const adjacency = new Map();
  const connect = (left, right) => {
    if (!left || !right || left === right) {
      return;
    }
    if (!adjacency.has(left)) {
      adjacency.set(left, new Set());
    }
    if (!adjacency.has(right)) {
      adjacency.set(right, new Set());
    }
    adjacency.get(left).add(right);
    adjacency.get(right).add(left);
  };
  for (const relation of state.relationships.values()) {
    connect(relation.source_id, relation.target_id);
  }
  for (const entity of state.entities.values()) {
    if (entity.parent_id) {
      connect(entity.id, entity.parent_id);
    }
  }
  return adjacency;
}

function professionalElasticCluster(rootId) {
  const adjacency = professionalGraphAdjacency();
  const weights = new Map([[rootId, 1]]);
  const depth = new Map([[rootId, 0]]);
  const queue = [rootId];
  while (queue.length && weights.size < ELASTIC_GRAPH.maxNodes) {
    const current = queue.shift();
    const currentDepth = depth.get(current) || 0;
    if (currentDepth >= ELASTIC_GRAPH.maxDepth) {
      continue;
    }
    for (const neighbor of adjacency.get(current) || []) {
      if (weights.has(neighbor) || !graphState.positions.has(neighbor)) {
        continue;
      }
      const nextDepth = currentDepth + 1;
      depth.set(neighbor, nextDepth);
      weights.set(
        neighbor,
        ELASTIC_GRAPH.weights[nextDepth] ||
          ELASTIC_GRAPH.weights[ELASTIC_GRAPH.weights.length - 1],
      );
      queue.push(neighbor);
      if (weights.size >= ELASTIC_GRAPH.maxNodes) {
        break;
      }
    }
  }
  return weights;
}

function professionalGraphCenter(id) {
  const position = graphState.positions.get(id);
  const dimensions = graphState.dimensions.get(id);
  if (!position || !dimensions) {
    return null;
  }
  return {
    x: position.x + (dimensions.centerX ?? dimensions.width / 2),
    y: position.y + (dimensions.centerY ?? dimensions.height / 2),
  };
}

function professionalRelationDistance(relation) {
  const source = professionalGraphCenter(relation.source_id);
  const target = professionalGraphCenter(relation.target_id);
  return source && target ? Math.hypot(target.x - source.x, target.y - source.y) : 0;
}

function clearProfessionalElasticClasses() {
  clearTimeout(professionalUiState.cleanupTimer);
  for (const entry of graphState.nodeElements.values()) {
    entry.group.classList.remove(
      "graph-node-elastic-root",
      "graph-node-elastic-related",
    );
  }
  for (const entry of graphState.edgeElements) {
    entry.path.classList.remove("graph-edge-elastic");
    entry.path.style.removeProperty("stroke-width");
  }
}

function updateProfessionalElasticVisuals() {
  const active = professionalUiState.elastic;
  if (!active) {
    return;
  }
  for (const [id, entry] of graphState.nodeElements.entries()) {
    entry.group.classList.toggle("graph-node-elastic-root", id === active.rootId);
    entry.group.classList.toggle(
      "graph-node-elastic-related",
      id !== active.rootId && active.weights.has(id),
    );
  }
  for (const entry of graphState.edgeElements) {
    const related =
      active.weights.has(entry.relation.source_id) &&
      active.weights.has(entry.relation.target_id);
    entry.path.classList.toggle("graph-edge-elastic", related);
    if (!related) {
      entry.path.style.removeProperty("stroke-width");
      continue;
    }
    const original = active.edgeLengths.get(entry.relation.id) || 1;
    const current = professionalRelationDistance(entry.relation) || original;
    const stretch = Math.min(1, Math.abs(current - original) / Math.max(80, original));
    entry.path.style.strokeWidth = String(2.4 + stretch * 2.2);
  }
}

function flushProfessionalElasticFrame() {
  professionalUiState.elasticFrame = null;
  const active = professionalUiState.elastic;
  if (!active) {
    return;
  }
  const { dx, dy } = active.pending;
  for (const [id, weight] of active.weights.entries()) {
    const origin = active.origins.get(id);
    const position = graphState.positions.get(id);
    if (!origin || !position) {
      continue;
    }
    position.x = origin.x + dx * weight;
    position.y = origin.y + dy * weight;
    const entry = graphState.nodeElements.get(id);
    entry?.group.setAttribute(
      "transform",
      `translate(${position.x} ${position.y})`,
    );
  }
  graphState.userTransformed = true;
  updateGraphEdges();
  updateProfessionalElasticVisuals();
}

function scheduleProfessionalElasticFrame() {
  if (professionalUiState.elasticFrame !== null) {
    return;
  }
  professionalUiState.elasticFrame = requestAnimationFrame(
    flushProfessionalElasticFrame,
  );
}

function beginProfessionalElasticDrag(event) {
  const group = event.target.closest?.(".graph-node");
  if (!group || event.button !== 0) {
    return;
  }
  const svg = $("graph");
  const rootId = group.dataset.entityId;
  if (!svg || !rootId || !graphState.positions.has(rootId)) {
    return;
  }

  event.preventDefault();
  event.stopImmediatePropagation();
  stopDynamicGraphMotion();
  hideGraphNodeTooltip?.();
  clearProfessionalElasticClasses();

  const weights = professionalElasticCluster(rootId);
  const origins = new Map();
  for (const id of weights.keys()) {
    const position = graphState.positions.get(id);
    if (position) {
      origins.set(id, { ...position });
    }
  }
  const edgeLengths = new Map(
    graphState.edgeElements.map((entry) => [
      entry.relation.id,
      professionalRelationDistance(entry.relation),
    ]),
  );
  const start = graphPoint(event);
  professionalUiState.elastic = {
    pointerId: event.pointerId,
    rootId,
    group,
    weights,
    origins,
    edgeLengths,
    start,
    pending: { dx: 0, dy: 0 },
    moved: false,
  };
  graphState.drag = {
    mode: "elastic-node",
    pointerId: event.pointerId,
    id: rootId,
    moved: false,
  };
  svg.setPointerCapture(event.pointerId);
  svg.classList.add("is-dragging", "is-elastic-dragging");
  group.classList.add("dragging");
  updateProfessionalElasticVisuals();
}

function moveProfessionalElasticDrag(event) {
  const active = professionalUiState.elastic;
  if (!active || active.pointerId !== event.pointerId) {
    return;
  }
  event.preventDefault();
  event.stopImmediatePropagation();
  const point = graphPoint(event);
  active.pending = {
    dx: point.x - active.start.x,
    dy: point.y - active.start.y,
  };
  if (Math.abs(active.pending.dx) + Math.abs(active.pending.dy) > 2) {
    active.moved = true;
    if (graphState.drag) {
      graphState.drag.moved = true;
    }
  }
  scheduleProfessionalElasticFrame();
}

function finishProfessionalElasticDrag(event) {
  const active = professionalUiState.elastic;
  if (!active || active.pointerId !== event.pointerId) {
    return;
  }
  event.preventDefault();
  event.stopImmediatePropagation();
  if (professionalUiState.elasticFrame !== null) {
    cancelAnimationFrame(professionalUiState.elasticFrame);
    flushProfessionalElasticFrame();
  }

  const svg = $("graph");
  if (svg?.hasPointerCapture(event.pointerId)) {
    svg.releasePointerCapture(event.pointerId);
  }
  active.group.classList.remove("dragging");
  svg?.classList.remove("is-dragging", "is-elastic-dragging");
  graphState.drag = null;

  if (!active.moved) {
    const entity = state.entities.get(active.rootId);
    if (entity) {
      toggleGraphNodeSelection?.(entity.id);
      openDrawer(entity);
    }
  } else {
    dynamicGraphState.movableIds = new Set(active.weights.keys());
    for (const [id, weight] of active.weights.entries()) {
      dynamicGraphState.velocities.set(id, {
        x: active.pending.dx * weight * 0.018,
        y: active.pending.dy * weight * 0.018,
      });
    }
    startDynamicGraphMotion(visibleGraphEntities());
  }

  professionalUiState.elastic = null;
  professionalUiState.cleanupTimer = setTimeout(
    clearProfessionalElasticClasses,
    ELASTIC_GRAPH.settleMilliseconds,
  );
}

function bindProfessionalElasticGraph() {
  const svg = $("graph");
  if (!svg || svg.dataset.elasticDragBound === "true") {
    return;
  }
  svg.dataset.elasticDragBound = "true";
  svg.addEventListener("pointerdown", beginProfessionalElasticDrag, true);
  svg.addEventListener("pointermove", moveProfessionalElasticDrag, true);
  svg.addEventListener("pointerup", finishProfessionalElasticDrag, true);
  svg.addEventListener("pointercancel", finishProfessionalElasticDrag, true);
  const help = document.querySelector(".graph-help");
  if (help) {
    help.textContent =
      "Drag a node to move its relationship cluster with elastic falloff. Drag the canvas to pan; use the wheel to zoom.";
  }
}

function applyProfessionalDensity() {
  const compact = professionalUiState.density === "compact";
  document.body.classList.toggle("ui-density-compact", compact);
  const button = $("densityToggle");
  if (button) {
    button.textContent = compact ? "Compact" : "Comfortable";
    button.setAttribute("aria-pressed", String(compact));
    button.title = compact
      ? "Switch to comfortable density"
      : "Switch to compact density";
  }
}

function buildProfessionalTopbarControls() {
  const topbar = document.querySelector(".topbar");
  const connection = $("connection");
  if (!topbar || !connection || $("densityToggle")) {
    return;
  }
  const tools = professionalElement("div", "professional-topbar-tools");
  const shortcuts = professionalElement(
    "span",
    "view-shortcuts",
    "1–5 views · / filter",
  );
  const density = professionalElement("button", "density-toggle", "Compact");
  density.id = "densityToggle";
  density.type = "button";
  density.addEventListener("click", () => {
    professionalUiState.density =
      professionalUiState.density === "compact" ? "comfortable" : "compact";
    localStorage.setItem("sqliblind.ui.density", professionalUiState.density);
    applyProfessionalDensity();
  });
  tools.append(shortcuts, density);
  connection.before(tools);
  applyProfessionalDensity();
}

function professionalTabCounts() {
  const counts = { schema: 0, table: 0, column: 0, row: 0, cell: 0 };
  for (const entity of state.entities.values()) {
    if (entity.type in counts) {
      counts[entity.type] += 1;
    }
  }
  return {
    tree: state.entities.size,
    graph: state.relationships.size,
    tables: counts.table,
    entities: state.entities.size,
    events: state.events.length,
  };
}

function updateProfessionalTabBadges() {
  const counts = professionalTabCounts();
  const defaults = {
    tree: "Tree",
    graph: "Graph",
    tables: "Tables",
    entities: "Entities",
    events: "Events",
  };
  document.querySelectorAll("[data-pane]").forEach((button) => {
    const pane = button.dataset.pane;
    if (!(pane in defaults)) {
      return;
    }
    const label = professionalElement("span", "", defaults[pane]);
    const badge = professionalElement(
      "span",
      "professional-tab-count",
      counts[pane],
    );
    button.replaceChildren(label, badge);
  });
}

function activateProfessionalPane(name) {
  document.querySelector(`[data-pane="${name}"]`)?.click();
}

function bindProfessionalKeyboardShortcuts() {
  if (document.body.dataset.professionalKeysBound === "true") {
    return;
  }
  document.body.dataset.professionalKeysBound = "true";
  const panes = { "1": "tree", "2": "graph", "3": "tables", "4": "entities", "5": "events" };
  document.addEventListener("keydown", (event) => {
    const target = event.target;
    const editing =
      target instanceof HTMLInputElement ||
      target instanceof HTMLTextAreaElement ||
      target instanceof HTMLSelectElement ||
      target?.isContentEditable;
    if (event.key === "/" && !editing && !event.ctrlKey && !event.metaKey) {
      event.preventDefault();
      $("filter")?.focus();
      return;
    }
    if (editing || event.ctrlKey || event.metaKey || event.altKey) {
      return;
    }
    if (event.key in panes) {
      event.preventDefault();
      activateProfessionalPane(panes[event.key]);
    }
  });
}

const renderAllBeforeProfessionalUi = renderAll;
renderAll = function renderAllProfessionally() {
  renderAllBeforeProfessionalUi();
  ensureProfessionalTableToolbar();
  updateProfessionalTabBadges();
  bindProfessionalElasticGraph();
};

function initializeProfessionalUi() {
  if (professionalUiState.initialized) {
    return;
  }
  professionalUiState.initialized = true;
  buildProfessionalTopbarControls();
  bindProfessionalKeyboardShortcuts();
  bindProfessionalElasticGraph();
  ensureProfessionalTableToolbar();
  renderAll();
}

queueMicrotask(initializeProfessionalUi);
