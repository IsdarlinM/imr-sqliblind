from __future__ import annotations

from blind_sqli.service_cli import SERVICE_COMMANDS, build_service_parser


def test_public_service_commands_are_routed() -> None:
    assert {"start", "stop", "restart", "status", "users", "config"} <= SERVICE_COMMANDS
    parser = build_service_parser()
    for command in ("start", "stop", "restart", "status"):
        args = parser.parse_args([command])
        assert args.service_command == command


def test_internal_runner_is_not_a_public_workflow() -> None:
    assert "_service-run" in SERVICE_COMMANDS
    parser = build_service_parser()
    args = parser.parse_args(["_service-run", "--config", "service.json"])
    assert args.service_command == "_service-run"
