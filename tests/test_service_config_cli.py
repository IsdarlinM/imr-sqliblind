from __future__ import annotations

import json
from pathlib import Path

import pytest

from blind_sqli.service_cli import build_service_parser, parse_duration
from blind_sqli.service_config import (
    DEFAULT_SERVICE_PORT,
    ServiceConfig,
    load_config,
    save_config,
)


def test_default_config_uses_unusual_loopback_port(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("IMR_SQLIBLIND_HOME", str(tmp_path / "home"))
    path, config = load_config(tmp_path / "service.json")
    assert path.exists()
    assert config.host == "127.0.0.1"
    assert config.port == DEFAULT_SERVICE_PORT == 43127
    assert config.allow_remote is False
    assert Path(config.auth_database).name == "users.db"
    assert json.loads(path.read_text(encoding="utf-8"))["port"] == 43127


def test_config_rejects_remote_without_opt_in(tmp_path: Path) -> None:
    config = ServiceConfig.defaults()
    with pytest.raises(ValueError, match="allow_remote"):
        ServiceConfig.from_mapping({**config.to_dict(), "host": "0.0.0.0"})


def test_config_roundtrip_and_runtime_override(tmp_path: Path) -> None:
    path = tmp_path / "service.json"
    config = ServiceConfig.from_mapping(
        {
            **ServiceConfig.defaults().to_dict(),
            "port": 45001,
            "workspace": str(tmp_path / "workspace"),
            "auth_database": str(tmp_path / "auth.db"),
            "state_file": str(tmp_path / "state.json"),
            "log_file": str(tmp_path / "service.log"),
        }
    )
    save_config(path, config)
    _, loaded = load_config(path)
    assert loaded.port == 45001
    assert loaded.with_overrides(port=45002).port == 45002
    assert loaded.port == 45001


def test_duration_and_command_parser() -> None:
    assert parse_duration("30m").total_seconds() == 1800
    assert parse_duration("7d").days == 7
    with pytest.raises(ValueError):
        parse_duration("tomorrow")
    parser = build_service_parser()
    start = parser.parse_args(["start", "--port", "43199"])
    assert start.service_command == "start"
    assert start.port == 43199
    create = parser.parse_args(
        [
            "users",
            "create",
            "analyst",
            "--role",
            "operator",
            "--expires-in",
            "7d",
        ]
    )
    assert create.users_command == "create"
    assert create.role == "operator"
