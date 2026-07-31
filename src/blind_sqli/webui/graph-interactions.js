"use strict";

const graphRelationState = {
  hoveredId: null,
  selectedId: null,
  tooltip: null,
  canvasBound: false,
};

const GRAPH_TOOLTIP_LIMITS = Object.freeze({
  relatedNames: 6,
  detailRows: 4,
  valueLength: 88,
});

function directGraphContext(entityId) {
  const entity = state.entities.get(entityId) || null;
  const relatedIds = new Set();
  const relationIds = new Set();
  const incoming = [];
  const outgoing = [];

  for (const relation of state.relationships.values()) {
    if (relation.source_id === entityId) {
      relatedIds.add(relation.target_id);
      relationIds.add(relation.id);
      outgoing.push(relation);
    }
    if (relation.target_id === entityId) {
      relatedIds.add(relation.source_id);
      relationIds.add(relation.id);
      incoming.push(relation);
    }
  }

  if (entity?.parent_id && state.entities.has(entity.parent_id)) {
    relatedIds.add(entity.parent_id);
  }
  for (const candidate of state.entities.values()) {
    if (candidate.parent_id === entityId) {
      relatedIds.add(candidate.id);
    }
  }

  const parents = [...relatedIds]
    .map((id) => state.entities.get(id))
    .filter((candidate) => candidate && entity?.parent_id === candidate.id);
  const children = [...relatedIds]
    .map((id) => state.entities.get(id))
    .filter((candidate) => candidate?.parent_id === entityId);
  const peers = [...relatedIds]
    .map((id) => state.entities.get(id))
    .filter(
      (candidate) =>
        candidate &&
        !parents.some((parent) => parent.id === candidate.id) &&
        !children.some((child) => child.id === candidate.id),
    );

  return {
    entity,
    relatedIds,
    relationIds,
    incoming,
    outgoing,
    parents,
    children,
    peers,
  };
}

function ensureGraphNodeTooltip() {
  if (graphRelationState.tooltip?.isConnected) {
    return graphRelationState.tooltip;
  }
  const viewport = $("graphViewport");
  if (!viewport) {
    return null;
  }
  const tooltip = document.createElement("aside");
  tooltip.id = "graphNodeTooltip";
  tooltip.className = "graph-node-tooltip";
  tooltip.setAttribute("role", "tooltip");
  tooltip.setAttribute("aria-hidden", "true");
  tooltip.hidden = true;
  viewport.append(tooltip);
  graphRelationState.tooltip = tooltip;
  return tooltip;
}

function graphTooltipValue(value) {
  if (value === null || value === undefined) {
    return null;
  }
  let text;
  if (Array.isArray(value)) {
    text = `${value.length} items`;
  } else if (typeof value === "object") {
    text = `${Object.keys(value).length} fields`;
  } else {
    text = String(value);
  }
  if (!text) {
    return null;
  }
  if (text.length > GRAPH_TOOLTIP_LIMITS.valueLength) {
    return `${text.slice(0, GRAPH_TOOLTIP_LIMITS.valueLength - 1)}…`;
  }
  return text;
}

function graphTooltipDetails(entity) {
  const sensitive = /(password|passwd|secret|token|cookie|session|authorization|api[_-]?key|credential)/i;
  return Object.entries(entity?.data || {})
    .filter(([key]) => !sensitive.test(key))
    .map(([key, value]) => [key, graphTooltipValue(value)])
    .filter(([, value]) => value !== null)
    .slice(0, GRAPH_TOOLTIP_LIMITS.detailRows);
}

function graphEntityNames(entities) {
  const names = entities
    .filter(Boolean)
    .slice(0, GRAPH_TOOLTIP_LIMITS.relatedNames)
    .map((entity) => entity.name);
  const remaining = Math.max(0, entities.length - names.length);
  return remaining ? `${names.join(", ")} +${remaining}` : names.join(", ");
}

function appendGraphTooltipRow(root, label, value) {
  if (value === null || value === undefined || value === "") {
    return;
  }
  const row = document.createElement("div");
  row.className = "graph-node-tooltip-row";
  const key = document.createElement("span");
  key.textContent = label;
  const content = document.createElement("strong");
  content.textContent = String(value);
  row.append(key, content);
  root.append(row);
}

