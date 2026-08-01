from __future__ import annotations

import re
import threading
import time
import unittest

from blind_sqli.extractor import BlindExtractor, ExtractorConfig
from blind_sqli.models import ProbeResult


class Client:
    def __init__(self) -> None:
        self.requests_used = 0
        self.lock = threading.Lock()

    def performance_snapshot(self) -> dict[str, int]:
        return {"responses": self.requests_used}


class Oracle:
    def evaluate(self, response: object) -> bool:
        return bool(response)


class StringDialect:
    name = "string"

    def boolean_payload(self, condition: str) -> str:
        return condition

    def text_expression(self, expression: str) -> str:
        return f"TEXT[{expression}]"

    def length_expression(self, expression: str) -> str:
        return f"LEN[{expression}]"

    def char_code_expression(self, expression: str, position: int) -> str:
        return f"CODE[{position}][{expression}]"


def decode_token(token: str, scalar) -> int:
    length = re.fullmatch(r"LEN\[(.*)]", token)
    if length:
        return len(str(scalar(length.group(1))))
    code = re.fullmatch(r"CODE\[(\d+)]\[(.*)]", token)
    if code:
        position = int(code.group(1))
        value = str(scalar(code.group(2)))
        return ord(value[position - 1]) if position <= len(value) else 0
    return int(scalar(token))


def evaluate_condition(condition: str, scalar) -> bool:
    text = re.fullmatch(r"\(TEXT\[(.*)]\) = '(.*)'", condition)
    if text:
        expected = text.group(2).replace("''", "'")
        return str(scalar(text.group(1))) == expected

    token_match = re.search(r"COALESCE\(\((.*?)\), 0\)", condition)
    if token_match:
        value = decode_token(token_match.group(1), scalar)
    else:
        code_match = re.search(r"CODE\[(\d+)]\[(.*?)]", condition)
        if not code_match:
            raise AssertionError(f"Unsupported condition: {condition}")
        value = decode_token(
            f"CODE[{code_match.group(1)}][{code_match.group(2)}]",
            scalar,
        )

    bit = re.search(r"& (\d+)\) <> 0", condition)
    if bit:
        return bool(value & int(bit.group(1)))
    residue = re.search(r"% 3\) = (\d+)", condition)
    if residue:
        return value % 3 == int(residue.group(1))
    between = re.search(r"BETWEEN (\d+) AND (\d+)", condition)
    if between:
        return int(between.group(1)) <= value <= int(between.group(2))
    comparison = re.search(r"\)?\s*([>=<]+)\s*(\d+)$", condition)
    if comparison:
        operator, expected = comparison.group(1), int(comparison.group(2))
        return {
            ">": value > expected,
            "=": value == expected,
            "<": value < expected,
        }[operator]
    raise AssertionError(f"Unsupported condition: {condition}")


def make_string_extractor(
    value: str,
    *,
    mode: str,
    workers: int = 64,
    latency: float = 0.0,
) -> tuple[BlindExtractor, Client, list[str]]:
    client = Client()
    conditions: list[str] = []
    extractor = BlindExtractor(
        client,
        Oracle(),
        StringDialect(),
        ExtractorConfig(
            workers=workers,
            max_length=128,
            max_items=128,
            min_char_code=32,
            max_char_code=126,
        ),
        inference_mode=mode,
        parallel_characters=True,
    )

    def probe(condition: str) -> ProbeResult:
        if latency:
            time.sleep(latency)
        with client.lock:
            client.requests_used += 1
            conditions.append(condition)
        matched = evaluate_condition(condition, lambda expression: expression)
        return ProbeResult(
            matched,
            200 if matched else 404,
            1,
            latency,
            "fake://",
        )

    extractor.probe_condition = probe  # type: ignore[method-assign]
    return extractor, client, conditions


DATA = {
    "large": {
        "audit": {
            "columns": ["id"],
            "rows": [{"id": "10"}],
        },
        "users": {
            "columns": ["id", "name"],
            "rows": [{"id": "1", "name": "Ada"}],
        },
    },
    "small": {
        "config": {
            "columns": ["key", "value"],
            "rows": [{"key": "mode", "value": "safe"}],
        },
    },
}


class MetadataDialect(StringDialect):
    name = "metadata"

    def schema_count_expression(self) -> str:
        return "SCHEMA_COUNT"

    def schema_name_expression(self, index: int) -> str:
        return f"SCHEMA_NAME|{index}"

    def table_count_expression(self, schema: str) -> str:
        return f"TABLE_COUNT|{schema}"

    def table_name_expression(self, schema: str, index: int) -> str:
        return f"TABLE_NAME|{schema}|{index}"

    def column_count_expression(self, schema: str, table: str) -> str:
        return f"COLUMN_COUNT|{schema}|{table}"

    def column_name_expression(
        self,
        schema: str,
        table: str,
        index: int,
    ) -> str:
        return f"COLUMN_NAME|{schema}|{table}|{index}"

    def row_count_expression(self, schema: str, table: str) -> str:
        return f"ROW_COUNT|{schema}|{table}"

    def cell_value_expression(
        self,
        schema: str,
        table: str,
        column: str,
        row_index: int,
        order_column: str | None = None,
    ) -> str:
        del order_column
        return f"CELL|{schema}|{table}|{column}|{row_index}"


