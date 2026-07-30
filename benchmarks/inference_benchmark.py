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

    def length_expression(self, expression: str) -> str:
        return f"LEN[{expression}]"

    def char_code_expression(self, expression: str, position: int) -> str:
        return f"CODE[{expression}|{position}]"


def evaluate(condition: str, value: str) -> bool:
    length = re.fullmatch(r"COALESCE\(\(LEN\[(.*)]\), 0\) > (\d+)", condition)
    if length:
        return len(length.group(1)) > int(length.group(2))

    found = re.search(r"CODE\[(.*)\|(\d+)]", condition)
    if not found:
        raise RuntimeError(condition)
    source, position = found.group(1), int(found.group(2))
    code = ord(source[position - 1])

    if " IN (" in condition:
        match = re.search(r" IN \(([^)]*)\)", condition)
        if match is None:
            raise RuntimeError(condition)
        values = {int(item) for item in match.group(1).split(",")}
        return code in values

    between = re.search(r" BETWEEN (\d+) AND (\d+)", condition)
    if between:
        return int(between.group(1)) <= code <= int(between.group(2))

    bit = re.search(r"& (\d+)\) <> 0", condition)
    if bit:
        return bool(code & int(bit.group(1)))

    compare = re.search(r"\)\s*([>=<]+)\s*(\d+)$", condition)
    if compare is None:
        raise RuntimeError(condition)
    operator, expected = compare.group(1), int(compare.group(2))
    return {
        ">": code > expected,
        "=": code == expected,
        "<": code < expected,
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
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare optimized inference modes with a deterministic oracle."
    )
    parser.add_argument("--value", default="User_Profile_50%_2026")
    parser.add_argument("--latency", type=float, default=0.005)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    if not args.value:
        parser.error("--value cannot be empty")
    if args.latency < 0:
        parser.error("--latency cannot be negative")
    if args.workers < 1:
        parser.error("--workers must be positive")

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
    for mode in ("binary", "adaptive", "bitwise"):
        for workers in (1, args.workers):
            results.append(run(args.value, mode, workers, args.latency))

    print(
        json.dumps(
            {
                "value": args.value,
                "length": len(args.value),
                "probe_latency": args.latency,
                "results": results,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
