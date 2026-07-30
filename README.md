# imr-sqliblind

`imr-sqliblind` is a bounded blind SQL injection research helper for authorized laboratories, CTFs, and explicitly permitted security assessments.

```text
imr-sqliblind
imr :: v0.5.0
```

The installed command is `sqliblind`. Version 0.5.0 adds a persistent realtime web console while keeping the CLI as the shared extraction engine.

## Requirements

- Python **3.10 or newer**.
- Internet access during installation when Python or packages are not already available.
- Linux: Bash, plus `curl` or `wget` only when Python must be bootstrapped.
- Windows 10/11: CMD and Windows PowerShell, used internally by the installer.

When Python 3.10+ is missing, the native installers use the official `uv` bootstrapper and install a managed Python 3.12 runtime.

## Features

- Status, marker, regex, and response-length boolean oracles.
- MySQL and SQLite dialects.
- Binary-search inference for counts, lengths, and characters.
- Bounded concurrency with a shared request budget and global delay.
- Schema, table, column, row, and cell entities.
- Unicode/ASCII trees, relationship lists, Mermaid, JSON, and HTML exports.
- Realtime web console with REST and Server-Sent Events (SSE).
- Typed discovery events and dynamic entity updates.
- Persistent SQLite workspaces and session history.
- Pause, resume, stop, search, filtering, entity details, and exports from the browser.
- Live SVG relationship graph that updates as schemas, tables, columns, rows, and cells appear.
- Opt-in row extraction with strict row, column, value-length, and byte limits.
- Sensitive-looking values masked by default.
- TLS validation enabled by default and redirects disabled.
- Native per-user installers and uninstallers for Linux and Windows.

## Native installation

Clone the repository first:

```bash
git clone https://github.com/IsdarlinM/imr-sqliblind.git
cd imr-sqliblind
```

### Linux

```bash
chmod +x install.sh uninstall.sh
./install.sh
source ~/.profile
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
sqliblind --version
sqliblind --help
```

Default locations:

```text
Application: %LOCALAPPDATA%\Programs\imr-sqliblind
Command:     %LOCALAPPDATA%\Programs\imr-sqliblind\bin\sqliblind.cmd
```

Both installers install the CLI and web dependencies, create an isolated virtual environment, configure `PATH`, and persist:

```text
IMR_SQLIBLIND_HOME
SQLIBLIND_PYTHON
SQLIBLIND_BIN
```

Installer options:

```bash
./install.sh --help
./install.sh --prefix "$HOME/tools/imr-sqliblind"
./install.sh --python /usr/bin/python3.10
./install.sh --no-path
```

```cmd
install.cmd --help
install.cmd --prefix "%USERPROFILE%\Tools\imr-sqliblind"
install.cmd --python "C:\Python310\python.exe"
install.cmd --no-path
```

### Updating

There is currently no `sqliblind update` command. Pull the repository and rerun the installer:

```bash
git pull
./install.sh
```

```cmd
git pull
install.cmd
```

### Uninstalling

```bash
./uninstall.sh
```

```cmd
uninstall.cmd
```

## Live activity progress

The CLI and web console show **current work**, not a guessed percentage. Concurrent workers are displayed like parallel downloads, with one activity row/card per active task.

Typical activity messages include:

```text
Count tables              main                  searching integer in range 0..64
Extract table name        main · table slot 2   extracting character 4/11
Count columns             main.users            resolved integer: 7
Extract cell value        main.users · row 1 · email  extracted 8/24 characters
```

In an interactive terminal the default `auto` mode uses an in-place multi-worker display on stderr, keeping final results on stdout:

```bash
sqliblind --workers 6 map
```

Progress modes:

```bash
sqliblind --progress live map      # force the dynamic terminal view
sqliblind --progress plain map     # append start/completion lifecycle lines
sqliblind --progress off map       # disable activity output
sqliblind --json map               # JSON stays clean; progress is disabled automatically
```

The web console persists activity state in SQLite, streams updates through SSE, and restores active/recent tasks after a page reload. Each card shows the worker, operation, target object, current extraction step, elapsed time, request count, and count-based details such as `character 4/11`; it intentionally does not show percentages.

## Realtime web console

Start the local console:

```bash
sqliblind web
```

Defaults:

```text
Host: 127.0.0.1
Port: 8088
Linux workspace:  ~/.local/share/imr-sqliblind/workspaces/sessions.db
Windows workspace: %LOCALAPPDATA%\Programs\imr-sqliblind\workspaces\sessions.db
```

When `IMR_SQLIBLIND_HOME` is configured by the native installer, the console stores workspaces below that installation directory.

The command generates a random authentication token, opens a tokenized bootstrap URL, stores the token in an `HttpOnly` `SameSite=Strict` cookie, redirects to a clean URL, and uses a separate double-submit CSRF token for state-changing requests.

Useful options:

```bash
sqliblind web --port 9000
sqliblind web --workspace "$HOME/sqliblind-workspaces"
sqliblind web --no-open-browser
```

Remote binding is blocked unless explicitly enabled. Remote access also requires an explicit token and TLS certificate/key pair:

