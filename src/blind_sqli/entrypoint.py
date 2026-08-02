from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import TextIO

from . import __version__
from .cli import build_parser, main as cli_main
from .productivity_cli import (
    PRODUCTIVITY_COMMANDS,
    ProductivityError,
    prepare_profile_arguments,
    productivity_main,
    run_jsonl_cli,
)
from .service_cli import SERVICE_COMMANDS, service_main
from .terminal import (
    TerminalOptionError,
    extract_terminal_options,
    is_machine_output,
    terminal_session,
)
from .updater import update_main

_ADDITIONAL_HELP = """
additional commands:
  start                 Start the authenticated web console in the background
  stop                  Stop the background web console
  restart               Restart the background web console
  status                Show service status, PID, URL, and log path
  users                 Create, expire, disable, delete, and audit users
  config                Initialize or edit service defaults
  update                Check for and install updates from the official repository
  doctor                Validate Python, PATH, TLS, SQLite and workspace readiness
  profiles              Save reusable non-secret CLI argument profiles
  preview               Parse and show the effective scan configuration safely
  sessions              List, inspect, diff and stream persisted sessions
  resume                Start a verified retry from a stored session configuration
  tui                   Monitor a persisted scan in a compact terminal workspace
  completion            Generate Bash, Zsh or PowerShell completion

productivity examples:
  sqliblind doctor
  sqliblind profiles save fast -- --workers 32 map --metadata-only
  sqliblind --profile fast --url https://lab.example/fetch
  sqliblind preview -- --url https://lab.example/fetch --workers 16 map
  sqliblind sessions --workspace ~/.local/share/imr-sqliblind/workspaces list
  sqliblind sessions events SCAN_ID --follow --jsonl
  sqliblind resume SCAN_ID --workspace ./workspace --dry-run
  sqliblind tui --scan-id SCAN_ID
  sqliblind completion bash
  sqliblind --jsonl --url https://lab.example/fetch schemas

terminal presentation:
  --color auto           Use colors only in an interactive terminal (default)
  --color always         Force professional ANSI colors
  --color never          Disable ANSI colors
  --no-color             Alias for --color never
  --no-banner            Hide the imr-sqliblind banner

service examples:
  sqliblind start
  sqliblind start --port 43128
  sqliblind status
  sqliblind users create analyst --role operator --expires-in 7d
  sqliblind users passwd admin
  sqliblind config show

update examples:
  sqliblind update --check
  sqliblind update
  sqliblind update --json
  sqliblind update --force
"""


def _banner_allowed(arguments: Sequence[str]) -> bool:
    return "--version" not in arguments and "_service-run" not in arguments


def _machine_output_requested(arguments: Sequence[str]) -> bool:
    if is_machine_output(arguments) or "--jsonl" in arguments:
        return True
    values = list(arguments)
    if values and values[0] == "config" and "show" in values[1:]:
        return True
    return bool(
        values
        and values[0] in {"doctor", "profiles", "sessions"}
        and any(value in {"--json", "--jsonl"} for value in values[1:])
    )


def _confirm_forced_update(
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> bool:
    source = input_stream or sys.stdin
    destination = output_stream or sys.stderr
    print("Update warning.", file=destination)
    print(
        "Saved changes could disappear during a forced update.",
        file=destination,
    )
    print(
        "Do you want to proceed? [y/N]: ",
        end="",
        file=destination,
        flush=True,
    )
    try:
        answer = source.readline()
    except KeyboardInterrupt:
        print(file=destination)
        print("Update cancelled.", file=destination)
        return False
    if not answer or answer.strip().casefold() not in {"y", "yes"}:
        print("Update cancelled.", file=destination)
        return False
    return True


def main(argv: Sequence[str] | None = None) -> int:
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        arguments, terminal_options = extract_terminal_options(raw_arguments)
        arguments = prepare_profile_arguments(arguments)
    except (TerminalOptionError, ProductivityError) as exc:
        print(f"sqliblind: error: {exc}", file=sys.stderr)
        return 2

    machine_output = _machine_output_requested(arguments)
    with terminal_session(terminal_options, machine_output=machine_output) as terminal:
        if _banner_allowed(arguments):
            terminal.print_banner(__version__)

        try:
            if arguments and arguments[0] == "update":
                update_arguments = arguments[1:]
                forced_update = (
                    "--force" in update_arguments
                    and "--check" not in update_arguments
                )
                if forced_update and not _confirm_forced_update():
                    return 0
                return update_main(update_arguments)
            if arguments and arguments[0] in SERVICE_COMMANDS:
                return service_main(arguments)
            if arguments and arguments[0] in PRODUCTIVITY_COMMANDS:
                return productivity_main(arguments, cli_main)
            if "--jsonl" in arguments:
                return run_jsonl_cli(arguments, cli_main)
            if arguments in (["-h"], ["--help"]):
                build_parser().print_help()
                print(_ADDITIONAL_HELP.rstrip())
                return 0
            return cli_main(arguments)
        except ProductivityError as exc:
            print(f"sqliblind: error: {exc}", file=sys.stderr)
            return 2


__all__ = ["main"]
