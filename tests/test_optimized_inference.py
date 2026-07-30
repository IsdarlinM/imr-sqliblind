from __future__ import annotations

import re
import threading
import time
import unittest

from blind_sqli.extractor import BlindExtractor, ExtractorConfig
from blind_sqli.models import ProbeResult


class FakeClient:
    def __init__(self) -> None:
        self.requests_used = 0
        self.lock = threading.Lock()

    def performance_snapshot(self) -> dict[str, int]:
        return {"responses": self.requests_used, "adaptive_limit": 8}


class FakeOracle:
    def evaluate(self, response: object) -> bool:
        return bool(response)


class FakeDialect:
    name = "fake"

    def boolean_payload(self, condition: str) -> str:
        return condition

    def length_expression(self, expression: str) -> str:
        return f"LEN[{expression}]"

    def char_code_expression(self, expression: str, position: int) -> str:
        return f"CODE[{expression}|{position}]"


def evaluate(condition: str, value: str) -> bool:
    condition = condition.strip()
    match = re.fullmatch(r"COALESCE\(\(LEN\[(.*)]\), 0\) > (\d+)", condition)
    if match:
        return len(match.group(1)) > int(match.group(2))

    code_match = re.search(r"CODE\[(.*)\|(\d+)]", condition)
    if not code_match:
        if condition == "1=1":
            return True
        if condition == "1=0":
            return False
        raise AssertionError(f"Unsupported condition: {condition}")
    source = code_match.group(1)
    position = int(code_match.group(2))
    code = ord(source[position - 1]) if 1 <= position <= len(source) else 0

    if " IN (" in condition:
        match = re.search(r" IN \(([^)]*)\)", condition)
        if match is None:
            raise AssertionError(condition)
        numbers = {int(item) for item in match.group(1).split(",")}
        return code in numbers

    between = re.search(r" BETWEEN (\d+) AND (\d+)", condition)
    if between:
        return int(between.group(1)) <= code <= int(between.group(2))

    bitwise = re.search(r"& (\d+)\) <> 0", condition)
    if bitwise:
        return (code & int(bitwise.group(1))) != 0

    comparison = re.search(r"\)\s*([>=<]+)\s*(\d+)$", condition)
    if comparison:
        operator, expected = comparison.group(1), int(comparison.group(2))
        return {
            ">": code > expected,
            "=": code == expected,
            "<": code < expected,
        }[operator]
    raise AssertionError(f"Unsupported condition: {condition}")


def make_extractor(
    value: str,
    *,
    mode: str = "adaptive",
    workers: int = 8,
    parallel: bool = True,
    latency: float = 0.0,
) -> tuple[BlindExtractor, FakeClient, list[str], set[str]]:
    client = FakeClient()
    conditions: list[str] = []
    threads: set[str] = set()
    extractor = BlindExtractor(
        client,
        FakeOracle(),
        FakeDialect(),
        ExtractorConfig(
            workers=workers,
            max_length=128,
            max_items=128,
            min_char_code=32,
            max_char_code=126,
        ),
        inference_mode=mode,
        parallel_characters=parallel,
    )

    def probe(condition: str) -> ProbeResult:
        if latency:
            time.sleep(latency)
        with client.lock:
            client.requests_used += 1
            conditions.append(condition)
            threads.add(threading.current_thread().name)
        matched = evaluate(condition, value)
        return ProbeResult(
            matched,
            200 if matched else 404,
            1,
            latency,
            "fake://",
        )

    extractor.probe_condition = probe  # type: ignore[method-assign]
    return extractor, client, conditions, threads


class OptimizedInferenceTests(unittest.TestCase):
    def test_percent_and_underscore_are_numeric_not_like_patterns(self) -> None:
        extractor, _, conditions, _ = make_extractor(
            "User_50%",
            mode="adaptive",
        )
        self.assertEqual(extractor.extract_string("User_50%"), "User_50%")
        character_conditions = [
            item for item in conditions if "CODE[" in item
        ]
        self.assertTrue(character_conditions)
        self.assertFalse(
            any("LIKE" in item.upper() for item in character_conditions)
        )
        self.assertTrue(any("95" in item for item in character_conditions))
        self.assertTrue(any("37" in item for item in character_conditions))

    def test_sentinel_length_search_needs_at_most_eight_probes(self) -> None:
        extractor, client, _, _ = make_extractor(
            "abcdefghijkl",
            mode="binary",
        )
        value, truncated = extractor.infer_integer_capped(
            "LEN[abcdefghijkl]",
            128,
        )
        self.assertEqual(value, 12)
        self.assertFalse(truncated)
        self.assertLessEqual(client.requests_used, 8)

    def test_fast_binary_reduces_normal_character_cost(self) -> None:
        extractor, client, _, _ = make_extractor(
            "User_50%",
            mode="binary",
        )
        self.assertEqual(extractor.extract_string("User_50%"), "User_50%")
        legacy_upper_bound = 9 + 11 * len("User_50%")
        self.assertLess(client.requests_used, legacy_upper_bound)
        self.assertLessEqual(client.requests_used, 8 + 8 * len("User_50%"))

    def test_global_character_scheduler_uses_multiple_workers(self) -> None:
        extractor, _, _, threads = make_extractor(
            "parallel_positions",
            mode="binary",
            workers=8,
            latency=0.001,
        )
        self.assertEqual(
            extractor.extract_string("parallel_positions"),
            "parallel_positions",
        )
        worker_threads = {
            name for name in threads if "sqliblind-char" in name
        }
        self.assertGreaterEqual(len(worker_threads), 2)

    def test_bitwise_mode_is_parallel_and_exact(self) -> None:
        value = "Ab_9%"
        parallel, _, conditions, threads = make_extractor(
            value,
            mode="bitwise",
            workers=8,
            latency=0.004,
        )
        started = time.monotonic()
        self.assertEqual(parallel.extract_string(value), value)
        elapsed_parallel = time.monotonic() - started

        serial, _, _, _ = make_extractor(
            value,
            mode="bitwise",
            workers=1,
            parallel=True,
            latency=0.004,
        )
        started = time.monotonic()
        self.assertEqual(serial.extract_string(value), value)
        elapsed_serial = time.monotonic() - started

        self.assertLess(elapsed_parallel, elapsed_serial * 0.55)
        self.assertFalse(
            any(
                "LIKE" in item.upper()
                for item in conditions
                if "CODE[" in item
            )
        )
        bit_threads = {
            name for name in threads if "sqliblind-bit" in name
        }
        self.assertGreaterEqual(len(bit_threads), 2)


if __name__ == "__main__":
    unittest.main()
