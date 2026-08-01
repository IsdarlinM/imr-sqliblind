# imr-sqliblind

```text
imr-sqliblind
imr :: v0.8.2
```

`imr-sqliblind` is a bounded blind SQL injection research helper for authorized laboratories, CTFs, and explicitly permitted security assessments.

The installed command is `sqliblind`. It provides a CLI, a realtime web console, an authenticated background service, persistent scan sessions, managed users, bounded concurrency, structured exports, and a secure self-update command.

## Requirements

- Python 3.10 or newer.
- Git available through `PATH` for repository installation and self-updates.
- Internet access when installing dependencies or checking for updates.
- A POSIX-compatible shell for `install.sh`, or Windows CMD for `install.cmd`.

## Features

- MySQL and SQLite blind extraction dialects.
- Status, marker, regex, and response-length oracles.
- Turbo bounded-integer and length inference using globally scheduled bit planes.
- Modulo-3 error detection plus exact whole-identifier confirmation and robust fallback.
- Adaptive character inference using weighted numeric partitions with exact fallback.
- Compatibility bitwise and binary inference modes.
- Character-position scheduling across all workers, including a single entity.
- Adaptive equality confirmation with noise-aware two-of-three fallback only when required.
- AIMD concurrency control, shared request budget, and configurable global delay.
- Smallest-schema-first schema → tables → columns → bounded rows discovery.
- Batched SQLite event persistence with sampled raw request events.
- Schemas, tables, columns, bounded rows, and cells.
- CLI activity monitor without misleading percentages.
- Realtime FastAPI/Uvicorn web console using SSE.
- Detached user-level service controlled with `start`, `stop`, `restart`, and `status`.
- Persistent JSON service configuration with an unusual loopback default port (`43127`).
- SQLite-backed users, roles, temporary-account expiration, session revocation, and audit events.
- Mandatory replacement of the bootstrap `admin:admin` password.
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

## Authenticated background service

Start the realtime console as a detached user-level service:

```bash
sqliblind start
sqliblind status
```

Default endpoint:

```text
http://127.0.0.1:43127/
```

The deliberately unusual default port is `43127`. Override the saved host or port for one launch without modifying the configuration:

```bash
sqliblind start --port 43128
sqliblind restart --host 127.0.0.1 --port 43129
```

Control the service:

```bash
sqliblind stop
sqliblind restart
sqliblind status
```

Use foreground mode for diagnostics:

```bash
sqliblind start --foreground
```

The service runs without root or Administrator privileges. Its state file contains the PID, effective URL, paths, and a random control token. `status` verifies an authenticated control endpoint, and `stop` requests graceful Uvicorn shutdown instead of killing an unverified PID.

### Bootstrap administrator

When the authentication database is empty, the first service start creates:

```text
Username: admin
Password: admin
```

The bootstrap account is marked for mandatory password replacement. The browser redirects it to the password-change screen and denies console/API access until the password has been changed. The default service binds only to loopback; change the password before enabling remote access.

### Users, roles, credentials, and expiration

Create permanent users:

```bash
sqliblind users create analyst --role operator
sqliblind users create auditor --role viewer
sqliblind users create backup-admin --role admin
```

Create temporary users:

```bash
sqliblind users create contractor --role operator --expires-in 12h
sqliblind users create reviewer --role viewer --expires-in 7d
```

Supported relative durations use minutes, hours, days, or weeks: `30m`, `12h`, `7d`, and `2w`.

Manage existing users:

```bash
sqliblind users list
sqliblind users passwd analyst
sqliblind users role analyst viewer
sqliblind users disable analyst
sqliblind users enable analyst
sqliblind users expire analyst --in 24h
sqliblind users expire analyst --never
sqliblind users delete analyst
sqliblind users audit --limit 100
```

Roles:

- `admin`: manage users, inspect audit events, change defaults, and operate scans.
- `operator`: create, pause, resume, and stop scans; read sessions and exports.
- `viewer`: read the console, sessions, events, graph, tables, and exports.

Administrators can also use the responsive browser administration page at:

```text
/admin/
```

It supports account creation, permanent or temporary expiration, role changes, enable/disable, credential resets with optional mandatory replacement, deletion, and audit inspection.

Passwords are prompted without echo. There is intentionally no `--password` argument because command-line secrets can leak through shell history and process listings. For controlled automation, provide one password line through standard input:

