import importlib
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from blind_sqli.client import HttpClient, HttpConfig, RequestBudget, RequestLimitExceeded
from blind_sqli.extractor import BlindExtractor, ExtractorConfig
from blind_sqli.models import ExtractionJob, Schema, Table
from blind_sqli.oracle import ResponseOracle


def response(status: int = 200, body: bytes = b"ok"):
    return SimpleNamespace(
        status_code=status,
        content=body,
        text=body.decode(),
        url="https://example.test",
    )


class ModelTests(unittest.TestCase):
    def test_add_row_maps_values_to_columns(self) -> None:
        table = Table("users", ["id", "name"])
        table.add_row([1, "alice"])
        self.assertEqual(table.rows, [{"id": 1, "name": "alice"}])

    def test_add_row_rejects_wrong_width(self) -> None:
        table = Table("users", ["id", "name"])
        with self.assertRaises(ValueError):
            table.add_row([1])

    def test_schema_deduplicates_tables_case_insensitively(self) -> None:
        schema = Schema("main")
        schema.add_table(Table("Users", ["id"]))
        schema.add_table(Table("users", ["id"]))
        self.assertEqual(len(schema.tables), 1)


class HttpClientTests(unittest.TestCase):
    def test_replaces_existing_parameter_and_preserves_others(self) -> None:
        client = HttpClient(
            HttpConfig(url="https://example.test/fetch?x=1&id=old", delay=0)
        )
        url = client.build_url("0 OR 1=1")
        self.assertIn("x=1", url)
        self.assertIn("id=0+OR+1%3D1", url)
        self.assertNotIn("id=old", url)

    def test_template_payload_is_percent_encoded(self) -> None:
        client = HttpClient(
            HttpConfig(
                url="https://unused.test",
                url_template="https://example.test/fetch?id={{PAYLOAD}}",
                delay=0,
            )
        )
        self.assertEqual(
            client.build_url("0 OR 1=1"),
            "https://example.test/fetch?id=0%20OR%201%3D1",
        )

    def test_request_budget_is_bounded(self) -> None:
        budget = RequestBudget(1)
        self.assertEqual(budget.consume(), 1)
        with self.assertRaises(RequestLimitExceeded):
            budget.consume()


class OracleTests(unittest.TestCase):
    def test_status_oracle(self) -> None:
        oracle = ResponseOracle.from_options(mode="status", true_statuses={200})
        self.assertTrue(oracle.evaluate(response(200)))
        self.assertFalse(oracle.evaluate(response(500)))

    def test_marker_oracle(self) -> None:
        oracle = ResponseOracle.from_options(
            mode="marker", true_statuses={200}, marker="TRUE"
        )
        self.assertTrue(oracle.evaluate(response(body=b"RESULT=TRUE")))
        self.assertFalse(oracle.evaluate(response(body=b"RESULT=FALSE")))

    def test_length_oracle_with_tolerance(self) -> None:
        oracle = ResponseOracle.from_options(
            mode="length",
            true_statuses={200},
            expected_length=10,
            length_tolerance=2,
        )
        self.assertTrue(oracle.evaluate(response(body=b"x" * 12)))
        self.assertFalse(oracle.evaluate(response(body=b"x" * 13)))


class DummyClient:
    requests_used = 0


class DummyOracle:
    pass


class DummyDialect:
    pass


class ConcurrentExtractor(BlindExtractor):
    def __init__(self) -> None:
        super().__init__(
            DummyClient(),
            DummyOracle(),
            DummyDialect(),
            ExtractorConfig(workers=3),
        )
        self.thread_names: set[str] = set()
        self.lock = threading.Lock()

    def extract_string(self, expression: str) -> str:
        with self.lock:
            self.thread_names.add(threading.current_thread().name)
        time.sleep(0.03)
        return expression.upper()


class ExtractorConcurrencyTests(unittest.TestCase):
    def test_extract_many_preserves_order_and_uses_workers(self) -> None:
        extractor = ConcurrentExtractor()
        result = extractor.extract_many(
            [
                ExtractionJob("a", "one"),
                ExtractionJob("b", "two"),
                ExtractionJob("c", "three"),
            ]
        )
        self.assertEqual(result, {"a": "ONE", "b": "TWO", "c": "THREE"})
        self.assertGreaterEqual(len(extractor.thread_names), 2)


class ImportTests(unittest.TestCase):
    def test_import_does_not_issue_requests(self) -> None:
        with patch("requests.Session.get") as mocked_get:
            importlib.import_module("blind_sqli")
            mocked_get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
