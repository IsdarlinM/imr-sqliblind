from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

from .auth import UserError, UserStore, utc_now
from .service_config import ServiceConfig, load_config, save_config
from .service_runtime import (
    restart_service,
    run_service,
    service_status,
    start_service,
    stop_service,
)

SERVICE_COMMANDS = {
    "start",
    "stop",
    "restart",
    "status",
    "users",
    "config",
    "_service-run",
}
_DURATION = re.compile(r"^(\d+)(m|h|d|w)$", re.IGNORECASE)


def parse_duration(value: str) -> timedelta:
    match = _DURATION.fullmatch(value.strip())
    if not match:
        raise ValueError("duration must use forms such as 30m, 12h, 7d, or 2w")
    amount = int(match.group(1))
    if amount < 1:
        raise ValueError("duration must be positive")
    unit = match.group(2).casefold()
    multipliers = {
        "m": timedelta(minutes=1),
        "h": timedelta(hours=1),
        "d": timedelta(days=1),
        "w": timedelta(weeks=1),
    }
    result = multipliers[unit] * amount
    if result > timedelta(days=3650):
        raise ValueError("duration cannot exceed 10 years")
    return result


def _expiration(value: str | None) -> datetime | None:
    return utc_now() + parse_duration(value) if value else None


def _read_password(*, stdin: bool, confirm: bool = True) -> str:
    if stdin:
        password = sys.stdin.readline().rstrip("\r\n")
        if not password:
            raise UserError("password input was empty")
        return password
    password = getpass.getpass("Password: ")
    if confirm:
        repeated = getpass.getpass("Confirm password: ")
        if password != repeated:
            raise UserError("passwords do not match")
    return password


def _print_status(value: dict[str, Any], *, json_output: bool = False) -> None:
    if json_output:
        print(json.dumps(value, indent=2, ensure_ascii=False))
        return
    status = value.get("status", "unknown")
    print(f"Service: {status}")
    for key in (
        "pid",
        "url",
        "config",
        "log_file",
        "auth_database",
        "started_at",
    ):
        if value.get(key) is not None:
            print(f"  {key.replace('_', ' ').title()}: {value[key]}")
    if value.get("already_running"):
        print("  The service was already running.")
    if value.get("already_stopped"):
        print("  The service was already stopped.")


def _user_store(
    config_path: str | Path | None,
) -> tuple[Path, ServiceConfig, UserStore]:
    path, config = load_config(config_path)
    store = UserStore(config.auth_database)
    store.bootstrap_admin()
    return path, config, store


