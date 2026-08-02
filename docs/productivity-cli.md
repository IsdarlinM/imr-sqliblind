# CLI productivity and automation

The productivity commands do not change the extraction or oracle algorithms. They improve repeatability, diagnostics, session inspection and terminal interaction.

## Doctor

```bash
sqliblind doctor
sqliblind doctor --json
sqliblind doctor --workspace ./workspace
```

Checks Python, SQLite, TLS trust paths, required `requests`, optional Web dependencies, PATH registration, configuration storage and workspace write access.

Exit codes:

- `0`: command completed successfully
- `1`: runtime or diagnostic failure
- `2`: invalid arguments or unsafe profile/resume configuration
- `130`: interrupted by the user

## Non-secret profiles

Save reusable argument templates:

```bash
sqliblind profiles save metadata-fast -- \
  --workers 32 \
  --delay 0 \
  map \
  --metadata-only
```

Use a profile and override global values:

```bash
sqliblind --profile metadata-fast \
  --url https://authorized-lab.example/fetch
```

Profiles deliberately reject cookies, proxy URLs and sensitive headers such as `Authorization`, `Cookie`, `Proxy-Authorization` and `X-API-Key`. Supply those values for the current execution instead of persisting them.

```bash
sqliblind profiles list
sqliblind profiles show metadata-fast
sqliblind profiles delete metadata-fast
```

## Safe configuration preview

Parse a command without making requests:

```bash
sqliblind preview -- \
  --url https://authorized-lab.example/fetch \
  --works 16 \
  map \
  --metadata-only
```
Cookies, proxy URLs and sensitive headers are masked in the output.

## Persisted sessions

The Web console stores sessions in `sessions.db` inside its workspace.

```bash
sqliblind sessions --workspace ./workspace list
sqliblind sessions --workspace ./workspace show SCAN_ID
sqliblind sessions --workspace ./workspace diff OLD_SCAN NEW_SCAN
```

Stream events as JSON Lines:

```bash
sqliblind sessions --workspace ./workspace \
  events SCAN_ID --follow --jsonl
```

This is the recommended real-time machine interface. Every line is an independent JSON object and can be consumed by `jq`, log shippers or automation.

## Verified retry and phase repetition

```bash
sqliblind resume SCAN_ID \
  --workspace ./workspace \
  --dry-run
```

The command reconstructs a new invocation from the stored non-secret configuration. It does not splice unverified partial values from an interrupted extraction.

Repeat a narrower phase:

```bash
sqliblind resume SCAN_ID --workspace ./workspace --phase schemas
sqliblind resume SCAN_ID --workspace ./workspace \
  --phase tables --schema main
sqliblind resume SCAN_ID --workspace ./workspace \
  --phase columns --schema main --table users
sqliblind resume SCAN_ID --workspace ./workspace \
  --phase rows --schema main --table users
```

Stored cookies, sensitive headers and proxy credentials are redacted. The retry reports each missing secret and accepts new `--header`, `--cookie` and `--proxy` values.

## Terminal workspace

Monitor the newest persisted scan:

```bash
sqliblind tui --workspace ./workspace
```

Monitor one session or print one frame:

```bash
sqliblind tui --workspace ./workspace --scan-id SCAN_ID
sqliblind tui --workspace ./workspace --scan-id SCAN_ID --once
```

The dependency-free terminal view shows entity counts, requests, active workers and recent events. It works without replacing the existing plain progress and JSON modes.

## JSON Lines for one-shot commands

```bash
sqliblind --jsonl \
  --url https://authorized-lab.example/fetch \
  schemas

```
List results are emitted one per line followed by a summary record. Do not combine `--jsonl` with `--output`; use session event streaming for long-running integrations.

## Shell completion

```bash
sqliblind completion bash
sqliblind completion zsh
sqliblind completion powershell
```

Evaluate or install the generated script according to the shell's normal completion configuration.
