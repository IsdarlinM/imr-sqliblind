from __future__ import annotations

import sys
from collections.abc import Sequence

from .cli import build_parser, main as cli_main
from .updater import update_main

_UPDATE_HELP = """
additional commands:
  update                Check for and install updates from the official repository

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
    if arguments in (["-h"], ["--help"]):
        build_parser().print_help()
        print(_UPDATE_HELP.rstrip())
        return 0
    return cli_main(arguments)


__all__ = ["main"]
