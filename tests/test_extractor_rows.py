from __future__ import annotations

import unittest
from types import SimpleNamespace

from blind_sqli.dialects import DialectError, MySqlDialect, SqliteDialect
from blind_sqli.events import ScanEvent
from blind_sqli.extractor import BlindExtractor, ExtractorConfig, protect_sensitive_value
from blind_sqli.models import ExtractionJob, Table
from blind_sqli.oracle import ResponseOracle


class FakeClient:
    requests_used = 0


class RowExtractor(BlindExtractor):
    def __init__(self, callback):
        super().__init__(
            FakeClient(),
            ResponseOracle(),
            MySqlDialect(),
            ExtractorConfig(),
            scan_id="scan",
            event_callback=callback,
        )

    def infer_integer_capped(self, expression: str, maximum: int):
        return (2, False)

    def extract_string(self, expression, *, maximum_length=None):
        column = "id" if "`id`" in expression else "name"
        value = f"{column}-value"
        return value[:maximum_length] if maximum_length else value


class RowExtractionTests(unittest.TestCase):
    def test_bounded_rows_emit_dynamic_entities(self) -> None:
        events: list[ScanEvent] = []
        extractor = RowExtractor(events.append)
        table = Table("users", ["id", "name"])
        count, truncated, used = extractor.extract_table_rows(
            "main",
            table,
            max_rows=5,
            max_columns=2,
            max_value_length=64,
            max_data_bytes=1000,
        )
        self.assertEqual(count, 2)
        self.assertFalse(truncated)
        self.assertGreater(used, 0)
        self.assertEqual(len(table.rows), 2)
        types = [event.event_type for event in events]
        self.assertIn("row.discovered", types)
        self.assertIn("cell.discovered", types)
        self.assertIn("entity.updated", types)

    def test_data_byte_budget_truncates(self) -> None:
        extractor = RowExtractor(lambda event: None)
        table = Table("users", ["id", "name"])
        count, truncated, _ = extractor.extract_table_rows(
            "main",
            table,
            max_rows=5,
            max_columns=2,
            max_value_length=64,
            max_data_bytes=1,
        )
        self.assertEqual(count, 1)
        self.assertEqual(len(table.rows), 1)
        self.assertEqual(next(iter(table.rows[0].values())), "i")
        self.assertTrue(truncated)

    def test_sensitive_values_are_masked_by_default(self) -> None:
        self.assertEqual(protect_sensitive_value("password", "hunter2"), "********")
        self.assertEqual(
            protect_sensitive_value("api_token", "abcdefghijklmnop"),
            "abcd…mnop",
        )
        self.assertEqual(
            protect_sensitive_value("password", "hunter2", reveal=True),
            "hunter2",
        )


    def test_sensitive_row_events_never_persist_raw_values_by_default(self) -> None:
        events: list[ScanEvent] = []
        extractor = RowExtractor(events.append)
        table = Table("users", ["password"])
        extractor.extract_table_rows(
            "main",
            table,
            max_rows=1,
            max_columns=1,
            max_value_length=64,
            max_data_bytes=1000,
        )
        serialized = repr([event.payload for event in events])
        self.assertNotIn("password-value", serialized)
        self.assertIn("********", serialized)

    def test_dialects_quote_data_identifiers(self) -> None:
        mysql = MySqlDialect()
        self.assertIn("`main`.`users`", mysql.row_count_expression("main", "users"))
        self.assertIn("OFFSET 2", mysql.cell_value_expression("main", "users", "id", 2))
        sqlite = SqliteDialect()
        self.assertIn('"main"."users"', sqlite.row_count_expression("main", "users"))
        with self.assertRaises(DialectError):
            mysql.row_count_expression("main;DROP", "users")


if __name__ == "__main__":
    unittest.main()
