"use strict";

const csrf = document.querySelector('meta[name="sqliblind-csrf"]').content;
const SVG_NS = "http://www.w3.org/2000/svg";
const terminal = new Set(["completed", "failed", "cancelled", "interrupted"]);

const state = {
  scanId: null,
  scan: null,
  entities: new Map(),
  relationships: new Map(),
  events: [],
  activities: new Map(),
  source: null,
  filter: "",
  activePane: "tree",
  renderQueued: false,
};

const graphState = {
  positions: new Map(),
  dimensions: new Map(),
  nodeElements: new Map(),
  edgeElements: [],
  transform: { x: 0, y: 0, scale: 1 },
  drag: null,
  userTransformed: false,
  resizeObserver: null,
};

const $ = (id) => document.getElementById(id);

function createSvg(name, attributes = {}) {
  const element = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) {
    element.setAttribute(key, String(value));
  }
  return element;
}

let toastTimer = null;
function toast(message) {
  const node = $("toast");
  node.textContent = String(message);
  node.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove("show"), 2600);
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.method && options.method !== "GET") {
    headers["X-SQLIBLIND-CSRF"] = csrf;
  }
  if (options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      // Keep the status-based message when the body is not JSON.
    }
    throw new Error(message);
  }
  return response;
}

function parseLines(value, separator) {
  const result = {};
  for (const line of value.split(/\r?\n/)) {
    if (!line.trim() || !line.includes(separator)) {
      continue;
    }
    const index = line.indexOf(separator);
    const key = line.slice(0, index).trim();
    if (key) {
      result[key] = line.slice(index + 1).trim();
    }
  }
  return result;
}

function formPayload(form) {
  const data = new FormData(form);
  const get = (name) => String(data.get(name) || "").trim();
  const number = (name, fallback) => {
    const value = get(name);
    return value ? Number(value) : fallback;
  };
  return {
    url: get("url"),
    parameter: get("parameter") || "id",
    url_template: get("url_template") || null,
    dialect: get("dialect"),
    oracle: get("oracle"),
    true_statuses: get("true_statuses") || "200",
    true_marker: get("true_marker") || null,
    true_regex: get("true_regex") || null,
    true_length: get("true_length") ? Number(get("true_length")) : null,
    length_tolerance: number("length_tolerance", 0),
    timeout: number("timeout", 10),
    retries: number("retries", 1),
    delay: number("delay", 0.1),
    max_requests: number("max_requests", 5000),
    workers: number("workers", 4),
    max_length: number("max_length", 128),
    max_items: number("max_items", 128),
    min_char_code: number("min_char_code", 32),
    max_char_code: number("max_char_code", 126),
    headers: parseLines(get("headers"), ":"),
    cookies: parseLines(get("cookies"), "="),
    proxy: get("proxy") || null,
    insecure: data.has("insecure"),
    skip_calibration: data.has("skip_calibration"),
    include_data: data.has("include_data"),
    data_tables: get("data_tables"),
    max_rows: number("max_rows", 5),
    max_data_columns: number("max_data_columns", 10),
    max_value_length: number("max_value_length", 128),
    max_data_bytes: number("max_data_bytes", 10000),
    reveal_sensitive_values: data.has("reveal_sensitive_values"),
  };
}

async function refreshSessions() {
  const scans = await (await api("/api/scans")).json();
  const root = $("sessions");
  const fragment = document.createDocumentFragment();

  if (!scans.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No sessions yet.";
    fragment.append(empty);
  }

  for (const scan of scans) {
    const item = document.createElement("div");
    item.className = `session${scan.id === state.scanId ? " selected" : ""}`;
    item.dataset.id = scan.id;
    item.tabIndex = 0;
    item.setAttribute("role", "button");

    const title = document.createElement("strong");
    title.textContent = `${scan.id.slice(0, 8)} · ${scan.status}`;

    const target = document.createElement("small");
    target.textContent = scan.config.url || scan.config.url_template || "target";

    const choose = () => {
      selectScan(scan.id).catch((error) => toast(error.message));
    };
    item.addEventListener("click", choose);
    item.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        choose();
      }
    });
    item.append(title, target);
    fragment.append(item);
  }

  root.replaceChildren(fragment);
}

