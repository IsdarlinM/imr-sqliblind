from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from blind_sqli.web_defaults import (
    DefaultScanProfileStore,
    merged_scan_defaults,
    normalize_saved_scan_defaults,
)


class WebDefaultProfileTests(unittest.TestCase):
    def test_defaults_are_merged_and_unknown_fields_are_rejected(self) -> None:
        merged = merged_scan_defaults({"workers": 7, "dialect": "sqlite"})
        self.assertEqual(merged["workers"], 7)
        self.assertEqual(merged["dialect"], "sqlite")
        self.assertEqual(merged["parameter"], "id")
        with self.assertRaisesRegex(ValueError, "unsupported default scan fields"):
            normalize_saved_scan_defaults({"unexpected": True})

    def test_profile_is_atomic_persistent_and_secret_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "sessions.sqlite3"
            store = DefaultScanProfileStore(database)
            result = store.save(
                {
                    "url": "https://lab.example/fetch",
                    "dialect": "sqlite",
                    "workers": 8,
                    "headers": {
                        "X-Trace": "research",
                        "Authorization": "Bearer secret",
                        "X-API-Key": "secret",
                        "X-Auth-Token": "secret",
                    },
                    "cookies": {"session": "secret"},
                    "proxy": "http://user:pass@127.0.0.1:8080",
                    "reveal_sensitive_values": True,
                }
            )

            self.assertTrue(result["saved"])
            self.assertTrue(store.path.exists())
            self.assertEqual(result["config"]["headers"], {"X-Trace": "research"})
            self.assertEqual(result["config"]["cookies"], {})
            self.assertIsNone(result["config"]["proxy"])
            self.assertFalse(result["config"]["reveal_sensitive_values"])

            loaded = store.load()
            self.assertTrue(loaded["saved"])
            self.assertEqual(loaded["config"]["workers"], 8)
            self.assertEqual(loaded["config"]["dialect"], "sqlite")
            self.assertEqual(loaded["config"]["headers"], {"X-Trace": "research"})
            if os.name != "nt":
                mode = stat.S_IMODE(store.path.stat().st_mode)
                self.assertEqual(mode, 0o600)

    def test_invalid_saved_file_falls_back_to_built_in_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = DefaultScanProfileStore(Path(temporary) / "sessions.sqlite3")
            store.path.write_text(
                '{"config":{"workers":999},"updated_at":"invalid"}',
                encoding="utf-8",
            )
            loaded = store.load()
            self.assertFalse(loaded["saved"])
            self.assertEqual(loaded["config"]["workers"], 4)
            self.assertIsNone(loaded["updated_at"])


if __name__ == "__main__":
    unittest.main()
