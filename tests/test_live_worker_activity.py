from __future__ import annotations

import itertools
import threading
import time
import unittest
from types import SimpleNamespace

from blind_sqli.inference_scheduler import InferenceSchedulingMixin
from blind_sqli.models import ExtractionJob


class _FakeDialect:
    @staticmethod
    def length_expression(expression: str) -> str:
        return f"length({expression})"

    @staticmethod
    def char_code_expression(expression: str, position: int) -> str:
        return f"code({expression},{position})"


class _SchedulerHarness(InferenceSchedulingMixin):
    def __init__(self, workers: int = 2) -> None:
        self.config = SimpleNamespace(
            workers=workers,
            min_char_code=32,
            max_char_code=126,
        )
        self.events = SimpleNamespace(scan_id="worker-test")
        self.client = SimpleNamespace(requests_used=0)
        self.dialect = _FakeDialect()
        self.parallel_characters = True
        self.inference_mode = "adaptive"
        self._activity_lock = threading.Lock()
        self._activity_counter = itertools.count(1)
        self._events_lock = threading.Lock()
        self.emitted: list[tuple[str, dict[str, object]]] = []

    def _emit(self, event_type: str, **payload: object) -> None:
        with self._events_lock:
            self.emitted.append((event_type, payload))

    @staticmethod
    def _activity_payload(
        value: dict[str, object],
    ) -> dict[str, object]:
        return {
            key: item
            for key, item in value.items()
            if not key.startswith("_")
        }

    def infer_integer_capped(
        self,
        expression: str,
        maximum: int,
    ) -> tuple[int, bool]:
        del expression, maximum
        time.sleep(0.012)
        self.client.requests_used += 1
        return 2, False

    def _infer_character_code(
        self,
        expression: str,
        position: int,
    ) -> int:
        del expression, position
        time.sleep(0.016)
        self.client.requests_used += 1
        return ord("a")


class LiveWorkerActivityTests(unittest.TestCase):
    def test_only_executing_workers_are_marked_active(self) -> None:
        scheduler = _SchedulerHarness(workers=2)
        jobs = [
            ExtractionJob(key=str(index), expression=f"value_{index}")
            for index in range(8)
        ]

        result = scheduler.extract_many(jobs, maximum_length=8)

        self.assertEqual(
            result,
            {str(index): "aa" for index in range(8)},
        )

        active: set[str] = set()
        maximum_active = 0
        worker_details: list[str] = []
        batch_running: list[dict[str, object]] = []

        for _, payload in scheduler.emitted:
            activity = payload.get("activity")
            if not isinstance(activity, dict):
                continue
            if (
                activity.get("kind") == "batch"
                and activity.get("status") == "running"
            ):
                batch_running.append(activity)
            if activity.get("kind") != "worker":
                continue

            worker_details.append(str(activity.get("detail", "")))
            identifier = str(activity["id"])
            if (
                activity.get("status") == "running"
                and activity.get("active") is True
            ):
                active.add(identifier)
            else:
                active.discard(identifier)
            maximum_active = max(maximum_active, len(active))

        self.assertFalse(batch_running)
        self.assertGreaterEqual(maximum_active, 1)
        self.assertLessEqual(maximum_active, 2)
        self.assertFalse(active)
        self.assertTrue(
            any(detail == "measuring value length" for detail in worker_details)
        )
        self.assertTrue(
            any(detail.startswith("character ") for detail in worker_details)
        )

    def test_batch_activities_are_queued_not_active(self) -> None:
        scheduler = _SchedulerHarness(workers=1)
        scheduler.extract_many(
            [ExtractionJob(key="0", expression="value")],
            maximum_length=4,
        )

        queued = [
            payload["activity"]
            for event_type, payload in scheduler.emitted
            if event_type == "activity.queued"
        ]
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["status"], "queued")
        self.assertIs(queued[0]["active"], False)
        self.assertEqual(queued[0]["kind"], "batch")


if __name__ == "__main__":
    unittest.main()