function resetGraph() {
  graphState.positions.clear();
  graphState.dimensions.clear();
  graphState.nodeElements.clear();
  graphState.edgeElements = [];
  graphState.transform = { x: 0, y: 0, scale: 1 };
  graphState.drag = null;
  graphState.userTransformed = false;
}

function resetScan() {
  state.scan = null;
  state.entities.clear();
  state.relationships.clear();
  state.events = [];
  state.activities.clear();
  resetGraph();
  scheduleRender();
}

async function selectScan(id) {
  state.scanId = id;
  if (state.source) {
    state.source.close();
    state.source = null;
  }
  resetScan();

  const snapshot = await (await api(`/api/scans/${id}/snapshot`)).json();
  state.scan = snapshot.scan;

  for (const entity of snapshot.entities || []) {
    state.entities.set(entity.id, entity);
  }
  for (const relation of snapshot.relationships || []) {
    state.relationships.set(relation.id, relation);
  }
  for (const activity of snapshot.activities || []) {
    applyActivity("activity.snapshot", activity);
  }

  const events = await (
    await api(`/api/scans/${id}/events?after=0&limit=5000`)
  ).json();
  for (const event of events) {
    applyEvent(event, false);
  }

  renderAll();
  const cursor = events.length ? events[events.length - 1].seq : 0;
  connectStream(cursor);
  await refreshSessions();
}

function applyActivity(type, activity) {
  if (!activity || !activity.id) {
    return;
  }
  const previous = state.activities.get(activity.id) || {};
  const startedAt =
    activity.started_at || previous.started_at || new Date().toISOString();
  state.activities.set(activity.id, {
    ...previous,
    ...activity,
    started_at: startedAt,
    event: type,
  });
}

function applyEvent(item, render = true) {
  if (state.events.some((event) => event.seq === item.seq)) {
    return;
  }
  state.events.push(item);
  const payload = item.payload || {};

  if (payload.entity) {
    const previous = state.entities.get(payload.entity.id) || {};
    state.entities.set(payload.entity.id, { ...previous, ...payload.entity });
  }
  if (payload.relationship) {
    state.relationships.set(payload.relationship.id, payload.relationship);
  }
  if (item.event.startsWith("activity.")) {
    applyActivity(item.event, payload.activity);
  }
  if (item.event === "phase.started") {
    $("activityPhase").textContent = payload.phase || "working";
  }
  if (item.event === "phase.completed") {
    $("activityPhase").textContent = `${payload.phase || "phase"} complete`;
  }
  if (item.event.startsWith("scan.")) {
    refreshScan().catch(() => {});
  }
  if (render) {
    scheduleRender();
  }
}

function connectStream(after) {
  if (!state.scanId) {
    return;
  }
  state.source = new EventSource(
    `/api/scans/${state.scanId}/stream?after=${after}`,
  );
  state.source.onopen = () => {
    $("connection").textContent = "live";
    $("connection").className = "status online";
  };
  state.source.onmessage = (event) => {
    applyEvent(JSON.parse(event.data));
  };
  state.source.onerror = () => {
    $("connection").textContent = "reconnecting";
    $("connection").className = "status";
  };
}

async function refreshScan() {
  if (!state.scanId) {
    return;
  }
  state.scan = await (await api(`/api/scans/${state.scanId}`)).json();
  renderMetrics();
  renderControlState();
  if (terminal.has(state.scan.status)) {
    setTimeout(() => refreshSessions().catch(() => {}), 50);
  }
}

