# imr-sqliblind

```text
imr-sqliblind
imr :: v0.6.4
```

`imr-sqliblind` is a bounded blind SQL injection research helper for authorized laboratories, CTFs, and explicitly permitted security assessments.

The installed command is `sqliblind`. It provides a CLI, a realtime web console, persistent sessions, bounded concurrency, structured exports, and a secure self-update command.

## Requirements

- Python 3.10 or newer.
- Git available through `PATH` for repository installation and self-updates.
- Internet access when installing dependencies or checking for updates.
- A POSIX-compatible shell for `install.sh`, or Windows CMD for `install.cmd`.

## Features

- MySQL and SQLite blind extraction dialects.
- Status, marker, regex, and response-length oracles.
- Binary-search inference for counts, lengths, and characters.
- Stable two-of-three character confirmation with bounded reinference.
- Bounded concurrency with a shared request budget and global delay.
- Schemas, tables, columns, bounded rows, and cells.
- CLI activity monitor without misleading percentages.
- Realtime FastAPI/Uvicorn web console using SSE.
- Responsive web layout for desktop, tablets, and narrow mobile screens.
- Interactive graph with draggable nodes, canvas panning, wheel zoom, fit, and reset.
- Graph positions preserved while realtime entities and relationships arrive.
- Authenticated remote HTTP access with optional TLS.
- SQLite session history, pause, resume, stop, filters, and exports.
- Unicode/ASCII trees, relations, Mermaid, JSON, and HTML reports.
- Sensitive-looking values masked by default.
- TLS validation enabled and redirects disabled by default for target requests.
- Native user-level installers for POSIX systems and Windows.
- `sqliblind update` for checking and installing official updates.

## Installation

Clone the official repository:

```bash
git clone https://github.com/IsdarlinM/imr-sqliblind.git
cd imr-sqliblind
```

### POSIX shell

```bash
chmod +x install.sh uninstall.sh
./install.sh
source ~/.profile 2>/dev/null || true
hash -r
sqliblind --version
```

Default locations:

```text
Application: ~/.local/share/imr-sqliblind
Command:     ~/.local/bin/sqliblind
```

### Windows CMD

```cmd
git clone https://github.com/IsdarlinM/imr-sqliblind.git
cd imr-sqliblind
install.cmd
```

Open a new CMD window and verify:

```cmd
where sqliblind
sqliblind --version
sqliblind --help
```

Default locations:

```text
Application: %LOCALAPPDATA%\Programs\imr-sqliblind
Command:     %LOCALAPPDATA%\Programs\imr-sqliblind\bin\sqliblind.cmd
```

## Updating

Check versions without changing files:

```bash
sqliblind update --check
```

Install an available update:

```bash
sqliblind update
```

Other updater options:

```bash
sqliblind update --check --json
sqliblind update --force
sqliblind update --source /path/to/imr-sqliblind
sqliblind update --timeout 20
sqliblind update --help
```

The updater invokes the literal `git` command through `PATH`; it does not embed a Git executable path for an operating system or distribution.

For a trusted checkout on a filesystem that Git reports as having dubious ownership, the updater passes a command-scoped option equivalent to:

```bash
git -c safe.directory=/absolute/checkout/path status --porcelain
```

The `safe.directory` exception applies only to that updater command. The updater never runs `git config --global`, does not modify `~/.gitconfig`, validates the official `origin`, refuses dirty worktrees, and updates `main` using fast-forward only.

Users upgrading from a version whose updater cannot access the checkout can update once from inside the clone:

```bash
git -c safe.directory="$(pwd -P)" checkout main
git -c safe.directory="$(pwd -P)" pull --ff-only origin main
./install.sh
```

## CLI usage

Show all commands:

```bash
sqliblind --help
```

Basic examples:

```bash
sqliblind schemas
sqliblind tables --schema level5
sqliblind columns --schema level5 --table photos
sqliblind extract --expression "SELECT DATABASE()"
sqliblind probe --condition "1=1"
sqliblind map
```

Use another authorized target:

```bash
sqliblind \
  --url "https://lab.example/fetch" \
  --parameter id \
  --workers 8 \
  map
```

## Activity progress

The CLI shows current work instead of a fabricated percentage. Concurrent workers appear as independent tasks with operation, target, extraction detail, request count, and elapsed time.

```bash
sqliblind --workers 8 map
sqliblind --progress live map
sqliblind --progress plain map
sqliblind --progress off map
```

JSON output remains machine-readable:

```bash
sqliblind --json map
```

## Reliable character inference

Each inferred character is confirmed with at least two independent equality probes. If the probes disagree, a third probe decides by majority. If a candidate is rejected, the complete binary search for that character is restarted up to three times.