```bash
printf '%s\n' 'Strong-Temporary-Password9' | \
  sqliblind users create ci-operator \
  --role operator \
  --expires-in 2h \
  --password-stdin
```

Password, role, activation, and expiration changes revoke existing sessions. Expired users stop resolving immediately. The store prevents deleting, disabling, demoting, or making temporary the last usable administrator.

### Service configuration

Create or locate the persistent configuration:

```bash
sqliblind config init
sqliblind config show
```

Default paths:

```text
Windows:
  %LOCALAPPDATA%\Programs\imr-sqliblind\config\service.json

POSIX:
  ~/.local/share/imr-sqliblind/config/service.json
```

Update persistent defaults:

```bash
sqliblind config set --port 43128
sqliblind config set --session-hours 8
sqliblind config set --workspace /srv/sqliblind/workspaces
sqliblind config set --log-file /var/log/sqliblind/service.log
```

Use another configuration file:

```bash
sqliblind start --config ./service.json
sqliblind users --config ./service.json list
sqliblind config --config ./service.json show
```

The JSON file controls the host, port, remote opt-in, TLS files, session lifetime, workspace, authentication database, log file, and state file. Writes use atomic replacement. On POSIX systems, configuration, service state, and the authentication database use user-only permissions where the filesystem supports them.

### Remote service access

Remote binding requires an explicit opt-in:

```bash
sqliblind config set --host 0.0.0.0 --allow-remote
```

Remote HTTP sends credentials, cookies, scan metadata, and results without transport encryption. Prefer TLS:

```bash
sqliblind config set \
  --host 0.0.0.0 \
  --allow-remote \
  --ssl-certfile /path/server.crt \
  --ssl-keyfile /path/server.key
sqliblind restart
```

Certificate and key must both exist. Authentication cookies are marked `Secure` when TLS is enabled.

### Service authentication security

- Passwords use PBKDF2-HMAC-SHA-256 with unique random 128-bit salts and 310,000 iterations.
- Password digest comparison is constant-time, including a same-cost fake hash for unknown users.
- Browser sessions use random 256-bit tokens; only SHA-256 token hashes are stored.
- Account activation, account expiration, session expiration, and authentication version are checked on every request.
- Browser mutations require CSRF tokens.
- Login errors do not reveal whether a username exists and repeated failures are rate-limited.
- The legacy web token remains random and internal to the authenticated gateway; client-supplied internal-token headers are stripped.
- Account-management and authentication events are audited without storing passwords or session tokens.

Complete reference: [docs/service-and-users.md](docs/service-and-users.md).

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

Service configuration, users, audit events, workspaces, and logs live in the application data root and are preserved across updates and reinstalls.

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
  --workers 16 \
  map
```

## Activity progress

The CLI shows current work instead of a fabricated percentage. Concurrent workers appear as independent tasks with operation, target, extraction detail, request count, and elapsed time.

```bash
sqliblind --workers 16 map
sqliblind --progress live map
sqliblind --progress plain map
sqliblind --progress off map
```

JSON output remains machine-readable:

```bash
sqliblind --json map
```

## Optimized exact inference

The default `turbo` mode uses globally scheduled bit planes for bounded integers, lengths, and character codes. Independent boolean decisions are executed breadth-first across the worker pool instead of waiting for the previous decision before choosing the next.

Character conditions use numeric comparisons only:

```sql
((code_expression) & 1) <> 0
((code_expression) & 2) <> 0
((code_expression) % 3) = 0
(code_expression) = 95
```

`%` is inferred as code `37` and `_` as code `95`. They are never inserted into a `LIKE` pattern, so neither character can act as a wildcard during character discovery. The SQLite catalog query `name NOT LIKE 'sqlite_%'` remains limited to excluding internal SQLite tables and is unrelated to character inference.

Turbo reconstructs the candidate from independent bits, checks its modulo-3 residue, and confirms the complete identifier with one equality probe. A checksum or confirmation mismatch falls back to the existing exact per-character path only for the affected value.

Available modes:

```bash
sqliblind --inference-mode turbo --workers 16 map
sqliblind --inference-mode adaptive --workers 8 map
sqliblind --inference-mode bitwise --workers 8 map
sqliblind --inference-mode binary --workers 8 map
```

- `turbo`: breadth-first bit planes, modulo-3 error detection, aggregate identifier confirmation, and exact fallback.
- `adaptive`: weighted numeric partitions, online character-frequency learning, one normal equality confirmation, and robust majority fallback only after inconsistency.
- `bitwise`: globally schedules independent code bits across workers, then confirms each reconstructed code.
- `binary`: compatibility mode using a fast numeric binary search and adaptive fallback.

Use `--serial-characters` only for diagnostics. By default, positions from one or many entities share the same worker pool. `--fixed-concurrency` disables AIMD backoff when a strictly fixed request concurrency is required. Adaptive concurrency begins at the configured worker ceiling, halves on HTTP 429 or transport failures, and recovers additively after stable responses.

Complete algorithm and workflow details: [docs/turbo-discovery.md](docs/turbo-discovery.md).

### Reproducible simulated benchmark

Run:

```bash
python benchmarks/inference_benchmark.py \
  --value 'A_9%' \
  --latency 0.01 \
  --workers 64 \
  --require-speedup 0.75
