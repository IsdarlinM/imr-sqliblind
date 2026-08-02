# Professional web workspace

The web console is optimized for large database maps while preserving the existing authenticated, CSRF-protected and CSP-restricted execution model.

## Hierarchical tree

The Tree view uses native `details` and `summary` controls. Schemas are initially visible, while tables, columns, rows and cells can be expanded only when needed. Filtering automatically opens matching branches. The interface records expanded branches per scan in browser-local workspace state.

## Compact table view

Each discovered table starts as a collapsed summary. Column chips and native HTML row tables are built only after expansion, reducing initial DOM size. `Expand visible` and `Collapse all` operate on the filtered set. HTML exports temporarily render all table bodies so exported reports remain complete.

## Elastic graph interactions

Dragging a node propagates movement through related nodes with bounded falloff:

- selected node: 100%
- first relationship level: 58%
- second level: 34%
- third level: 20%
- fourth level: 12%

Propagation stops after four levels or 120 nodes. Curved relationship paths are recalculated during pointer movement. On release, the existing collision and relationship-force simulation settles the affected cluster.

Advanced controls can hide node types, center the selected node, isolate direct relationships and restore all nodes. Graph positions, zoom and pan are persisted per scan.

## Large result sets

Events and flat entities use fixed-height windowed rendering with overscan. Only visible rows and a small buffer exist in the DOM. Raw data remains in application state and selected rows can still open the details drawer.

## Session comparison

The comparison panel loads two stored snapshots and compares canonical hierarchy signatures. It lists added, removed and changed entities without requiring another scan.

## Workspace and ergonomics

Per-scan browser state retains:

- active result view
- filter
- tree branches
- open table cards
- graph positions, zoom and pan
- details panel width
- compact or comfortable density

Keyboard shortcuts:

- `/`: focus global result filter
- `1`: Tree
- `2`: Graph
- `3`: Tables
- `4`: Entities
- `5`: Events

## Security

The feature layer constructs DOM nodes and assigns text through `textContent`. It does not use `innerHTML`, `eval`, dynamic script injection or third-party CDNs. Authentication, CSRF validation, CSP, response security headers, TLS behavior, request limits and redaction behavior are unchanged.
