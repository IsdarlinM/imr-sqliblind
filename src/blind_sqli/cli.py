from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from . import __version__
from .client import HttpClient, HttpConfig
from .dialects import get_dialect
from .events import EventCallback
from .extractor import BlindExtractor, ExtractorConfig, INFERENCE_MODES
from .graph import FORMATS, render_database_map, write_report
from .models import DatabaseMap, Table
from .oracle import ResponseOracle
from .progress import ActivityMonitor

BASE_URL = "https://08d9880a384777322d0e2df7db7e5215.ctf.hacker101.com/fetch"
_MAP_COMMANDS = {"map", "graph", "schema-map"}


def _parse_key_value(
    values: list[str],
    separator: str,
    option: str,
) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        if separator not in value:
            raise ValueError(
                f"{option} expects KEY{separator}VALUE: {value!r}"
            )
        key, item = value.split(separator, 1)
        key = key.strip()
        if not key:
            raise ValueError(f"{option} contains an empty key")
        parsed[key] = item.strip()
    return parsed


def _parse_statuses(value: str) -> set[int]:
    try:
        statuses = {
            int(item.strip())
            for item in value.split(",")
            if item.strip()
        }
    except ValueError as exc:
        raise ValueError("--true-status must contain integers") from exc
    if not statuses or any(status < 100 or status > 599 for status in statuses):
        raise ValueError("--true-status must contain valid HTTP status codes")
    return statuses


def _add_data_options(
    parser: argparse.ArgumentParser,
    *,
    table_required: bool,
) -> None:
    if table_required:
        parser.add_argument("--schema", required=True)
        parser.add_argument("--table", required=True)
    else:
        parser.add_argument(
            "--include-data",
            action="store_true",
            help="Extract bounded row values from explicitly selected tables",
        )
        parser.add_argument(
            "--data-table",
            action="append",
            default=[],
            metavar="SCHEMA.TABLE",
        )
    parser.add_argument("--max-rows", type=int, default=5)
    parser.add_argument("--max-data-columns", type=int, default=10)
    parser.add_argument("--max-value-length", type=int, default=128)
    parser.add_argument("--max-data-bytes", type=int, default=10_000)
    parser.add_argument("--show-sensitive-values", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sqliblind",
        description=(
            "Bounded blind SQLi helper for authorized laboratories and CTFs."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument("--url", default=BASE_URL)
    parser.add_argument("--parameter", default="id")
    parser.add_argument(
        "--url-template",
        help="URL containing {{PAYLOAD}} or [TO_REPLACE]",
    )
    parser.add_argument(
        "--dialect",
        choices=("mysql", "sqlite"),
        default="mysql",
    )
    parser.add_argument(
        "--oracle",
        choices=("status", "marker", "regex", "length"),
        default="status",
    )
    parser.add_argument("--true-status", default="200")
    parser.add_argument("--true-marker")
    parser.add_argument("--true-regex")
    parser.add_argument("--true-length", type=int)
    parser.add_argument("--length-tolerance", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument(
        "--delay",
        type=float,
        default=0.1,
        help="Global delay between request starts",
    )
    parser.add_argument("--max-requests", type=int, default=5000)
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Concurrent probe and character workers (1-64)",
    )
    parser.add_argument("--max-length", type=int, default=128)
    parser.add_argument("--max-items", type=int, default=128)
    parser.add_argument("--min-char-code", type=int, default=32)
    parser.add_argument("--max-char-code", type=int, default=126)
    parser.add_argument(
        "--inference-mode",
        choices=tuple(sorted(INFERENCE_MODES)),
        default="adaptive",
        help=(
            "adaptive uses weighted numeric partitions; bitwise parallelizes "
            "independent code bits"
        ),
    )
    parser.add_argument(
        "--serial-characters",
        action="store_true",
        help="Disable position-level scheduling",
    )
    parser.add_argument(
        "--no-adaptive-confirmation",
        action="store_true",
        help=(
            "Skip the second/third equality probes before robust fallback"
        ),
    )
    parser.add_argument(
        "--fixed-concurrency",
        action="store_true",
        help="Disable AIMD concurrency adjustment",
    )
    parser.add_argument("--header", action="append", default=[], metavar="KEY:VALUE")
    parser.add_argument("--cookie", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--proxy")
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--skip-calibration", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument(
        "--progress",
        choices=("auto", "live", "plain", "off"),
        default="auto",
    )

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("schemas", help="Enumerate database schemas")

    tables = subparsers.add_parser(
        "tables",
        help="Enumerate tables in one schema",
    )
    tables.add_argument("--schema", required=True)

    columns = subparsers.add_parser(
        "columns",
        help="Enumerate columns in one table",
    )
    columns.add_argument("--schema", required=True)
    columns.add_argument("--table", required=True)

    extract = subparsers.add_parser(
        "extract",
        help="Extract one scalar SQL expression",
    )
    extract.add_argument("--expression", required=True)

    probe = subparsers.add_parser(
        "probe",
        help="Evaluate one boolean SQL condition",
    )
    probe.add_argument("--condition", required=True)

    rows = subparsers.add_parser(
        "rows",
        help="Extract bounded rows from one table",
    )
    _add_data_options(rows, table_required=True)

    graph = subparsers.add_parser(
        "map",
        aliases=("graph", "schema-map"),
        help="Map schemas, tables and columns",
    )
    graph.add_argument(
        "--format",
        choices=tuple(sorted(FORMATS)),
        default="tree",
    )
    graph.add_argument("--output")
    graph.add_argument("--ascii", action="store_true", dest="ascii_only")
    graph.add_argument("--no-columns", action="store_true")
    graph.add_argument("--title", default="imr-sqliblind schema map")
    _add_data_options(graph, table_required=False)

    web = subparsers.add_parser("web", help="Start the realtime web console")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8088)
    web.add_argument("--workspace")
    web.add_argument("--allow-remote", action="store_true")
    web.add_argument("--token")
    web.add_argument("--ssl-certfile")
    web.add_argument("--ssl-keyfile")
    web.add_argument("--no-open-browser", action="store_true")
    return parser


def _build_extractor(
    args: argparse.Namespace,
    event_callback: EventCallback | None = None,
) -> BlindExtractor:
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
            headers=_parse_key_value(args.header, ":", "--header"),
            cookies=_parse_key_value(args.cookie, "=", "--cookie"),
            proxy=args.proxy,
            adaptive_concurrency=not args.fixed_concurrency,
            min_concurrency=1,
            max_concurrency=args.workers,
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
        event_callback=event_callback,
        inference_mode=args.inference_mode,
        parallel_characters=not args.serial_characters,
        adaptive_confirmation=not args.no_adaptive_confirmation,
    )


