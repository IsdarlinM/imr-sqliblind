from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .productivity_common import (
    EXIT_INTERRUPTED,
    EXIT_OK,
    ProductivityError,
    TERMINAL_SCAN_STATUSES,
    json_print,
    snapshot_diff,
    workspace_database,
)
from .store import SessionStore


class ObserverSessionStore(SessionStore):
    """Open the workspace without changing active scan status."""

    def mark_running_as_interrupted(self) -> None:
        return


def _sessions_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sqliblind sessions")
    parser.add_argument("--workspace")
    sub = parser.add_subparsers(dest="action", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument("--json", action="store_true")
    show = sub.add_parser("show")
    show.add_argument("scan_id")
    show.add_argument("--json", action="store_true")
    diff = sub.add_parser("diff")
    diff.add_argument("left")
    diff.add_argument("right")
    diff.add_argument("--json", action="store_true")
    events = sub.add_parser("events")
    events.add_argument("scan_id")
    events.add_argument("--after", type=int, default=0)
    events.add_argument("--limit", type=int, default=500)
    events.add_argument("--follow", action="store_true")
    events.add_argument("--refresh", type=float, default=0.5)
    events.add_argument("--jsonl", action="store_true")
    return parser


def sessions_main(arguments: Sequence[str]) -> int:
    args = _sessions_parser().parse_args(arguments)
    store = ObserverSessionStore(workspace_database(args.workspace))
    try:
        if args.action == "list":
            scans = store.list_scans(limit=max(1, min(args.limit, 1000)))
            if args.json:
                json_print(scans)
            else:
                for scan in scans:
                    print(
                        f"{scan['id']}  {scan['status']:<12}  "
                        f"{scan['updated_at']}  "
                        f"{scan['config'].get('url', '')}"
                    )
            return EXIT_OK

        if args.action == "show":
            snapshot = store.snapshot(args.scan_id)
            if snapshot is None:
                raise ProductivityError(f"Unknown scan: {args.scan_id}")
            if args.json:
                json_print(snapshot)
            else:
                scan = snapshot["scan"]
                print(
                    f"{scan['id']} · {scan['status']} · "
                    f"{scan['updated_at']}"
                )
                print(
                    json.dumps(
                        snapshot.get("counts", {}),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                if scan.get("error"):
                    print(f"Error: {scan['error']}")
            return EXIT_OK

        if args.action == "diff":
            left = store.snapshot(args.left)
            right = store.snapshot(args.right)
            if left is None or right is None:
                raise ProductivityError("Both scan IDs must exist")
            result = snapshot_diff(left, right)
            if args.json:
                json_print(result)
            else:
                for title in ("added", "removed", "changed"):
                    print(f"{title.upper()} ({len(result[title])})")
                    for value in result[title]:
                        print(f"  {value}")
            return EXIT_OK

        if store.get_scan(args.scan_id) is None:
            raise ProductivityError(f"Unknown scan: {args.scan_id}")
        cursor = args.after
        while True:
            rows = store.get_events(
                args.scan_id,
                after=cursor,
                limit=max(1, min(args.limit, 5000)),
            )
            for item in rows:
                cursor = int(item["seq"])
                if args.jsonl:
                    print(
                        json.dumps(
                            item,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        flush=True,
                    )
                else:
                    print(
                        f"{item['seq']} {item['timestamp']} "
                        f"{item['event']} "
                        f"{json.dumps(item['payload'], ensure_ascii=False)}",
                        flush=True,
                    )
            if not args.follow:
                return EXIT_OK
            scan = store.get_scan(args.scan_id)
            if scan is None:
                raise ProductivityError(f"Unknown scan: {args.scan_id}")
            if scan["status"] in TERMINAL_SCAN_STATUSES and not rows:
                return EXIT_OK
            time.sleep(max(0.1, args.refresh))
    finally:
        store.close()


def _resume_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sqliblind resume")
    parser.add_argument("scan_id")
    parser.add_argument("--workspace")
    parser.add_argument(
        "--phase",
        choices=("map", "schemas", "tables", "columns", "rows"),
        default="map",
    )
    parser.add_argument("--schema")
    parser.add_argument("--table")
    parser.add_argument("--url")
    parser.add_argument("--header", action="append", default=[])
    parser.add_argument("--cookie", action="append", default=[])
    parser.add_argument("--proxy")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--delay", type=float)
    parser.add_argument("--max-requests", type=int)
    data = parser.add_mutually_exclusive_group()
    data.add_argument("--metadata-only", action="store_true")
    data.add_argument("--include-data", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _option(result: list[str], name: str, value: object | None) -> None:
    if value is not None and value != "":
        result.extend((name, str(value)))


def resume_arguments(
    config: dict[str, Any],
    args: argparse.Namespace,
) -> tuple[list[str], list[str]]:
    result: list[str] = []
    warnings: list[str] = []
    scalar = {
        "--url": args.url or config.get("url"),
        "--parameter": config.get("parameter"),
        "--url-template": config.get("url_template"),
        "--dialect": config.get("dialect"),
        "--oracle": config.get("oracle"),
        "--true-marker": config.get("true_marker"),
        "--true-regex": config.get("true_regex"),
        "--true-length": config.get("true_length"),
        "--length-tolerance": config.get("length_tolerance"),
        "--timeout": config.get("timeout"),
        "--retries": config.get("retries"),
        "--delay": (
            args.delay if args.delay is not None else config.get("delay")
        ),
        "--max-requests": (
            args.max_requests
            if args.max_requests is not None
            else config.get("max_requests")
        ),
        "--workers": (
            args.workers
            if args.workers is not None
            else config.get("workers")
        ),
        "--max-length": config.get("max_length"),
        "--max-items": config.get("max_items"),
        "--min-char-code": config.get("min_char_code"),
        "--max-char-code": config.get("max_char_code"),
        "--inference-mode": config.get("inference_mode"),
    }
    statuses = config.get("true_statuses")
    if statuses:
        scalar["--true-status"] = ",".join(str(item) for item in statuses)
    for name, value in scalar.items():
        _option(result, name, value)

    if config.get("insecure"):
        result.append("--insecure")
    if config.get("skip_calibration"):
        result.append("--skip-calibration")
    if not config.get("parallel_characters", True):
        result.append("--serial-characters")
    if not config.get("adaptive_confirmation", True):
        result.append("--no-adaptive-confirmation")
    if not config.get("adaptive_concurrency", True):
        result.append("--fixed-concurrency")

    for name, value in (config.get("headers") or {}).items():
        if value == "***":
            warnings.append(
                f"Sensitive header {name!r} must be supplied again."
            )
        else:
            result.extend(("--header", f"{name}:{value}"))
    for name, value in (config.get("cookies") or {}).items():
        if value == "***":
            warnings.append(f"Cookie {name!r} must be supplied again.")
        else:
            result.extend(("--cookie", f"{name}={value}"))
    if config.get("proxy") == "configured":
        warnings.append("The proxy URL must be supplied again.")
    elif config.get("proxy"):
        result.extend(("--proxy", str(config["proxy"])))

    for header in args.header:
        result.extend(("--header", header))
    for cookie in args.cookie:
        result.extend(("--cookie", cookie))
    if args.proxy:
        result.extend(("--proxy", args.proxy))

    if args.phase == "map":
        result.append("map")
        include_data = config.get("include_data", True)
        if args.metadata_only or (not args.include_data and not include_data):
            result.append("--metadata-only")
        for selector in config.get("data_tables") or []:
            result.extend(("--data-table", str(selector)))
        for option, key in (
            ("--max-rows", "max_rows"),
            ("--max-data-columns", "max_data_columns"),
            ("--max-value-length", "max_value_length"),
            ("--max-data-bytes", "max_data_bytes"),
        ):
            _option(result, option, config.get(key))
        if config.get("reveal_sensitive_values"):
            result.append("--show-sensitive-values")
    elif args.phase == "schemas":
        result.append("schemas")
    elif args.phase == "tables":
        if not args.schema:
            raise ProductivityError("--schema is required for tables")
        result.extend(("tables", "--schema", args.schema))
    elif args.phase == "columns":
        if not args.schema or not args.table:
            raise ProductivityError(
                "--schema and --table are required for columns"
            )
        result.extend(
            ("columns", "--schema", args.schema, "--table", args.table)
        )
    else:
        if not args.schema or not args.table:
            raise ProductivityError(
                "--schema and --table are required for rows"
            )
        result.extend(
            ("rows", "--schema", args.schema, "--table", args.table)
        )
    return result, warnings


def resume_main(
    arguments: Sequence[str],
    cli_main: Callable[[Sequence[str] | None], int],
) -> int:
    args = _resume_parser().parse_args(arguments)
    store = ObserverSessionStore(workspace_database(args.workspace))
    try:
        scan = store.get_scan(args.scan_id)
    finally:
        store.close()
    if scan is None:
        raise ProductivityError(f"Unknown scan: {args.scan_id}")
    command, warnings = resume_arguments(scan["config"], args)
    for warning in warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    print(
        "Resume starts a new verified run from stored non-secret settings; "
        "it does not splice incomplete values.",
        file=sys.stderr,
    )
    if args.dry_run:
        print(" ".join(command))
        return EXIT_OK
    return int(cli_main(command))


def _tui_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sqliblind tui")
    parser.add_argument("--workspace")
    parser.add_argument("--scan-id")
    parser.add_argument("--refresh", type=float, default=0.5)
    parser.add_argument("--once", action="store_true")
    return parser


def _clip(value: object, width: int) -> str:
    text = str(value).replace("\n", " ")
    return text if len(text) <= width else text[: max(1, width - 1)] + "…"


def _render_tui(snapshot: dict[str, Any], width: int) -> str:
    scan = snapshot["scan"]
    counts = snapshot.get("counts", {})
    activities = [
        item
        for item in snapshot.get("activities", [])
        if item.get("status") == "running"
    ]
    lines = [
        f"imr-sqliblind TUI · {_clip(scan['id'], 12)} · {scan['status']}",
        "─" * min(width, 110),
        "Entities  "
        + "  ".join(
            f"{kind}:{counts.get(kind, 0)}"
            for kind in ("schema", "table", "column", "row", "cell")
        ),
        (
            f"Requests:{scan.get('stats', {}).get('requests', 0)}  "
            f"Updated:{scan.get('updated_at', '')}"
        ),
        "",
        "CURRENT ACTIVITY",
    ]
    if not activities:
        lines.append("  No active workers.")
    for activity in activities[:12]:
        lines.append(
            "  "
            + _clip(
                f"{activity.get('worker')} · "
                f"{activity.get('operation')} · "
                f"{activity.get('target')} · "
                f"{activity.get('detail')}",
                max(20, width - 2),
            )
        )
    lines.extend(("", "LATEST EVENTS"))
    for event in snapshot.get("events", [])[-10:]:
        lines.append(
            "  "
            + _clip(
                f"{event.get('seq')} {event.get('event')} "
                f"{json.dumps(event.get('payload', {}), ensure_ascii=False)}",
                max(20, width - 2),
            )
        )
    return "\n".join(lines)


def tui_main(arguments: Sequence[str]) -> int:
    args = _tui_parser().parse_args(arguments)
    store = ObserverSessionStore(workspace_database(args.workspace))
    try:
        scan_id = args.scan_id
        if not scan_id:
            scans = store.list_scans(limit=1)
            if not scans:
                raise ProductivityError("No saved sessions")
            scan_id = scans[0]["id"]
        while True:
            snapshot = store.snapshot(scan_id)
            if snapshot is None:
                raise ProductivityError(f"Unknown scan: {scan_id}")
            snapshot["events"] = store.get_events(
                scan_id,
                after=0,
                limit=5000,
            )
            if sys.stdout.isatty():
                print("\x1b[2J\x1b[H", end="")
            width = shutil.get_terminal_size((100, 30)).columns
            print(_render_tui(snapshot, width), flush=True)
            if (
                args.once
                or snapshot["scan"]["status"] in TERMINAL_SCAN_STATUSES
            ):
                return EXIT_OK
            time.sleep(max(0.1, args.refresh))
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    finally:
        store.close()
