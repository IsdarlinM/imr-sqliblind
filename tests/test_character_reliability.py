from __future__ import annotations

import re
import unittest
from types import SimpleNamespace

from blind_sqli.extractor import BlindExtractor
from blind_sqli.models import ProbeResult


class FakeDialect:
    def length_expression(self, expression: str) -> str:
        del expression
        return "length"

    def char_code_expression(self, expression: str, position: int) -> str:
        del expression, position
        return "character-code"


class FakeControl:
    def checkpoint(self) -> None:
        return None


class UnstableCharacterExtractor(BlindExtractor):
    def __init__(self, mode: str) -> None:
        self.config = SimpleNamespace(
            min_char_code=32,
            max_char_code=126,
            max_length=16,
        )
        self.dialect = FakeDialect()
        self.control = FakeControl()
        self.mode = mode
        self.binary_glitch_used = False
        self.confirmation_glitch_used = False
        self.emitted_events: list[str] = []

    def _current(self) -> dict[str, object]:
        return {}

    def _activity_update(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def _emit(self, event_type: str, **payload: object) -> None:
        del payload
        self.emitted_events.append(event_type)

    def infer_integer_capped(self, expression: str, maximum: int) -> tuple[int, bool]:
        del expression, maximum
        return 1, False

    def probe_condition(self, condition: str) -> ProbeResult:
        match = re.search(r"([<>=])\s*(\d+)\s*$", condition)
        if match is None:
            raise AssertionError(f"Unexpected condition: {condition}")
        operator, raw_value = match.groups()
        value = int(raw_value)
        actual = ord("A")

        if (
            self.mode == "bad-binary-branch"
            and operator == ">"
            and value == 64
            and not self.binary_glitch_used
        ):
            self.binary_glitch_used = True
            matched = False
        elif (
            self.mode == "transient-confirmation-false"
            and operator == "="
            and value == actual
            and not self.confirmation_glitch_used
        ):
            self.confirmation_glitch_used = True
            matched = False
        else:
            matched = {
                "<": actual < value,
                ">": actual > value,
                "=": actual == value,
            }[operator]

        return ProbeResult(
            matched=matched,
            status_code=200 if matched else 404,
            body_length=100 if matched else 20,
            elapsed_seconds=0.01,
            final_url="https://lab.example/fetch",
        )


class CharacterReliabilityTests(unittest.TestCase):
    def test_restarts_binary_search_after_wrong_candidate(self) -> None:
        extractor = UnstableCharacterExtractor("bad-binary-branch")

        self.assertEqual(extractor.extract_string("SELECT value"), "A")
        self.assertIn("inference.retry", extractor.emitted_events)
        self.assertIn("inference.recovered", extractor.emitted_events)

    def test_two_of_three_confirmation_recovers_transient_false(self) -> None:
        extractor = UnstableCharacterExtractor("transient-confirmation-false")

        self.assertEqual(extractor.extract_string("SELECT value"), "A")
        self.assertNotIn("inference.retry", extractor.emitted_events)


if __name__ == "__main__":
    unittest.main()
