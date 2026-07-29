# blind_sqli

A bounded blind SQL injection research helper for authorized laboratories and CTFs.

The original target remains the default URL. When `--url` is omitted, the tool uses:

```text
https://08d9880a384777322d0e2df7db7e5215.ctf.hacker101.com/fetch
```

## Improvements in v0.3.0

- No network traffic occurs when modules are imported.
- Safe URL parameter encoding and replacement.
- TLS verification enabled by default.
- Timeouts, limited retries, global request budget, and global rate limiting.
- Configurable status, marker, regex, or response-length oracle.
- Automatic TRUE/FALSE oracle calibration.
- MySQL and SQLite dialect support.
- Concurrent schema, table, and column extraction with `ThreadPoolExecutor`.
- Complete database map: schema → table → column.
- CLI tree and relation representations.
- Mermaid graph export.
- Self-contained interactive HTML schema graph.
- Atomic TXT, JSON, Mermaid, and HTML report writes.
- HTML escaping and a restrictive Content Security Policy.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Windows CMD:

```cmd
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -e .
```

## Basic usage

Running without a command enumerates schemas using the default URL and `id` parameter:

```bash
python sqli_gallery.py
```

Explicit commands:

```bash
blind-sqli schemas
blind-sqli tables --schema level5
blind-sqli columns --schema level5 --table photos
blind-sqli extract --expression "SELECT DATABASE()"
blind-sqli probe --condition "1=1"
```

Use another authorized target:

```bash
blind-sqli --url "https://lab.example/fetch" --parameter id schemas
```

## Schema maps and graphs

`map`, `graph`, and `schema-map` are aliases. They enumerate the hierarchy and then render it.

### CLI tree

```bash
blind-sqli --workers 6 map
```

Example:

```text
DATABASE STRUCTURE
└── [SCHEMA] level5
    └── [TABLE] photos
        ├── [COLUMN] id
        └── [COLUMN] filename

SUMMARY
Schemas: 1
Tables: 1
Columns: 2
Relationships: 3
```

ASCII-only terminals:

```bash
blind-sqli map --ascii
```

### Text export

```bash
blind-sqli map --format tree --output reports/schema-map.txt
blind-sqli map --format relations --output reports/relations.txt
```

When the path has no extension, `.txt` is added automatically.

### Mermaid graph

```bash
blind-sqli map --format mermaid --output reports/schema-map.mmd
```

The generated file can be pasted into a Mermaid-compatible Markdown renderer.

### Interactive HTML graph

```bash
blind-sqli map --format html --output reports/schema-map.html
```

When `--output` is omitted for HTML, the default file is:

```text
blind-sqli-schema-map.html
```

The HTML report is self-contained and includes:

- schema, table, column, and relationship counters;
- collapsible schema and table nodes;
- client-side filtering;
- expand/collapse controls;
- responsive desktop/mobile layout;
- no remote scripts, fonts, styles, or images;
- escaped discovered identifiers and a restrictive CSP.

Custom title:

```bash
blind-sqli map --format html --title "Authorized lab schema map"
```

### Faster partial map

Stop after schemas and tables to reduce requests:

```bash
blind-sqli map --no-columns
```

### JSON map

```bash
blind-sqli --json map
blind-sqli --json map --output reports/schema-map.json
```

## Safe concurrency

`--workers` controls independent extraction jobs. Each character remains sequential because blind inference depends on previous comparisons, but independent names and metadata counts are processed concurrently.

```bash
blind-sqli --workers 8 --delay 0.1 --max-requests 5000 map
```

Safety characteristics:

- `1 <= workers <= 16`
- one active thread pool per extraction phase, avoiding nested executors
- global request delay shared by every worker
- global request limit shared by every worker
- one `requests.Session` per thread
- deterministic result ordering
- pending work cancellation after a worker failure
- redirects are not followed
- TLS validation is enabled unless `--insecure` is explicitly passed

## Oracle modes

Status code, default:

```bash
blind-sqli --oracle status --true-status 200 schemas
```

Body marker:

```bash
blind-sqli --oracle marker --true-marker "RESULT=TRUE" schemas
```

Regular expression:

```bash
blind-sqli --oracle regex --true-regex "Welcome\s+back" schemas
```

Response length:

```bash
blind-sqli --oracle length --true-length 3246 --length-tolerance 3 schemas
```

## Headers, cookies, proxy, and TLS

```bash
blind-sqli \
  --header "User-Agent:blind-sqli-lab/0.3.0" \
  --cookie "session=test-value" \
  --proxy "http://127.0.0.1:8080" \
  schemas
```

Use `--insecure` only in a controlled laboratory with a known self-signed certificate.

## URL template mode

```bash
blind-sqli \
  --url-template "https://lab.example/fetch?id={{PAYLOAD}}" \
  schemas
```

`[TO_REPLACE]` is also supported.

## Default limits

```text
--workers 4
--delay 0.1
--max-requests 5000
--max-items 128
--max-length 128
--min-char-code 32
--max-char-code 126
```

Increase a bound explicitly only when the authorized laboratory requires it.

## Help

```bash
blind-sqli --help
blind-sqli schemas --help
blind-sqli tables --help
blind-sqli columns --help
blind-sqli extract --help
blind-sqli probe --help
blind-sqli map --help
```

## Tests

The suite covers commands, aliases, all CLI arguments, URL handling, HTTP controls, each oracle, both SQL dialects, binary inference, bounded threading, data models, all graph formats, report writing, HTML escaping, and import safety.

```bash
python -m unittest discover -s tests -v
```

Optional quality checks:

```bash
python -m pip install -e ".[dev]"
ruff check .
mypy src/blind_sqli
bandit -r src
pytest
```

## Scope

Metadata enumeration includes schemas, tables, and columns. Arbitrary scalar expressions can be extracted with `extract`. Automated bulk row dumping is intentionally not included; keep tests minimal and within the authorized scope.
