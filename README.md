# imr-sqliblind

```text
imr-sqliblind
imr :: v0.8.0
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
- Adaptive, binary, and globally scheduled bitwise character inference.
- Character-position scheduling across all workers, including a single entity.
- AIMD concurrency control, shared request budget, global delay, and bounded extraction.
- Pipelined schema → table → column discovery.
- Schemas, tables, columns, bounded rows, and cells.
- CLI activity monitor without misleading percentages.
- Realtime FastAPI/Uvicorn web console using SSE.
- Detached user-level service controlled with `start`, `stop`, `restart`, and `status`.
- Persistent service configuration with an unusual local default port (`43127`).
- SQLite-backed users, roles, temporary-account expiration, session revocation, and audit events.
- Mandatory replacement of the bootstrap `admin:admin` password.
- Responsive web layout and interactive circular relationship graph.
- SQLite scan history, pause, resume, stop, filters, exports, and saved defaults.
- Unicode/ASCII trees, relations, tables, Mermaid, JSON, and HTML reports.
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

## Quick start: authenticated background service

Start the web console as a detached user-level service:

```bash
sqliblind start
sqliblind status
```

Open:

```text
http://127.0.0.1:43127/
```

On the first start, the empty user database receives this bootstrap account:

```text
Username: admin
Password: admin
```

The account is marked for a mandatory password change. The console and API remain unavailable to that account until the password has been replaced.

Control the process:

```bash
sqliblind stop
sqliblind restart
sqliblind status
```

Override the saved host or port for one launch:

```bash
sqliblind start --port 43128
sqliblind restart --host 127.0.0.1 --port 43129
```

Run in the foreground for diagnostics:

```bash
sqliblind start --foreground
```

The service is user-level and does not require root or Administrator privileges. It starts a detached Python/Uvicorn process, records user-owned state, and uses a random control token for authenticated graceful shutdown instead of terminating an unverified PID.

## User management

Three roles are available:

- `admin`: manage users and defaults, inspect audit events, and operate scans.
- `operator`: create, pause, resume, and stop scans; read sessions and exports.
- `viewer`: read the console, graph, tables, events, sessions, and exports.

Create users:

```bash
sqliblind users create analyst --role operator
sqliblind users create auditor --role viewer
sqliblind users create backup-admin --role admin
```

Create temporary accounts:

```bash
sqliblind users create contractor --role operator --expires-in 12h
sqliblind users create reviewer --role viewer --expires-in 7d
```

Supported relative durations are minutes, hours, days, and weeks: `30m`, `12h`, `7d`, and `2w`.

Manage existing accounts:

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

Passwords are prompted without echo. For controlled automation, `--password-stdin` accepts one password line; there is intentionally no `--password` argument that could expose a secret in shell history or process listings.

```bash
printf '%s\n' 'Strong-Temporary-Password9' | \
  sqliblind users create ci-operator \
  --role operator \
  --expires-in 2h \
  --password-stdin
```

Password, role, activation, and expiration changes revoke existing sessions. The store prevents deletion, disabling, demotion, or temporary expiration of the last usable administrator.

See [Authenticated background service and user management](docs/service-and-users.md) for the complete command, storage, remote-access, and security reference.

## Service configuration

Create or display the default JSON configuration:

```bash
sqliblind config init
sqliblind config show
```

Persistent defaults can be changed without editing JSON manually:

```bash
sqliblind config set --port 43128
sqliblind config set --session-hours 8
sqliblind config set --workspace /srv/sqliblind/workspaces
sqliblind config set --log-file /var/log/sqliblind/service.log
```

Default configuration paths:

```text
Windows: %LOCALAPPDATA%\Programs\imr-sqliblind\config\service.json
POSIX:   ~/.local/share/imr-sqliblind/config/service.json
```

The file stores the bind host, port, remote-access policy, TLS files, session lifetime, workspace, authentication database, log file, and state file. Writes use an atomic replace; POSIX files receive user-only permissions where supported.

Use another configuration file:

```bash
sqliblind start --config ./service.json
sqliblind users --config ./service.json list
sqliblind config --config ./service.json show
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