function renderActivities() {
  const root = $("activityView");
  const values = [...state.activities.values()].sort(
    (a, b) =>
      Number(b.status === "running") - Number(a.status === "running") ||
      String(b.id).localeCompare(String(a.id)),
  );
  const shown = values
    .filter((item) => item.status === "running")
    .concat(values.filter((item) => item.status !== "running").slice(0, 8));

  if (!shown.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "Waiting for extraction activity.";
    root.replaceChildren(empty);
    return;
  }

  const fragment = document.createDocumentFragment();
  for (const item of shown) {
    const card = document.createElement("article");
    card.className = `activity-card activity${
      item.status === "running" ? "" : " done"
    }`;

    const operation = document.createElement("strong");
    operation.textContent = item.operation || "Working";

    const target = document.createElement("span");
    target.className = "target";
    target.textContent = item.target || "target";

    const detail = document.createElement("span");
    detail.className = "detail";
    detail.textContent = item.detail || item.status || "working";

    const footer = document.createElement("footer");
    const worker = document.createElement("span");
    worker.textContent = item.worker || "worker";

    const timing = document.createElement("span");
    const count =
      item.current !== undefined
        ? ` · ${item.current}${
            item.maximum !== undefined ? `/${item.maximum}` : ""
          } ${item.unit || ""}`
        : "";
    timing.textContent = `${Number(item.elapsed_seconds || 0).toFixed(
      1,
    )}s · ${item.requests_used || 0} req${count}`;

    footer.append(worker, timing);
    card.append(operation, target, detail, footer);
    fragment.append(card);
  }
  root.replaceChildren(fragment);
}

function renderMetrics() {
  const counts = { schema: 0, table: 0, column: 0, row: 0, cell: 0 };
  for (const entity of state.entities.values()) {
    if (entity.type in counts) {
      counts[entity.type] += 1;
    }
  }
  const stats = state.scan?.stats || {};
  const values = [
    ...Object.entries(counts),
    ["requests", stats.requests || 0],
    ["status", state.scan?.status || "idle"],
  ];
  const cards = values.map(([name, value]) => {
    const card = document.createElement("div");
    card.className = "metric";
    const strong = document.createElement("strong");
    strong.textContent = String(value);
    card.append(strong, document.createTextNode(name));
    return card;
  });
  $("metrics").replaceChildren(...cards);
}

function renderControlState() {
  const hasScan = Boolean(state.scanId);
  const finished = terminal.has(state.scan?.status);
  $("pauseBtn").disabled = !hasScan || finished;
  $("resumeBtn").disabled = !hasScan || finished;
  $("stopBtn").disabled = !hasScan || finished;
  $("exportBtn").disabled = !hasScan;
}

function children(parent) {
  return [...state.entities.values()].filter(
    (entity) => (entity.parent_id || null) === (parent || null),
  );
}

function entityMatches(entity) {
  const query = state.filter.toLowerCase();
  return (
    !query ||
    `${entity.type} ${entity.name} ${JSON.stringify(
      entity.data || {},
    )}`.toLowerCase().includes(query)
  );
}

function branchMatches(entity, seen = new Set()) {
  if (seen.has(entity.id)) {
    return false;
  }
  seen.add(entity.id);
  if (entityMatches(entity)) {
    return true;
  }
  return children(entity.id).some((child) => branchMatches(child, seen));
}

function treeNode(entity) {
  const box = document.createElement("div");
  box.className = "tree-node";

  const button = document.createElement("button");
  button.type = "button";

  const kind = document.createElement("span");
  kind.className = "kind";
  kind.textContent = entity.type.toUpperCase();

  button.append(kind, document.createTextNode(entity.name));
  button.addEventListener("click", () => openDrawer(entity));
  box.append(button);

  for (const child of children(entity.id)) {
    if (branchMatches(child)) {
      box.append(treeNode(child));
    }
  }
  return box;
}

function renderTree() {
  const root = $("treePane");
  const roots = children(null).filter((entity) => branchMatches(entity));
  if (!roots.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No matching entities.";
    root.replaceChildren(empty);
    return;
  }
  root.replaceChildren(...roots.map(treeNode));
}

function renderEntities() {
  const root = $("entities");
  const entities = [...state.entities.values()].filter(entityMatches);
  if (!entities.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No matching entities.";
    root.replaceChildren(empty);
    return;
  }

  const fragment = document.createDocumentFragment();
  for (const entity of entities) {
    const card = document.createElement("article");
    card.className = "entity-card";
    card.tabIndex = 0;
    card.setAttribute("role", "button");

    const title = document.createElement("strong");
    title.textContent = entity.name;

    const meta = document.createElement("small");
    meta.textContent = `${entity.type} · ${entity.status}`;

    const open = () => openDrawer(entity);
    card.addEventListener("click", open);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        open();
      }
    });
    card.append(title, meta);
    fragment.append(card);
  }
  root.replaceChildren(fragment);
}

