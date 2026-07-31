"use strict";

const fs = require("fs");
const vm = require("vm");

class ClassList {
  constructor(element) {
    this.element = element;
  }

  values() {
    return new Set(
      String(this.element.className || "")
        .split(/\s+/)
        .filter(Boolean),
    );
  }

  add(...names) {
    const values = this.values();
    names.forEach((name) => values.add(name));
    this.element.className = [...values].join(" ");
  }

  remove(...names) {
    const values = this.values();
    names.forEach((name) => values.delete(name));
    this.element.className = [...values].join(" ");
  }

  toggle(name, force) {
    const values = this.values();
    const enabled = force === undefined ? !values.has(name) : Boolean(force);
    if (enabled) {
      values.add(name);
    } else {
      values.delete(name);
    }
    this.element.className = [...values].join(" ");
    return enabled;
  }

  contains(name) {
    return this.values().has(name);
  }
}

class Element {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.dataset = {};
    this.attributes = {};
    this.listeners = {};
    this.className = "";
    this.classList = new ClassList(this);
    this.textContent = "";
    this.id = "";
    this.value = "";
    this.type = "";
    this.hidden = false;
  }

  append(...children) {
    children.forEach((child) => {
      if (child === null || child === undefined) {
        return;
      }
      this.children.push(child);
      if (child instanceof Element) {
        child.parentNode = this;
      }
    });
  }

  replaceChildren(...children) {
    this.children = [];
    this.append(...children);
  }

  addEventListener(type, callback, options) {
    this.listeners[type] = this.listeners[type] || [];
    this.listeners[type].push({ callback, options });
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === "id") {
      this.id = String(value);
    }
  }

  removeAttribute(name) {
    delete this.attributes[name];
    if (name === "id") {
      this.id = "";
    }
  }

  after(node) {
    const parent = this.parentNode;
    const index = parent.children.indexOf(this);
    parent.children.splice(index + 1, 0, node);
    node.parentNode = parent;
  }

  before(node) {
    const parent = this.parentNode;
    const index = parent.children.indexOf(this);
    parent.children.splice(index, 0, node);
    node.parentNode = parent;
  }

  querySelector(selector) {
    if (selector.startsWith('option[value="')) {
      const value = selector.slice(14, -2);
      return (
        this.descendants().find(
          (node) => node.tagName === "OPTION" && node.value === value,
        ) || null
      );
    }
    return null;
  }

  querySelectorAll(selector) {
    if (selector === "[id]") {
      return this.descendants().filter((node) => node.id);
    }
    return [];
  }

  descendants() {
    const result = [];
    for (const child of this.children) {
      if (!(child instanceof Element)) {
        continue;
      }
      result.push(child, ...child.descendants());
    }
    return result;
  }

  cloneNode(deep) {
    const clone = new Element(this.tagName);
    clone.className = this.className;
    clone.id = this.id;
    clone.value = this.value;
    clone.textContent = this.textContent;
    clone.dataset = { ...this.dataset };
    clone.attributes = { ...this.attributes };
    if (deep) {
      clone.append(
        ...this.children.map((child) =>
          child instanceof Element ? child.cloneNode(true) : child,
        ),
      );
    }
    return clone;
  }

  closest() {
    return null;
  }
}

const elements = new Map();
function register(id, element) {
  element.id = id;
  elements.set(id, element);
  return element;
}

const tabs = new Element("nav");
const treeButton = new Element("button");
treeButton.dataset.pane = "tree";
const graphButton = new Element("button");
graphButton.dataset.pane = "graph";
const entitiesButton = new Element("button");
entitiesButton.dataset.pane = "entities";
tabs.append(treeButton, graphButton, entitiesButton);

const workspace = new Element("main");
const entitiesPane = register("entitiesPane", new Element("section"));
workspace.append(entitiesPane);
register("treePane", new Element("section"));
register("graphPane", new Element("section"));
register("eventsPane", new Element("section"));
register("exportFormat", new Element("select"));
register("exportBtn", new Element("button"));

const document = {
  body: new Element("body"),
  createElement: (name) => new Element(name),
  createDocumentFragment: () => new Element("fragment"),
  querySelector(selector) {
    if (selector === ".tabs") {
      return tabs;
    }
    if (selector === '[data-pane="graph"]') {
      return graphButton;
    }
    return null;
  },
  querySelectorAll(selector) {
    const panes = tabs.children.filter((node) => node.dataset.pane);
    if (selector === "[data-pane]") {
      return panes;
    }
    if (selector.includes(":not")) {
      return panes.filter((node) => node.dataset.pane !== "tables");
    }
    return [];
  },
};

document.body.append(tabs, workspace);
for (const id of [
  "treePane",
  "graphPane",
  "eventsPane",
  "exportFormat",
  "exportBtn",
]) {
  document.body.append(elements.get(id));
}

function byId(id) {
  if (elements.has(id)) {
    return elements.get(id);
  }
  return document.body.descendants().find((node) => node.id === id) || null;
}

const schema = {
  id: "s1",
  type: "schema",
  name: "main",
  parent_id: null,
  status: "complete",
  data: {},
};
const table = {
  id: "t1",
  type: "table",
  name: "User_Profile%",
  parent_id: "s1",
  status: "complete",
  data: {},
};
const column1 = {
  id: "c1",
  type: "column",
  name: "id",
  parent_id: "t1",
  status: "complete",
  data: {},
};
const column2 = {
  id: "c2",
  type: "column",
  name: "_marker",
  parent_id: "t1",
  status: "complete",
  data: {},
};
const row = {
  id: "r1",
  type: "row",
  name: "row 1",
  parent_id: "t1",
  status: "complete",
  data: { values: { id: "1", _marker: "%" } },
};

const context = {
  console,
  document,
  state: {
    scanId: "abcdef123456",
    activePane: "tree",
    filter: "",
    entities: new Map(
      [schema, table, column1, column2, row].map((entity) => [
        entity.id,
        entity,
      ]),
    ),
  },
  $: byId,
  renderAll: () => {},
  openDrawer: () => {},
  toast: () => {},
  Blob: class Blob {},
  URL: {
    createObjectURL: () => "blob:test",
    revokeObjectURL: () => {},
  },
  setTimeout: (callback) => callback(),
  XMLSerializer: class XMLSerializer {
    serializeToString(node) {
      const render = (item) => {
        if (!(item instanceof Element)) {
          return String(item);
        }
        const children = item.children.map(render).join("");
        return `<${item.tagName.toLowerCase()}>${
          item.textContent
        }${children}</${item.tagName.toLowerCase()}>`;
      };
      return render(node);
    }
  },
};

vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), context);
vm.runInContext(fs.readFileSync(process.argv[3], "utf8"), context);

context.activateTablePane();
const grid = byId("tableEntityGrid");
if (!grid || grid.children.length !== 1) {
  throw new Error("table card was not rendered");
}
if (!grid.descendants().some((node) => node.tagName === "TABLE")) {
  throw new Error("native HTML table missing");
}
const ascii = context.tableViewAsciiReport();
if (!ascii.includes("TABLE main.User_Profile%") || !ascii.includes("_marker")) {
  throw new Error("ASCII export missing entities");
}
const html = context.tableViewHtmlReport();
if (!html.includes("<table>") || !html.includes("User_Profile%")) {
  throw new Error("HTML export missing table content");
}
const formats = byId("exportFormat").children.map((node) => node.value);
if (!formats.includes("tables") || !formats.includes("html-tables")) {
  throw new Error("export formats missing");
}
console.log("table view harness passed");
