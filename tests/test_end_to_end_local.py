from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from blind_sqli.cli import main as cli_main
from blind_sqli.manager import ScanManager
from blind_sqli.store import SessionStore
from blind_sqli.web_app import create_app


EXPECTED = {
    "main": {
        "User_Profile%": ["User_ID", "ratio%"],
        "audit_log": ["event_id", "_marker"],
    }
}


class _OracleHandler(BaseHTTPRequestHandler):
    database_path: Path

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        payload = query.get("id", [""])[0]
        matched = False
        if payload and ";" not in payload:
            connection = sqlite3.connect(str(self.database_path))
            try:
                row = connection.execute(
                    f"SELECT CASE WHEN ({payload}) THEN 1 ELSE 0 END"
                ).fetchone()
                matched = bool(row and row[0])
            except sqlite3.Error:
                matched = False
            finally:
                connection.close()
        body = b"TRUE" if matched else b"FALSE"
        self.send_response(200 if matched else 404)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


class LocalBlindSqlLab:
    def __init__(self, directory: Path) -> None:
        self.database_path = directory / "target.db"
        connection = sqlite3.connect(str(self.database_path))
        try:
            connection.executescript(
                '''
                CREATE TABLE "User_Profile%" (
                    "User_ID" INTEGER,
                    "ratio%" TEXT
                );
                CREATE TABLE "audit_log" (
                    "event_id" INTEGER,
                    "_marker" TEXT
                );
                '''
            )
            connection.commit()
        finally:
            connection.close()

        handler = type(
            "OracleHandler",
            (_OracleHandler,),
            {"database_path": self.database_path},
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            name="sqliblind-local-lab",
            daemon=True,
        )
        self.thread.start()

    @property
    def url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}/fetch"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def normalize_map(document: dict[str, object]) -> dict[str, dict[str, list[str]]]:
    normalized: dict[str, dict[str, list[str]]] = {}
    for schema in document["schemas"]:  # type: ignore[index,union-attr]
        schema_name = schema["name"]
        normalized[schema_name] = {
            table["name"]: table["columns"]
            for table in schema["tables"]
        }
    return normalized


class LocalEndToEndTests(unittest.TestCase):
    def test_cli_and_web_complete_exact_maps_over_http(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            lab = LocalBlindSqlLab(directory)
            try:
                output = io.StringIO()
                with redirect_stdout(output):
                    code = cli_main(
                        [
                            "--url",
                            lab.url,
                            "--dialect",
                            "sqlite",
                            "--oracle",
                            "status",
                            "--true-status",
                            "200",
                            "--delay",
                            "0",
                            "--retries",
                            "0",
                            "--workers",
                            "8",
                            "--max-length",
                            "64",
                            "--max-items",
                            "10",
                            "--inference-mode",
                            "adaptive",
                            "--json",
                            "--progress",
                            "off",
                            "map",
                        ]
                    )
                self.assertEqual(code, 0, output.getvalue())
                cli_document = json.loads(output.getvalue())
                self.assertEqual(normalize_map(cli_document["result"]), EXPECTED)
                self.assertLess(cli_document["requests"], 500)
                self.assertEqual(
                    cli_document["performance"]["inference_mode"],
                    "adaptive",
                )

                store = SessionStore(directory / "sessions.db")
                manager = ScanManager(store)
                app = create_app(
                    manager,
                    auth_token="secret",
                    csrf_token="csrf",
                )
                client = TestClient(app)
                login = client.get("/?token=secret", follow_redirects=True)
                self.assertEqual(login.status_code, 200)
                response = client.post(
                    "/api/scans",
                    headers={"X-SQLIBLIND-CSRF": "csrf"},
                    json={
                        "url": lab.url,
                        "dialect": "sqlite",
                        "oracle": "status",
                        "true_statuses": "200",
                        "delay": 0,
                        "retries": 0,
                        "workers": 8,
                        "max_length": 64,
                        "max_items": 10,
                        "max_requests": 1000,
                        "inference_mode": "bitwise",
                        "parallel_characters": True,
                        "adaptive_confirmation": True,
                        "adaptive_concurrency": True,
                        "request_event_sample": 20,
                    },
                )
                self.assertEqual(response.status_code, 200, response.text)
                scan_id = response.json()["id"]

                status = "queued"
                for _ in range(400):
                    scan = store.get_scan(scan_id)
                    status = scan["status"] if scan else "missing"
                    if status in {"completed", "failed", "cancelled"}:
                        break
                    time.sleep(0.025)
                self.assertEqual(status, "completed", store.get_scan(scan_id))

                snapshot = store.snapshot(scan_id)
                self.assertIsNotNone(snapshot)
                database, _ = manager.export(scan_id, "json")
                exported = json.loads(database)
                entities = exported["entities"]
                names = {(item["type"], item["name"]) for item in entities}
                for schema, tables in EXPECTED.items():
                    self.assertIn(("schema", schema), names)
                    for table, columns in tables.items():
                        self.assertIn(("table", table), names)
                        for column in columns:
                            self.assertIn(("column", column), names)
                stats = snapshot["scan"]["stats"]
                self.assertLess(stats["requests"], 600)
                self.assertEqual(
                    stats["performance"]["inference_mode"],
                    "bitwise",
                )
                manager.shutdown()
                store.close()
            finally:
                lab.close()


if __name__ == "__main__":
    unittest.main()
