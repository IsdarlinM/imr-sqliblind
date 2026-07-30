from __future__ import annotations

import re
import threading
import time
import unittest

from blind_sqli.extractor import BlindExtractor, ExtractorConfig
from blind_sqli.models import ProbeResult


DATA = {
    "Main_DB": {
        "User_Profile": ["User_ID", "display_name", "ratio%"],
        "audit_log": ["event_id", "actor_IP"],
    },
    "audit%": {
        "Events_2026": ["ID", "event_type"],
    },
}


class Client:
    def __init__(self) -> None:
        self.requests_used = 0
        self.lock = threading.Lock()

    def performance_snapshot(self) -> dict[str, int]:
        return {"responses": self.requests_used}


class Oracle:
    def evaluate(self, response: object) -> bool:
        return bool(response)


class MetadataDialect:
    name = "metadata"

    def boolean_payload(self, condition: str) -> str:
        return condition

    def text_expression(self, expression: str) -> str:
        return expression

    def length_expression(self, expression: str) -> str:
        return f"LEN@{expression}"

    def char_code_expression(self, expression: str, position: int) -> str:
        return f"CODE@{position}@{expression}"

    def schema_count_expression(self) -> str:
        return "SCHEMA_COUNT"

    def schema_name_expression(self, index: int) -> str:
        return f"SCHEMA_NAME@{index}"

    def table_count_expression(self, schema: str) -> str:
        return f"TABLE_COUNT@{schema}"

    def table_name_expression(self, schema: str, index: int) -> str:
        return f"TABLE_NAME@{schema}@{index}"

    def column_count_expression(self, schema: str, table: str) -> str:
        return f"COLUMN_COUNT@{schema}@{table}"

    def column_name_expression(
        self,
        schema: str,
        table: str,
        index: int,
    ) -> str:
        return f"COLUMN_NAME@{schema}@{table}@{index}"


def scalar(expression: str) -> int | str:
    schemas = sorted(DATA)
    if expression == "SCHEMA_COUNT":
        return len(schemas)
    if expression.startswith("SCHEMA_NAME@"):
        return schemas[int(expression.split("@", 1)[1])]
    if expression.startswith("TABLE_COUNT@"):
        schema = expression.split("@", 1)[1]
        return len(DATA[schema])
    if expression.startswith("TABLE_NAME@"):
        _, schema, index = expression.split("@")
        return sorted(DATA[schema])[int(index)]
    if expression.startswith("COLUMN_COUNT@"):
        _, schema, table = expression.split("@")
        return len(DATA[schema][table])
    if expression.startswith("COLUMN_NAME@"):
        _, schema, table, index = expression.split("@")
        return DATA[schema][table][int(index)]
    raise AssertionError(expression)


def evaluate(condition: str) -> bool:
    length = re.fullmatch(r"COALESCE\(\(LEN@(.*)\), 0\) > (\d+)", condition)
    if length:
        return len(str(scalar(length.group(1)))) > int(length.group(2))

    integer = re.fullmatch(r"COALESCE\(\((.*)\), 0\) > (\d+)", condition)
    if integer:
        return int(scalar(integer.group(1))) > int(integer.group(2))

    found = re.search(
        r"CODE@(\d+)@(.*?)(?=\)|\sIN|\sBETWEEN|\s[>=<])",
        condition,
    )
    if not found:
        raise AssertionError(condition)
    position, expression = int(found.group(1)), found.group(2)
    value = str(scalar(expression))
    code = ord(value[position - 1])

    if " IN (" in condition:
        match = re.search(r" IN \(([^)]*)\)", condition)
        if match is None:
            raise AssertionError(condition)
        values = {int(item) for item in match.group(1).split(",")}
        return code in values

    between = re.search(r" BETWEEN (\d+) AND (\d+)", condition)
    if between:
        return int(between.group(1)) <= code <= int(between.group(2))

    bit = re.search(r"& (\d+)\) <> 0", condition)
    if bit:
        return bool(code & int(bit.group(1)))

    comparison = re.search(r"\)\s*([>=<]+)\s*(\d+)$", condition)
    if comparison is None:
        raise AssertionError(condition)
    operator, expected = comparison.group(1), int(comparison.group(2))
    return {
        ">": code > expected,
        "=": code == expected,
        "<": code < expected,
    }[operator]


class MapPipelineTests(unittest.TestCase):
    def test_full_map_is_exact_and_pipeline_overlaps_counts(self) -> None:
        client = Client()
        conditions: list[str] = []
        threads: set[str] = set()
        extractor = BlindExtractor(
            client,
            Oracle(),
            MetadataDialect(),
            ExtractorConfig(
                workers=8,
                max_length=64,
                max_items=20,
                min_char_code=32,
                max_char_code=126,
            ),
            inference_mode="adaptive",
            parallel_characters=True,
        )

        def probe(condition: str) -> ProbeResult:
            time.sleep(0.0005)
            with client.lock:
                client.requests_used += 1
                conditions.append(condition)
                threads.add(threading.current_thread().name)
            matched = evaluate(condition)
            return ProbeResult(
                matched,
                200 if matched else 404,
                1,
                0.0005,
                "fake://",
            )

        extractor.probe_condition = probe  # type: ignore[method-assign]
        database = extractor.build_database_map()
        result = database.to_dict()
        self.assertEqual(
            result["summary"],
            {
                "schemas": 2,
                "tables": 3,
                "columns": 7,
                "rows": 0,
                "cells": 0,
                "relationships": 10,
            },
        )
        actual = {
            schema["name"]: {
                table["name"]: table["columns"]
                for table in schema["tables"]
            }
            for schema in result["schemas"]
        }
        expected = {
            schema: {
                table: list(columns)
                for table, columns in tables.items()
            }
            for schema, tables in DATA.items()
        }
        self.assertEqual(actual, expected)

        character_conditions = [
            item for item in conditions if "CODE@" in item
        ]
        self.assertFalse(
            any("LIKE" in item.upper() for item in character_conditions)
        )
        worker_threads = {
            name for name in threads if "sqliblind-char" in name
        }
        self.assertGreaterEqual(len(worker_threads), 2)

        first_column_count = next(
            index
            for index, item in enumerate(conditions)
            if "COLUMN_COUNT@" in item
        )
        last_table_character = max(
            index
            for index, item in enumerate(conditions)
            if "CODE@" in item and "TABLE_NAME@" in item
        )
        self.assertLess(first_column_count, last_table_character)


if __name__ == "__main__":
    unittest.main()
