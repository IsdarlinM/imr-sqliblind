#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from blind_sqli.extractor import BlindExtractor, ExtractorConfig  # noqa: E402
from blind_sqli.models import ProbeResult  # noqa: E402


class Client:
    def __init__(self) -> None:
        self.requests_used = 0
        self.lock = threading.Lock()

    def performance_snapshot(self) -> dict[str, int]:
        return {"responses": self.requests_used}


class Oracle:
    def evaluate(self, response: object) -> bool:
        return bool(response)


class Dialect:
    name = "benchmark"

    def boolean_payload(self, condition: str) -> str:
        return condition

    def text_expression(self, expression: str) -> str:
        return f"TEXT[{expression}]"

    def length_expression(self, expression: str) -> str:
        return f"LEN[{expression}]"

    def char_code_expression(self, expression: str, position: int) -> str:
        return f"CODE[{position}][{expression}]"


def numeric_value(token: str, value: str) -> int:
    length = re.fullmatch(r"LEN\[(.*)]", token)
    if length:
        return len(length.group(1))
    code = re.fullmatch(r"CODE\[(\d+)]\[(.*)]", token)
    if code:
        position = int(code.group(1))
        source = code.group(2)
        return ord(source[position - 1]) if position <= len(source) else 0
    raise RuntimeError(token)


def evaluate(condition: str, value: str) -> bool:
    text = re.fullmatch(r"\(TEXT\[(.*)]\) = '(.*)'", condition)
    if text:
        expected = text.group(2).replace("''", "'")
        return text.group(1) == expected

    wrapped = re.search(r"COALESCE\(\((.*?)\), 0\)", condition)
    if wrapped:
        number = numeric_value(wrapped.group(1), value)
    else:
        code = re.search(r"CODE\[(\d+)]\[(.*?)]", condition)
        if not code:
            raise RuntimeError(condition)
        number = numeric_value(
            f"CODE[{code.group(1)}][{code.group(2)}]",
            value,
        )

    if " IN (" in condition:
        match = re.search(r" IN \(([^)]*)\)", condition)
        if match is None:
            raise RuntimeError(condition)
        values = {int(item) for item in match.group(1).split(",")}
        return number in values

    between = re.search(r" BETWEEN (\d+) AND (\d+)", condition)
    if between:
        return int(between.group(1)) <= number <= int(between.group(2))

    bit = re.search(r"& (\d+)\) <> 0", condition)
    if bit:
        return bool(number & int(bit.group(1)))

    residue = re.search(r"% 3\) = (\d+)", condition)
    if residue:
        return number % 3 == int(residue.group(1))

    compare = re.search(r"\)?\s*([>=<]+)\s*(\d+)$", condition)
    if compare is None:
        raise RuntimeError(condition)
    operator, expected = compare.group(1), int(compare.group(2))
    return {
        ">": number > expected,
        "=": number == expected,
        "<": number < expected,
    }[operator]


def run(
    value: str,
    mode: str,
    workers: int,
    latency: float,
) -> dict[str, object]:
    client = Client()
    extractor = BlindExtractor(
        client,
        Oracle(),
        Dialect(),
        ExtractorConfig(
            workers=workers,
            max_length=128,
            min_char_code=32,
            max_char_code=126,
        ),
        inference_mode=mode,
        parallel_characters=True,
    )

    def probe(condition: str) -> ProbeResult:
        time.sleep(latency)
        with client.lock:
            client.requests_used += 1
        matched = evaluate(condition, value)
        return ProbeResult(
            matched,
            200 if matched else 404,
            1,
            latency,
            "benchmark://",
        )

    extractor.probe_condition = probe  # type: ignore[method-assign]
    started = time.monotonic()
    result = extractor.extract_string(value)
    elapsed = time.monotonic() - started
    if result != value:
        raise RuntimeError(f"unexpected result: {result!r}")
    return {
        "mode": mode,
        "workers": workers,
        "requests": client.requests_used,
        "elapsed_seconds": round(elapsed, 4),
        "requests_per_character": round(client.requests_used / len(value), 2),
        "performance": extractor.performance_snapshot()["inference"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare exact inference modes with a deterministic oracle."
    )
    parser.add_argument("--value", default="A_9%")
    parser.add_argument("--latency", type=float, default=0.01)
    parser.add_argument("--workers", type=int, default=64)
    parser.add_argument(
        "--require-speedup",
        type=float,
        default=0.75,
        help="Fail when turbo is not this much faster than adaptive",
    )
    args = parser.parse_args()

    if not args.value:
        parser.error("--value cannot be empty")
    if args.latency < 0:
        parser.error("--latency cannot be negative")
    if not 1 <= args.workers <= 64:
        parser.error("--workers must be between 1 and 64")
    if not 0 <= args.require_speedup < 1:
        parser.error("--require-speedup must be between 0 and 1")

    legacy_requests = 9 + 11 * len(args.value)
    results: list[dict[str, object]] = [
        {
            "mode": "legacy-estimate",
            "workers": 1,
            "requests": legacy_requests,
            "elapsed_seconds": round(legacy_requests * args.latency, 4),
            "requests_per_character": round(
                legacy_requests / len(args.value),
                2,
            ),
        }
    ]
    measured: dict[str, dict[str, object]] = {}
    for mode in ("binary", "adaptive", "bitwise", "turbo"):
        result = run(args.value, mode, args.workers, args.latency)
        measured[mode] = result
        results.append(result)

    adaptive_elapsed = float(measured["adaptive"]["elapsed_seconds"])
    turbo_elapsed = float(measured["turbo"]["elapsed_seconds"])
    speedup = 1 - turbo_elapsed / adaptive_elapsed
    document = {
        "value": args.value,
        "length": len(args.value),
        "probe_latency": args.latency,
        "workers": args.workers,
        "turbo_speedup_vs_adaptive": round(speedup, 4),
        "required_speedup": args.require_speedup,
        "results": results,
    }
    print(json.dumps(document, indent=2))
    return 0 if speedup >= args.require_speedup else 1


if __name__ == "__main__":
    raise SystemExit(main())