function wrapGraphLabel(value, maximum = 30) {
  const text = String(value || "");
  const words = text.split(/\s+/).filter(Boolean);
  const lines = [];
  let current = "";

  const pushChunks = (word) => {
    let remaining = word;
    while (remaining.length > maximum) {
      lines.push(remaining.slice(0, maximum));
      remaining = remaining.slice(maximum);
    }
    current = remaining;
  };

  for (const word of words.length ? words : [text]) {
    if (!current) {
      pushChunks(word);
      continue;
    }
    if (`${current} ${word}`.length <= maximum) {
      current += ` ${word}`;
    } else {
      lines.push(current);
      current = "";
      pushChunks(word);
    }
  }
  if (current || !lines.length) {
    lines.push(current);
  }
  return lines;
}

function graphNodeDimensions(entity) {
  const lines = wrapGraphLabel(entity.name);
  const longest = Math.max(
    String(entity.type || "").length,
    ...lines.map((line) => line.length),
  );
  return {
    width: Math.max(170, Math.min(360, 28 + longest * 7.3)),
    height: 42 + lines.length * 16,
    lines,
  };
}

function visibleGraphEntities() {
  const all = new Map(
    [...state.entities.values()].map((entity) => [entity.id, entity]),
  );
  if (!state.filter) {
    return [...all.values()];
  }

  const visible = new Set(
    [...all.values()].filter(entityMatches).map((entity) => entity.id),
  );
  for (const id of [...visible]) {
    let current = all.get(id);
    const seen = new Set();
    while (current?.parent_id && !seen.has(current.parent_id)) {
      seen.add(current.parent_id);
      visible.add(current.parent_id);
      current = all.get(current.parent_id);
    }
  }
  return [...visible].map((id) => all.get(id)).filter(Boolean);
}

function graphDepth(entity, byId, cache, visiting = new Set()) {
  if (cache.has(entity.id)) {
    return cache.get(entity.id);
  }
  if (!entity.parent_id || !byId.has(entity.parent_id)) {
    cache.set(entity.id, 0);
    return 0;
  }
  if (visiting.has(entity.id)) {
    cache.set(entity.id, 0);
    return 0;
  }
  visiting.add(entity.id);
  const parent = byId.get(entity.parent_id);
  const depth = graphDepth(parent, byId, cache, visiting) + 1;
  visiting.delete(entity.id);
  cache.set(entity.id, depth);
  return depth;
}

function layoutGraph(entities, force = false) {
  if (force) {
    graphState.positions.clear();
    graphState.dimensions.clear();
  }

  const byId = new Map(entities.map((entity) => [entity.id, entity]));
  const depthCache = new Map();
  const columns = new Map();

  for (const entity of entities) {
    const dimensions = graphNodeDimensions(entity);
    graphState.dimensions.set(entity.id, dimensions);
    const depth = graphDepth(entity, byId, depthCache);
    if (!columns.has(depth)) {
      columns.set(depth, []);
    }
    columns.get(depth).push(entity);
  }

  for (const [depth, column] of [...columns.entries()].sort(
    ([left], [right]) => left - right,
  )) {
    column.sort(
      (a, b) =>
        String(a.type).localeCompare(String(b.type)) ||
        String(a.name).localeCompare(String(b.name)),
    );
    let cursorY = 54;
    for (const entity of column) {
      const dimensions = graphState.dimensions.get(entity.id);
      const existing = graphState.positions.get(entity.id);
      if (existing && !force) {
        cursorY = Math.max(cursorY, existing.y + dimensions.height + 30);
        continue;
      }
      graphState.positions.set(entity.id, {
        x: 54 + depth * 286,
        y: cursorY,
      });
      cursorY += dimensions.height + 30;
    }
  }

  const visibleIds = new Set(entities.map((entity) => entity.id));
  for (const id of [...graphState.positions.keys()]) {
    if (!state.entities.has(id)) {
      graphState.positions.delete(id);
      graphState.dimensions.delete(id);
    } else if (!visibleIds.has(id)) {
      // Keep filtered-out positions so they return where the user placed them.
      continue;
    }
  }
}

