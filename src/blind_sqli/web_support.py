from __future__ import annotations

import html
import ipaddress
import os
from importlib import resources
from pathlib import Path

from . import __version__

TERMINAL_STATUSES = {"completed", "failed", "cancelled", "interrupted"}
AUTH_COOKIE = "sqliblind_session"
CSRF_COOKIE = "sqliblind_csrf"


def is_loopback(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def default_workspace() -> Path:
    configured = os.environ.get("IMR_SQLIBLIND_HOME")
    if configured:
        return Path(configured).expanduser() / "workspaces"
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        root = Path(local) if local else Path.home() / "AppData" / "Local"
        return root / "Programs" / "imr-sqliblind" / "workspaces"
    xdg = os.environ.get("XDG_DATA_HOME")
    root = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return root / "imr-sqliblind" / "workspaces"


def load_ui(csrf_token: str, nonce: str) -> str:
    document = (
        resources.files("blind_sqli")
        .joinpath("webui/index.html")
        .read_text(encoding="utf-8")
    )
    return (
        document.replace("__CSRF__", html.escape(csrf_token, quote=True))
        .replace("__NONCE__", html.escape(nonce, quote=True))
        .replace("__VERSION__", html.escape(__version__, quote=True))
    )


def load_asset(name: str) -> str:
    if name not in {"app.css", "app.js"}:
        raise ValueError("unsupported web asset")
    return (
        resources.files("blind_sqli")
        .joinpath(f"webui/{name}")
        .read_text(encoding="utf-8")
    )
