# imr-sqliblind

`imr-sqliblind` is a bounded blind SQL injection research helper for authorized laboratories, CTFs, and explicitly permitted security assessments.

The installed command is:

```text
sqliblind
```

The original target remains the default URL. When `--url` is omitted, the tool uses:

```text
https://08d9880a384777322d0e2df7db7e5215.ctf.hacker101.com/fetch
```

## Requirements

- Python **3.10 or newer**.
- Internet access during installation to obtain Python or Python packages when they are not already available.
- Linux: `bash` plus `curl` or `wget` only when Python must be bootstrapped automatically.
- Windows: Windows 10/11 with `cmd.exe` and Windows PowerShell, used internally only for user environment variables and the official `uv` bootstrapper.

If a compatible Python is not installed, the native installers bootstrap `uv` and install a managed Python 3.12 runtime. Existing Python 3.10+ installations are reused.

## Features

- No network traffic during module import.
- Safe query-parameter encoding and URL-template replacement.
- TLS verification enabled by default.
- Timeouts, bounded retries, global request budget, and global rate limiting.
- Status, body-marker, regex, and response-length oracles.
- Automatic TRUE/FALSE oracle calibration.
- MySQL and SQLite dialects.
- Binary-search inference for integers, lengths, and characters.
- Bounded multithreading with deterministic output ordering.
- Schema, table, and column enumeration.
- Complete schema → table → column maps.
- CLI tree, relation list, Mermaid, JSON, and self-contained HTML reports.
- Atomic report writes and escaped HTML identifiers.
- Native per-user installers and uninstallers for Linux and Windows.

## Native installation

The installers run without administrator privileges and create an isolated virtual environment for the current user. They install all Python dependencies, create the global `sqliblind` wrapper, persist environment variables, update `PATH`, and verify the command before finishing.

### Linux

```bash
chmod +x install.sh uninstall.sh
./install.sh
```

Default locations:

```text
Application: ~/.local/share/imr-sqliblind
Command:     ~/.local/bin/sqliblind
```

Open a new shell after installation, or load the updated profile immediately:

```bash
source ~/.profile
sqliblind --version
```

### Windows CMD

Run from Command Prompt:

```cmd
install.cmd
```

Default locations:

```text
Application: %LOCALAPPDATA%\Programs\imr-sqliblind
Command:     %LOCALAPPDATA%\Programs\imr-sqliblind\bin\sqliblind.cmd
```

Open a new CMD window after installation:

```cmd
sqliblind --version
sqliblind --help
```

### Installer options

Linux:

```bash
./install.sh --help
./install.sh --prefix "$HOME/tools/imr-sqliblind"
./install.sh --python /usr/bin/python3.10
./install.sh --no-path
```

Windows CMD:

```cmd
install.cmd --help
install.cmd --prefix "%USERPROFILE%\Tools\imr-sqliblind"
install.cmd --python "C:\Python310\python.exe"
install.cmd --no-path
```

`--no-path` is intended for CI or portable installations. It creates the environment and wrapper but does not persist user environment variables or modify `PATH`.

### Environment variables

A normal native installation persists:

```text
IMR_SQLIBLIND_HOME   Installation directory
SQLIBLIND_PYTHON     Isolated Python executable
SQLIBLIND_BIN        Directory containing the sqliblind wrapper
PATH                 Includes SQLIBLIND_BIN
```

Linux updates `~/.profile` and existing `~/.bashrc` / `~/.zshrc` files using a replaceable marked block. Windows updates only the current user's environment, not the machine-wide environment.

### Updating

Pull the latest repository changes and rerun the installer. Existing user reports and unrelated files outside the installation directory are not modified.

Linux:

```bash
git pull
./install.sh
```

Windows CMD:

```cmd
git pull
install.cmd
```

### Uninstalling

Linux:

```bash
./uninstall.sh
```

Windows CMD:

```cmd
uninstall.cmd
```

For a custom installation prefix, pass the same `--prefix` value used during installation.

## Manual installation

Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
```

Windows CMD:

```cmd
py -3 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
```

Confirm the installation:

```bash
sqliblind --version
sqliblind --help
```

## Basic usage

Running without a command enumerates schemas using the default URL and `id` parameter:

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

The legacy entry point remains available for compatibility:

```bash
python sqli_gallery.py
```

## Schema maps and graphs

`map`, `graph`, and `schema-map` are aliases.

### CLI tree

```bash
sqliblind --workers 6 map
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
sqliblind map --ascii
```

### TXT reports

```bash
sqliblind map --format tree --output reports/schema-map.txt
sqliblind map --format relations --output reports/relations.txt
```

When the path has no extension, `.txt` is added automatically.

### Mermaid

```bash
sqliblind map --format mermaid --output reports/schema-map.mmd
```

### Interactive HTML

```bash
sqliblind map --format html --output reports/schema-map.html
```

Without `--output`, the generated file is:

```text
imr-sqliblind-schema-map.html
```

The HTML report is self-contained and includes counters, expandable nodes, filtering, expand/collapse controls, responsive layout, escaped identifiers, and a restrictive Content Security Policy. It does not load external scripts, fonts, styles, images, or CDNs.

Custom title:

```bash
sqliblind map --format html --title "Authorized lab schema map"
```

### JSON

```bash
sqliblind --json map
sqliblind --json map --output reports/schema-map.json
```

### Faster partial map

Stop after schemas and tables:

```bash
sqliblind map --no-columns
```

## Safe concurrency

`--workers` controls independent extraction jobs. Character inference remains sequential, while independent names and metadata counts are processed concurrently.

```bash
sqliblind --workers 8 --delay 0.1 --max-requests 5000 map
```

Safety characteristics:

- `1 <= workers <= 16`.
- One active thread pool per extraction phase.
- Shared global request delay and request limit.
- One `requests.Session` per worker thread.
- Deterministic result ordering.
- Pending-work cancellation after worker failure.
- Redirects are not followed.
- TLS verification is enabled unless `--insecure` is explicitly passed.

## Oracle modes

Status code, default:

```bash
sqliblind --oracle status --true-status 200 schemas
```

Body marker:

```bash
sqliblind --oracle marker --true-marker "RESULT=TRUE" schemas
```

Regular expression:

```bash
sqliblind --oracle regex --true-regex "Welcome\s+back" schemas
```

Response length:

```bash
sqliblind --oracle length --true-length 3246 --length-tolerance 3 schemas
```

## Headers, cookies, proxy, and TLS

```bash
sqliblind \
  --header "User-Agent:imr-sqliblind/0.4.0" \
  --cookie "session=test-value" \
  --proxy "http://127.0.0.1:8080" \
  schemas
```

Use `--insecure` only in a controlled laboratory with a known self-signed certificate.

## URL template mode

```bash
sqliblind \
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

## Help

```bash
sqliblind --help
sqliblind schemas --help
sqliblind tables --help
sqliblind columns --help
sqliblind extract --help
sqliblind probe --help
sqliblind map --help
```

## Tests

```bash
python -m unittest discover -s tests -v
pytest -q
bash -n install.sh uninstall.sh
```

Optional quality checks:

```bash
python -m pip install -e ".[dev]"
ruff check .
mypy src/blind_sqli
bandit -r src
```

GitHub Actions tests Python 3.10, 3.11, 3.12, and 3.13. Dedicated Linux and Windows jobs perform native-installer smoke tests with temporary prefixes.

## Scope

Metadata enumeration includes schemas, tables, and columns. Arbitrary scalar expressions can be extracted with `extract`. Automated bulk row dumping is intentionally excluded. Keep all testing minimal and within the authorized scope.
