from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Any

from .manager import SENSITIVE_HEADERS, ScanSettings

DEFAULT_SCAN_SETTING_KEY = "web.default_scan"

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
    "delay": 0.1,
    "max_requests": 5000,
    "workers": 4,
    "max_length": 128,
    "max_items": 128,
    "min_char_code": 32,
    "max_char_code": 126,
    "headers": {},
    "cookies": {},
    "proxy": None,
    "insecure": False,
    "skip_calibration": False,
    "include_data": False,
    "data_tables": [],
    "max_rows": 5,
    "max_data_columns": 10,
    "max_value_length": 128,
    "max_data_bytes": 10_000,
    "reveal_sensitive_values": False,
    "inference_mode": "adaptive",
    "parallel_characters": True,
    "adaptive_confirmation": True,
    "adaptive_concurrency": True,
    "request_event_sample": 20,
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
        if str(key).casefold() not in SENSITIVE_HEADERS
    }
    normalized["cookies"] = {}
    normalized["proxy"] = None
    normalized["reveal_sensitive_values"] = False
    return merged_scan_defaults(normalized)
