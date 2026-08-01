from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .manager import SENSITIVE_HEADERS, ScanSettings

BUILTIN_SCAN_DEFAULTS: dict[str, Any] = {
    "url": "",
    "parameter": "id",
    "url_template": None,
    "dialect": "mysql",
    "oracle": "status",
    "true_statuses": [200],
    "true_marker": None,
    "true_regex": None,
    "true_length": None,
    "length_tolerance": 0,
    "timeout": 10.0,
    "retries": 1,
    "delay": 0.0,
    "max_requests": 5000,
    "workers": 16,
    "max_length": 128,
    "max_items": 128,
    "min_char_code": 32,
    "max_char_code": 126,
    "headers": {},
    "cookies": {},
    "proxy": None,
    "insecure": False,
    "skip_calibration": False,
    "include_data": True,
    "data_tables": [],
    "max_rows": 5,
    "max_data_columns": 10,
    "max_value_length": 128,
    "max_data_bytes": 10_000,
    "reveal_sensitive_values": False,
    "inference_mode": "turbo",
    "parallel_characters": True,
    "adaptive_confirmation": True,
    "adaptive_concurrency": True,
    "request_event_sample": 20,
}

_ADDITIONAL_SENSITIVE_HEADER_PARTS = {
    "auth",
    "credential",
    "secret",
    "session",
    "token",
}


def merged_scan_defaults(stored: dict[str, Any] | None) -> dict[str, Any]:
    result = deepcopy(BUILTIN_SCAN_DEFAULTS)
    if stored:
        for key, value in stored.items():
            if key in result:
                result[key] = deepcopy(value)
    return result


def _settings_mapping(settings: ScanSettings) -> dict[str, Any]:
    result = asdict(settings)
    result["true_statuses"] = sorted(settings.true_statuses)
    result["data_tables"] = sorted(settings.data_tables)
    return result


def _header_is_sensitive(name: str) -> bool:
    normalized = name.casefold().replace("_", "-")
    if normalized in SENSITIVE_HEADERS:
        return True
    if "api-key" in normalized or normalized.endswith("-key"):
        return True
    return any(part in normalized for part in _ADDITIONAL_SENSITIVE_HEADER_PARTS)


def normalize_saved_scan_defaults(raw: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(raw) - set(BUILTIN_SCAN_DEFAULTS))
    if unknown:
        raise ValueError(f"unsupported default scan fields: {', '.join(unknown)}")

    merged = merged_scan_defaults(raw)
    original_url = str(merged.get("url") or "").strip()
    original_template = str(merged.get("url_template") or "").strip()

    validation = deepcopy(merged)
    if not original_url and not original_template:
        validation["url"] = "https://defaults.invalid/"

    settings = ScanSettings.from_mapping(validation)
    normalized = _settings_mapping(settings)
    normalized["url"] = original_url
    normalized["url_template"] = original_template or None

    headers = normalized.get("headers", {})
    normalized["headers"] = {
        str(key): str(value)
        for key, value in headers.items()
        if not _header_is_sensitive(str(key))
    }
    normalized["cookies"] = {}
    normalized["proxy"] = None
    normalized["reveal_sensitive_values"] = False
    return merged_scan_defaults(normalized)


class DefaultScanProfileStore:
    """Atomic local persistence for the web console's default scan profile."""

    def __init__(self, session_database: str | Path) -> None:
        database = Path(session_database).expanduser()
        self.path = database.with_name("web-default-scan.json")
        self._lock = threading.RLock()

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "config": merged_scan_defaults(None),
            "saved": False,
            "updated_at": None,
        }

    def load(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                return self._empty()
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                config = payload.get("config")
                if not isinstance(config, dict):
                    raise ValueError("saved profile config must be an object")
                normalized = normalize_saved_scan_defaults(config)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                return self._empty()
            return {
                "config": normalized,
                "saved": True,
                "updated_at": payload.get("updated_at"),
            }

    def save(self, raw: dict[str, Any]) -> dict[str, Any]:
        config = normalize_saved_scan_defaults(raw)
        updated_at = datetime.now(timezone.utc).isoformat()
        payload = {"config": config, "updated_at": updated_at}
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )

        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".json.tmp")
            temporary.write_text(encoded + "\n", encoding="utf-8")
            if os.name != "nt":
                temporary.chmod(0o600)
            temporary.replace(self.path)
            if os.name != "nt":
                self.path.chmod(0o600)
        return {"config": config, "saved": True, "updated_at": updated_at}
