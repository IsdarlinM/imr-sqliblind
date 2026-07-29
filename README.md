# blind_sqli

A bounded blind SQL injection research helper for authorized laboratories and CTFs.

The original target remains the default URL. When `--url` is omitted, the tool uses:

```text
https://08d9880a384777322d0e2df7db7e5215.ctf.hacker101.com/fetch
```

## Improvements in v0.2.0

- No network traffic occurs when the module is imported.
- Correct `Table` and `Schema` data models.
- Safe URL parameter encoding and replacement.
- TLS verification enabled by default.
- Timeouts, limited retries, global request budget, and global rate limiting.
- Configurable status, marker, regex, or response-length oracle.
- Automatic TRUE/FALSE oracle calibration.
- MySQL and SQLite dialect support.
- Concurrent schema, table, and column-name extraction with `ThreadPoolExecutor`.
- One thread-local HTTP session per worker.
- Deterministic result ordering and cancellation after worker failure.

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

## Usage

Running without a command enumerates schemas using the default URL and `id` parameter:

```bash
python sqli_gallery.py
```

Explicit command:

```bash
blind-sqli schemas
```

Use another authorized target:

```bash
blind-sqli --url "https://lab.example/fetch" --parameter id schemas
```

Enumerate tables and columns:

```bash
blind-sqli --workers 4 tables --schema level5
blind-sqli --workers 4 columns --schema level5 --table photos
```

Extract one scalar expression:

```bash
blind-sqli extract --expression "SELECT DATABASE()"
```

Test a condition:

```bash
blind-sqli probe --condition "1=1"
```

URL template mode:

```bash
blind-sqli \
  --url-template "https://lab.example/fetch?id={{PAYLOAD}}" \
  schemas
```

Status code 200 is the default TRUE condition. Multiple true statuses can be configured:

```bash
blind-sqli --true-status "200,302" schemas
```

## Safe concurrency

`--workers` controls independent extraction jobs. Each schema, table, or column name is an independent job, while each individual character remains sequential because blind inference depends on previous comparisons.

```bash
blind-sqli --workers 8 --delay 0.1 --max-requests 5000 schemas
```

Safety characteristics:

- `1 <= workers <= 16`
- Global request delay shared by every worker
- Global request limit shared by every worker
- One `requests.Session` per thread
- Limited retries only for transport failures
- Redirects are not followed
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
  --header "User-Agent:blind-sqli-lab/0.2.0" \
  --cookie "session=test-value" \
  --proxy "http://127.0.0.1:8080" \
  schemas
```

Use `--insecure` only in a controlled laboratory with a known self-signed certificate.

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

Increase a bound explicitly when the authorized laboratory requires it.

## Tests

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

Metadata enumeration includes schemas, tables, and columns. Arbitrary scalar expressions can be extracted with the `extract` command. Automated bulk row dumping is intentionally not included; keep tests minimal and within the authorized scope.
