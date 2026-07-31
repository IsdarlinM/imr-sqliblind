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
  density: 1.45,
  randomAttempts: 180,
  simulationMilliseconds: 950,
});

const dynamicGraphState = {
  knownIds: new Set(),
  velocities: new Map(),
  pendingMotion: false,
  movableIds: new Set(),
  animationFrame: null,
  animationStartedAt: 0,
  lastFrameAt: 0,
};

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

function rectanglesOverlap(left, right, gapX = 0, gapY = 0) {
  return !(
    left.x + left.width + gapX <= right.x ||
    right.x + right.width + gapX <= left.x ||
    left.y + left.height + gapY <= right.y ||
    right.y + right.height + gapY <= left.y
  );
}

function dynamicGraphBounds(entities) {
  const viewport = graphViewportSize();
  const dimensions = entities.map((entity) =>
    graphState.dimensions.get(entity.id),
  );
  const occupiedArea = dimensions.reduce(
    (total, item) =>
      total +
      (item.width + COMPACT_GRAPH.horizontalGap) *
        (item.height + COMPACT_GRAPH.verticalGap),
    0,
  );
  const aspect = viewport.width / Math.max(viewport.height, 1);
  const requiredArea = Math.max(
    viewport.width * viewport.height * 0.78,
    occupiedArea * COMPACT_GRAPH.density,
  );
  const width = Math.max(
    viewport.width - COMPACT_GRAPH.startX * 2,
    Math.sqrt(requiredArea * aspect),
  );
  const height = Math.max(
    viewport.height - COMPACT_GRAPH.startY * 2,
    requiredArea / Math.max(width, 1),
  );
  return {
    x: COMPACT_GRAPH.startX,
    y: COMPACT_GRAPH.startY,
    width,
    height,
  };
}

function randomGraphCandidate(bounds, dimensions, randomSource = Math.random) {
  const availableWidth = Math.max(1, bounds.width - dimensions.width);
  const availableHeight = Math.max(1, bounds.height - dimensions.height);
  return {
    x: bounds.x + randomSource() * availableWidth,
    y: bounds.y + randomSource() * availableHeight,
    width: dimensions.width,
    height: dimensions.height,
  };
}

function randomAvailableGraphPosition(
  dimensions,
  occupied,
  initialBounds,
  randomSource = Math.random,
) {
  const bounds = { ...initialBounds };
  for (let expansion = 0; expansion < 7; expansion += 1) {
    for (let attempt = 0; attempt < COMPACT_GRAPH.randomAttempts; attempt += 1) {
      const candidate = randomGraphCandidate(
        bounds,
        dimensions,
        randomSource,
      );
      const collision = occupied.some((rectangle) =>
        rectanglesOverlap(
          candidate,
          rectangle,
          COMPACT_GRAPH.horizontalGap,
          COMPACT_GRAPH.verticalGap,
        ),
      );
      if (!collision) {
        return {
          x: candidate.x,
          y: candidate.y,
          bounds,
        };
      }
    }
    bounds.width *= 1.22;
    bounds.height *= 1.22;
  }

  const slot = occupied.length;
  const columns = Math.max(1, Math.ceil(Math.sqrt(slot + 1)));
  return {
    x:
      bounds.x +
      (slot % columns) *
        (dimensions.width + COMPACT_GRAPH.horizontalGap),
    y:
      bounds.y +
      Math.floor(slot / columns) *
        (dimensions.height + COMPACT_GRAPH.verticalGap),
    bounds,
  };
}

function stopDynamicGraphMotion() {
  if (dynamicGraphState.animationFrame !== null) {
    cancelAnimationFrame(dynamicGraphState.animationFrame);
    dynamicGraphState.animationFrame = null;
  }
}

const baseResetGraph = resetGraph;
resetGraph = function resetDynamicGraph() {
  stopDynamicGraphMotion();
  dynamicGraphState.knownIds.clear();
  dynamicGraphState.velocities.clear();
  dynamicGraphState.pendingMotion = false;
  dynamicGraphState.movableIds.clear();
  baseResetGraph();
};