function graphFill(type) {
  return (
    {
      schema: "#32689b",
      table: "#8a6725",
      column: "#245f50",
      row: "#6b467b",
      cell: "#7a4f42",
    }[type] || "#344b66"
  );
}

function graphEndpoint(source, target) {
  const sourcePosition = graphState.positions.get(source.entity.id);
  const targetPosition = graphState.positions.get(target.entity.id);
  const sourceDimensions = graphState.dimensions.get(source.entity.id);
  const targetDimensions = graphState.dimensions.get(target.entity.id);

  const sourceCenter = {
    x: sourcePosition.x + sourceDimensions.width / 2,
    y: sourcePosition.y + sourceDimensions.height / 2,
  };
  const targetCenter = {
    x: targetPosition.x + targetDimensions.width / 2,
    y: targetPosition.y + targetDimensions.height / 2,
  };

  if (targetCenter.x >= sourceCenter.x) {
    return {
      source: {
        x: sourcePosition.x + sourceDimensions.width,
        y: sourceCenter.y,
      },
      target: {
        x: targetPosition.x,
        y: targetCenter.y,
      },
    };
  }
  return {
    source: { x: sourcePosition.x, y: sourceCenter.y },
    target: {
      x: targetPosition.x + targetDimensions.width,
      y: targetCenter.y,
    },
  };
}

function updateGraphEdges() {
  for (const entry of graphState.edgeElements) {
    const source = graphState.nodeElements.get(entry.relation.source_id);
    const target = graphState.nodeElements.get(entry.relation.target_id);
    if (!source || !target) {
      continue;
    }
    const points = graphEndpoint(source, target);
    const distance = Math.max(70, Math.abs(points.target.x - points.source.x) * 0.45);
    const direction = points.target.x >= points.source.x ? 1 : -1;
    entry.path.setAttribute(
      "d",
      `M ${points.source.x} ${points.source.y} C ${
        points.source.x + distance * direction
      } ${points.source.y}, ${points.target.x - distance * direction} ${
        points.target.y
      }, ${points.target.x} ${points.target.y}`,
    );
  }
}

function applyGraphTransform() {
  const viewport = $("graphWorld");
  if (!viewport) {
    return;
  }
  const { x, y, scale } = graphState.transform;
  viewport.setAttribute("transform", `translate(${x} ${y}) scale(${scale})`);
}

function graphBounds(entities) {
  if (!entities.length) {
    return null;
  }
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const entity of entities) {
    const position = graphState.positions.get(entity.id);
    const dimensions = graphState.dimensions.get(entity.id);
    if (!position || !dimensions) {
      continue;
    }
    minX = Math.min(minX, position.x);
    minY = Math.min(minY, position.y);
    maxX = Math.max(maxX, position.x + dimensions.width);
    maxY = Math.max(maxY, position.y + dimensions.height);
  }
  return { minX, minY, maxX, maxY };
}

function graphViewportSize() {
  const svg = $("graph");
  return {
    width: Math.max(svg.clientWidth, 320),
    height: Math.max(svg.clientHeight, 320),
  };
}

function fitGraph(entities = visibleGraphEntities()) {
  const bounds = graphBounds(entities);
  if (!bounds) {
    return;
  }
  const viewport = graphViewportSize();
  const padding = 54;
  const contentWidth = Math.max(1, bounds.maxX - bounds.minX);
  const contentHeight = Math.max(1, bounds.maxY - bounds.minY);
  const scale = Math.max(
    0.12,
    Math.min(
      1.5,
      (viewport.width - padding * 2) / contentWidth,
      (viewport.height - padding * 2) / contentHeight,
    ),
  );
  graphState.transform = {
    scale,
    x: (viewport.width - contentWidth * scale) / 2 - bounds.minX * scale,
    y: (viewport.height - contentHeight * scale) / 2 - bounds.minY * scale,
  };
  applyGraphTransform();
}

function screenPoint(event) {
  const svg = $("graph");
  const rect = svg.getBoundingClientRect();
  const viewport = graphViewportSize();
  return {
    x: ((event.clientX - rect.left) / Math.max(rect.width, 1)) * viewport.width,
    y: ((event.clientY - rect.top) / Math.max(rect.height, 1)) * viewport.height,
  };
}

