from __future__ import annotations

import unittest

from blind_sqli.extractor_core import BlindExtractor, ExtractorConfig
from blind_sqli.models import DatabaseMap, ExtractionJob, Schema, Table


class FakeDialect:
    def table_count_expression(self, schema: str) -> str:
        return f"table-count:{schema}"

    def table_name_expression(self, schema: str, index: int) -> str:
        return f"table-name:{schema}:{index}"

    def column_count_expression(self, schema: str, table: str) -> str:
        return f"column-count:{schema}:{table}"

    def column_name_expression(self, schema: str, table: str, index: int) -> str:
        return f"column-name:{schema}:{table}:{index}"


class CallbackRegressionExtractor(BlindExtractor):
    def __init__(self) -> None:
        self.config = ExtractorConfig(workers=64, max_items=64)
        self.dialect = FakeDialect()
        self.emitted_tables: list[tuple[str, str]] = []

    def enumerate_schemas(self) -> list[str]:
        return ["main"]

    def _parallel_map(self, items, function, on_result=None):
        values = []
        for item in items:
            result = function(item)
            values.append(result)
            if on_result is not None:
                on_result(item, result)
        return values

    def infer_integer(self, expression: str, maximum: int) -> int:
        del maximum
        if expression.startswith("table-count:"):
            return 2
        if expression.startswith("column-count:"):
            return 0
        raise AssertionError(f"Unexpected expression: {expression}")

    def extract_many(
        self,
        jobs: list[ExtractionJob],
        *,
        maximum_length: int | None = None,
        on_result=None,
    ) -> dict[str, str]:
        del maximum_length
        result: dict[str, str] = {}
        for index, job in enumerate(jobs):
            value = f"table_{index}"
            result[job.key] = value
            if on_result is not None:
                on_result(job, value)
        return result

    def _emit_entity(self, **kwargs) -> str:
        if kwargs.get("kind") == "table":
            data = kwargs["data"]
            self.emitted_tables.append((data["schema"], data["table"]))
        return "entity-id"


class MapCallbackAndWorkerLimitTests(unittest.TestCase):
    def test_map_table_callback_uses_received_job(self) -> None:
        extractor = CallbackRegressionExtractor()

        database = extractor.build_database_map(include_columns=False)

        self.assertIsInstance(database, DatabaseMap)
        self.assertEqual([schema.name for schema in database.schemas], ["main"])
        self.assertEqual(
            [table.name for table in database.schemas[0].tables],
            ["table_0", "table_1"],
        )
        self.assertEqual(
            extractor.emitted_tables,
            [("main", "table_0"), ("main", "table_1")],
        )

    def test_64_workers_are_allowed(self) -> None:
        self.assertEqual(ExtractorConfig(workers=64).workers, 64)

    def test_more_than_64_workers_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 1 and 64"):
            ExtractorConfig(workers=65)


if __name__ == "__main__":
    unittest.main()
