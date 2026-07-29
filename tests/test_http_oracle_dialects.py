from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from requests.exceptions import Timeout

from blind_sqli.client import (
    GlobalRateLimiter,
    HttpClient,
    HttpConfig,
    HttpRequestError,
    RequestBudget,
    RequestLimitExceeded,
)
from blind_sqli.dialects import (
    DialectError,
    MySqlDialect,
    SqliteDialect,
    get_dialect,
    sql_literal,
    validate_identifier,
)
from blind_sqli.oracle import OracleConfigurationError, ResponseOracle


def response(status: int = 200, body: bytes = b"ok") -> SimpleNamespace:
    return SimpleNamespace(
        status_code=status,
        content=body,
        text=body.decode(),
        url="https://example.test",
    )


class HttpConfigTests(unittest.TestCase):
    def test_defaults_are_secure(self) -> None:
        config = HttpConfig("https://example.test")
        self.assertTrue(config.verify_tls)
        self.assertEqual(config.parameter, "id")
        self.assertEqual(config.retries, 1)

    def test_rejects_invalid_timeout_retries_and_parameter(self) -> None:
        with self.assertRaises(ValueError):
            HttpConfig("https://example.test", timeout=0)
        with self.assertRaises(ValueError):
            HttpConfig("https://example.test", retries=6)
        with self.assertRaises(ValueError):
            HttpConfig("https://example.test", parameter="")

    def test_replaces_existing_parameter_and_preserves_others(self) -> None:
        client = HttpClient(HttpConfig("https://example.test/fetch?x=1&id=old", delay=0))
        url = client.build_url("0 OR 1=1")
        self.assertIn("x=1", url)
        self.assertIn("id=0+OR+1%3D1", url)
        self.assertNotIn("id=old", url)

    def test_adds_missing_parameter(self) -> None:
        client = HttpClient(
            HttpConfig("https://example.test/fetch?x=1", parameter="q", delay=0)
        )
        self.assertIn("q=value", client.build_url("value"))

    def test_template_supports_both_markers_and_percent_encoding(self) -> None:
        first = HttpClient(
            HttpConfig("unused", url_template="https://x/?id={{PAYLOAD}}", delay=0)
        )
        second = HttpClient(
            HttpConfig("unused", url_template="https://x/?id=[TO_REPLACE]", delay=0)
        )
        self.assertEqual(first.build_url("a b&c"), "https://x/?id=a%20b%26c")
        self.assertEqual(second.build_url("a b&c"), "https://x/?id=a%20b%26c")

    def test_template_without_marker_is_rejected(self) -> None:
        client = HttpClient(
            HttpConfig("unused", url_template="https://x/?id=none", delay=0)
        )
        with self.assertRaises(ValueError):
            client.build_url("payload")

    def test_thread_local_sessions_receive_headers_cookies_and_proxy(self) -> None:
        client = HttpClient(
            HttpConfig(
                "https://example.test",
                headers={"X-Test": "1"},
                cookies={"session": "abc"},
                proxy="http://127.0.0.1:8080",
                delay=0,
            )
        )
        session = client._session()
        self.assertEqual(session.headers["X-Test"], "1")
        self.assertEqual(session.cookies["session"], "abc")
        self.assertEqual(session.proxies["https"], "http://127.0.0.1:8080")

    def test_get_passes_tls_timeout_and_redirect_policy(self) -> None:
        client = HttpClient(
            HttpConfig(
                "https://example.test", timeout=3, verify_tls=False, delay=0
            )
        )
        fake = Mock(return_value=response())
        with patch.object(client._session(), "get", fake):
            client.get("1=1")
        kwargs = fake.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 3)
        self.assertFalse(kwargs["verify"])
        self.assertFalse(kwargs["allow_redirects"])

    def test_retries_transport_errors_and_raises_bounded_error(self) -> None:
        client = HttpClient(
            HttpConfig("https://example.test", retries=1, delay=0)
        )
        with patch.object(
            client._session(), "get", side_effect=Timeout("no response")
        ) as mocked:
            with self.assertRaises(HttpRequestError):
                client.get("1=1")
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(client.requests_used, 2)