function populateGraphNodeTooltip(context) {
  const tooltip = ensureGraphNodeTooltip();
  if (!tooltip || !context.entity) {
    return null;
  }
  const heading = document.createElement("div");
  heading.className = "graph-node-tooltip-heading";
  const kind = document.createElement("span");
  kind.textContent = String(context.entity.type || "entity").toUpperCase();
  const title = document.createElement("strong");
  title.textContent = context.entity.name;
  heading.append(kind, title);

  const body = document.createElement("div");
  body.className = "graph-node-tooltip-body";
  appendGraphTooltipRow(body, "Status", context.entity.status || "unknown");
  appendGraphTooltipRow(body, "Direct links", context.relatedIds.size);
  appendGraphTooltipRow(body, "Parents", graphEntityNames(context.parents));
  appendGraphTooltipRow(body, "Children", graphEntityNames(context.children));
  appendGraphTooltipRow(body, "Other links", graphEntityNames(context.peers));

  const kinds = new Set(
    [...context.incoming, ...context.outgoing]
      .map((relation) => relation.kind)
      .filter(Boolean),
  );
  appendGraphTooltipRow(body, "Relations", [...kinds].join(", "));
  for (const [key, value] of graphTooltipDetails(context.entity)) {
    appendGraphTooltipRow(body, key, value);
  }

  tooltip.replaceChildren(heading, body);
  tooltip.hidden = false;
  tooltip.setAttribute("aria-hidden", "false");
  return tooltip;
}

function positionGraphNodeTooltip(clientX, clientY) {
  const tooltip = graphRelationState.tooltip;
  const viewport = $("graphViewport");
  if (!tooltip || tooltip.hidden || !viewport) {
    return;
  }
  const bounds = viewport.getBoundingClientRect();
  const width = Math.min(tooltip.offsetWidth || 300, bounds.width - 16);
  const height = Math.min(tooltip.offsetHeight || 180, bounds.height - 16);
  let left = clientX - bounds.left + 16;
  let top = clientY - bounds.top + 16;
  if (left + width > bounds.width - 8) {
    left = clientX - bounds.left - width - 16;
  }
  if (top + height > bounds.height - 8) {
    top = clientY - bounds.top - height - 16;
  }
  tooltip.style.left = `${Math.max(8, left)}px`;
  tooltip.style.top = `${Math.max(8, top)}px`;
}

function positionTooltipAtNode(group) {
  const bounds = group.getBoundingClientRect();
  positionGraphNodeTooltip(bounds.right, bounds.top + bounds.height / 2);
}

function hideGraphNodeTooltip() {
  const tooltip = graphRelationState.tooltip;
  if (!tooltip) {
    return;
  }
  tooltip.hidden = true;
  tooltip.setAttribute("aria-hidden", "true");
}

function applyDirectGraphHighlight(entityId) {
  const context = entityId ? directGraphContext(entityId) : null;
  for (const [id, entry] of graphState.nodeElements.entries()) {
    entry.group.classList.remove(
      "graph-node-focused",
      "graph-node-related",
      "graph-node-muted",
      "graph-node-selected",
    );
    entry.group.removeAttribute("aria-pressed");
    if (!context?.entity) {
      continue;
    }
    if (id === entityId) {
      entry.group.classList.add("graph-node-focused");
    } else if (context.relatedIds.has(id)) {
      entry.group.classList.add("graph-node-related");
    } else {
      entry.group.classList.add("graph-node-muted");
    }
    if (id === graphRelationState.selectedId) {
      entry.group.classList.add("graph-node-selected");
      entry.group.setAttribute("aria-pressed", "true");
    }
  }

  for (const entry of graphState.edgeElements) {
    entry.path.classList.remove("graph-edge-related", "graph-edge-muted");
    if (!context?.entity) {
      continue;
    }
    if (context.relationIds.has(entry.relation.id)) {
      entry.path.classList.add("graph-edge-related");
    } else {
      entry.path.classList.add("graph-edge-muted");
    }
  }
}