function graphPoint(event) {
  const point = screenPoint(event);
  return {
    x: (point.x - graphState.transform.x) / graphState.transform.scale,
    y: (point.y - graphState.transform.y) / graphState.transform.scale,
  };
}

function zoomGraph(factor, clientX = null, clientY = null) {
  const svg = $("graph");
  const rect = svg.getBoundingClientRect();
  const viewport = graphViewportSize();
  const screen =
    clientX === null || clientY === null
      ? { x: viewport.width / 2, y: viewport.height / 2 }
      : {
          x: ((clientX - rect.left) / Math.max(rect.width, 1)) * viewport.width,
          y: ((clientY - rect.top) / Math.max(rect.height, 1)) * viewport.height,
        };

  const oldScale = graphState.transform.scale;
  const nextScale = Math.max(0.1, Math.min(4, oldScale * factor));
  const worldX = (screen.x - graphState.transform.x) / oldScale;
  const worldY = (screen.y - graphState.transform.y) / oldScale;

  graphState.transform.scale = nextScale;
  graphState.transform.x = screen.x - worldX * nextScale;
  graphState.transform.y = screen.y - worldY * nextScale;
  graphState.userTransformed = true;
  applyGraphTransform();
}

function renderGraph() {
  const entities = visibleGraphEntities();
  const visibleIds = new Set(entities.map((entity) => entity.id));
  const relations = [...state.relationships.values()].filter(
    (relation) =>
      visibleIds.has(relation.source_id) && visibleIds.has(relation.target_id),
  );
  $("graphSummary").textContent = `${entities.length} nodes · ${relations.length} relations`;

  if (state.activePane !== "graph") {
    return;
  }

  const svg = $("graph");
  const viewport = graphViewportSize();
  svg.setAttribute("viewBox", `0 0 ${viewport.width} ${viewport.height}`);
  svg.replaceChildren();
  graphState.nodeElements.clear();
  graphState.edgeElements = [];

  if (!entities.length) {
    const empty = createSvg("text", {
      x: viewport.width / 2,
      y: viewport.height / 2,
      "text-anchor": "middle",
      class: "graph-empty",
    });
    empty.textContent = "No matching graph entities.";
    svg.append(empty);
    return;
  }

  layoutGraph(entities);

  const defs = createSvg("defs");
  const marker = createSvg("marker", {
    id: "graphArrow",
    markerWidth: 8,
    markerHeight: 8,
    refX: 7,
    refY: 4,
    orient: "auto",
    markerUnits: "strokeWidth",
  });
  marker.append(
    createSvg("path", {
      d: "M 0 0 L 8 4 L 0 8 z",
      fill: "#3c5b7d",
    }),
  );
  defs.append(marker);

  const world = createSvg("g", { id: "graphWorld" });
  const edgeLayer = createSvg("g", { "aria-hidden": "true" });
  const nodeLayer = createSvg("g");
  world.append(edgeLayer, nodeLayer);
  svg.append(defs, world);

  for (const relation of relations) {
    const path = createSvg("path", {
      class: "graph-edge",
      "marker-end": "url(#graphArrow)",
    });
    path.style.pointerEvents = "none";
    edgeLayer.append(path);
    graphState.edgeElements.push({ path, relation });
  }

  for (const entity of entities) {
    const position = graphState.positions.get(entity.id);
    const dimensions = graphState.dimensions.get(entity.id);
    const group = createSvg("g", {
      class: "graph-node",
      transform: `translate(${position.x} ${position.y})`,
      tabindex: "0",
      role: "button",
      "aria-label": `${entity.type}: ${entity.name}`,
      "data-entity-id": entity.id,
    });

    const rectangle = createSvg("rect", {
      width: dimensions.width,
      height: dimensions.height,
      rx: 10,
      fill: graphFill(entity.type),
    });

    const kind = createSvg("text", {
      x: 12,
      y: 17,
      class: "node-kind",
    });
    kind.textContent = String(entity.type || "entity").toUpperCase();

    const label = createSvg("text", {
      x: 12,
      y: 38,
      class: "node-label",
    });
    dimensions.lines.forEach((line, index) => {
      const span = createSvg("tspan", {
        x: 12,
        dy: index === 0 ? 0 : 16,
      });
      span.textContent = line;
      label.append(span);
    });

    const title = createSvg("title");
    title.textContent = `${entity.type}: ${entity.name}`;

    group.append(rectangle, kind, label, title);
    group.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      const start = graphPoint(event);
      graphState.drag = {
        mode: "node",
        pointerId: event.pointerId,
        id: entity.id,
        start,
        origin: { ...graphState.positions.get(entity.id) },
        moved: false,
      };
      svg.setPointerCapture(event.pointerId);
      group.classList.add("dragging");
      svg.classList.add("is-dragging");
    });
    group.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openDrawer(entity);
      }
    });

    nodeLayer.append(group);
    graphState.nodeElements.set(entity.id, { group, entity });
  }

  updateGraphEdges();
  applyGraphTransform();
  if (!graphState.userTransformed) {
    fitGraph(entities);
  }
}