```bash
sqliblind web \
  --host 0.0.0.0 \
  --allow-remote \
  --token "a-long-random-token" \
  --ssl-certfile server.crt \
  --ssl-keyfile server.key
```

### Realtime entities

The console represents discoveries as typed entities:

```text
Scan
└── Schema
    └── Table
        ├── Column
        └── Row
            └── Cell
```

Entity states include:

```text
queued
running
paused
discovering
complete
stopping
cancelled
failed
interrupted
```

The web form exposes the same target, URL-template, oracle, HTTP, proxy, header, cookie, TLS, concurrency, and extraction-limit controls as the CLI. Findings can be viewed as a hierarchy, a live SVG graph, entity cards, explicit relationships, or raw events. Selecting an object opens a right-side detail drawer with its structured data and related edges.

The browser receives events through SSE, including:

```text
scan.started
scan.calibrated
phase.started
schema.discovered
table.discovered
column.discovered
row.discovered
cell.discovered
entity.updated
relationship.created
request.completed
scan.paused
scan.resumed
scan.completed
scan.failed
scan.cancelled
```

### Persistence

SQLite stores:

- Scan configuration with sensitive headers and cookies redacted.
- Scan status and statistics.
- Ordered typed events.
- Entities and parent relationships.
- Completed and interrupted session history.

SQLite uses foreign keys, WAL mode, parameterized queries, and a process-local write lock for concurrent extractor events.

### Bounded row extraction

Row extraction is disabled by default. In the web form, enable it and specify one or more exact `schema.table` selectors.

Hard web limits:

```text
Rows per table:      1–25
Columns per table:   1–20
Value length:        1–512 characters
Total extracted:     1–50,000 bytes
Workers:             1–16
```

Sensitive-looking columns such as passwords, tokens, sessions, API keys, authorization values, and card fields are masked before persistence and export unless the user explicitly enables unmasked display.

## CLI usage

Running without a subcommand enumerates schemas:

```bash
sqliblind
```

Explicit commands:

```bash
sqliblind schemas
sqliblind tables --schema level5
sqliblind columns --schema level5 --table photos
sqliblind extract --expression "SELECT DATABASE()"
sqliblind probe --condition "1=1"
```

Use another authorized target:

```bash
sqliblind --url "https://lab.example/fetch" --parameter id schemas
```

### Bounded rows from CLI

```bash
sqliblind rows \
  --schema level5 \
  --table photos \
  --max-rows 5 \
  --max-data-columns 10 \
  --max-value-length 128 \
  --max-data-bytes 10000
```

Unmask sensitive-looking values only when explicitly required:

```bash
sqliblind rows \
  --schema level5 \
  --table photos \
  --show-sensitive-values
```

### Schema maps and exports

`map`, `graph`, and `schema-map` are aliases:

```bash
sqliblind map
sqliblind map --ascii
sqliblind map --format relations
sqliblind map --format mermaid --output reports/schema-map.mmd
sqliblind map --format html --output reports/schema-map.html
sqliblind --json map --output reports/schema-map.json
```

Include bounded row values only for explicit tables:

```bash
sqliblind map \
  --include-data \
  --data-table level5.photos \
  --max-rows 5 \
  --format html \
  --output reports/full-map.html
```

### Safe concurrency

```bash
sqliblind --workers 8 --delay 0.1 --max-requests 5000 map
```

Safety characteristics:

- `1 <= workers <= 16`.
- One active thread pool per extraction phase.
- Shared global delay and request budget.
- One `requests.Session` per worker thread.
- Deterministic output ordering.
- Cooperative pause, resume, and cancellation checkpoints.
- Pending future cancellation after failures.
- TLS validation enabled unless `--insecure` is explicitly supplied.
- Redirects are not followed.

### Oracle modes

```bash
sqliblind --oracle status --true-status 200 schemas
sqliblind --oracle marker --true-marker "RESULT=TRUE" schemas
sqliblind --oracle regex --true-regex "Welcome\s+back" schemas
sqliblind --oracle length --true-length 3246 --length-tolerance 3 schemas
```

### Headers, cookies, proxy, and TLS

```bash
sqliblind \
  --header "User-Agent:imr-sqliblind/0.5.0" \
  --cookie "session=test-value" \
  --proxy "http://127.0.0.1:8080" \
  schemas
```

Use `--insecure` only in a controlled laboratory with a known self-signed certificate.

## Development and validation

Install all development and web dependencies:

```bash
python -m pip install -e ".[dev,web]"
```

Run the complete suite:

```bash
python -m unittest discover -s tests -v
pytest -q
python -m compileall -q src sqli_gallery.py sqliblind.py tests
bash -n install.sh uninstall.sh
ruff check .
bandit -q -r src
```

The CI matrix covers Python 3.10, 3.11, 3.12, and 3.13, native Linux/Windows installer smoke tests, web API tests, packaged UI resources, and JavaScript syntax validation.

## Scope

Metadata enumeration includes schemas, tables, and columns. Row and cell extraction is explicit, bounded, and disabled by default. Automated unlimited database dumping is not included. Keep all testing minimal and within the authorized scope.
