from __future__ import annotations

import ipaddress
import json
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

DEFAULT_SERVICE_PORT = 43127


def application_root() -> Path:
    configured = os.environ.get("IMR_SQLIBLIND_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        root = Path(local) if local else Path.home() / "AppData" / "Local"
        return (root / "Programs" / "imr-sqliblind").resolve()
    xdg = os.environ.get("XDG_DATA_HOME")
    root = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return (root / "imr-sqliblind").resolve()


def default_config_path() -> Path:
    return application_root() / "config" / "service.json"


@dataclass(frozen=True)
class ServiceConfig:
    host: str
    port: int
    workspace: str
    auth_database: str
    state_file: str
    log_file: str
    session_hours: int = 12
    allow_remote: bool = False
    ssl_certfile: str | None = None
    ssl_keyfile: str | None = None

    @classmethod
    def defaults(cls) -> "ServiceConfig":
        root = application_root()
        return cls(
            host="127.0.0.1",
            port=DEFAULT_SERVICE_PORT,
            workspace=str(root / "workspaces"),
            auth_database=str(root / "auth" / "users.db"),
            state_file=str(root / "run" / "service.json"),
            log_file=str(root / "logs" / "service.log"),
        )

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "ServiceConfig":
        defaults = asdict(cls.defaults())
        unknown = sorted(set(value) - set(defaults))
        if unknown:
            raise ValueError(f"unknown service configuration keys: {', '.join(unknown)}")
        merged = {**defaults, **value}
        if not isinstance(merged["allow_remote"], bool):
            raise ValueError("allow_remote must be true or false")
        config = cls(
            host=str(merged["host"]).strip(),
            port=int(merged["port"]),
            workspace=str(Path(str(merged["workspace"])).expanduser().resolve()),
            auth_database=str(Path(str(merged["auth_database"])).expanduser().resolve()),
            state_file=str(Path(str(merged["state_file"])).expanduser().resolve()),
            log_file=str(Path(str(merged["log_file"])).expanduser().resolve()),
            session_hours=int(merged["session_hours"]),
            allow_remote=merged["allow_remote"],
            ssl_certfile=(
                str(Path(str(merged["ssl_certfile"])).expanduser().resolve())
                if merged.get("ssl_certfile")
                else None
            ),
            ssl_keyfile=(
                str(Path(str(merged["ssl_keyfile"])).expanduser().resolve())
                if merged.get("ssl_keyfile")
                else None
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.host or any(character.isspace() for character in self.host):
            raise ValueError("service host is invalid")
        if not 1 <= self.port <= 65535:
            raise ValueError("service port must be between 1 and 65535")
        if not 1 <= self.session_hours <= 24 * 30:
            raise ValueError("session_hours must be between 1 and 720")
        if bool(self.ssl_certfile) != bool(self.ssl_keyfile):
            raise ValueError("ssl_certfile and ssl_keyfile must be configured together")
        for label, value in (
            ("ssl_certfile", self.ssl_certfile),
            ("ssl_keyfile", self.ssl_keyfile),
        ):
            if value and not Path(value).is_file():
                raise ValueError(f"{label} does not exist: {value}")
        loopback = self.host.casefold() == "localhost"
        if not loopback:
            try:
                loopback = ipaddress.ip_address(self.host).is_loopback
            except ValueError:
                loopback = False
        if not loopback and not self.allow_remote:
            raise ValueError("non-loopback service hosts require allow_remote=true")

    def with_overrides(
        self,
        *,
        host: str | None = None,
        port: int | None = None,
    ) -> "ServiceConfig":
        updated = replace(
            self,
            host=host if host is not None else self.host,
            port=port if port is not None else self.port,
        )
        updated.validate()
        return updated

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _secure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            path.parent.chmod(0o700)
        except OSError:
            pass


def atomic_write_json(path: str | Path, value: dict[str, Any]) -> Path:
    destination = Path(path).expanduser().resolve()
    _secure_parent(destination)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            temporary.chmod(0o600)
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return destination


def load_config(
    path: str | Path | None = None,
    *,
    create: bool = True,
) -> tuple[Path, ServiceConfig]:
    config_path = Path(path).expanduser().resolve() if path else default_config_path()
    if not config_path.exists():
        config = ServiceConfig.defaults()
        if create:
            atomic_write_json(config_path, config.to_dict())
        return config_path, config
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read service configuration: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("service configuration must contain a JSON object")
    return config_path, ServiceConfig.from_mapping(value)


def save_config(path: str | Path, config: ServiceConfig) -> Path:
    config.validate()
    return atomic_write_json(path, config.to_dict())
