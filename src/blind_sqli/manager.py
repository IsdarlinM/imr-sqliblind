from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .client import HttpClient, HttpConfig
from .dialects import get_dialect
from .events import EventEmitter, ScanCancelled, ScanControl, ScanEvent
from .extractor import BlindExtractor, ExtractorConfig
from .graph import render_database_map
from .models import DatabaseMap, Schema, Table
from .oracle import ResponseOracle
from .store import SessionStore


SENSITIVE_HEADERS = {"authorization", "cookie", "proxy-authorization", "x-api-key"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class ScanSettings:
    url: str
    parameter: str = "id"
    url_template: str | None = None
    dialect: str = "mysql"
    oracle: str = "status"
    true_statuses: set[int] = field(default_factory=lambda: {200})
    true_marker: str | None = None
    true_regex: str | None = None
    true_length: int | None = None
    length_tolerance: int = 0
    timeout: float = 10.0
    retries: int = 1
    delay: float = 0.1
    max_requests: int = 5000
    workers: int = 4
    max_length: int = 128
    max_items: int = 128
    min_char_code: int = 32
    max_char_code: int = 126
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    proxy: str | None = None
    insecure: bool = False
    skip_calibration: bool = False
    include_data: bool = False
    data_tables: set[str] = field(default_factory=set)
    max_rows: int = 5
    max_data_columns: int = 10
    max_value_length: int = 128
    max_data_bytes: int = 10_000
    reveal_sensitive_values: bool = False

    def __post_init__(self) -> None:
        if not self.url and not self.url_template:
            raise ValueError("url is required")
        if self.dialect not in {"mysql", "sqlite"}:
            raise ValueError("dialect must be mysql or sqlite")
        if self.oracle not in {"status", "marker", "regex", "length"}:
            raise ValueError("invalid oracle mode")
        if not self.true_statuses or any(
            code < 100 or code > 599 for code in self.true_statuses
        ):
            raise ValueError("true_statuses must contain valid HTTP status codes")
        if not 1 <= self.workers <= 16:
            raise ValueError("workers must be between 1 and 16")
        if not 1 <= self.max_rows <= 25:
            raise ValueError("max_rows must be between 1 and 25")
        if not 1 <= self.max_data_columns <= 20:
            raise ValueError("max_data_columns must be between 1 and 20")
        if not 1 <= self.max_value_length <= 512:
            raise ValueError("max_value_length must be between 1 and 512")
        if not 1 <= self.max_data_bytes <= 50_000:
            raise ValueError("max_data_bytes must be between 1 and 50000")
        if self.include_data and not self.data_tables:
            raise ValueError("data_tables is required when include_data is enabled")
        for selector in self.data_tables:
            if selector.count(".") != 1:
                raise ValueError("data table selectors must use schema.table")

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "ScanSettings":
        data = dict(value)
        statuses = data.get("true_statuses", {200})
        if isinstance(statuses, str):
            statuses = {
                int(item.strip()) for item in statuses.split(",") if item.strip()
            }
        else:
            statuses = {int(item) for item in statuses}
        tables = data.get("data_tables", set())
        if isinstance(tables, str):
            tables = {item.strip() for item in tables.split(",") if item.strip()}
        else:
            tables = {str(item).strip() for item in tables if str(item).strip()}
        data["true_statuses"] = statuses
        data["data_tables"] = tables
        return cls(**data)

    def public_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["true_statuses"] = sorted(self.true_statuses)
        result["data_tables"] = sorted(self.data_tables)
        result["cookies"] = {key: "***" for key in self.cookies}
        result["headers"] = {
            key: ("***" if key.casefold() in SENSITIVE_HEADERS else value)
            for key, value in self.headers.items()
        }
        if result.get("proxy"):
            result["proxy"] = "configured"
        return result


@dataclass(slots=True)
class RuntimeScan:
    control: ScanControl
    thread: threading.Thread


class ScanManager:
    def __init__(
        self,
        store: SessionStore,
        extractor_factory: Callable[
            [ScanSettings, str, Callable[[ScanEvent], None], ScanControl], BlindExtractor
        ]
        | None = None,
    ) -> None:
        self.store = store
        self._factory = extractor_factory or self._default_extractor
        self._runtime: dict[str, RuntimeScan] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _default_extractor(
        settings: ScanSettings,
        scan_id: str,
        callback: Callable[[ScanEvent], None],
        control: ScanControl,
    ) -> BlindExtractor:
        client = HttpClient(
            HttpConfig(
                url=settings.url,
                parameter=settings.parameter,
                url_template=settings.url_template,
                timeout=settings.timeout,
                verify_tls=not settings.insecure,
                retries=settings.retries,
                delay=settings.delay,
                max_requests=settings.max_requests,
                headers=settings.headers,
                cookies=settings.cookies,
                proxy=settings.proxy,
            )
        )
        oracle = ResponseOracle.from_options(
            mode=settings.oracle,
            true_statuses=settings.true_statuses,
            marker=settings.true_marker,
            regex=settings.true_regex,
            expected_length=settings.true_length,
            length_tolerance=settings.length_tolerance,
        )
        return BlindExtractor(
            client,
            oracle,
            get_dialect(settings.dialect),
            ExtractorConfig(
                workers=settings.workers,
                max_length=settings.max_length,
                max_items=settings.max_items,
                min_char_code=settings.min_char_code,
                max_char_code=settings.max_char_code,
            ),
            scan_id=scan_id,
            event_callback=callback,
            control=control,
        )

    def start(self, settings: ScanSettings) -> str:
        scan_id = uuid.uuid4().hex
        created = utc_now()
        self.store.create_scan(scan_id, settings.public_dict(), created)
        control = ScanControl()
        thread = threading.Thread(
            target=self._run,
            args=(scan_id, settings, control),
            name=f"sqliblind-scan-{scan_id[:8]}",
            daemon=True,
        )
        with self._lock:
            self._runtime[scan_id] = RuntimeScan(control=control, thread=thread)
        thread.start()
        return scan_id

    def _record(self, event: ScanEvent) -> None:
        self.store.record_event(event)
        if event.event_type == "request.completed":
            scan = self.store.get_scan(event.scan_id)
            stats = dict(scan["stats"] if scan else {})
            stats["requests"] = event.payload.get("requests_used", 0)
            stats["last_request_seconds"] = event.payload.get("elapsed_seconds", 0)
            self.store.update_scan(
                event.scan_id, stats=stats, timestamp=event.timestamp
            )

    def _run(
        self, scan_id: str, settings: ScanSettings, control: ScanControl
    ) -> None:
        emitter = EventEmitter(scan_id, self._record)
        self.store.update_scan(scan_id, status="running", timestamp=utc_now())
        emitter.emit("scan.started", config=settings.public_dict())
        try:
            extractor = self._factory(settings, scan_id, self._record, control)
            if not settings.skip_calibration:
                extractor.calibrate()
            database = extractor.build_database_map(
                include_columns=True,
                include_data=settings.include_data,
                data_tables=settings.data_tables,
                max_rows=settings.max_rows,
                max_data_columns=settings.max_data_columns,
                max_value_length=settings.max_value_length,
                max_data_bytes=settings.max_data_bytes,
                reveal_sensitive_values=settings.reveal_sensitive_values,
            )
            summary = database.to_dict()["summary"]
            stats = {
                **summary,
                "requests": extractor.client.requests_used,
                "elapsed_seconds": round(extractor.elapsed_seconds, 3),
            }
            emitter.emit("scan.completed", summary=stats)
            self.store.update_scan(
                scan_id, status="completed", stats=stats, timestamp=utc_now()
            )
        except ScanCancelled:
            emitter.emit("scan.cancelled")
            self.store.update_scan(scan_id, status="cancelled", timestamp=utc_now())
        except Exception as exc:
            emitter.emit("scan.failed", error=str(exc))
            self.store.update_scan(
                scan_id,
                status="failed",
                error=str(exc),
                timestamp=utc_now(),
            )
        finally:
            with self._lock:
                self._runtime.pop(scan_id, None)

    def _runtime_scan(self, scan_id: str) -> RuntimeScan:
        with self._lock:
            runtime = self._runtime.get(scan_id)
        if runtime is None:
            raise KeyError(scan_id)
        return runtime

    def pause(self, scan_id: str) -> None:
        runtime = self._runtime_scan(scan_id)
        runtime.control.pause()
        event = EventEmitter(scan_id, self._record).emit("scan.paused")
        self.store.update_scan(scan_id, status="paused", timestamp=event.timestamp)

    def resume(self, scan_id: str) -> None:
        runtime = self._runtime_scan(scan_id)
        runtime.control.resume()
        event = EventEmitter(scan_id, self._record).emit("scan.resumed")
        self.store.update_scan(scan_id, status="running", timestamp=event.timestamp)

    def stop(self, scan_id: str) -> None:
        runtime = self._runtime_scan(scan_id)
        runtime.control.stop()
        event = EventEmitter(scan_id, self._record).emit("scan.stopping")
        self.store.update_scan(scan_id, status="stopping", timestamp=event.timestamp)

    def export(self, scan_id: str, output_format: str) -> tuple[str, str]:
        snapshot = self.store.snapshot(scan_id)
        if snapshot is None:
            raise KeyError(scan_id)
        selected = output_format.casefold()
        if selected == "json":
            return (
                json.dumps(snapshot, ensure_ascii=False, indent=2),
                "application/json",
            )
        database = self._database_from_snapshot(snapshot)
        if selected in {"tree", "relations", "mermaid", "html"}:
            content = render_database_map(
                database,
                output_format=selected,
                title=f"imr-sqliblind scan {scan_id[:8]}",
            )
            media = "text/html" if selected == "html" else "text/plain"
            return content, media
        raise ValueError("format must be json, tree, relations, mermaid, or html")

    @staticmethod
    def _database_from_snapshot(snapshot: dict[str, Any]) -> DatabaseMap:
        database = DatabaseMap()
        schemas: dict[str, Schema] = {}
        tables: dict[str, Table] = {}
        row_values: dict[str, dict[str, str]] = {}
        for entity in snapshot["entities"]:
            kind = entity["type"]
            data = entity["data"]
            if kind == "schema":
                schema = Schema(entity["name"])
                database.add_schema(schema)
                schemas[entity["id"]] = schema
            elif kind == "table":
                parent = schemas.get(entity["parent_id"])
                if parent is not None:
                    table = parent.add_table(Table(entity["name"]))
                    tables[entity["id"]] = table
            elif kind == "column":
                parent = tables.get(entity["parent_id"])
                if parent is not None:
                    parent.add_column(entity["name"])
            elif kind == "row":
                row_values[entity["id"]] = {
                    str(key): str(value)
                    for key, value in data.get("values", {}).items()
                }
        for entity in snapshot["entities"]:
            if entity["type"] != "row":
                continue
            parent = tables.get(entity["parent_id"])
            values = row_values.get(entity["id"], {})
            if parent is not None and values:
                parent.rows.append(values)
        return database

    def shutdown(self, timeout: float = 5.0) -> None:
        with self._lock:
            runtimes = list(self._runtime.values())
        for runtime in runtimes:
            runtime.control.stop()
        for runtime in runtimes:
            if runtime.thread is not threading.current_thread():
                runtime.thread.join(timeout=timeout)

    def workspace_path(self) -> Path:
        return self.store.path
