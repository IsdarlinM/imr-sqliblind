#!/usr/bin/env python3
"""Backward-compatible entry point for the blind_sqli package."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from blind_sqli.cli import BASE_URL, main  # noqa: E402
from blind_sqli.models import Schema, Table  # noqa: E402

__all__ = ["BASE_URL", "Schema", "Table", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