class BudgetAndLimiterTests(unittest.TestCase):
    def test_request_budget_is_thread_safe_and_bounded(self) -> None:
        budget = RequestBudget(20)
        values: list[int] = []
        lock = threading.Lock()

        def consume() -> None:
            value = budget.consume()
            with lock:
                values.append(value)

        threads = [threading.Thread(target=consume) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(values), list(range(1, 21)))
        with self.assertRaises(RequestLimitExceeded):
            budget.consume()

    def test_rate_limiter_rejects_negative_delay(self) -> None:
        with self.assertRaises(ValueError):
            GlobalRateLimiter(-0.1)


class OracleTests(unittest.TestCase):
    def test_all_oracle_modes(self) -> None:
        self.assertTrue(
            ResponseOracle.from_options(
                mode="status", true_statuses={200}
            ).evaluate(response(200))
        )
        self.assertTrue(
            ResponseOracle.from_options(
                mode="marker", true_statuses={200}, marker="TRUE"
            ).evaluate(response(body=b"TRUE"))
        )
        self.assertTrue(
            ResponseOracle.from_options(
                mode="regex", true_statuses={200}, regex=r"A\d+"
            ).evaluate(response(body=b"A123"))
        )
        self.assertTrue(
            ResponseOracle.from_options(
                mode="length",
                true_statuses={200},
                expected_length=10,
                length_tolerance=2,
            ).evaluate(response(body=b"x" * 12))
        )

    def test_oracle_required_arguments_and_negative_tolerance(self) -> None:
        with self.assertRaises(OracleConfigurationError):
            ResponseOracle.from_options(mode="marker", true_statuses={200})
        with self.assertRaises(OracleConfigurationError):
            ResponseOracle.from_options(mode="regex", true_statuses={200})
        with self.assertRaises(OracleConfigurationError):
            ResponseOracle.from_options(mode="length", true_statuses={200})
        with self.assertRaises(OracleConfigurationError):
            ResponseOracle.from_options(
                mode="status", true_statuses={200}, length_tolerance=-1
            )

    def test_fingerprint(self) -> None:
        value = ResponseOracle().fingerprint(response(302, b"abc"))
        self.assertIn("status=302", value)
        self.assertIn("bytes=3", value)


class DialectTests(unittest.TestCase):
    def test_sql_literal_escapes_quotes(self) -> None:
        self.assertEqual(sql_literal("o'reilly"), "'o''reilly'")

    def test_identifier_validation(self) -> None:
        self.assertEqual(validate_identifier("main-db"), "main-db")
        with self.assertRaises(DialectError):
            validate_identifier("main;drop")

    def test_mysql_expressions(self) -> None:
        dialect = MySqlDialect()
        self.assertEqual(dialect.boolean_payload("1=1"), "0 OR (1=1)")
        self.assertIn(
            "information_schema.schemata", dialect.schema_count_expression()
        )
        self.assertIn("'my''schema'", dialect.table_count_expression("my'schema"))
        self.assertIn(
            "ordinal_position", dialect.column_name_expression("s", "t", 2)
        )

    def test_sqlite_expressions_and_schema_guard(self) -> None:
        dialect = SqliteDialect()
        self.assertIn("pragma_database_list", dialect.schema_count_expression())
        self.assertIn(
            '"main".sqlite_schema', dialect.table_count_expression("main")
        )
        self.assertIn(
            "pragma_table_info", dialect.column_count_expression("main", "users")
        )
        with self.assertRaises(DialectError):
            dialect.column_count_expression("attached", "users")

    def test_get_dialect(self) -> None:
        self.assertIsInstance(get_dialect("MYSQL"), MySqlDialect)
        self.assertIsInstance(get_dialect("sqlite"), SqliteDialect)
        with self.assertRaises(DialectError):
            get_dialect("postgres")


if __name__ == "__main__":
    unittest.main()
