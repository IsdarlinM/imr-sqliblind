"use strict";

const professionalUiState = {
  treeOpen: new Set(),
  tableOpen: new Set(),
  virtual: Object.create(null),
  density: localStorage.getItem("sqliblind.ui.density") || "compact",
  workspaceLoadedFor: null,
  lastPersistAt: 0,
  compare: { left: null, right: null },
  resizersBound: false,
};

const PROFESSIONAL_UI = Object.freeze({
  virtualItemHeight: 34,
  virtualOverscan: 8,
  elasticWeights: Object.freeze([1, 0.58, 0.34, 0.2, 0.12]),
  elasticMaxNodes: 120,
  persistInterval: 300,
});

function professionalElement(name, className = "", text = null) {
  const node = document.createElement(name);
  if (className) node.className = className;
  if (text !== null) node.textContent = String(text);
  return node;
}

function professionalChildren(parentId) {
  return [...state.entities.values()]
    .filter((entity) => (entity.parent_id || null) === (parentId || null))
    .sort((left, right) =>
      String(left.type).localeCompare(String(right.type)) ||
      String(left.name).localeCompare(String(right.name)),
    );
}

function professionalDescendantCount(id) {
  let total = 0;
  const queue = [id];
  const seen = new Set();
  while (queue.length) {
    const current = queue.shift();
    if (seen.has(current)) continue;
    seen.add(current);
    for (const child of professionalChildren(current)) {
      total += 1;
      queue.push(child.id);
    }
  }
  return total;
}

function professionalBranchMatches(entity) {
  if (!state.filter) return true;
  return branchMatches(entity);
}

function renderProfessionalTreeNode(entity, depth = 0) {
  const descendants = professionalChildren(entity.id).filter(professionalBranchMatches);
  const branch = document.createElement("details");
  branch.className = `professional-tree-branch type-${entity.type}`;
  branch.dataset.entityId = entity.id;
  branch.style.setProperty("--tree-depth", String(depth));
  const forcedOpen = Boolean(state.filter && branchMatches(entity));
  branch.open = forcedOpen || professionalUiState.treeOpen.has(entity.id) || depth === 0;

  const summary = document.createElement("summary");
  summary.className = "professional-tree-summary";
  const kind = professionalElement("span", "professional-tree-kind", entity.type);
  const name = professionalElement("strong", "professional-tree-name", entity.name);
  const count = professionalElement(
    "span",
    "professional-tree-count",
    descendants.length ? `${descendants.length} direct · ${professionalDescendantCount(entity.id)} total` : entity.status || "",
  );
  const details = professionalElement("button", "professional-icon-button", "Details");
  details.type = "button";
  details.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    openDrawer(entity);
  });
  summary.append(kind, name, count, details);
  branch.append(summary);

  const body = professionalElement("div", "professional-tree-body");
  for (const child of descendants) body.append(renderProfessionalTreeNode(child, depth + 1));
  branch.append(body);
  branch.addEventListener("toggle", () => {
    if (branch.open) professionalUiState.treeOpen.add(entity.id);
    else professionalUiState.treeOpen.delete(entity.id);
    persistProfessionalWorkspace();
  });
  return branch;
}

function professionalTreeToolbar() {
  const bar = professionalElement("div", "professional-view-toolbar");
  const actions = [
    ["Schemas only", () => {
      professionalUiState.treeOpen.clear();
      renderTree();
    }],
    ["Expand visible", () => {
      for (const entity of state.entities.values()) {
        if (professionalBranchMatches(entity)) professionalUiState.treeOpen.add(entity.id);
      }
      renderTree();
    }],
    ["Collapse all", () => {
      professionalUiState.treeOpen.clear();
      renderTree();
    }],
  ];
  for (const [label, action] of actions) {
    const button = professionalElement("button", "", label);
    button.type = "button";
    button.addEventListener("click", action);
    bar.append(button);
  }
  return bar;
}

