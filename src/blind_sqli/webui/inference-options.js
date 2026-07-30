"use strict";

const baseInferenceFormPayload = formPayload;
formPayload = function optimizedInferenceFormPayload(form) {
  const payload = baseInferenceFormPayload(form);
  const data = new FormData(form);
  const sample = Number(String(data.get("request_event_sample") || "20"));
  return {
    ...payload,
    inference_mode: String(data.get("inference_mode") || "adaptive"),
    parallel_characters: data.has("parallel_characters"),
    adaptive_confirmation: data.has("adaptive_confirmation"),
    adaptive_concurrency: data.has("adaptive_concurrency"),
    request_event_sample: Number.isFinite(sample) ? sample : 20,
  };
};

const COMPACT_GRAPH = Object.freeze({
  radii: Object.freeze({
    schema: 18,
    table: 16,
    column: 14,
    row: 13,
    cell: 12,
    default: 14,
  }),
  labelLength: 18,
  horizontalGap: 14,
  verticalGap: 12,
  startX: 24,
  startY: 24,
});

function compactGraphRadius(type) {
  return COMPACT_GRAPH.radii[type] || COMPACT_GRAPH.radii.default;
}

function compactGraphLabel(value, maximum = COMPACT_GRAPH.labelLength) {
  const text = String(value || "");
  if (text.length <= maximum) {
    return text;
  }
  return `${text.slice(0, Math.max(1, maximum - 1))}…`;
}

function compactGraphKind(type) {
  return (
    {
      schema: "S",
      table: "T",
      column: "C",
      row: "R",
      cell: "V",
    }[type] || "•"
  );
}

graphNodeDimensions = function compactGraphNodeDimensions(entity) {
  const radius = compactGraphRadius(entity.type);
  const label = compactGraphLabel(entity.name);
  const centerX = radius + 4;
  const centerY = Math.max(radius + 4, 22);
  const labelX = radius * 2 + 12;
  const labelWidth = Math.max(36, label.length * 6.6);
  return {
    width: labelX + labelWidth,
    height: Math.max(radius * 2 + 8, 44),
    lines: [label],
    radius,
    centerX,
    centerY,
    labelX,
  };
};

function packedGraphOrder(entities) {
  const byId = new Map(entities.map((entity) => [entity.id, entity]));
  const childrenByParent = new Map();
  const roots = [];

  for (const entity of entities) {
    if (!entity.parent_id || !byId.has(entity.parent_id)) {
      roots.push(entity);
      continue;
    }
    if (!childrenByParent.has(entity.parent_id)) {
      childrenByParent.set(entity.parent_id, []);
    }
    childrenByParent.get(entity.parent_id).push(entity);
  }

  const compare = (left, right) =>
    String(left.type).localeCompare(String(right.type)) ||
    String(left.name).localeCompare(String(right.name));
  roots.sort(compare);
  for (const values of childrenByParent.values()) {
    values.sort(compare);
  }

  const ordered = [];
  const queue = [...roots];
  const seen = new Set();
  while (queue.length) {
    const entity = queue.shift();
    if (!entity || seen.has(entity.id)) {
      continue;
    }
    seen.add(entity.id);
    ordered.push(entity);
    queue.push(...(childrenByParent.get(entity.id) || []));
  }

  for (const entity of [...entities].sort(compare)) {
    if (!seen.has(entity.id)) {
      ordered.push(entity);
    }
  }
  return ordered;
}

function packedGraphColumns(count, cellWidth, cellHeight) {
  if (count <= 1) {
    return 1;
  }
  const viewport = graphViewportSize();
  const aspect = viewport.width / Math.max(viewport.height, 1);
  const balanced = Math.ceil(
    Math.sqrt((count * aspect * cellHeight) / Math.max(cellWidth, 1)),
  );
  return Math.max(1, Math.min(count, balanced));
}

function rectanglesOverlap(left, right) {
  return !(
    left.x + left.width + COMPACT_GRAPH.horizontalGap <= right.x ||
    right.x + right.width + COMPACT_GRAPH.horizontalGap <= left.x ||
    left.y + left.height + COMPACT_GRAPH.verticalGap <= right.y ||
    right.y + right.height + COMPACT_GRAPH.verticalGap <= left.y
  );
}

layoutGraph = function packedLayoutGraph(entities, force = false) {
  const preserveManualLayout = graphState.userTransformed && !force;
  if (!preserveManualLayout) {
    graphState.positions.clear();
  }
  if (force) {
    graphState.dimensions.clear();
  }

  const ordered = packedGraphOrder(entities);
  for (const entity of ordered) {
    graphState.dimensions.set(entity.id, graphNodeDimensions(entity));
  }

  const maximumWidth = Math.max(
    1,
    ...ordered.map((entity) => graphState.dimensions.get(entity.id).width),
  );
  const maximumHeight = Math.max(
    1,
    ...ordered.map((entity) => graphState.dimensions.get(entity.id).height),
  );
  const cellWidth = maximumWidth + COMPACT_GRAPH.horizontalGap;
  const cellHeight = maximumHeight + COMPACT_GRAPH.verticalGap;
  const columns = packedGraphColumns(ordered.length, cellWidth, cellHeight);
  const occupied = [];

  if (preserveManualLayout) {
    for (const entity of ordered) {
      const position = graphState.positions.get(entity.id);
      const dimensions = graphState.dimensions.get(entity.id);
      if (position && dimensions) {
        occupied.push({ ...position, ...dimensions });
      }
    }
  }

  let nextSlot = 0;
  for (const entity of ordered) {
    if (preserveManualLayout && graphState.positions.has(entity.id)) {
      continue;
    }
    const dimensions = graphState.dimensions.get(entity.id);
    let placed = false;
    while (!placed) {
      const column = nextSlot % columns;
      const row = Math.floor(nextSlot / columns);
      nextSlot += 1;
      const candidate = {
        x: COMPACT_GRAPH.startX + column * cellWidth,
        y: COMPACT_GRAPH.startY + row * cellHeight,
        width: dimensions.width,
        height: dimensions.height,
      };
      if (occupied.some((rectangle) => rectanglesOverlap(candidate, rectangle))) {
        continue;
      }
      graphState.positions.set(entity.id, { x: candidate.x, y: candidate.y });
      occupied.push(candidate);
      placed = true;
    }
  }

  const visibleIds = new Set(entities.map((entity) => entity.id));
  for (const id of [...graphState.positions.keys()]) {
    if (!state.entities.has(id)) {
      graphState.positions.delete(id);
      graphState.dimensions.delete(id);
    } else if (!visibleIds.has(id)) {
      continue;
    }
  }
};

