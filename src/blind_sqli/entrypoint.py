from __future__ import annotations

import sys
from collections.abc import Sequence

from . import __version__
from .cli import build_parser, main as cli_main
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


def main(argv: Sequence[str] | None = None) -> int:
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        arguments, terminal_options = extract_terminal_options(raw_arguments)
    except TerminalOptionError as exc:
        print(f"sqliblind: error: {exc}", file=sys.stderr)
        return 2

    machine_output = is_machine_output(arguments)
    with terminal_session(terminal_options, machine_output=machine_output) as terminal:
        if _banner_allowed(arguments):
            terminal.print_banner(__version__)

        if arguments and arguments[0] == "update":
            return update_main(arguments[1:])
        if arguments and arguments[0] in SERVICE_COMMANDS:
            return service_main(arguments)
        if arguments in (["-h"], ["--help"]):
            build_parser().print_help()
            print(_ADDITIONAL_HELP.rstrip())
            return 0
        return cli_main(arguments)


__all__ = ["main"]
