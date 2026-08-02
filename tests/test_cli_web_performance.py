from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from blind_sqli.cli import build_parser, main as cli_main
from blind_sqli.client import AdaptiveConcurrencyLimiter
from blind_sqli.events import ScanEvent
from blind_sqli.manager import EventBatchWriter
from blind_sqli.web_app import create_app


class DummyStore:
    def list_scans(self) -> list[dict[str, Any]]:
        return []

    def get_scan(self, scan_id: str) -> None:
        del scan_id
        return None

    def snapshot(self, scan_id: str) -> None:
        del scan_id
        return None

    def get_events(
        self,
        scan_id: str,
        *,
        after: int = 0,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        del scan_id, after, limit
        return []


class DummyManager:
    def __init__(self) -> None:
        self.store = DummyStore()
        self.settings: Any = None

    def start(self, settings: Any) -> str:
        self.settings = settings
        return "scan-optimized"

    def export(self, scan_id: str, output_format: str) -> tuple[str, str]:
        del scan_id, output_format
        return "{}", "application/json"


class FakeCliClient:
    requests_used = 64


class FakeCliExtractor:
    client = FakeCliClient()
    elapsed_seconds = 0.125

    def extract_string(self, expression: str) -> str:
        del expression
        return "User_50%"

    def performance_snapshot(self) -> dict[str, object]:
        return {
            "inference_mode": "bitwise",
            "parallel_characters": True,
            "inference": {"characters": 8},
            "http": {"adaptive_limit": 8},
        }


class BatchStore:
    def __init__(self) -> None:
        self.batches: list[
            tuple[list[ScanEvent], dict[str, tuple[dict[str, Any], str]]]
        ] = []

    def apply_batch(
        self,
        events: list[ScanEvent],
        stats: dict[str, tuple[dict[str, Any], str]],
    ) -> None:
        self.batches.append((list(events), dict(stats)))


class CliWebPerformanceTests(unittest.TestCase):
    def test_cli_defaults_to_turbo_bounded_full_mapping(self) -> None:
        args = build_parser().parse_args(["map"])
        self.assertEqual(args.inference_mode, "turbo")
        self.assertEqual(args.workers, 16)
        self.assertEqual(args.delay, 0.0)
        self.assertTrue(args.include_data)
        self.assertEqual(args.data_table, [])

    def test_cli_exposes_and_routes_optimized_modes(self) -> None:
        args = build_parser().parse_args(
            [
                "--inference-mode",
                "bitwise",
                "--workers",
                "8",
                "--fixed-concurrency",
                "extract",
                "--expression",
                "SELECT 'User_50%'",
            ]
        )
        self.assertEqual(args.inference_mode, "bitwise")
        self.assertEqual(args.workers, 8)
        self.assertTrue(args.fixed_concurrency)

        output = io.StringIO()
        with patch(
            "blind_sqli.cli._build_extractor",
            return_value=FakeCliExtractor(),
        ):
            with redirect_stdout(output):
                code = cli_main(
                    [
                        "--skip-calibration",
                        "--inference-mode",
                        "bitwise",
                        "extract",
                        "--expression",
                        "SELECT 'User_50%'",
                    ]
                )
        self.assertEqual(code, 0)
        self.assertIn("User_50%", output.getvalue())
        self.assertIn("Mode: bitwise", output.getvalue())

    def test_web_form_and_api_use_optimized_settings(self) -> None:
        manager = DummyManager()
        app = create_app(manager, auth_token="secret", csrf_token="csrf")
        client = TestClient(app)
        response = client.get("/?token=secret", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="inference_mode"', response.text)
        self.assertIn("modulo-3 checks in global waves", response.text)

        response = client.post(
            "/api/scans",
            headers={"X-SQLIBLIND-CSRF": "csrf"},
            json={
                "url": "https://lab.invalid/fetch",
                "inference_mode": "bitwise",
                "workers": 8,
                "parallel_characters": True,
                "adaptive_confirmation": True,
                "adaptive_concurrency": True,
                "request_event_sample": 25,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"id": "scan-optimized"})
        self.assertEqual(manager.settings.inference_mode, "bitwise")
        self.assertTrue(manager.settings.parallel_characters)
        self.assertEqual(manager.settings.request_event_sample, 25)

    def test_request_events_are_sampled_and_committed_in_batches(self) -> None:
        store = BatchStore()
        writer = EventBatchWriter(
            store,
            batch_size=50,
            flush_interval=0.02,
            request_sample=20,
        )
        writer.configure_scan("scan", request_sample=20)
        for number in range(1, 101):
            writer.submit(
                ScanEvent(
                    "request.completed",
                    "scan",
                    {
                        "requests_used": number,
                        "elapsed_seconds": 0.01,
                        "status_code": 200,
                    },
                )
            )
        writer.submit(
            ScanEvent(
                "schema.discovered",
                "scan",
                {
                    "entity": {
                        "id": "schema:1",
                        "type": "schema",
                        "name": "main",
                        "status": "complete",
                    }
                },
            )
        )
        writer.flush()
        writer.stop()

        persisted = [event for events, _ in store.batches for event in events]
        request_events = [
            event
            for event in persisted
            if event.event_type == "request.completed"
        ]
        schema_events = [
            event
            for event in persisted
            if event.event_type == "schema.discovered"
        ]
        self.assertEqual(len(request_events), 5)
        self.assertEqual(len(schema_events), 1)

        latest_stats: dict[str, tuple[dict[str, Any], str]] = {}
        for _, stats in store.batches:
            latest_stats.update(stats)
        self.assertEqual(latest_stats["scan"][0]["requests"], 100)

    def test_aimd_concurrency_backs_off_and_recovers_after_429(self) -> None:
        limiter = AdaptiveConcurrencyLimiter(1, 8, enabled=True)
        self.assertEqual(limiter.limit, 8)

        limiter.acquire()
        limiter.release(
            elapsed=0.01,
            status_code=429,
            failed=False,
        )
        self.assertEqual(limiter.limit, 4)

        for _ in range(12):
            limiter.acquire()
            limiter.release(
                elapsed=0.01,
                status_code=200,
                failed=False,
            )
        self.assertEqual(limiter.limit, 5)

    def test_aimd_does_not_treat_oracle_5xx_as_transport_congestion(self) -> None:
        limiter = AdaptiveConcurrencyLimiter(2, 8, enabled=True)
        before = limiter.limit
        limiter.acquire()
        limiter.release(
            elapsed=0.01,
            status_code=500,
            failed=False,
        )
        self.assertGreaterEqual(limiter.limit, before)


if __name__ == "__main__":
    unittest.main()