def build_service_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sqliblind",
        description="Manage the imr-sqliblind background web service and users.",
    )
    subparsers = parser.add_subparsers(dest="service_command", required=True)

    def service_options(command: str, help_text: str) -> argparse.ArgumentParser:
        item = subparsers.add_parser(command, help=help_text)
        item.add_argument("--config", help="Service JSON configuration path")
        item.add_argument("--json", action="store_true", dest="json_output")
        return item

    start = service_options("start", "Start the web console in the background")
    start.add_argument("--host", help="Override the configured host for this start")
    start.add_argument("--port", type=int, help="Override the configured port")
    start.add_argument(
        "--foreground",
        action="store_true",
        help="Run in the current terminal instead of detaching",
    )

    service_options("stop", "Stop the background web console")

    restart = service_options("restart", "Restart the background web console")
    restart.add_argument("--host", help="Override the configured host")
    restart.add_argument("--port", type=int, help="Override the configured port")

    service_options("status", "Show service status")

    users = subparsers.add_parser("users", help="Create and manage service users")
    users.add_argument("--config", help="Service JSON configuration path")
    users.add_argument("--json", action="store_true", dest="json_output")
    user_commands = users.add_subparsers(dest="users_command", required=True)

    user_commands.add_parser("list", help="List users and expiration state")

    create = user_commands.add_parser("create", help="Create a user")
    create.add_argument("username")
    create.add_argument(
        "--role",
        choices=("admin", "operator", "viewer"),
        default="viewer",
    )
    create.add_argument("--expires-in", metavar="DURATION")
    create.add_argument("--must-change-password", action="store_true")
    create.add_argument("--password-stdin", action="store_true")

    passwd = user_commands.add_parser("passwd", help="Reset a user's password")
    passwd.add_argument("username")
    passwd.add_argument("--password-stdin", action="store_true")
    passwd.add_argument(
        "--no-force-change",
        action="store_true",
        help="Do not require another password change at next login",
    )

    for command in ("enable", "disable", "delete"):
        item = user_commands.add_parser(command, help=f"{command.title()} a user")
        item.add_argument("username")

    role = user_commands.add_parser("role", help="Change a user's role")
    role.add_argument("username")
    role.add_argument("role", choices=("admin", "operator", "viewer"))

    expire = user_commands.add_parser("expire", help="Set or remove user expiration")
    expire.add_argument("username")
    group = expire.add_mutually_exclusive_group(required=True)
    group.add_argument("--in", dest="expires_in", metavar="DURATION")
    group.add_argument("--never", action="store_true")

    audit = user_commands.add_parser(
        "audit",
        help="Show recent authentication audit events",
    )
    audit.add_argument("--limit", type=int, default=100)

    config = subparsers.add_parser(
        "config",
        help="Initialize, show, or edit service config",
    )
    config.add_argument("--config", help="Service JSON configuration path")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    config_commands.add_parser("init", help="Create the default config if missing")
    config_commands.add_parser("show", help="Print the effective JSON config")
    set_config = config_commands.add_parser(
        "set",
        help="Update persistent service defaults",
    )
    set_config.add_argument("--host")
    set_config.add_argument("--port", type=int)
    set_config.add_argument("--workspace")
    set_config.add_argument("--auth-database")
    set_config.add_argument("--state-file")
    set_config.add_argument("--log-file")
    set_config.add_argument("--session-hours", type=int)
    set_config.add_argument(
        "--allow-remote",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    set_config.add_argument("--ssl-certfile")
    set_config.add_argument("--ssl-keyfile")

    internal = subparsers.add_parser("_service-run", help=argparse.SUPPRESS)
    internal.add_argument("--config", required=True)
    internal.add_argument("--host")
    internal.add_argument("--port", type=int)
    return parser


def _run_users(args: argparse.Namespace) -> int:
    _, _, store = _user_store(args.config)
    command = args.users_command
    if command == "list":
        users = store.list_users()
        if args.json_output:
            print(json.dumps(users, indent=2, ensure_ascii=False))
            return 0
        print("USERNAME                      ROLE      STATE       EXPIRES")
        for user in users:
            state = (
                "disabled"
                if not user["active"]
                else "expired"
                if user["expired"]
                else "active"
            )
            expires = user["expires_at"] or "never"
            marker = " *change-password" if user["must_change_password"] else ""
            print(
                f"{user['username'][:28]:28}  {user['role'][:8]:8}  "
                f"{state[:10]:10}  {expires}{marker}"
            )
        return 0
    if command == "create":
        password = _read_password(stdin=args.password_stdin)
        user = store.create_user(
            args.username,
            password,
            role=args.role,
            expires_at=_expiration(args.expires_in),
            must_change_password=args.must_change_password,
        )
        print(f"Created user {user['username']} ({user['role']}).")
        return 0
    if command == "passwd":
        password = _read_password(stdin=args.password_stdin)
        store.reset_password(
            args.username,
            password,
            must_change_password=not args.no_force_change,
        )
        print(
            f"Password reset for {args.username}; existing sessions were revoked."
        )
        return 0
    if command == "enable":
        store.set_active(args.username, True)
        print(f"Enabled {args.username}.")
        return 0
    if command == "disable":
        store.set_active(args.username, False)
        print(f"Disabled {args.username}; existing sessions were revoked.")
        return 0
    if command == "delete":
        store.delete_user(args.username)
        print(f"Deleted {args.username}.")
        return 0
    if command == "role":
        store.set_role(args.username, args.role)
        print(
            f"Set {args.username} role to {args.role}; existing sessions were revoked."
        )
        return 0
    if command == "expire":
        expires = None if args.never else _expiration(args.expires_in)
        store.set_expiration(args.username, expires)
        print(
            f"Updated expiration for {args.username}; existing sessions were revoked."
        )
        return 0
    if command == "audit":
        events = store.audit_events(args.limit)
        if args.json_output:
            print(json.dumps(events, indent=2, ensure_ascii=False))
        else:
            for event in events:
                target = f" -> {event['target']}" if event.get("target") else ""
                details = f" ({event['details']})" if event.get("details") else ""
                print(
                    f"{event['created_at']} {event['actor']} {event['action']}"
                    f"{target}{details}"
                )
        return 0
    raise ValueError(f"unsupported users command: {command}")


def _run_config(args: argparse.Namespace) -> int:
    path, config = load_config(args.config)
    if args.config_command == "init":
        print(f"Service configuration: {path}")
        return 0
    if args.config_command == "show":
        print(json.dumps(config.to_dict(), indent=2, ensure_ascii=False))
        return 0
    if args.config_command == "set":
        changes: dict[str, Any] = {}
        for name in (
            "host",
            "port",
            "workspace",
            "auth_database",
            "state_file",
            "log_file",
            "session_hours",
            "allow_remote",
            "ssl_certfile",
            "ssl_keyfile",
        ):
            value = getattr(args, name)
            if value is not None:
                if name in {
                    "workspace",
                    "auth_database",
                    "state_file",
                    "log_file",
                    "ssl_certfile",
                    "ssl_keyfile",
                } and value:
                    value = str(Path(value).expanduser().resolve())
                changes[name] = value
        if not changes:
            raise ValueError("config set requires at least one option")
        updated = replace(config, **changes)
        updated.validate()
        save_config(path, updated)
        print(f"Updated service configuration: {path}")
        print(json.dumps(updated.to_dict(), indent=2, ensure_ascii=False))
        return 0
    raise ValueError(f"unsupported config command: {args.config_command}")


def service_main(argv: Sequence[str] | None = None) -> int:
    parser = build_service_parser()
    args = parser.parse_args(argv)
    try:
        command = args.service_command
        if command == "start":
            result = start_service(
                args.config,
                host=args.host,
                port=args.port,
                foreground=args.foreground,
            )
            _print_status(result, json_output=args.json_output)
            if result.get("status") == "running" and not result.get(
                "already_running"
            ):
                print(
                    "Bootstrap login on first start: admin / admin "
                    "(password change required)."
                )
            return 0
        if command == "stop":
            _print_status(
                stop_service(args.config),
                json_output=args.json_output,
            )
            return 0
        if command == "restart":
            _print_status(
                restart_service(
                    args.config,
                    host=args.host,
                    port=args.port,
                ),
                json_output=args.json_output,
            )
            return 0
        if command == "status":
            value = service_status(args.config)
            _print_status(value, json_output=args.json_output)
            return 0 if value["status"] == "running" else 3
        if command == "users":
            return _run_users(args)
        if command == "config":
            return _run_config(args)
        if command == "_service-run":
            run_service(args.config, host=args.host, port=args.port)
            return 0
        parser.error(f"Unknown service command: {command}")
    except KeyboardInterrupt:
        print("Interrupted by user.", file=sys.stderr)
        return 130
    except (OSError, RuntimeError, UserError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 1


__all__ = [
    "SERVICE_COMMANDS",
    "build_service_parser",
    "parse_duration",
    "service_main",
]