graphEndpoint = function compactGraphEndpoint(source, target) {
  const sourcePosition = graphState.positions.get(source.entity.id);
  const targetPosition = graphState.positions.get(target.entity.id);
  const sourceDimensions = graphState.dimensions.get(source.entity.id);
  const targetDimensions = graphState.dimensions.get(target.entity.id);

  const sourceCenter = {
    x: sourcePosition.x + sourceDimensions.centerX,
    y: sourcePosition.y + sourceDimensions.centerY,
  };
  const targetCenter = {
    x: targetPosition.x + targetDimensions.centerX,
    y: targetPosition.y + targetDimensions.centerY,
  };
  const dx = targetCenter.x - sourceCenter.x;
  const dy = targetCenter.y - sourceCenter.y;
  const distance = Math.max(1, Math.hypot(dx, dy));
  const unitX = dx / distance;
  const unitY = dy / distance;

  return {
    source: {
      x: sourceCenter.x + unitX * sourceDimensions.radius,
      y: sourceCenter.y + unitY * sourceDimensions.radius,
    },
    target: {
      x: targetCenter.x - unitX * targetDimensions.radius,
      y: targetCenter.y - unitY * targetDimensions.radius,
    },
  };
};

const baseRenderGraph = renderGraph;
renderGraph = function renderCompactGraph() {
  baseRenderGraph();
  if (state.activePane !== "graph") {
    return;
  }

  for (const [id, entry] of graphState.nodeElements.entries()) {
    const dimensions = graphState.dimensions.get(id);
    if (!dimensions) {
      continue;
    }

    const rectangle = entry.group.querySelector("rect");
    if (rectangle) {
      const circle = createSvg("circle", {
        class: "node-circle",
        cx: dimensions.centerX,
        cy: dimensions.centerY,
        r: dimensions.radius,
        fill: graphFill(entry.entity.type),
        stroke: "rgba(255,255,255,0.28)",
        "stroke-width": 1.25,
      });
      rectangle.replaceWith(circle);

      const restoreStroke = () => {
        circle.setAttribute("stroke", "rgba(255,255,255,0.28)");
        circle.setAttribute("stroke-width", "1.25");
      };
      const highlightStroke = () => {
        circle.setAttribute("stroke", "#4fd1a1");
        circle.setAttribute("stroke-width", "2");
      };
      entry.group.addEventListener("pointerenter", highlightStroke);
      entry.group.addEventListener("pointerleave", restoreStroke);
      entry.group.addEventListener("focus", highlightStroke);
      entry.group.addEventListener("blur", restoreStroke);
    }

    const kind = entry.group.querySelector(".node-kind");
    if (kind) {
      kind.textContent = compactGraphKind(entry.entity.type);
      kind.setAttribute("x", String(dimensions.centerX));
      kind.setAttribute("y", String(dimensions.centerY + 3.5));
      kind.setAttribute("text-anchor", "middle");
      kind.setAttribute("fill", "#ffffff");
      kind.setAttribute("font-size", "10");
      kind.setAttribute("font-weight", "800");
      kind.setAttribute("letter-spacing", "0");
    }

    const label = entry.group.querySelector(".node-label");
    if (label) {
      const span = createSvg("tspan", {
        x: dimensions.labelX,
        dy: 0,
      });
      span.textContent = compactGraphLabel(entry.entity.name);
      label.replaceChildren(span);
      label.setAttribute("x", String(dimensions.labelX));
      label.setAttribute("y", String(dimensions.centerY + 4));
      label.setAttribute("text-anchor", "start");
      label.setAttribute("font-size", "11");
      label.setAttribute("font-weight", "600");
    }
  }

  updateGraphEdges();
};

const baseRenderActivities = renderActivities;
renderActivities = function renderOnlyActiveWorkers() {
  const allActivities = state.activities;
  const workerLimit = Math.max(
    1,
    Number(state.scan?.config?.workers || state.scan?.config?.max_workers || 1),
  );
  const activeActivities = new Map(
    [...allActivities.entries()]
      .filter(([, activity]) => activity.status === "running")
      .slice(0, workerLimit),
  );
  state.activities = activeActivities;
  try {
    baseRenderActivities();
  } finally {
    state.activities = allActivities;
  }

  if (!activeActivities.size) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No active workers.";
    $("activityView").replaceChildren(empty);
  }
};

if (state.activePane === "graph") {
  renderGraph();
}