const renderTreeBeforeProfessional = renderTree;
renderTree = function renderProfessionalTree() {
  const root = $("treePane");
  if (!root) return;
  const roots = professionalChildren(null).filter(professionalBranchMatches);
  if (!roots.length) {
    root.replaceChildren(professionalElement("div", "empty", "No matching entities."));
    return;
  }
  const content = professionalElement("div", "professional-tree");
  for (const entity of roots) content.append(renderProfessionalTreeNode(entity));
  root.replaceChildren(professionalTreeToolbar(), content);
};

function professionalTableSummary(schema, table, columns, rows) {
  const head = professionalElement("summary", "professional-table-summary");
  const identity = professionalElement("span", "professional-table-identity");
  identity.append(
    professionalElement("span", "professional-table-kind", "TABLE"),
    professionalElement("strong", "", `${schema.name}.${table.name}`),
  );
  head.append(
    identity,
    professionalElement("span", "professional-table-meta", `${columns.length} columns · ${rows.length} rows · ${table.status || "unknown"}`),
  );
  return head;
}

function professionalColumnChips(columns) {
  const chips = professionalElement("div", "professional-column-chips");
  columns.forEach((column, index) => {
    const chip = professionalElement("button", "professional-column-chip", column);
    chip.type = "button";
    chip.title = `Column ${index + 1}: ${column}`;
    chips.append(chip);
  });
  return chips;
}

function buildProfessionalTableCard(schema, table) {
  const rows = tableViewChildren(table.id, "row");
  const columns = tableViewColumns(table, rows);
  const card = document.createElement("details");
  card.className = "professional-table-card";
  card.dataset.entityId = table.id;
  card.dataset.search = tableViewSearchText(schema, table, columns, rows);
  card.open = professionalUiState.tableOpen.has(table.id);
  card.append(professionalTableSummary(schema, table, columns, rows));
  const body = professionalElement("div", "professional-table-body");
  body.dataset.loaded = "false";
  card.append(body);

  const load = () => {
    if (body.dataset.loaded === "true") return;
    const dataRows = rows.map((row, index) => {
      const values = tableViewRowValues(row);
      return [index + 1, ...columns.map((column) => values[column] ?? "")];
    });
    body.replaceChildren(
      professionalColumnChips(columns),
      rows.length
        ? tableViewTable(["Row", ...columns], dataRows, "entity-table entity-table-data")
        : professionalElement("p", "entity-table-empty", "Rows were not extracted for this table."),
    );
    body.dataset.loaded = "true";
    card.dataset.loaded = "true";
  };
  if (card.open) load();
  card.addEventListener("toggle", () => {
    if (card.open) {
      professionalUiState.tableOpen.add(table.id);
      load();
    } else professionalUiState.tableOpen.delete(table.id);
    persistProfessionalWorkspace();
  });
  card.addEventListener("dblclick", () => openDrawer(table));
  return card;
}

const renderTableViewBeforeProfessional = renderTableView;
renderTableView = function renderProfessionalTableView(force = false) {
  if (!force && state.activePane !== "tables") return;
  const root = $("tableEntityGrid");
  const summary = $("tableViewSummary");
  if (!root || !summary) return;
  const schemas = [...state.entities.values()]
    .filter((entity) => entity.type === "schema")
    .sort((a, b) => String(a.name).localeCompare(String(b.name)));
  const cards = [];
  for (const schema of schemas) {
    for (const table of tableViewChildren(schema.id, "table")) cards.push(buildProfessionalTableCard(schema, table));
  }
  const query = String(state.filter || "").trim().toLowerCase();
  const visible = cards.filter((card) => !query || card.dataset.search.includes(query));
  summary.textContent = `${visible.length}/${cards.length} tables · ${schemas.length} schemas`;
  const toolbar = professionalElement("div", "professional-view-toolbar");
  for (const [label, open] of [["Expand visible", true], ["Collapse all", false]]) {
    const button = professionalElement("button", "", label);
    button.type = "button";
    button.addEventListener("click", () => {
      visible.forEach((card) => {
        card.open = open;
        card.dispatchEvent(new Event("toggle"));
      });
    });
    toolbar.append(button);
  }
  root.replaceChildren(toolbar, ...visible);
};

