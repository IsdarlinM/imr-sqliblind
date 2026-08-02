# Browser end-to-end tests

The browser suite validates the actual authenticated Web console with a temporary local FastAPI/Uvicorn server and a seeded SQLite session. It never sends extraction probes to an external target.

## Installation

```bash
python -m pip install -e ".[dev,web,browser]"
python -m playwright install chromium
```

For a Linux CI runner that needs browser system packages:

```bash
python -m playwright install --with-deps chromium
```

## Run

```bash
pytest -m browser --browser chromium -q
```

The suite covers:

- authenticated session selection
- collapsible Tree behavior
- lazy table construction
- SSE-driven entity updates
- elastic graph dragging
- graph minimap visibility
- responsive mobile overflow
- safe local seeded data only

Use Playwright tracing when debugging:

```bash
pytest -m browser --browser chromium --tracing=retain-on-failure
```

Browser tests are optional and separated from unit tests because browser downloads and OS dependencies are significantly larger than the core package.
