from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import platform
import shutil
import sqlite3
import ssl
import sys
from collections.abc import Callable, Sequence

from . import __version__
from .productivity_common import (
    EXIT_OK,
    EXIT_RUNTIME_ERROR,
    ProductivityError,
    config_home,
    json_print,
    workspace_database,
)
from .productivity_profiles import (
    prepare_profile_arguments,
    preview_main,
    profiles_main,
)
from .productivity_sessions import resume_main, sessions_main, tui_main

PRODUCTIVITY_COMMANDS = {
    "doctor",
    "profiles",
    "preview",
    "resume",
    "sessions",
    "tui",
    "completion",
}


def _doctor_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sqliblind doctor")
    parser.add_argument("--workspace")
    parser.add_argument("--json", action="store_true")
    return parser


def _check(
    name: str,
    ok: bool,
    detail: str,
    *,
    required: bool = True,
) -> dict[str, object]:
    return {
        "name": name,
        "ok": ok,
        "required": required,
        "detail": detail,
    }


def doctor_main(arguments: Sequence[str]) -> int:
    args = _doctor_parser().parse_args(arguments)
    workspace = workspace_database(args.workspace)
    checks: list[dict[str, object]] = [
        _check(
            "python",
            sys.version_info >= (3, 10),
            f"{platform.python_implementation()} {platform.python_version()}",
        ),
        _check("sqlite", True, sqlite3.sqlite_version),
        _check(
            "requests",
            importlib.util.find_spec("requests") is not None,
            (
                "installed"
                if importlib.util.find_spec("requests")
                else "missing"
            ),
        ),
    ]
    verify = ssl.get_default_verify_paths()
    checks.append(
        _check(
            "tls-ca",
            bool(verify.cafile or verify.capath),
            str(verify),
        )
    )
    web_ready = all(
        importlib.util.find_spec(name) is not None
        for name in ("fastapi", "uvicorn")
    )
    checks.append(
        _check(
            "web-extra",
            web_ready,
            "installed" if web_ready else "optional dependencies missing",
            required=False,
        )
    )
    command = shutil.which("sqliblind")
    checks.append(
        _check("path", command is not None, command or "not on PATH")
    )
    try:
        workspace.parent.mkdir(parents=True, exist_ok=True)
        probe = workspace.parent / ".sqliblind-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        workspace_ok = True
        workspace_detail = str(workspace)
    except OSError as exc:
        workspace_ok = False
        workspace_detail = f"{workspace}: {exc}"
    checks.append(
        _check("workspace", workspace_ok, workspace_detail)
    )
    configuration = config_home()
    try:
        configuration.mkdir(parents=True, exist_ok=True)
        config_ok = os.access(configuration, os.W_OK)
    except OSError:
        config_ok = False
    checks.append(_check("config", config_ok, str(configuration)))
    proxies = sorted(
        key
        for key in os.environ
        if key.casefold() in {"http_proxy", "https_proxy", "all_proxy"}
    )
    checks.append(
        _check(
            "proxy-environment",
            True,
            ", ".join(proxies) or "not configured",
            required=False,
        )
    )
    failed = any(
        not bool(item["ok"]) and bool(item["required"])
        for item in checks
    )
    result = {"version": __version__, "ok": not failed, "checks": checks}
    if args.json:
        json_print(result)
    else:
        print(f"imr-sqliblind doctor v{__version__}")
        for item in checks:
            marker = (
                "OK"
                if item["ok"]
                else ("FAIL" if item["required"] else "WARN")
            )
            print(
                f"[{marker:4}] {item['name']:<20} {item['detail']}"
            )
    return EXIT_RUNTIME_ERROR if failed else EXIT_OK


def completion_main(arguments: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="sqliblind completion")
    parser.add_argument(
        "shell",
        choices=("bash", "zsh", "powershell"),
    )
    shell = parser.parse_args(arguments).shell
    commands = (
        "schemas tables columns extract probe rows map web start stop "
        "restart status users config update doctor profiles preview "
        "sessions resume tui completion"
    )
    if shell == "bash":
        print(
            "_sqliblind_complete() {\n"
            "  local cur=\"${COMP_WORDS[COMP_CWORD]}\"\n"
            f"  COMPREPLY=( $(compgen -W '{commands}' -- \"$cur\") )\n"
            "}\n"
            "complete -F _sqliblind_complete sqliblind"
        )
    elif shell == "zsh":
        print(
            f"#compdef sqliblind\n"
            f"_arguments '1:command:({commands})'"
        )
    else:
        print(
            "Register-ArgumentCompleter -Native "
            "-CommandName sqliblind -ScriptBlock {\n"
            "  param($wordToComplete)\n"
            f"  '{commands}'.Split(' ') | "
            "Where-Object { $_ -like \"$wordToComplete*\" }\n"
            "}"
        )
    return EXIT_OK


def run_jsonl_cli(
    arguments: Sequence[str],
    cli_main: Callable[[Sequence[str] | None], int],
) -> int:
    values = [item for item in arguments if item != "--jsonl"]
    if "--output" in values or any(
        item.startswith("--output=") for item in values
    ):
        raise ProductivityError(
            "--jsonl cannot be combined with --output"
        )
    if "--json" not in values:
        values.insert(0, "--json")
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = int(cli_main(values))
    text = output.getvalue().strip()
    if not text:
        return code
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        print(
            json.dumps(
                {"type": "text", "value": text},
                ensure_ascii=False,
            )
        )
        return code

    result = document.get("result")
    if isinstance(result, list):
        for index, item in enumerate(result):
            print(
                json.dumps(
                    {
                        "type": "result",
                        "index": index,
                        "value": item,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
    else:
        print(
            json.dumps(
                {"type": "result", "value": result},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    print(
        json.dumps(
            {
                "type": "summary",
                "requests": document.get("requests"),
                "elapsed_seconds": document.get("elapsed_seconds"),
                "performance": document.get("performance"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return code


def productivity_main(
    arguments: Sequence[str],
    cli_main: Callable[[Sequence[str] | None], int],
) -> int:
    if not arguments:
        raise ProductivityError("Missing productivity command")
    command, rest = arguments[0], arguments[1:]
    if command == "doctor":
        return doctor_main(rest)
    if command == "profiles":
        return profiles_main(rest)
    if command == "preview":
        return preview_main(rest)
    if command == "sessions":
        return sessions_main(rest)
    if command == "resume":
        return resume_main(rest, cli_main)
    if command == "tui":
        return tui_main(rest)
    if command == "completion":
        return completion_main(rest)
    raise ProductivityError(
        f"Unknown productivity command: {command}"
    )


__all__ = [
    "PRODUCTIVITY_COMMANDS",
    "ProductivityError",
    "prepare_profile_arguments",
    "productivity_main",
    "run_jsonl_cli",
]