The updater validates the official origin, refuses dirty worktrees, updates `main` using fast-forward only, and never modifies global Git configuration. Updates and reinstalls preserve the application data root, including service configuration, users, audit events, workspaces, and logs.

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
sqliblind --json map
```

## Optimized exact inference

The default `adaptive` mode partitions the configured numeric character-code range using identifier-oriented probabilities learned during the current scan. It does not use wordlists and it preserves uppercase, lowercase, digits, punctuation, `%`, and `_`.

Character conditions use numeric comparisons only:

```sql
(code_expression) > 80
(code_expression) = 95
(code_expression) IN (37,48,65,95,97)
```

`%` is inferred as code `37` and `_` as code `95`; neither is inserted into a `LIKE` pattern during character discovery.

Available modes:

```bash
sqliblind --inference-mode adaptive --workers 8 map
sqliblind --inference-mode bitwise --workers 8 map
sqliblind --inference-mode binary --workers 8 map
```

Use `--serial-characters` only for diagnostics. `--fixed-concurrency` disables AIMD backoff when fixed request concurrency is required.

Run the deterministic simulator:

```bash
python benchmarks/inference_benchmark.py --latency 0.003 --workers 8
```

Benchmark figures are laboratory measurements, not guarantees for remote targets.

## Direct web-console mode

The original foreground token-authenticated web command remains available:

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

Remote direct mode requires an explicit opt-in and token:

```bash
sqliblind web \
  --host 0.0.0.0 \
  --allow-remote \
  --token "a-long-random-token"
```

Optional HTTPS requires both certificate files:

```bash
sqliblind web \
  --host 0.0.0.0 \
  --allow-remote \
  --token "a-long-random-token" \
  --ssl-certfile server.crt \
  --ssl-keyfile server.key
```

Remote HTTP is unencrypted. Prefer the authenticated service with TLS for persistent remote use.

## Remote service access

The service binds to `127.0.0.1` by default. Remote binding requires an explicit persistent opt-in:

```bash
sqliblind config set --host 0.0.0.0 --allow-remote
```

Remote HTTP exposes credentials, cookies, metadata, and scan results to the network path. Prefer TLS:

```bash
sqliblind config set \
  --host 0.0.0.0 \
  --allow-remote \
  --ssl-certfile /path/server.crt \
  --ssl-keyfile /path/server.key
sqliblind restart
```

Certificate and key must both exist. Authentication cookies are marked `Secure` when TLS is enabled.

## Realtime frontend

The responsive console includes:

- A hamburger menu for sessions, saved defaults, and temporary custom scans.
- Live worker activity and SSE updates.
- Compact circular graph nodes with dragging, pan, zoom, fit, reset, and relationship highlighting.
- Native table views and bounded text/HTML table exports.
- Filters, raw events, session history, and a right-side detail drawer.
- Mobile layouts with safe wrapping and full-screen detail panels.

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
  --format html-tables \
  --output reports/full-map.html
```

## Authentication and service security

- Passwords use PBKDF2-HMAC-SHA-256 with unique random salts and 310,000 iterations.
- Password verification uses constant-time digest comparison.
- Browser sessions use random 256-bit tokens; only token hashes are stored.
- User and session expiration are verified on every request.
- Mutating browser requests require CSRF validation.
- Login errors do not reveal whether a username exists and repeated failures are rate-limited.
- The internal legacy token is generated at runtime and is not accepted from external clients.
- User and account-management actions are written to an audit table without passwords or session tokens.
- Remote binding is rejected unless `allow_remote` is explicitly enabled.
- Service stop performs an authenticated graceful shutdown.

## Concurrency and target safety

```bash
sqliblind --workers 64 --delay 0.1 --max-requests 5000 map
```

- Workers: 1–64 in the CLI.
- One thread-local HTTP session per worker.
- Shared global delay and request budget.
- Deterministic output ordering.
- Cooperative pause, resume, and cancellation.
- TLS validation enabled unless `--insecure` is explicitly supplied.
- Redirects are not followed.
- Automated unlimited database dumping is intentionally excluded.

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
  --header "User-Agent:imr-sqliblind/0.8.0" \
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
python benchmarks/inference_benchmark.py --latency 0.003 --workers 8
ruff check .
bandit -q -r src
```

Service regression coverage includes user bootstrap, password hashing and changes, role enforcement, expiration, last-admin protection, persistent configuration, entrypoint routing, login, CSRF, account APIs, authenticated service control, and detached start/status/stop behavior.

All testing and target interaction must remain minimal and within an explicitly authorized scope.
