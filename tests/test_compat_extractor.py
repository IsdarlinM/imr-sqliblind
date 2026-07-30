from __future__ import annotations

import re
import threading
import time
import unittest

from blind_sqli.extractor import BlindExtractor, ExtractionError, ExtractorConfig
from blind_sqli.models import ExtractionJob, ProbeResult


class DummyClient:
    requests_used = 0


class DummyOracle:
    pass


class TaggedDialect:
    name = "tagged"

    def boolean_payload(self, condition):
        return condition

    def length_expression(self, expression):
        return f"LEN:{expression}"

    def char_code_expression(self, expression, position):
        return f"CHAR:{expression}:{position}"

    def schema_count_expression(self):
        return "schema_count"

    def schema_name_expression(self, index):
        return f"schema_name:{index}"

    def table_count_expression(self, schema):
        return f"table_count:{schema}"

    def table_name_expression(self, schema, index):
        return f"table_name:{schema}:{index}"

    def column_count_expression(self, schema, table):
        return f"column_count:{schema}:{table}"

    def column_name_expression(self, schema, table, index):
        return f"column_name:{schema}:{table}:{index}"


class AlgorithmExtractor(BlindExtractor):
    def __init__(self, values, **config):
        super().__init__(
            DummyClient(), DummyOracle(), TaggedDialect(), ExtractorConfig(**config)
        )
        self.values = values

    def _resolve(self, expression):
        if expression.startswith("LEN:"):
            return len(str(self.values[expression[4:]]))
        if expression.startswith("CHAR:"):
            _, key, position = expression.split(":", 2)
            return ord(str(self.values[key])[int(position) - 1])
        return int(self.values[expression])

    def probe_condition(self, condition):
        integer = re.fullmatch(r"COALESCE\(\((.+)\), 0\) > (\d+)", condition)
        character = re.fullmatch(r"\((.+)\) ([<>=]) (\d+)", condition)
        if integer:
            matched = self._resolve(integer.group(1)) > int(integer.group(2))
        elif character:
            value = self._resolve(character.group(1))
            expected = int(character.group(3))
            matched = {
                "<": value < expected,
                ">": value > expected,
                "=": value == expected,
            }[character.group(2)]
        else:
            matched = condition == "1=1"
        return ProbeResult(matched, 200 if matched else 400, 2, 0, "https://test")


class MapExtractor(BlindExtractor):
    def __init__(self):
        super().__init__(
            DummyClient(), DummyOracle(), TaggedDialect(), ExtractorConfig(workers=4)
        )
        self.lock = threading.Lock()
        self.thread_names = set()
        self.values = {
            "table_count:main": 1,
            "column_count:main:users": 2,
            "table_name:main:0": "users",
            "column_name:main:users:0": "id",
            "column_name:main:users:1": "name",
        }

    def enumerate_schemas(self):
        return ["main"]

    def infer_integer(self, expression, maximum):
        del maximum
        with self.lock:
            self.thread_names.add(threading.current_thread().name)
        time.sleep(0.002)
        return int(self.values[expression])

    def extract_string(self, expression):
        with self.lock:
            self.thread_names.add(threading.current_thread().name)
        time.sleep(0.002)
        return str(self.values[expression])


class ExtractorCompatibilityTests(unittest.TestCase):
    def test_integer_string_map_and_legacy_extract_many(self) -> None:
        extractor = AlgorithmExtractor({"count": 37, "word": "Hello"}, max_length=20)
        self.assertEqual(extractor.infer_integer("count", 100), 37)
        self.assertEqual(extractor.extract_string("word"), "Hello")
        with self.assertRaises(ExtractionError):
            AlgorithmExtractor({"count": 101}).infer_integer("count", 100)

        mapped = MapExtractor()
        database = mapped.build_database_map()
        self.assertEqual((database.schema_count, database.table_count), (1, 1))
        self.assertEqual(database.schemas[0].tables[0].columns, ["id", "name"])
        result = mapped.extract_many([ExtractionJob("a", "table_name:main:0")])
        self.assertEqual(result, {"a": "users"})


if __name__ == "__main__":
    unittest.main()
