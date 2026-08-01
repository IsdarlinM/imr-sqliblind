from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .web_support import default_workspace

TERMINAL_SCAN_STATUSES = {"completed", "failed", "cancelled", "interrupted"}
EXIT_OK = 0
EXIT_RUNTIME_ERROR = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130


class ProductivityError(ValueError):
    pass


def config_home() -> Path:
    configured = os.environ.get("IMR_SQLIBLIND_HOME")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(
            Path.home() / "AppData" / "Roaming"
        )
        return Path(base) / "imr-sqliblind"
    configured_home = os.environ.get("XDG_CONFIG_HOME")
    base = (
        Path(configured_home).expanduser()
        if configured_home
        else Path.home() / ".config"
    )
    return base / "imr-sqliblind"


def workspace_database(value: str | None) -> Path:
    if value:
        path = Path(value).expanduser()
        if path.suffix.casefold() in {".db", ".sqlite3"}:
            return path
        return path / "sessions.db"
    workspace = default_workspace()
    return (
        workspace
        if workspace.suffix.casefold() in {".db", ".sqlite3"}
        else workspace / "sessions.db"
    )


def json_print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def signature_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entities = {
        str(item["id"]): item for item in snapshot.get("entities", [])
    }
    result: dict[str, dict[str, Any]] = {}
    for entity in entities.values():
        parts: list[str] = []
        current: dict[str, Any] | None = entity
        seen: set[str] = set()
        while current is not None and str(current["id"]) not in seen:
            seen.add(str(current["id"]))
            parts.insert(0, f"{current.get('type')}:{current.get('name')}")
            parent = current.get("parent_id")
            current = entities.get(str(parent)) if parent else None
        result["/".join(parts)] = entity
    return result


def snapshot_diff(
    left: dict[str, Any],
    right: dict[str, Any],
) -> dict[str, list[str]]:
    first = signature_map(left)
    second = signature_map(right)
    return {
        "added": sorted(key for key in second if key not in first),
        "removed": sorted(key for key in first if key not in second),
        "changed": sorted(
            key
            for key in second
            if key in first
            and json.dumps(first[key].get("data", {}), sort_keys=True)
            != json.dumps(second[key].get("data", {}), sort_keys=True)
        ),
    }