function professionalElasticCluster(rootId) {
  const weights = PROFESSIONAL_UI.elasticWeights;
  const result = new Map([[rootId, 1]]);
  const queue = [{ id: rootId, depth: 0 }];
  while (queue.length && result.size < PROFESSIONAL_UI.elasticMaxNodes) {
    const { id, depth } = queue.shift();
    if (depth >= weights.length - 1) continue;
    const context = directGraphContext(id);
    for (const relatedId of context.relatedIds) {
      if (result.has(relatedId)) continue;
      const nextDepth = depth + 1;
      result.set(relatedId, weights[nextDepth]);
      queue.push({ id: relatedId, depth: nextDepth });
      if (result.size >= PROFESSIONAL_UI.elasticMaxNodes) break;
    }
  }
  return result;
}

const graphPointerMoveBase = setupGraphInteraction;
// Elastic propagation is installed through a capturing listener so the original
// single-node drag remains the source of truth for pointer ownership.
const graphSurface = $("graph");
if (graphSurface) {
  graphSurface.addEventListener("pointerdown", (event) => {
    const group = event.target.closest?.(".graph-node");
    if (!group) return;
    const id = group.dataset.entityId;
    const cluster = professionalElasticCluster(id);
    const origins = new Map();
    cluster.forEach((weight, entityId) => {
      const position = graphState.positions.get(entityId);
      if (position) origins.set(entityId, { ...position, weight });
    });
    professionalUiState.elasticDrag = { id, origins, last: null };
    graphSurface.classList.add("elastic-dragging");
  }, { capture: true });

  graphSurface.addEventListener("pointermove", (event) => {
    const drag = graphState.drag;
    const elastic = professionalUiState.elasticDrag;
    if (!drag || drag.mode !== "node" || !elastic || drag.id !== elastic.id) return;
    const point = graphPoint(event);
    const dx = point.x - drag.start.x;
    const dy = point.y - drag.start.y;
    elastic.last = { dx, dy };
    for (const [id, origin] of elastic.origins.entries()) {
      if (id === drag.id) continue;
      const position = {
        x: origin.x + dx * origin.weight,
        y: origin.y + dy * origin.weight,
      };
      graphState.positions.set(id, position);
      const node = graphState.nodeElements.get(id);
      node?.group.setAttribute("transform", `translate(${position.x} ${position.y})`);
    }
    for (const edge of graphState.edgeElements) {
      const connected = edge.relation.source_id === drag.id || edge.relation.target_id === drag.id;
      edge.path.classList.toggle("graph-edge-elastic", connected);
    }
    updateGraphEdges();
  }, { capture: true });

  const finishElastic = () => {
    const elastic = professionalUiState.elasticDrag;
    if (!elastic) return;
    professionalUiState.elasticDrag = null;
    graphSurface.classList.remove("elastic-dragging");
    graphState.edgeElements.forEach((entry) => entry.path.classList.remove("graph-edge-elastic"));
    dynamicGraphState.pendingMotion = true;
    dynamicGraphState.movableIds = new Set(elastic.origins.keys());
    startDynamicGraphMotion(visibleGraphEntities());
    persistProfessionalWorkspace();
  };
  graphSurface.addEventListener("pointerup", finishElastic, { capture: true });
  graphSurface.addEventListener("pointercancel", finishElastic, { capture: true });
}

