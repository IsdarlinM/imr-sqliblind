from __future__ import annotations

import io
import tempfile
import threading
import time
import unittest
from pathlib import Path

from blind_sqli.events import EventEmitter, ScanEvent
from blind_sqli.extractor import BlindExtractor, ExtractorConfig
from blind_sqli.models import ExtractionJob
from blind_sqli.progress import ActivityMonitor
from blind_sqli.store import SessionStore


class TtyBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


class DummyClient:
    requests_used = 0


class DummyDialect:
    name = "dummy"


class ConcurrentExtractor(BlindExtractor):
    def __init__(self, callback):
        super().__init__(
            DummyClient(),
            object(),
            DummyDialect(),
            ExtractorConfig(workers=2),
            event_callback=callback,
        )

    def extract_string(self, expression: str, *, maximum_length=None) -> str:
        del maximum_length
        self._update_activity(
            "extracting character 1/2",
            force=True,
            current=1,
            maximum=2,
            unit="characters",
        )
        time.sleep(0.02)
        return expression.upper()


class ProgressTests(unittest.TestCase):
    def test_parallel_workers_emit_separate_activities(self) -> None:
        events = []
        lock = threading.Lock()

        def capture(event):
            with lock:
                events.append(event)

        extractor = ConcurrentExtractor(capture)
        result = extractor.extract_many(
            [ExtractionJob("a", "one"), ExtractionJob("b", "two")],
            activity_operation="Extract table name",
            activity_target=lambda job, index: f"slot {index + 1}:{job.key}",
        )
        self.assertEqual(result, {"a": "ONE", "b": "TWO"})
        started = [e for e in events if e.event_type == "activity.started"]
        updated = [e for e in events if e.event_type == "activity.updated"]
        self.assertEqual(len(started), 2)
        self.assertGreaterEqual(len(updated), 2)
        self.assertGreaterEqual(
            len({e.payload["activity"]["worker"] for e in started}), 2
        )

    def test_plain_and_live_outputs_have_activity_not_percentages(self) -> None:
        plain = io.StringIO()
        monitor = ActivityMonitor(mode="plain", workers=2, stream=plain)
        activity = {
            "id": "a1",
            "operation": "Extract column name",
            "target": "main.users · column 1",
            "detail": "extracting character 2/8",
            "status": "running",
            "worker": "sqliblind_0",
        }
        monitor(ScanEvent("activity.started", "cli", {"activity": activity}))
        monitor(
            ScanEvent(
                "activity.completed",
                "cli",
                {"activity": {**activity, "status": "completed", "elapsed_seconds": 1.2}},
            )
        )
        self.assertIn("Extract column name", plain.getvalue())
        self.assertNotIn("%", plain.getvalue())

        live = TtyBuffer()
        with ActivityMonitor(
            mode="live", workers=2, stream=live, refresh_interval=0.05
        ) as display:
            for index in range(2):
                display(
                    ScanEvent(
                        "activity.started",
                        "cli",
                        {
                            "activity": {
                                **activity,
                                "id": f"a{index}",
                                "worker": f"sqliblind_{index}",
                            }
                        },
                    )
                )
            time.sleep(0.07)
        output = live.getvalue()
        self.assertIn("SQLIBLIND ACTIVITY", output)
        self.assertIn("sqliblind_0", output)
        self.assertIn("sqliblind_1", output)
        self.assertNotIn("%", output)

    def test_activity_is_persisted_in_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory) / "sessions.db")
            store.create_scan("scan", {}, "2026-07-30T00:00:00+00:00")
            emitter = EventEmitter("scan", store.record_event)
            emitter.emit(
                "activity.updated",
                activity={
                    "id": "a1",
                    "operation": "Count tables",
                    "target": "main",
                    "detail": "searching integer in range 0..64",
                    "kind": "extraction",
                    "status": "running",
                    "worker": "sqliblind_0",
                    "requests_used": 7,
                },
            )
            snapshot = store.snapshot("scan")
            self.assertEqual(snapshot["activities"][0]["requests_used"], 7)
            store.close()

    def test_web_assets_include_dynamic_activity_board(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src/blind_sqli/webui"
        content = "".join(
            (root / name).read_text(encoding="utf-8")
            for name in ("index.html", "app.css", "app.js")
        )
        self.assertIn('id="activityView"', content)
        self.assertIn("function renderActivities()", content)
        self.assertIn("startsWith('activity.')", content)
        self.assertNotIn("progress-percent", content)


if __name__ == "__main__":
    unittest.main()