Retry and recovery events are recorded as `inference.retry` and `inference.recovered`.

## Realtime web console

Start locally:

```bash
sqliblind web
```

Defaults:

```text
Host: 127.0.0.1
Port: 8088
```

Useful options:

```bash
sqliblind web --port 9000
sqliblind web --workspace "$HOME/sqliblind-workspaces"
sqliblind web --no-open-browser
```

### Remote HTTP access

Remote HTTP access requires an explicit non-loopback opt-in and a token, but it does not require a TLS certificate:

```bash
sqliblind web \
  --host 0.0.0.0 \
  --allow-remote \
  --token "a-long-random-token"
```

The console starts at `http://HOST:8088`. A warning is printed because the token, session metadata, and scan results are not encrypted in transit. Use this mode only on a trusted local network.

### Optional remote HTTPS

TLS remains available by supplying both certificate files:

```bash
sqliblind web \
  --host 0.0.0.0 \
  --allow-remote \
  --token "a-long-random-token" \
  --ssl-certfile server.crt \
  --ssl-keyfile server.key
```

Certificate and key options must be used together. When TLS is enabled, the console uses HTTPS and secure cookies.

### Responsive frontend

The web interface uses fluid grids and safe text wrapping so long URLs, entity names, activity details, raw events, and form fields do not overflow their panels.

At narrower widths:

- The sidebar becomes a full-width section above the workspace.
- Multi-column forms collapse to one column.
- Scan and export controls wrap instead of being clipped.
- Tabs remain horizontally scrollable.
- The details drawer becomes a full-screen mobile panel.
- Activity cards, metrics, sessions, entities, and long raw values remain readable.

### Interactive graph

Open the **Graph** tab to use the dynamic relationship graph.

- Drag any node with the mouse or a pointer device.
- Drag empty canvas space to pan.
- Use the mouse wheel or `+` and `−` controls to zoom.
- Use **Fit** to center all visible nodes.
- Use **Reset layout** to rebuild the hierarchy.
- Node positions persist while realtime events add entities and relationships.
- Filtering preserves ancestor context.
- All matching entities are rendered; the previous 120-node frontend truncation was removed.
- Long node names wrap across multiple SVG text lines instead of being cut.

The browser also displays current activities, schemas, tables, columns, rows, cells, raw events, session history, filters, exports, and a right-side details drawer.

## Bounded row extraction

Row extraction is disabled by default and must target an explicit table:

```bash
sqliblind rows \
  --schema level5 \
  --table photos \
  --max-rows 5 \
  --max-data-columns 10 \
  --max-value-length 128 \
  --max-data-bytes 10000
```

Include bounded data in a map only for explicitly selected tables:

```bash
sqliblind map \
  --include-data \
  --data-table level5.photos \
  --max-rows 5 \
  --format html \
  --output reports/full-map.html
```

## Concurrency and safety

```bash
sqliblind --workers 64 --delay 0.1 --max-requests 5000 map
```

- Workers: 1–64 in the CLI.
- One thread-local HTTP session per worker.
- Shared global delay and request budget.
- Deterministic output ordering.
- Stable character confirmation and bounded reinference.
- Cooperative pause, resume, and cancellation.
- Pending futures cancelled after failures.
- TLS validation enabled unless `--insecure` is explicitly supplied.
- Redirects are not followed.

## Oracle modes

```bash
sqliblind --oracle status --true-status 200 schemas
sqliblind --oracle marker --true-marker "RESULT=TRUE" schemas
sqliblind --oracle regex --true-regex "Welcome\s+back" schemas
sqliblind --oracle length --true-length 3246 --length-tolerance 3 schemas
```

## Headers, cookies, proxy, and TLS

```bash
sqliblind \
  --header "User-Agent:imr-sqliblind/0.6.4" \
  --cookie "session=test-value" \
  --proxy "http://127.0.0.1:8080" \
  schemas
```

Use `--insecure` only in a controlled laboratory with a known self-signed certificate.

## Uninstalling

POSIX shell:

```bash
./uninstall.sh
```

Windows CMD:

```cmd
uninstall.cmd
```

## Development and validation

```bash
python -m pip install -e ".[dev,web]"
python -m unittest discover -s tests -v
pytest -q
python -m compileall -q src sqli_gallery.py sqliblind.py tests
bash -n install.sh uninstall.sh
node --check src/blind_sqli/webui/app.js
ruff check .
bandit -q -r src
```

Frontend regression checks cover required graph controls, overflow-safe CSS, mobile breakpoints, pointer interactions, persistent graph positions, full graph rendering, non-truncated labels, and valid JavaScript syntax.

All testing must remain minimal and within an explicitly authorized scope. Automated unlimited database dumping is intentionally excluded.