def _statistics(extractor: BlindExtractor, workers: int) -> str:
    snapshot = extractor.performance_snapshot()
    return (
        f"Requests: {extractor.client.requests_used} | "
        f"Elapsed: {round(extractor.elapsed_seconds, 3)}s | "
        f"Workers: {workers} | Mode: {snapshot['inference_mode']}"
    )


def _result_document(
    data: object,
    extractor: BlindExtractor,
) -> dict[str, object]:
    return {
        "result": data,
        "requests": extractor.client.requests_used,
        "elapsed_seconds": round(extractor.elapsed_seconds, 3),
        "performance": extractor.performance_snapshot(),
    }


def _emit(
    args: argparse.Namespace,
    data: object,
    extractor: BlindExtractor,
) -> None:
    result = _result_document(data, extractor)
    if args.json_output:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    if isinstance(data, list):
        for index, value in enumerate(data, 1):
            print(f"[{index}] {value}")
    elif isinstance(data, dict):
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(data)
    print(f"\n{_statistics(extractor, args.workers)}")


def _emit_map(
    args: argparse.Namespace,
    database: DatabaseMap,
    extractor: BlindExtractor,
) -> None:
    if args.json_output:
        content = json.dumps(
            _result_document(database.to_dict(), extractor),
            indent=2,
            ensure_ascii=False,
        )
        if args.output:
            path = write_report(args.output, content, default_suffix=".json")
            print(f"Report written: {path}")
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
    if output is None and args.format == "html":
        output = "imr-sqliblind-schema-map.html"
    if output:
        suffix = {"html": ".html", "mermaid": ".mmd"}.get(
            args.format,
            ".txt",
        )
        path = write_report(output, content, default_suffix=suffix)
        print(f"Report written: {path}")
    else:
        print(content)
    print(f"\n{_statistics(extractor, args.workers)}")


