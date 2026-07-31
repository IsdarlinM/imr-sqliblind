"use strict";

const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

function classList() {
  const values = new Set();
  return {
    add: (...names) => names.forEach((name) => values.add(name)),
    remove: (...names) => names.forEach((name) => values.delete(name)),
    contains: (name) => values.has(name),
  };
}

function graphEntry(entity) {
  return {
    entity,
    group: {
      classList: classList(),
      dataset: {},
      setAttribute() {},
      removeAttribute() {},
      addEventListener() {},
    },
  };
}

function edgeEntry(relation) {
  return { relation, path: { classList: classList() } };
}

const entities = [
  {
    id: "schema",
    type: "schema",
    name: "main",
    status: "complete",
    data: {},
  },
  {
    id: "users",
    type: "table",
    name: "users",
    parent_id: "schema",
    status: "complete",
    data: { rows: 5 },
  },
  {
    id: "audit",
    type: "table",
    name: "audit",
    parent_id: "schema",
    status: "complete",
    data: {},
  },
  {
    id: "email",
    type: "column",
    name: "email",
    parent_id: "users",
    status: "complete",
    data: {},
  },
];
const relations = [
  {
    id: "r1",
    source_id: "schema",
    target_id: "users",
    kind: "contains",
  },
  {
    id: "r2",
    source_id: "schema",
    target_id: "audit",
    kind: "contains",
  },
  {
    id: "r3",
    source_id: "users",
    target_id: "email",
    kind: "contains",
  },
];
const graph = { addEventListener() {} };
const context = {
  console,
  Math,
  Set,
  Map,
  Object,
  Array,
  String,
  Number,
  Date,
  state: {
    activePane: "tree",
    entities: new Map(entities.map((entity) => [entity.id, entity])),
    relationships: new Map(
      relations.map((relation) => [relation.id, relation]),
    ),
  },
  graphState: {
    nodeElements: new Map(
      entities.map((entity) => [entity.id, graphEntry(entity)]),
    ),
    edgeElements: relations.map(edgeEntry),
    drag: null,
  },
  document: {
    createElement() {
      return {
        className: "",
        hidden: false,
        style: {},
        dataset: {},
        append() {},
        replaceChildren() {},
        setAttribute() {},
        addEventListener() {},
        isConnected: true,
      };
    },
  },
  $: (id) => (id === "graph" ? graph : null),
  renderGraph() {},
  resetGraph() {},
};
vm.createContext(context);
const source = fs.readFileSync(process.argv[2], "utf8");
vm.runInContext(
  `${source}\nthis.__graphTests = { directGraphContext, applyDirectGraphHighlight };`,
  context,
);

const direct = context.__graphTests.directGraphContext("users");
assert.deepStrictEqual([...direct.relatedIds].sort(), ["email", "schema"]);
assert.deepStrictEqual([...direct.relationIds].sort(), ["r1", "r3"]);
assert.strictEqual(direct.parents[0].id, "schema");
assert.strictEqual(direct.children[0].id, "email");

context.__graphTests.applyDirectGraphHighlight("users");
assert(
  context.graphState.nodeElements
    .get("users")
    .group.classList.contains("graph-node-focused"),
);
assert(
  context.graphState.nodeElements
    .get("schema")
    .group.classList.contains("graph-node-related"),
);
assert(
  context.graphState.nodeElements
    .get("email")
    .group.classList.contains("graph-node-related"),
);
assert(
  context.graphState.nodeElements
    .get("audit")
    .group.classList.contains("graph-node-muted"),
);
assert(
  context.graphState.edgeElements[0].path.classList.contains(
    "graph-edge-related",
  ),
);
assert(
  context.graphState.edgeElements[1].path.classList.contains(
    "graph-edge-muted",
  ),
);
assert(
  context.graphState.edgeElements[2].path.classList.contains(
    "graph-edge-related",
  ),
);

console.log("graph relationship interaction harness: ok");
