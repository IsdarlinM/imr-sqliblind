from __future__ import annotations

import re
import threading
import time
import unittest

from blind_sqli.extractor import (
    BlindExtractor,
    CalibrationError,
    ExtractionError,
    ExtractorConfig,
)
from blind_sqli.models import ExtractionJob, ProbeResult


class DummyClient:
    requests_used = 0


class DummyOracle:
    pass


class TaggedDialect:
    name = "tagged"

    def boolean_payload(self, condition: str) -> str:
        return condition

    def length_expression(self, expression: str) -> str:
        return f"LEN:{expression}"

    def char_code_expression(self, expression: str, position: int) -> str:
        return f"CHAR:{expression}:{position}"

    def schema_count_expression(self) -> str:
        return "schema_count"

    def schema_name_expression(self, index: int) -> str:
        return f"schema_name:{index}"

    def table_count_expression(self, schema: str) -> str:
        return f"table_count:{schema}"

    def table_name_expression(self, schema: str, index: int) -> str:
        return f"table_name:{schema}:{index}"

    def column_count_expression(self, schema: str, table: str) -> str:
        return f"column_count:{schema}:{table}"

    def column_name_expression(self, schema: str, table: str, index: int) -> str:
        return f"column_name:{schema}:{table}:{index}"


class AlgorithmExtractor(BlindExtractor):
    def __init__(self, values: dict[str, object], **config: int) -> None:
        super().__init__(
            DummyClient(),
            DummyOracle(),
            TaggedDialect(),
            ExtractorConfig(**config),
        )
        self.values = values

    def _resolve(self, expression: str) -> int:
        if expression.startswith("LEN:"):
            return len(str(self.values[expression[4:]]))
        if expression.startswith("CHAR:"):
            _, key, position = expression.split(":", 2)
            return ord(str(self.values[key])[int(position) - 1])
        return int(self.values[expression])

    def probe_condition(self, condition: str) -> ProbeResult:
        integer = re.fullmatch(r"COALESCE\(\((.+)\), 0\) > (\d+)", condition)
        character = re.fullmatch(r"\((.+)\) ([<>=]) (\d+)", condition)
        if integer:
            matched = self._resolve(integer.group(1)) > int(integer.group(2))
        elif character:
            value = self._resolve(character.group(1))
            operator = character.group(2)
            expected = int(character.group(3))
            matched = {
                "<": value < expected,
                ">": value > expected,
                "=": value == expected,
            }[operator]
        else:
            matched = condition == "1=1"
        return ProbeResult(
            matched, 200 if matched else 400, 2, 0.0, "https://test"
        )


class MapExtractor(BlindExtractor):
    def __init__(self, workers: int = 4) -> None:
        super().__init__(
            DummyClient(),
            DummyOracle(),
            TaggedDialect(),
            ExtractorConfig(workers=workers),
        )
        self.thread_names: set[str] = set()
        self.lock = threading.Lock()
        self.values = {
            "table_count:main": 2,
            "table_count:audit": 1,
            "column_count:main:users": 2,
            "column_count:main:sessions": 1,
            "column_count:audit:events": 2,
            "table_name:main:0": "users",
            "table_name:main:1": "sessions",
            "table_name:audit:0": "events",
            "column_name:main:users:0": "id",
            "column_name:main:users:1": "name",
            "column_name:main:sessions:0": "token",
            "column_name:audit:events:0": "event_id",
            "column_name:audit:events:1": "created_at",
        }

    def enumerate_schemas(self) -> list[str]:
        return ["main", "audit"]

    def infer_integer(self, expression: str, maximum: int) -> int:
        del maximum
        with self.lock:
            self.thread_names.add(threading.current_thread().name)
        time.sleep(0.01)
        return int(self.values[expression])

    def extract_string(self, expression: str) -> str:
        with self.lock:
            self.thread_names.add(threading.current_thread().name)
        time.sleep(0.01)
        return str(self.values[expression])


class ConfigTests(unittest.TestCase):
    def test_config_bounds(self) -> None:
        for kwargs in (
            {"workers": 0},
            {"workers": 17},
            {"max_length": 0},
            {"max_items": 0},
            {"min_char_code": 100, "max_char_code": 10},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ExtractorConfig(**kwargs)


class AlgorithmTests(unittest.TestCase):
    def test_calibration_success_and_failure(self) -> None:
        extractor = AlgorithmExtractor({"value": 1})
        true_result, false_result = extractor.calibrate()
        self.assertTrue(true_result.matched)
        self.assertFalse(false_result.matched)

        extractor.probe_condition = lambda condition: ProbeResult(
            True, 200, 1, 0, "x"
        )
        with self.assertRaises(CalibrationError):
            extractor.calibrate()

    def test_infer_integer_uses_binary_search(self) -> None:
        extractor = AlgorithmExtractor({"count": 37})
        self.assertEqual(extractor.infer_integer("count", 100), 37)

    def test_infer_integer_rejects_negative_and_overflow(self) -> None:
        extractor = AlgorithmExtractor({"count": 101})
        with self.assertRaises(ValueError):
            extractor.infer_integer("count", -1)
        with self.assertRaises(ExtractionError):
            extractor.infer_integer("count", 100)

    def test_extract_string(self) -> None:
        extractor = AlgorithmExtractor({"word": "Hello"}, max_length=20)
        self.assertEqual(extractor.extract_string("word"), "Hello")

    def test_extract_string_honors_character_bounds(self) -> None:
        extractor = AlgorithmExtractor(
            {"word": "é"},
            max_length=5,
            min_char_code=32,
            max_char_code=126,
        )
        with self.assertRaises(ExtractionError):
            extractor.extract_string("word")


class ConcurrencyAndMapTests(unittest.TestCase):
    def test_extract_many_preserves_order_and_uses_workers(self) -> None:
        extractor = MapExtractor(workers=3)
        jobs = [
            ExtractionJob("a", "table_name:main:0"),
            ExtractionJob("b", "table_name:main:1"),
            ExtractionJob("c", "table_name:audit:0"),
        ]
        result = extractor.extract_many(jobs)
        self.assertEqual(
            result, {"a": "users", "b": "sessions", "c": "events"}
        )
        self.assertGreaterEqual(len(extractor.thread_names), 2)

    def test_build_database_map_with_columns(self) -> None:
        extractor = MapExtractor(workers=4)
        database = extractor.build_database_map()
        self.assertEqual(database.schema_count, 2)
        self.assertEqual(database.table_count, 3)
        self.assertEqual(database.column_count, 5)
        self.assertEqual(database.schemas[0].tables[0].columns, ["id", "name"])
        self.assertGreaterEqual(len(extractor.thread_names), 2)

    def test_build_database_map_without_columns(self) -> None:
        database = MapExtractor().build_database_map(include_columns=False)
        self.assertEqual(database.table_count, 3)
        self.assertEqual(database.column_count, 0)

    def test_empty_parallel_map_and_extract_many(self) -> None:
        extractor = MapExtractor()
        self.assertEqual(extractor._parallel_map([], str), [])
        self.assertEqual(extractor.extract_many([]), {})


if __name__ == "__main__":
    unittest.main()