function professionalVirtualList(root, items, renderItem, key) {
  if (!root) return;
  const height = PROFESSIONAL_UI.virtualItemHeight;
  const viewportHeight = Math.max(root.clientHeight || 480, 160);
  const scrollTop = root.scrollTop || 0;
  const start = Math.max(0, Math.floor(scrollTop / height) - PROFESSIONAL_UI.virtualOverscan);
  const count = Math.ceil(viewportHeight / height) + PROFESSIONAL_UI.virtualOverscan * 2;
  const end = Math.min(items.length, start + count);
  const shell = professionalElement("div", "professional-virtual-shell");
  shell.style.height = `${items.length * height}px`;
  const slice = professionalElement("div", "professional-virtual-slice");
  slice.style.transform = `translateY(${start * height}px)`;
  for (let index = start; index < end; index += 1) slice.append(renderItem(items[index], index));
  shell.append(slice);
  root.replaceChildren(shell);
  professionalUiState.virtual[key] = { items, renderItem };
  if (root.dataset.virtualBound !== "true") {
    root.dataset.virtualBound = "true";
    root.addEventListener("scroll", () => {
      const value = professionalUiState.virtual[key];
      if (value) professionalVirtualList(root, value.items, value.renderItem, key);
    }, { passive: true });
  }
}

const renderEntitiesBeforeVirtual = renderEntities;
renderEntities = function renderVirtualEntities() {
  const root = $("entities");
  if (!root) return;
  const items = [...state.entities.values()].filter(entityMatches);
  professionalVirtualList(root, items, (entity) => {
    const row = professionalElement("button", "professional-entity-row");
    row.type = "button";
    row.append(
      professionalElement("span", "professional-entity-kind", entity.type),
      professionalElement("strong", "", entity.name),
      professionalElement("small", "", entity.status || ""),
    );
    row.addEventListener("click", () => openDrawer(entity));
    return row;
  }, "entities");
};

const renderEventsBeforeVirtual = renderEvents;
renderEvents = function renderVirtualEvents() {
  const root = $("events");
  if (!root) return;
  const items = state.events;
  professionalVirtualList(root, items, (item) => {
    const row = professionalElement("button", "professional-event-row");
    row.type = "button";
    const payload = JSON.stringify(item.payload || {});
    row.textContent = `${item.seq} ${item.timestamp} ${item.event} ${payload}`;
    row.title = row.textContent;
    row.addEventListener("click", () => {
      $("drawerTitle").textContent = `event: ${item.event}`;
      $("drawerBody").textContent = JSON.stringify(item, null, 2);
      $("drawer").classList.add("open");
      $("drawer").setAttribute("aria-hidden", "false");
      $("drawerBackdrop").hidden = false;
    });
    return row;
  }, "events");
};

function workspaceKey() {
  return state.scanId ? `sqliblind.workspace.${state.scanId}` : null;
}

function persistProfessionalWorkspace() {
  const key = workspaceKey();
  if (!key) return;
  const now = Date.now();
  if (now - professionalUiState.lastPersistAt < PROFESSIONAL_UI.persistInterval) return;
  professionalUiState.lastPersistAt = now;
  const positions = {};
  for (const [id, point] of graphState.positions.entries()) positions[id] = point;
  const payload = {
    activePane: state.activePane,
    filter: state.filter,
    density: professionalUiState.density,
    treeOpen: [...professionalUiState.treeOpen],
    tableOpen: [...professionalUiState.tableOpen],
    graph: { positions, transform: graphState.transform },
    panelWidth: getComputedStyle(document.documentElement).getPropertyValue("--details-width").trim(),
  };
  try { localStorage.setItem(key, JSON.stringify(payload)); } catch { /* quota or privacy mode */ }
}