function setupGraphInteraction() {
  const svg = $("graph");

  svg.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || event.target.closest?.(".graph-node")) {
      return;
    }
    event.preventDefault();
    const start = screenPoint(event);
    graphState.drag = {
      mode: "pan",
      pointerId: event.pointerId,
      start,
      origin: { ...graphState.transform },
      moved: false,
    };
    svg.setPointerCapture(event.pointerId);
    svg.classList.add("is-panning");
  });

  svg.addEventListener("pointermove", (event) => {
    const drag = graphState.drag;
    if (!drag || drag.pointerId !== event.pointerId) {
      return;
    }
    event.preventDefault();

    if (drag.mode === "node") {
      const point = graphPoint(event);
      const dx = point.x - drag.start.x;
      const dy = point.y - drag.start.y;
      if (Math.abs(dx) + Math.abs(dy) > 2) {
        drag.moved = true;
      }
      const position = {
        x: drag.origin.x + dx,
        y: drag.origin.y + dy,
      };
      graphState.positions.set(drag.id, position);
      const node = graphState.nodeElements.get(drag.id);
      node.group.setAttribute(
        "transform",
        `translate(${position.x} ${position.y})`,
      );
      graphState.userTransformed = true;
      updateGraphEdges();
      return;
    }

    const point = screenPoint(event);
    const dx = point.x - drag.start.x;
    const dy = point.y - drag.start.y;
    if (Math.abs(dx) + Math.abs(dy) > 2) {
      drag.moved = true;
    }
    graphState.transform.x = drag.origin.x + dx;
    graphState.transform.y = drag.origin.y + dy;
    graphState.userTransformed = true;
    applyGraphTransform();
  });

  const finishPointer = (event) => {
    const drag = graphState.drag;
    if (!drag || drag.pointerId !== event.pointerId) {
      return;
    }
    if (svg.hasPointerCapture(event.pointerId)) {
      svg.releasePointerCapture(event.pointerId);
    }
    if (drag.mode === "node") {
      const node = graphState.nodeElements.get(drag.id);
      node?.group.classList.remove("dragging");
      if (!drag.moved) {
        const entity = state.entities.get(drag.id);
        if (entity) {
          openDrawer(entity);
        }
      }
    }
    svg.classList.remove("is-panning", "is-dragging");
    graphState.drag = null;
  };

  svg.addEventListener("pointerup", finishPointer);
  svg.addEventListener("pointercancel", finishPointer);

  svg.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      zoomGraph(event.deltaY < 0 ? 1.12 : 0.89, event.clientX, event.clientY);
    },
    { passive: false },
  );

  $("graphZoomIn").addEventListener("click", () => zoomGraph(1.2));
  $("graphZoomOut").addEventListener("click", () => zoomGraph(1 / 1.2));
  $("graphFit").addEventListener("click", () => {
    graphState.userTransformed = true;
    fitGraph();
  });
  $("graphReset").addEventListener("click", () => {
    graphState.userTransformed = false;
    layoutGraph(visibleGraphEntities(), true);
    renderGraph();
  });

  if ("ResizeObserver" in window) {
    graphState.resizeObserver = new ResizeObserver(() => {
      if (state.activePane === "graph") {
        renderGraph();
      }
    });
    graphState.resizeObserver.observe($("graphViewport"));
  } else {
    window.addEventListener("resize", () => {
      if (state.activePane === "graph") {
        renderGraph();
      }
    });
  }
}