function refreshGraphRelationshipHighlight() {
  applyDirectGraphHighlight(
    graphRelationState.hoveredId || graphRelationState.selectedId,
  );
}

function showGraphNodeHover(entity, event = null, group = null) {
  graphRelationState.hoveredId = entity.id;
  const context = directGraphContext(entity.id);
  populateGraphNodeTooltip(context);
  refreshGraphRelationshipHighlight();
  if (event) {
    positionGraphNodeTooltip(event.clientX, event.clientY);
  } else if (group) {
    positionTooltipAtNode(group);
  }
}

function clearGraphNodeHover(entityId) {
  if (graphRelationState.hoveredId !== entityId) {
    return;
  }
  graphRelationState.hoveredId = null;
  hideGraphNodeTooltip();
  refreshGraphRelationshipHighlight();
}

function toggleGraphNodeSelection(entityId) {
  graphRelationState.selectedId =
    graphRelationState.selectedId === entityId ? null : entityId;
  refreshGraphRelationshipHighlight();
}

function bindGraphRelationshipNode(entry) {
  const { group, entity } = entry;
  if (group.dataset.directRelationsBound === "true") {
    return;
  }
  group.dataset.directRelationsBound = "true";
  group.setAttribute("aria-describedby", "graphNodeTooltip");

  group.addEventListener("pointerenter", (event) => {
    showGraphNodeHover(entity, event, group);
  });
  group.addEventListener("pointermove", (event) => {
    if (graphRelationState.hoveredId === entity.id) {
      positionGraphNodeTooltip(event.clientX, event.clientY);
    }
  });
  group.addEventListener("pointerleave", () => {
    clearGraphNodeHover(entity.id);
  });
  group.addEventListener("focus", () => {
    showGraphNodeHover(entity, null, group);
  });
  group.addEventListener("blur", () => {
    clearGraphNodeHover(entity.id);
  });
  group.addEventListener("pointerup", () => {
    const drag = graphState.drag;
    if (
      drag?.mode === "node" &&
      drag.id === entity.id &&
      !drag.moved
    ) {
      toggleGraphNodeSelection(entity.id);
    }
  });
  group.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      toggleGraphNodeSelection(entity.id);
    }
  });
}

function bindGraphRelationshipCanvas() {
  if (graphRelationState.canvasBound) {
    return;
  }
  const svg = $("graph");
  if (!svg) {
    return;
  }
  graphRelationState.canvasBound = true;
  svg.addEventListener("pointerup", (event) => {
    if (event.target.closest?.(".graph-node")) {
      return;
    }
    graphRelationState.selectedId = null;
    graphRelationState.hoveredId = null;
    hideGraphNodeTooltip();
    refreshGraphRelationshipHighlight();
  });
}

const renderGraphBeforeDirectRelations = renderGraph;
renderGraph = function renderGraphWithDirectRelations() {
  renderGraphBeforeDirectRelations();
  if (state.activePane !== "graph") {
    return;
  }
  ensureGraphNodeTooltip();
  bindGraphRelationshipCanvas();
  for (const entry of graphState.nodeElements.values()) {
    bindGraphRelationshipNode(entry);
  }
  if (
    graphRelationState.selectedId &&
    !graphState.nodeElements.has(graphRelationState.selectedId)
  ) {
    graphRelationState.selectedId = null;
  }
  if (
    graphRelationState.hoveredId &&
    !graphState.nodeElements.has(graphRelationState.hoveredId)
  ) {
    graphRelationState.hoveredId = null;
    hideGraphNodeTooltip();
  }
  refreshGraphRelationshipHighlight();
};

const resetGraphBeforeDirectRelations = resetGraph;
resetGraph = function resetGraphDirectRelations() {
  graphRelationState.hoveredId = null;
  graphRelationState.selectedId = null;
  hideGraphNodeTooltip();
  resetGraphBeforeDirectRelations();
};

bindGraphRelationshipCanvas();
if (state.activePane === "graph") {
  renderGraph();
}