def _validate_data_limits(args: argparse.Namespace) -> None:
    if not 1 <= args.max_rows <= 25:
        raise ValueError("--max-rows must be between 1 and 25")
    if not 1 <= args.max_data_columns <= 20:
        raise ValueError("--max-data-columns must be between 1 and 20")
    if not 1 <= args.max_value_length <= 512:
        raise ValueError("--max-value-length must be between 1 and 512")
    if not 1 <= args.max_data_bytes <= 50_000:
        raise ValueError("--max-data-bytes must be between 1 and 50000")


def _run_rows(
    args: argparse.Namespace,
    extractor: BlindExtractor,
) -> dict[str, object]:
    _validate_data_limits(args)
    table = Table(
        args.table,
        extractor.enumerate_columns(args.schema, args.table),
    )
    count, truncated, bytes_used = extractor.extract_table_rows(
        args.schema,
        table,
        max_rows=args.max_rows,
        max_columns=args.max_data_columns,
        max_value_length=args.max_value_length,
        max_data_bytes=args.max_data_bytes,
        reveal_sensitive_values=args.show_sensitive_values,
    )
    return {
        **table.to_dict(),
        "schema": args.schema,
        "rows_extracted": count,
        "truncated": truncated,
        "data_bytes": bytes_used,
    }


def _run_map(
    args: argparse.Namespace,
    extractor: BlindExtractor,
) -> DatabaseMap:
    _validate_data_limits(args)
    if args.include_data and not args.data_table:
        raise ValueError(
            "--include-data requires at least one --data-table SCHEMA.TABLE"
        )
    return extractor.build_database_map(
        include_columns=not args.no_columns,
        include_data=args.include_data,
        data_tables=set(args.data_table),
        max_rows=args.max_rows,
        max_data_columns=args.max_data_columns,
        max_value_length=args.max_value_length,
        max_data_bytes=args.max_data_bytes,
        reveal_sensitive_values=args.show_sensitive_values,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        args.command = "schemas"

    try:
        if args.command == "web":
            from .web import launch_web_server

            launch_web_server(
                host=args.host,
                port=args.port,
                workspace=args.workspace,
                allow_remote=args.allow_remote,
                token=args.token,
                ssl_certfile=args.ssl_certfile,
                ssl_keyfile=args.ssl_keyfile,
                open_browser=not args.no_open_browser,
            )
            return 0

        progress_mode = "off" if args.json_output else args.progress
        database_result: DatabaseMap | None = None
        data_result: object | None = None
        calibration_message: str | None = None

        with ActivityMonitor(
            mode=progress_mode,
            workers=args.workers,
        ) as monitor:
            callback = monitor if monitor.enabled else None
            extractor = _build_extractor(args, event_callback=callback)
            if not args.skip_calibration:
                true_result, false_result = extractor.calibrate()
                calibration_message = (
                    "Oracle calibrated: "
                    f"TRUE={true_result.status_code}/{true_result.body_length}B, "
                    f"FALSE={false_result.status_code}/{false_result.body_length}B"
                )

            if args.command == "schemas":
                data_result = extractor.enumerate_schemas()
            elif args.command == "tables":
                data_result = extractor.enumerate_tables(args.schema)
            elif args.command == "columns":
                data_result = extractor.enumerate_columns(args.schema, args.table)
            elif args.command == "extract":
                data_result = extractor.extract_string(args.expression)
            elif args.command == "probe":
                probe = extractor.probe_condition(args.condition)
                data_result = {
                    "matched": probe.matched,
                    "status_code": probe.status_code,
                    "body_length": probe.body_length,
                    "elapsed_seconds": round(probe.elapsed_seconds, 3),
                    "url": probe.final_url,
                }
            elif args.command == "rows":
                data_result = _run_rows(args, extractor)
            elif args.command in _MAP_COMMANDS:
                database_result = _run_map(args, extractor)
            else:
                parser.error(f"Unknown command: {args.command}")

        if calibration_message and not args.json_output:
            print(calibration_message)
        if database_result is not None:
            _emit_map(args, database_result, extractor)
        else:
            _emit(args, data_result, extractor)
        return 0
    except KeyboardInterrupt:
        print("Interrupted by user.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
