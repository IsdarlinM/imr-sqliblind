from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from .productivity_common import (
    EXIT_OK,
    ProductivityError,
    config_home,
    json_print,
)

COMMANDS = {
    "schemas",
    "tables",
    "columns",
    "extract",
    "probe",
    "rows",
    "map",
    "graph",
    "schema-map",
    "web",
}
VALUE_OPTIONS = {
    "--url",
    "--parameter",
    "--url-template",
    "--dialect",
    "--oracle",
    "--true-status",
    "--true-marker",
    "--true-regex",
    "--true-length",
    "--length-tolerance",
    "--timeout",
    "--retries",
    "--delay",
    "--max-requests",
    "--workers",
    "--max-length",
    "--max-items",
    "--min-char-code",
    "--max-char-code",
    "--inference-mode",
    "--header",
    "--cookie",
    "--proxy",
    "--progress",
}
FLAG_OPTIONS = {
    "--insecure",
    "--skip-calibration",
    "--json",
    "--serial-characters",
    "--no-adaptive-confirmation",
    "--fixed-concurrency",
}
SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "x-api-key",
}


class ProfileStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_home() / "profiles.json"

    def load(self) -> dict[str, list[str]]:
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProductivityError(f"Could not read profiles: {exc}") from exc
        if not isinstance(value, dict):
            raise ProductivityError("Profile storage is not a JSON object")
        return {
            str(name): [str(item) for item in arguments]
            for name, arguments in value.items()
            if isinstance(arguments, list)
        }

    def save(self, profiles: dict[str, list[str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(profiles, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        temporary.replace(self.path)


def validate_profile_arguments(arguments: Sequence[str]) -> None:
    for index, argument in enumerate(arguments):
        lowered = argument.casefold()
        if (
            lowered in {"--cookie", "--proxy"}
            or lowered.startswith("--cookie=")
            or lowered.startswith("--proxy=")
        ):
            raise ProductivityError(
                "Profiles do not store cookies or proxy URLs."
            )
        header: str | None = None
        if argument == "--header" and index + 1 < len(arguments):
            header = arguments[index + 1]
        elif argument.startswith("--header="):
            header = argument.split("=", 1)[1]
        if header:
            name = header.split(":", 1)[0].strip().casefold()
            if name in SENSITIVE_HEADERS:
                raise ProductivityError(
                    f"Profiles do not store sensitive header {name!r}."
                )


def _split_explicit_globals(
    arguments: Sequence[str],
) -> tuple[list[str], list[str]]:
    globals_before: list[str] = []
    command_specific: list[str] = []
    index = 0
    values = list(arguments)
    while index < len(values):
        item = values[index]
        name = item.split("=", 1)[0]
        if name in VALUE_OPTIONS:
            globals_before.append(item)
            if "=" not in item:
                if index + 1 >= len(values):
                    raise ProductivityError(f"{item} requires a value")
                globals_before.append(values[index + 1])
                index += 2
                continue
        elif name in FLAG_OPTIONS:
            globals_before.append(item)
        else:
            command_specific.append(item)
        index += 1
    return globals_before, command_specific


def prepare_profile_arguments(arguments: Sequence[str]) -> list[str]:
    values = list(arguments)
    selected: str | None = None
    cleaned: list[str] = []
    index = 0
    while index < len(values):
        item = values[index]
        if item == "--profile":
            if index + 1 >= len(values):
                raise ProductivityError("--profile requires a name")
            selected = values[index + 1]
            index += 2
            continue
        if item.startswith("--profile="):
            selected = item.split("=", 1)[1]
            index += 1
            continue
        cleaned.append(item)
        index += 1
    if not selected:
        return cleaned

    profiles = ProfileStore().load()
    if selected not in profiles:
        raise ProductivityError(f"Unknown profile: {selected}")
    saved = list(profiles[selected])
    saved_command = next(
        (i for i, item in enumerate(saved) if item in COMMANDS),
        None,
    )
    explicit_command = next(
        (i for i, item in enumerate(cleaned) if item in COMMANDS),
        None,
    )
    if saved_command is None or explicit_command is not None:
        return [*saved, *cleaned]
    global_values, command_values = _split_explicit_globals(cleaned)
    return [
        *saved[:saved_command],
        *global_values,
        *saved[saved_command:],
        *command_values,
    ]


def _profiles_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sqliblind profiles")
    sub = parser.add_subparsers(dest="action", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("--json", action="store_true")
    show = sub.add_parser("show")
    show.add_argument("name")
    show.add_argument("--json", action="store_true")
    save = sub.add_parser("save")
    save.add_argument("name")
    save.add_argument("arguments", nargs=argparse.REMAINDER)
    delete = sub.add_parser("delete")
    delete.add_argument("name")
    return parser


def profiles_main(arguments: Sequence[str]) -> int:
    args = _profiles_parser().parse_args(arguments)
    store = ProfileStore()
    profiles = store.load()
    if args.action == "list":
        if args.json:
            json_print({"profiles": sorted(profiles)})
        else:
            print("\n".join(sorted(profiles)))
        return EXIT_OK
    if args.action == "show":
        if args.name not in profiles:
            raise ProductivityError(f"Unknown profile: {args.name}")
        if args.json:
            json_print({"name": args.name, "arguments": profiles[args.name]})
        else:
            print(" ".join(profiles[args.name]))
        return EXIT_OK
    if args.action == "save":
        values = list(args.arguments)
        if values and values[0] == "--":
            values.pop(0)
        if not values:
            raise ProductivityError("Provide CLI arguments after the name")
        validate_profile_arguments(values)
        profiles[args.name] = values
        store.save(profiles)
        print(f"Saved profile {args.name!r} without secrets.")
        return EXIT_OK
    if args.name not in profiles:
        raise ProductivityError(f"Unknown profile: {args.name}")
    del profiles[args.name]
    store.save(profiles)
    print(f"Deleted profile {args.name!r}.")
    return EXIT_OK


def preview_main(arguments: Sequence[str]) -> int:
    from .cli import build_parser

    values = list(arguments)
    if values and values[0] == "--":
        values.pop(0)
    if not values:
        raise ProductivityError("Provide scan arguments after preview")
    parsed = vars(build_parser().parse_args(values))
    parsed.pop("func", None)
    parsed["cookie"] = [
        f"{str(item).split('=', 1)[0]}=***"
        for item in parsed.get("cookie") or []
    ]
    headers: list[str] = []
    for item in parsed.get("header") or []:
        name = str(item).split(":", 1)[0]
        headers.append(
            f"{name}:***"
            if name.casefold() in SENSITIVE_HEADERS
            else str(item)
        )
    parsed["header"] = headers
    if parsed.get("proxy"):
        parsed["proxy"] = "configured"
    json_print(
        {
            "command": parsed.get("command") or "schemas",
            "configuration": parsed,
        }
    )
    return EXIT_OK
