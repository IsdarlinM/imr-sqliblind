# Professional web workspace

The web console adds a presentation layer on top of the existing scan engine. It does not alter extraction payloads, oracle decisions, request limits, authentication, CSRF handling, or persistence.

## Compact hierarchy

The Tree view uses native `details` and `summary` controls. Schemas are expanded initially while tables, columns, rows, and cells remain collapsible. Filtering automatically opens matching branches. The toolbar can expand schemas, expand everything, or collapse the complete tree.

Only open branches render their descendants. This reduces DOM size when a scan contains many tables, columns, rows, or cells.

## Compact table view

Each discovered table is represented by one collapsed summary row containing its fully qualified name, status, column count, and row count. Column chips and row data are created only when the table is expanded.

The view includes controls to expand visible tables or collapse them all. HTML exports temporarily expand every table so the exported report remains complete.

## Elastic graph interaction

Dragging a graph node moves the connected relationship cluster using distance-based falloff:

- selected node: 100%
- direct relation: 58%
- distance two: 34%
- distance three: 20%
- distance four: 12%

The propagation is bounded to 120 nodes to keep pointer interaction responsive on large scans. Related edges use animated elastic styling while dragging. On release, the existing collision and relationship-force simulation settles the affected cluster.

## Workspace controls

- Compact and comfortable density modes, persisted in local storage.
- Sticky scan controls and result tabs on desktop.
- Per-view result counters.
- `/` focuses the global filter.
- Number keys `1` through `5` select Tree, Graph, Tables, Entities, and Events.
- Reduced-motion preferences disable decorative edge animation.

## Security and performance

The implementation uses DOM construction and `textContent`; it does not use `innerHTML`, `eval`, or dynamic code generation. Existing same-origin CSP, authenticated asset loading, CSRF controls, and no-store response headers remain unchanged.