function restoreProfessionalWorkspace() {
  const key = workspaceKey();
  if (!key || professionalUiState.workspaceLoadedFor === state.scanId) return;
  professionalUiState.workspaceLoadedFor = state.scanId;
  let payload = null;
  try { payload = JSON.parse(localStorage.getItem(key) || "null"); } catch { payload = null; }
  if (!payload) return;
  state.filter = String(payload.filter || "");
  if ($("filter")) $("filter").value = state.filter;
  professionalUiState.density = payload.density === "comfortable" ? "comfortable" : "compact";
  professionalUiState.treeOpen = new Set(payload.treeOpen || []);
  professionalUiState.tableOpen = new Set(payload.tableOpen || []);
  graphState.transform = payload.graph?.transform || graphState.transform;
  for (const [id, point] of Object.entries(payload.graph?.positions || {})) {
    if (state.entities.has(id)) graphState.positions.set(id, point);
  }
  if (payload.panelWidth) document.documentElement.style.setProperty("--details-width", payload.panelWidth);
  applyProfessionalDensity();
}

const selectScanBeforeWorkspace = selectScan;
selectScan = async function selectScanWithWorkspace(id) {
  professionalUiState.workspaceLoadedFor = null;
  await selectScanBeforeWorkspace(id);
  restoreProfessionalWorkspace();
  renderAll();
};

function applyProfessionalDensity() {
  document.body.classList.toggle("ui-density-compact", professionalUiState.density === "compact");
  document.body.classList.toggle("ui-density-comfortable", professionalUiState.density === "comfortable");
  localStorage.setItem("sqliblind.ui.density", professionalUiState.density);
}

function installProfessionalToolbar() {
  const controls = document.querySelector(".controls");
  if (!controls || $("professionalDensity")) return;
  const select = professionalElement("select");
  select.id = "professionalDensity";
  select.setAttribute("aria-label", "Interface density");
  for (const value of ["compact", "comfortable"]) {
    const option = professionalElement("option", "", value[0].toUpperCase() + value.slice(1));
    option.value = value;
    option.selected = value === professionalUiState.density;
    select.append(option);
  }
  select.addEventListener("change", () => {
    professionalUiState.density = select.value;
    applyProfessionalDensity();
    persistProfessionalWorkspace();
  });
  controls.append(select);
}

function updateProfessionalTabCounts() {
  const counts = {
    tree: state.entities.size,
    graph: state.entities.size,
    tables: [...state.entities.values()].filter((e) => e.type === "table").length,
    entities: state.entities.size,
    events: state.events.length,
  };
  document.querySelectorAll("[data-pane]").forEach((button) => {
    let badge = button.querySelector(".professional-tab-count");
    if (!badge) {
      badge = professionalElement("span", "professional-tab-count");
      button.append(badge);
    }
    badge.textContent = String(counts[button.dataset.pane] || 0);
  });
}

const renderAllBeforeProfessional = renderAll;
renderAll = function renderAllProfessional() {
  restoreProfessionalWorkspace();
  renderAllBeforeProfessional();
  updateProfessionalTabCounts();
};

function bindProfessionalShortcuts() {
  document.addEventListener("keydown", (event) => {
    if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
    const tag = event.target?.tagName?.toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return;
    if (event.key === "/") {
      event.preventDefault();
      $("filter")?.focus();
      return;
    }
    const pane = { "1": "tree", "2": "graph", "3": "tables", "4": "entities", "5": "events" }[event.key];
    if (pane) document.querySelector(`[data-pane="${pane}"]`)?.click();
  });
}

function bindPanelResize() {
  if (professionalUiState.resizersBound) return;
  professionalUiState.resizersBound = true;
  const drawer = $("drawer");
  if (!drawer) return;
  const handle = professionalElement("button", "professional-resize-handle");
  handle.type = "button";
  handle.setAttribute("aria-label", "Resize details panel");
  drawer.prepend(handle);
  handle.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = drawer.getBoundingClientRect().width;
    handle.setPointerCapture(event.pointerId);
    const move = (next) => {
      const width = Math.max(300, Math.min(window.innerWidth * 0.82, startWidth + startX - next.clientX));
      document.documentElement.style.setProperty("--details-width", `${width}px`);
    };
    const end = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      persistProfessionalWorkspace();
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
  });
}

applyProfessionalDensity();
installProfessionalToolbar();
bindProfessionalShortcuts();
bindPanelResize();
