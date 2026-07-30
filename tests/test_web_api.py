from __future__ import annotations

import re
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from blind_sqli.events import EventEmitter, entity_id
from blind_sqli.manager import ScanManager
from blind_sqli.models import DatabaseMap, Schema
from blind_sqli.store import SessionStore
from blind_sqli.web import create_app


class ImmediateExtractor:
    def __init__(self, scan_id, callback, control):
        del control
        self.events = EventEmitter(scan_id, callback)
        self.client = SimpleNamespace(requests_used=2)
        self.elapsed_seconds = 0.01

    def calibrate(self):
        self.events.emit("scan.calibrated")

    def build_database_map(self, **kwargs):
        del kwargs
        self.events.emit(
            "activity.started",
            activity={
                "id": "activity-1",
                "operation": "Enumerate schemas",
                "target": "database",
                "detail": "reading schema names",
                "status": "running",
                "worker": "sqliblind_0",
            },
        )
        self.events.emit(
            "schema.discovered",
            entity={
                "id": entity_id("schema", "main"),
                "type": "schema",
                "name": "main",
                "parent_id": None,
                "status": "complete",
                "data": {},
            },
        )
        self.events.emit(
            "activity.completed",
            activity={
                "id": "activity-1",
                "operation": "Enumerate schemas",
                "target": "database",
                "detail": "1 schema found",
                "status": "completed",
                "worker": "sqliblind_0",
                "elapsed_seconds": 0.01,
            },
        )
        return DatabaseMap([Schema("main")])


class WebApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = SessionStore(Path(self.temp.name) / "sessions.db")
        self.manager = ScanManager(
            self.store,
            lambda settings, scan_id, callback, control: ImmediateExtractor(
                scan_id, callback, control
            ),
        )
        self.client = TestClient(
            create_app(
                self.manager,
                auth_token="auth-secret",
                csrf_token="csrf-secret",
            )
        )

    def tearDown(self):
        self.manager.shutdown()
        self.store.close()
        self.temp.cleanup()

    def authenticate(self):
        response = self.client.get("/?token=auth-secret", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_security_assets_lifecycle_and_persisted_activity(self) -> None:
        self.assertEqual(self.client.get("/api/scans").status_code, 401)
        self.authenticate()
        page = self.client.get("/")
        self.assertIn('/assets/app.js', page.text)
        self.assertEqual(self.client.get("/assets/app.js").status_code, 200)
        self.assertEqual(page.headers["x-frame-options"], "DENY")
        nonce = re.search(r'<script nonce="([^"]+)" src=', page.text)
        self.assertIsNotNone(nonce)
        self.assertNotIn("script-src 'unsafe-inline'", page.headers["content-security-policy"])

        denied = self.client.post("/api/scans", json={"url": "https://lab"})
        self.assertEqual(denied.status_code, 403)
        response = self.client.post(
            "/api/scans",
            json={"url": "https://lab.example/fetch", "parameter": "id"},
            headers={"X-SQLIBLIND-CSRF": "csrf-secret"},
        )
        scan_id = response.json()["id"]
        for _ in range(100):
            scan = self.client.get(f"/api/scans/{scan_id}").json()
            if scan["status"] == "completed":
                break
            time.sleep(0.01)
        self.assertEqual(scan["status"], "completed")
        snapshot = self.client.get(f"/api/scans/{scan_id}/snapshot").json()
        self.assertEqual(snapshot["counts"]["schema"], 1)
        self.assertEqual(snapshot["activities"][0]["operation"], "Enumerate schemas")
        events = self.client.get(f"/api/scans/{scan_id}/events").json()
        self.assertTrue(any(item["event"] == "scan.completed" for item in events))
        exported = self.client.get(f"/api/scans/{scan_id}/export?format=json")
        self.assertIn("attachment", exported.headers["content-disposition"])

    def test_row_data_requires_explicit_table_selector(self) -> None:
        self.authenticate()
        response = self.client.post(
            "/api/scans",
            json={"url": "https://lab", "include_data": True},
            headers={"X-SQLIBLIND-CSRF": "csrf-secret"},
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
