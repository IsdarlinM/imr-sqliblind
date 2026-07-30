from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from blind_sqli.cli import build_parser

ROOT = Path(__file__).resolve().parents[1]


class BrandingTests(unittest.TestCase):
    def test_public_project_and_command_names(self) -> None:
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(metadata["project"]["name"], "imr-sqliblind")
        self.assertEqual(metadata["project"]["version"], "0.6.0")
        self.assertEqual(metadata["project"]["requires-python"], ">=3.10")
        self.assertEqual(
            metadata["project"]["scripts"],
            {"sqliblind": "blind_sqli.entrypoint:main"},
        )
        self.assertEqual(build_parser().prog, "sqliblind")

    def test_default_html_identity(self) -> None:
        args = build_parser().parse_args(["map", "--format", "html"])
        self.assertEqual(args.title, "imr-sqliblind schema map")

    def test_direct_entry_point_import_has_no_network_activity(self) -> None:
        spec = importlib.util.spec_from_file_location("sqliblind_entry", ROOT / "sqliblind.py")
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        with patch("requests.Session.get") as mocked_get:
            spec.loader.exec_module(module)
            mocked_get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