def metadata_scalar(expression: str) -> int | str:
    schemas = sorted(DATA)
    if expression == "SCHEMA_COUNT":
        return len(schemas)
    if expression.startswith("SCHEMA_NAME|"):
        return schemas[int(expression.rsplit("|", 1)[1])]
    if expression.startswith("TABLE_COUNT|"):
        schema = expression.split("|", 1)[1]
        return len(DATA[schema])
    if expression.startswith("TABLE_NAME|"):
        _, schema, index = expression.split("|")
        return sorted(DATA[schema])[int(index)]
    if expression.startswith("COLUMN_COUNT|"):
        _, schema, table = expression.split("|")
        return len(DATA[schema][table]["columns"])
    if expression.startswith("COLUMN_NAME|"):
        _, schema, table, index = expression.split("|")
        return DATA[schema][table]["columns"][int(index)]
    if expression.startswith("ROW_COUNT|"):
        _, schema, table = expression.split("|")
        return len(DATA[schema][table]["rows"])
    if expression.startswith("CELL|"):
        _, schema, table, column, row = expression.split("|")
        return DATA[schema][table]["rows"][int(row)][column]
    raise AssertionError(expression)


class TurboDiscoveryTests(unittest.TestCase):
    def test_turbo_is_exact_and_uses_numeric_bit_planes(self) -> None:
        value = "A_9%"
        extractor, _client, conditions = make_string_extractor(
            value,
            mode="turbo",
        )
        self.assertEqual(extractor.extract_string(value), value)
        self.assertTrue(any("% 3" in item for item in conditions))
        self.assertTrue(any("& 64" in item for item in conditions))
        self.assertFalse(any("LIKE" in item.upper() for item in conditions))
        metrics = extractor.performance_snapshot()["inference"]
        self.assertGreater(metrics["checksum_probes"], 0)
        self.assertEqual(metrics["fallbacks"], 0)

    def test_turbo_dependency_depth_is_at_least_75_percent_faster(self) -> None:
        value = "A_9%"
        latency = 0.01
        adaptive, _client, _conditions = make_string_extractor(
            value,
            mode="adaptive",
            latency=latency,
        )
        started = time.monotonic()
        self.assertEqual(adaptive.extract_string(value), value)
        adaptive_elapsed = time.monotonic() - started

        turbo, _client, _conditions = make_string_extractor(
            value,
            mode="turbo",
            latency=latency,
        )
        started = time.monotonic()
        self.assertEqual(turbo.extract_string(value), value)
        turbo_elapsed = time.monotonic() - started

        speedup = 1 - turbo_elapsed / adaptive_elapsed
        self.assertGreaterEqual(
            speedup,
            0.75,
            (adaptive_elapsed, turbo_elapsed, speedup),
        )

    def test_map_finishes_smallest_schema_before_next_schema(self) -> None:
        client = Client()
        conditions: list[str] = []
        extractor = BlindExtractor(
            client,
            Oracle(),
            MetadataDialect(),
            ExtractorConfig(
                workers=64,
                max_length=64,
                max_items=20,
                min_char_code=32,
                max_char_code=126,
            ),
            inference_mode="turbo",
            parallel_characters=True,
        )

        def probe(condition: str) -> ProbeResult:
            with client.lock:
                client.requests_used += 1
                conditions.append(condition)
            matched = evaluate_condition(condition, metadata_scalar)
            return ProbeResult(
                matched,
                200 if matched else 404,
                1,
                0.0,
                "fake://",
            )

        extractor.probe_condition = probe  # type: ignore[method-assign]
        database = extractor.build_database_map(
            include_columns=True,
            include_data=True,
            max_rows=2,
            max_data_columns=4,
            max_value_length=32,
            max_data_bytes=1000,
            reveal_sensitive_values=True,
        )
        result = database.to_dict()
        self.assertEqual(
            [schema["name"] for schema in result["schemas"]],
            ["small", "large"],
        )
        self.assertEqual(result["summary"]["tables"], 3)
        self.assertEqual(result["summary"]["rows"], 3)

        small_conditions = [
            index
            for index, condition in enumerate(conditions)
            if any(
                marker in condition
                for marker in (
                    "TABLE_NAME|small",
                    "COLUMN_COUNT|small",
                    "COLUMN_NAME|small",
                    "ROW_COUNT|small",
                    "CELL|small",
                )
            )
        ]
        large_table_conditions = [
            index
            for index, condition in enumerate(conditions)
            if "TABLE_NAME|large" in condition
        ]
        self.assertTrue(small_conditions)
        self.assertTrue(large_table_conditions)
        self.assertLess(max(small_conditions), min(large_table_conditions))


if __name__ == "__main__":
    unittest.main()