```

The simulator exits non-zero when turbo does not achieve at least a 75% latency reduction versus adaptive mode under this controlled clean-oracle configuration. This threshold measures dependency depth with enough workers to execute one character bit plane concurrently.

It is a deterministic laboratory target, not a promise for every remote system. Real performance depends on target latency, configured delay, rate limits, oracle noise, transport failures, identifier lengths, worker count, and server capacity.

## Smallest-schema-first map flow

After schema discovery, the mapper infers all table counts concurrently and orders schemas by `(table count, case-insensitive name)`. For each schema it then:

1. Discovers every table name.
2. Discovers columns for every table.
3. Extracts bounded rows for every table, or for optional `schema.table` filters.
4. Completes the schema before starting the next one.

The table count is used as the size metric because it is bounded metadata available before table names and content are extracted.

## Realtime web console

The original foreground token-authenticated command remains available independently of service mode.

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

The dedicated `rows` command always targets one explicit table:

```bash
sqliblind rows \
  --schema level5 \
  --table photos \
  --max-rows 5 \
  --max-data-columns 10 \
  --max-value-length 128 \
  --max-data-bytes 10000
```

`map` extracts bounded rows from all discovered tables by default. Use an optional filter to limit it:

```bash
sqliblind map \
  --data-table level5.photos \
  --max-rows 5 \
  --format html \
  --output reports/full-map.html
```

Disable row values and retain schemas, tables, and columns:

```bash
sqliblind map --metadata-only
```

All map data shares the global byte budget. Sensitive-looking values remain masked unless `--show-sensitive-values` is explicitly supplied.

## Concurrency and safety

```bash
sqliblind --workers 16 --delay 0 --max-requests 5000 map
```

- Workers: 1–64 in the CLI and 1–16 in the web console.
- One thread-local HTTP session per worker.
- Shared global delay and request budget.
- Deterministic output ordering.
- Turbo checksum and aggregate confirmation with exact fallback.
- Character positions are scheduled globally instead of serially per entity.
- HTTP concurrency starts at the configured ceiling and backs off only after HTTP 429 or network failures.
- Web events are committed in short transactions; raw request events are sampled while exact counters are retained.
- Cooperative pause, resume, and cancellation.
- Pending futures cancelled after failures.
- TLS validation enabled unless `--insecure` is explicitly supplied.
- Redirects are not followed.

Set a positive `--delay` or reduce `--workers` when the authorized environment requires a lower request rate.

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
  --header "User-Agent:imr-sqliblind/0.8.2" \
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
python -m compileall -q src sqliblind.py tests benchmarks
bash -n install.sh uninstall.sh
node --check src/blind_sqli/webui/app.js
node --check src/blind_sqli/webui/inference-options.js
python benchmarks/inference_benchmark.py \
  --value 'A_9%' \
  --latency 0.01 \
  --workers 64 \
  --require-speedup 0.75
ruff check .
bandit -q -r src
```

Frontend regression checks cover required graph controls, overflow-safe CSS, mobile breakpoints, pointer interactions, persistent graph positions, full graph rendering, non-truncated labels, and valid JavaScript syntax.

Service regression coverage includes bootstrap users, password hashing and changes, roles, account expiration, last-admin protection, persistent configuration, login, CSRF, browser administration, user APIs, authenticated service control, and detached `start` → `status` → `stop` behavior.

All testing must remain minimal and within an explicitly authorized scope. Automated unlimited database dumping is intentionally excluded.