function renderEvents() {
  $("events").textContent = state.events
    .map(
      (item) =>
        `${item.seq} ${item.timestamp} ${item.event} ${JSON.stringify(
          item.payload,
        )}`,
    )
    .join("\n");
}

function scheduleRender() {
  if (state.renderQueued) {
    return;
  }
  state.renderQueued = true;
  requestAnimationFrame(() => {
    state.renderQueued = false;
    renderAll();
  });
}

function renderAll() {
  renderActivities();
  renderMetrics();
  renderControlState();
  renderTree();
  renderEntities();
  renderGraph();
  renderEvents();
}

function openDrawer(entity) {
  $("drawerTitle").textContent = `${entity.type}: ${entity.name}`;
  const related = [...state.relationships.values()].filter(
    (relation) =>
      relation.source_id === entity.id || relation.target_id === entity.id,
  );
  $("drawerBody").textContent = JSON.stringify(
    { ...entity, relationships: related },
    null,
    2,
  );
  $("drawer").classList.add("open");
  $("drawer").setAttribute("aria-hidden", "false");
  $("drawerBackdrop").hidden = false;
  $("drawerClose").focus();
}

function closeDrawer() {
  $("drawer").classList.remove("open");
  $("drawer").setAttribute("aria-hidden", "true");
  $("drawerBackdrop").hidden = true;
}

async function control(action) {
  if (!state.scanId) {
    toast("Select a scan first.");
    return;
  }
  await api(`/api/scans/${state.scanId}/${action}`, { method: "POST" });
  toast(action);
  await refreshScan();
}

$("scanForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const response = await api("/api/scans", {
      method: "POST",
      body: JSON.stringify(formPayload(event.currentTarget)),
    });
    const result = await response.json();
    await selectScan(result.id);
  } catch (error) {
    toast(error.message);
  }
});

$("pauseBtn").addEventListener("click", () => {
  control("pause").catch((error) => toast(error.message));
});
$("resumeBtn").addEventListener("click", () => {
  control("resume").catch((error) => toast(error.message));
});
$("stopBtn").addEventListener("click", () => {
  control("stop").catch((error) => toast(error.message));
});
$("exportBtn").addEventListener("click", () => {
  if (!state.scanId) {
    toast("Select a scan first.");
    return;
  }
  location.href = `/api/scans/${state.scanId}/export?format=${
    $("exportFormat").value
  }`;
});
$("filter").addEventListener("input", (event) => {
  state.filter = event.target.value;
  graphState.userTransformed = false;
  scheduleRender();
});
$("drawerClose").addEventListener("click", closeDrawer);
$("drawerBackdrop").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeDrawer();
  }
});

document.querySelectorAll("[data-pane]").forEach((button) => {
  button.addEventListener("click", () => {
    state.activePane = button.dataset.pane;
    document.querySelectorAll("[data-pane]").forEach((node) => {
      node.classList.toggle("active", node === button);
    });
    for (const name of ["tree", "graph", "entities", "events"]) {
      $(`${name}Pane`).classList.toggle(
        "hidden",
        name !== button.dataset.pane,
      );
    }
    if (state.activePane === "graph") {
      requestAnimationFrame(() => renderGraph());
    }
  });
});

setupGraphInteraction();
renderControlState();
refreshSessions().catch((error) => toast(error.message));

setInterval(() => {
  if (state.scanId) {
    refreshScan().catch(() => {});
  }
}, 1500);

setInterval(() => {
  if (!state.scanId) {
    return;
  }
  const now = Date.now();
  for (const activity of state.activities.values()) {
    if (activity.status === "running" && activity.started_at) {
      activity.elapsed_seconds = Math.max(
        0,
        (now - Date.parse(activity.started_at)) / 1000,
      );
    }
  }
  renderActivities();
}, 500);
