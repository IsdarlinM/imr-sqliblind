from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from blind_sqli.events import EventEmitter, ScanControl, entity_id, relationship_id
from blind_sqli.manager import ScanManager, ScanSettings
from blind_sqli.models import DatabaseMap, Schema, Table
from blind_sqli.store import SessionStore


class FakeExtractor:
    def __init__(self, scan_id, callback, control, *, slow=False):
        self.events = EventEmitter(scan_id, callback)
        self.control = control
        self.client = SimpleNamespace(requests_used=7)
        self.elapsed_seconds = 0.25
        self.slow = slow

    def calibrate(self):
        self.events.emit("scan.calibrated")
        return None

    def build_database_map(self, **kwargs):
        schema_id = entity_id("schema", "main")
        table_id = entity_id("table", "main", "users")
        self.events.emit(
            "schema.discovered",
            entity={
                "id": schema_id,
                "type": "schema",
                "name": "main",
                "parent_id": None,
                "status": "complete",
                "data": {},
            },
        )
        if self.slow:
            for _ in range(100):
                self.control.checkpoint()
                time.sleep(0.005)
        self.events.emit(
            "table.discovered",
            entity={
                "id": table_id,
                "type": "table",
                "name": "users",
                "parent_id": schema_id,
                "status": "complete",
                "data": {},
            },
        )
        self.events.emit(
            "relationship.created",
            relationship={
                "id": relationship_id(schema_id, table_id, "contains"),
                "source_id": schema_id,
                "target_id": table_id,
                "kind": "contains",
            },
        )
        return DatabaseMap([Schema("main", [Table("users", ["id"])])])


class ManagerTests(unittest.TestCase):
    def make_manager(self, directory: str, *, slow: bool = False):
        store = SessionStore(Path(directory) / "sessions.db")

        def factory(settings, scan_id, callback, control):
            return FakeExtractor(scan_id, callback, control, slow=slow)

        return store, ScanManager(store, factory)

    def wait_terminal(self, store, scan_id):
        for _ in range(200):
            status = store.get_scan(scan_id)["status"]
            if status in {"completed", "failed", "cancelled"}:
                return status
            time.sleep(0.01)
        self.fail("scan did not finish")

    def test_settings_validate_data_limits_and_redact_secrets(self) -> None:
        with self.assertRaises(ValueError):
            ScanSettings(url="https://lab", include_data=True)
        settings = ScanSettings(
            url="https://lab",
            include_data=True,
            data_tables={"main.users"},
            headers={"Authorization": "Bearer secret", "X-Test": "yes"},
            cookies={"session": "secret"},
        )
        public = settings.public_dict()
        self.assertEqual(public["headers"]["Authorization"], "***")
        self.assertEqual(public["headers"]["X-Test"], "yes")
        self.assertEqual(public["cookies"]["session"], "***")

    def test_scan_completes_and_exports_all_formats(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, manager = self.make_manager(directory)
            scan_id = manager.start(ScanSettings(url="https://lab"))
            self.assertEqual(self.wait_terminal(store, scan_id), "completed")
            snapshot = store.snapshot(scan_id)
            self.assertEqual(snapshot["counts"]["schema"], 1)
            for fmt, marker in (
                ("json", '"entities"'),
                ("tree", "DATABASE STRUCTURE"),
                ("relations", "DATABASE RELATIONSHIPS"),
                ("mermaid", "flowchart LR"),
                ("html", "<!doctype html>"),
            ):
                content, _ = manager.export(scan_id, fmt)
                self.assertIn(marker, content)
            store.close()

    def test_pause_resume_and_stop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, manager = self.make_manager(directory, slow=True)
            scan_id = manager.start(ScanSettings(url="https://lab"))
            time.sleep(0.03)
            manager.pause(scan_id)
            self.assertEqual(store.get_scan(scan_id)["status"], "paused")
            manager.resume(scan_id)
            self.assertEqual(store.get_scan(scan_id)["status"], "running")
            manager.stop(scan_id)
            self.assertEqual(self.wait_terminal(store, scan_id), "cancelled")
            store.close()


if __name__ == "__main__":
    unittest.main()
