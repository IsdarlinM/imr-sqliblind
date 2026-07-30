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
  horizontalGap: 176,
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

layoutGraph = function compactLayoutGraph(entities, force = false) {
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
    let cursorY = COMPACT_GRAPH.startY;
    for (const entity of column) {
      const dimensions = graphState.dimensions.get(entity.id);
      const existing = graphState.positions.get(entity.id);
      if (existing && !force) {
        cursorY = Math.max(
          cursorY,
          existing.y + dimensions.height + COMPACT_GRAPH.verticalGap,
        );
        continue;
      }
      graphState.positions.set(entity.id, {
        x: COMPACT_GRAPH.startX + depth * COMPACT_GRAPH.horizontalGap,
        y: cursorY,
      });
      cursorY += dimensions.height + COMPACT_GRAPH.verticalGap;
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

if (state.activePane === "graph") {
  renderGraph();
}
