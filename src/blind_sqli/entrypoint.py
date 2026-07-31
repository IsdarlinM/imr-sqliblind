from __future__ import annotations

import sys
from collections.abc import Sequence

from .cli import build_parser, main as cli_main
from .service_cli import SERVICE_COMMANDS, service_main
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


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
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
