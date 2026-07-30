from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from blind_sqli.events import (
    EventEmitter,
    ScanCancelled,
    ScanControl,
    entity_id,
    relationship_id,
)
from blind_sqli.store import SessionStore


class EventControlTests(unittest.TestCase):
    def test_entity_and_relationship_ids_are_deterministic(self) -> None:
        first = entity_id("table", "main", "users")
        self.assertEqual(first, entity_id("table", "main", "users"))
        self.assertNotEqual(first, entity_id("table", "main", "sessions"))
        self.assertEqual(
            relationship_id("a", "b", "contains"),
            relationship_id("a", "b", "contains"),
        )

    def test_pause_resume_and_cancel_are_cooperative(self) -> None:
        control = ScanControl()
        control.pause()
        completed = threading.Event()

        def worker() -> None:
            control.checkpoint()
            completed.set()

        thread = threading.Thread(target=worker)
        thread.start()
        time.sleep(0.05)
        self.assertFalse(completed.is_set())
        control.resume()
        thread.join(timeout=1)
        self.assertTrue(completed.is_set())
        control.stop()
        with self.assertRaises(ScanCancelled):
            control.checkpoint()


class StoreTests(unittest.TestCase):
    def test_store_persists_entities_relations_and_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory) / "sessions.db")
            store.create_scan("scan1", {"url": "https://lab"}, "2026-01-01T00:00:00Z")
            emitter = EventEmitter("scan1", store.record_event)
            schema_id = entity_id("schema", "main")
            table_id = entity_id("table", "main", "users")
            emitter.emit(
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
            emitter.emit(
                "table.discovered",
                entity={
                    "id": table_id,
                    "type": "table",
                    "name": "users",
                    "parent_id": schema_id,
                    "status": "complete",
                    "data": {"schema": "main"},
                },
            )
            emitter.emit(
                "relationship.created",
                relationship={
                    "id": relationship_id(schema_id, table_id, "contains"),
                    "source_id": schema_id,
                    "target_id": table_id,
                    "kind": "contains",
                },
            )
            snapshot = store.snapshot("scan1")
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot["counts"], {"schema": 1, "table": 1})
            self.assertEqual(len(snapshot["relationships"]), 1)
            self.assertEqual(len(store.get_events("scan1")), 3)
            store.close()

    def test_running_scans_are_marked_interrupted_on_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.db"
            store = SessionStore(path)
            store.create_scan("scan1", {}, "2026-01-01T00:00:00Z")
            store.update_scan(
                "scan1", status="running", timestamp="2026-01-01T00:00:01Z"
            )
            store.close()
            reopened = SessionStore(path)
            self.assertEqual(reopened.get_scan("scan1")["status"], "interrupted")
            reopened.close()


if __name__ == "__main__":
    unittest.main()