layoutGraph = function randomAvailableLayoutGraph(entities, force = false) {
  if (force) {
    stopDynamicGraphMotion();
    graphState.positions.clear();
    graphState.dimensions.clear();
    dynamicGraphState.knownIds.clear();
    dynamicGraphState.velocities.clear();
  }

  const visibleIds = new Set(entities.map((entity) => entity.id));
  for (const entity of entities) {
    graphState.dimensions.set(entity.id, graphNodeDimensions(entity));
  }

  for (const id of [...dynamicGraphState.knownIds]) {
    if (!state.entities.has(id)) {
      dynamicGraphState.knownIds.delete(id);
      dynamicGraphState.velocities.delete(id);
      graphState.positions.delete(id);
      graphState.dimensions.delete(id);
    }
  }

  const bounds = dynamicGraphBounds(entities);
  const occupied = [];
  for (const entity of entities) {
    const position = graphState.positions.get(entity.id);
    const dimensions = graphState.dimensions.get(entity.id);
    if (position && dimensions && dynamicGraphState.knownIds.has(entity.id)) {
      occupied.push({ ...position, ...dimensions, id: entity.id });
    }
  }

  const newIds = new Set();
  const shuffled = [...entities].sort(() => Math.random() - 0.5);
  for (const entity of shuffled) {
    if (
      dynamicGraphState.knownIds.has(entity.id) &&
      graphState.positions.has(entity.id)
    ) {
      continue;
    }
    const dimensions = graphState.dimensions.get(entity.id);
    const placement = randomAvailableGraphPosition(
      dimensions,
      occupied,
      bounds,
    );
    graphState.positions.set(entity.id, {
      x: placement.x,
      y: placement.y,
    });
    occupied.push({
      x: placement.x,
      y: placement.y,
      width: dimensions.width,
      height: dimensions.height,
      id: entity.id,
    });
    dynamicGraphState.knownIds.add(entity.id);
    dynamicGraphState.velocities.set(entity.id, {
      x: (Math.random() - 0.5) * 1.6,
      y: (Math.random() - 0.5) * 1.6,
    });
    newIds.add(entity.id);
  }

  for (const id of [...graphState.positions.keys()]) {
    if (!state.entities.has(id)) {
      graphState.positions.delete(id);
      graphState.dimensions.delete(id);
      dynamicGraphState.knownIds.delete(id);
      dynamicGraphState.velocities.delete(id);
    } else if (!visibleIds.has(id)) {
      continue;
    }
  }

  if (newIds.size || force) {
    dynamicGraphState.pendingMotion = true;
    dynamicGraphState.movableIds = graphState.userTransformed
      ? newIds
      : new Set(visibleIds);
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

function graphRectangle(entity) {
  const position = graphState.positions.get(entity.id);
  const dimensions = graphState.dimensions.get(entity.id);
  return position && dimensions
    ? {
        id: entity.id,
        x: position.x,
        y: position.y,
        width: dimensions.width,
        height: dimensions.height,
      }
    : null;
}

function graphSpatialBuckets(entities, cellSize = 180) {
  const buckets = new Map();
  for (const entity of entities) {
    const rectangle = graphRectangle(entity);
    if (!rectangle) {
      continue;
    }
    const centerX = rectangle.x + rectangle.width / 2;
    const centerY = rectangle.y + rectangle.height / 2;
    const key = `${Math.floor(centerX / cellSize)}:${Math.floor(
      centerY / cellSize,
    )}`;
    if (!buckets.has(key)) {
      buckets.set(key, []);
    }
    buckets.get(key).push(entity);
  }
  return buckets;
}

function applyCollisionForces(entities, forces) {
  const buckets = graphSpatialBuckets(entities);
  const processed = new Set();
  for (const [key, bucket] of buckets.entries()) {
    const [baseX, baseY] = key.split(":").map(Number);
    const neighbors = [];
    for (let offsetX = -1; offsetX <= 1; offsetX += 1) {
      for (let offsetY = -1; offsetY <= 1; offsetY += 1) {
        neighbors.push(
          ...(buckets.get(`${baseX + offsetX}:${baseY + offsetY}`) || []),
        );
      }
    }
    for (const left of bucket) {
      const leftRectangle = graphRectangle(left);
      if (!leftRectangle) {
        continue;
      }
      for (const right of neighbors) {
        if (left.id === right.id) {
          continue;
        }
        const pair = [left.id, right.id].sort().join("|");
        if (processed.has(pair)) {
          continue;
        }
        processed.add(pair);
        const rightRectangle = graphRectangle(right);
        if (
          !rightRectangle ||
          !rectanglesOverlap(
            leftRectangle,
            rightRectangle,
            COMPACT_GRAPH.horizontalGap,
            COMPACT_GRAPH.verticalGap,
          )
        ) {
          continue;
        }

        const leftCenterX = leftRectangle.x + leftRectangle.width / 2;
        const leftCenterY = leftRectangle.y + leftRectangle.height / 2;
        const rightCenterX = rightRectangle.x + rightRectangle.width / 2;
        const rightCenterY = rightRectangle.y + rightRectangle.height / 2;
        let dx = rightCenterX - leftCenterX;
        let dy = rightCenterY - leftCenterY;
        if (Math.abs(dx) + Math.abs(dy) < 0.001) {
          dx = Math.random() - 0.5;
          dy = Math.random() - 0.5;
        }
        const distance = Math.max(1, Math.hypot(dx, dy));
        const push = 1.9;
        const unitX = dx / distance;
        const unitY = dy / distance;
        forces.get(left.id).x -= unitX * push;
        forces.get(left.id).y -= unitY * push;
        forces.get(right.id).x += unitX * push;
        forces.get(right.id).y += unitY * push;
      }
    }
  }
}

function applyRelationshipForces(entitiesById, forces) {
  for (const relation of state.relationships.values()) {
    const source = entitiesById.get(relation.source_id);
    const target = entitiesById.get(relation.target_id);
    if (!source || !target) {
      continue;
    }
    const sourceRectangle = graphRectangle(source);
    const targetRectangle = graphRectangle(target);
    if (!sourceRectangle || !targetRectangle) {
      continue;
    }
    const sourceX = sourceRectangle.x + sourceRectangle.width / 2;
    const sourceY = sourceRectangle.y + sourceRectangle.height / 2;
    const targetX = targetRectangle.x + targetRectangle.width / 2;
    const targetY = targetRectangle.y + targetRectangle.height / 2;
    const dx = targetX - sourceX;
    const dy = targetY - sourceY;
    const distance = Math.max(1, Math.hypot(dx, dy));
    const preferred = 145;
    const spring = (distance - preferred) * 0.0035;
    const unitX = dx / distance;
    const unitY = dy / distance;
    forces.get(source.id).x += unitX * spring;
    forces.get(source.id).y += unitY * spring;
    forces.get(target.id).x -= unitX * spring;
    forces.get(target.id).y -= unitY * spring;
  }
}

function updateDynamicGraphNodes(entities) {
  for (const entity of entities) {
    const position = graphState.positions.get(entity.id);
    const entry = graphState.nodeElements.get(entity.id);
    if (!position || !entry) {
      continue;
    }
    entry.group.setAttribute(
      "transform",
      `translate(${position.x} ${position.y})`,
    );
  }
  updateGraphEdges();
}

function dynamicGraphStep(timestamp, entities) {
  if (!dynamicGraphState.animationStartedAt) {
    dynamicGraphState.animationStartedAt = timestamp;
    dynamicGraphState.lastFrameAt = timestamp;
  }
  const elapsed = timestamp - dynamicGraphState.animationStartedAt;
  const delta = Math.min(
    2,
    Math.max(
      0.35,
      (timestamp - dynamicGraphState.lastFrameAt) / 16.67,
    ),
  );
  dynamicGraphState.lastFrameAt = timestamp;

  const movable = dynamicGraphState.movableIds;
  const forces = new Map(
    entities.map((entity) => [entity.id, { x: 0, y: 0 }]),
  );
  const entitiesById = new Map(entities.map((entity) => [entity.id, entity]));
  applyCollisionForces(entities, forces);
  applyRelationshipForces(entitiesById, forces);

  const bounds = dynamicGraphBounds(entities);
  const centerX = bounds.x + bounds.width / 2;
  const centerY = bounds.y + bounds.height / 2;
  let speedTotal = 0;

  for (const entity of entities) {
    if (!movable.has(entity.id)) {
      continue;
    }
    const position = graphState.positions.get(entity.id);
    const dimensions = graphState.dimensions.get(entity.id);
    const force = forces.get(entity.id);
    const velocity =
      dynamicGraphState.velocities.get(entity.id) || { x: 0, y: 0 };
    const nodeCenterX = position.x + dimensions.width / 2;
    const nodeCenterY = position.y + dimensions.height / 2;
    force.x += (centerX - nodeCenterX) * 0.00045;
    force.y += (centerY - nodeCenterY) * 0.00045;

    velocity.x = (velocity.x + force.x * delta) * 0.82;
    velocity.y = (velocity.y + force.y * delta) * 0.82;
    position.x += velocity.x * delta;
    position.y += velocity.y * delta;
    position.x = Math.max(
      bounds.x,
      Math.min(bounds.x + bounds.width - dimensions.width, position.x),
    );
    position.y = Math.max(
      bounds.y,
      Math.min(bounds.y + bounds.height - dimensions.height, position.y),
    );
    dynamicGraphState.velocities.set(entity.id, velocity);
    speedTotal += Math.abs(velocity.x) + Math.abs(velocity.y);
  }

  updateDynamicGraphNodes(entities);
  if (
    !graphState.userTransformed &&
    Math.floor(elapsed / 120) !== Math.floor((elapsed - 17) / 120)
  ) {
    fitGraph(entities);
  }

  const averageSpeed = speedTotal / Math.max(1, movable.size);
  if (
    elapsed < COMPACT_GRAPH.simulationMilliseconds &&
    (elapsed < 260 || averageSpeed > 0.025)
  ) {
    dynamicGraphState.animationFrame = requestAnimationFrame((next) =>
      dynamicGraphStep(next, entities),
    );
    return;
  }

  dynamicGraphState.animationFrame = null;
  dynamicGraphState.animationStartedAt = 0;
  dynamicGraphState.lastFrameAt = 0;
  if (!graphState.userTransformed) {
    fitGraph(entities);
  }
}

function startDynamicGraphMotion(entities) {
  stopDynamicGraphMotion();
  dynamicGraphState.animationStartedAt = 0;
  dynamicGraphState.lastFrameAt = 0;
  dynamicGraphState.pendingMotion = false;
  if (!entities.length || !dynamicGraphState.movableIds.size) {
    return;
  }
  dynamicGraphState.animationFrame = requestAnimationFrame((timestamp) =>
    dynamicGraphStep(timestamp, entities),
  );
}

const baseRenderGraph = renderGraph;
renderGraph = function renderDynamicCompactGraph() {
  baseRenderGraph();
  if (state.activePane !== "graph") {
    return;
  }

  const entities = visibleGraphEntities();
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
  if (dynamicGraphState.pendingMotion) {
    startDynamicGraphMotion(entities);
  }
};

const baseApplyActivity = applyActivity;
applyActivity = function applyLiveActivity(type, activity) {
  baseApplyActivity(type, activity);
  const stored = activity?.id ? state.activities.get(activity.id) : null;
  if (stored) {
    stored.ui_updated_at = Date.now();
  }
};

const baseRenderActivities = renderActivities;
renderActivities = function renderOnlyCurrentSearches() {
  const allActivities = state.activities;
  const workerLimit = Math.max(
    1,
    Number(state.scan?.config?.workers || state.scan?.config?.max_workers || 1),
  );
  const activeActivities = new Map(
    [...allActivities.entries()]
      .filter(([, activity]) => {
        if (activity.status !== "running") {
          return false;
        }
        if (activity.active === false || activity.kind === "batch") {
          return false;
        }
        return true;
      })
      .sort(
        ([, left], [, right]) =>
          Number(right.ui_updated_at || 0) - Number(left.ui_updated_at || 0) ||
          Number(right.requests_used || 0) - Number(left.requests_used || 0),
      )
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
    empty.textContent = "No active searches.";
    $("activityView").replaceChildren(empty);
  }
};

const graphInteractionSurface = $("graph");
if (graphInteractionSurface) {
  graphInteractionSurface.addEventListener(
    "pointerdown",
    stopDynamicGraphMotion,
    { capture: true },
  );
  graphInteractionSurface.addEventListener(
    "wheel",
    stopDynamicGraphMotion,
    { capture: true, passive: true },
  );
}
for (const controlId of ["graphZoomIn", "graphZoomOut", "graphFit"]) {
  const control = $(controlId);
  control?.addEventListener("click", stopDynamicGraphMotion);
}

if (state.activePane === "graph") {
  renderGraph();
}
