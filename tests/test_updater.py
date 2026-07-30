from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from blind_sqli import updater
from blind_sqli.entrypoint import main as entrypoint_main


class UpdaterTests(unittest.TestCase):
    def test_semantic_version_parsing(self) -> None:
        self.assertEqual(updater.parse_version("1.2.3"), (1, 2, 3))
        with self.assertRaises(updater.UpdateError):
            updater.parse_version("1.2")

    def test_remote_version_check(self) -> None:
        response = Mock()
        response.text = '__version__ = "0.7.0"\n'
        response.raise_for_status.return_value = None
        with patch("blind_sqli.updater.requests.get", return_value=response):
            self.assertEqual(updater.fetch_available_version(timeout=3), "0.7.0")

    def test_check_reports_available_version(self) -> None:
        with patch("blind_sqli.updater.fetch_available_version", return_value="0.7.0"):
            status = updater.check_for_updates()
        self.assertEqual(status.installed_version, "0.6.1")
        self.assertEqual(status.available_version, "0.7.0")
        self.assertTrue(status.update_available)

    def test_checkout_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            (root / "src" / "blind_sqli").mkdir(parents=True)
            (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
            (root / "src" / "blind_sqli" / "__init__.py").write_text(
                '__version__ = "0.6.1"\n', encoding="utf-8"
            )
            with patch("blind_sqli.updater.Path.cwd", return_value=root):
                self.assertEqual(updater.discover_source(), root.resolve())

    def test_unexpected_remote_is_rejected(self) -> None:
        completed = Mock(stdout="https://example.invalid/fork.git\n")
        with patch("blind_sqli.updater._run", return_value=completed):
            with self.assertRaisesRegex(updater.UpdateError, "unexpected repository"):
                updater._validate_remote(Path("/tmp/source"), "git")

    def test_entrypoint_help_lists_update(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = entrypoint_main(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("sqliblind update --check", output.getvalue())

    def test_entrypoint_routes_update_command(self) -> None:
        with patch("blind_sqli.entrypoint.update_main", return_value=7) as update:
            self.assertEqual(entrypoint_main(["update", "--check"]), 7)
        update.assert_called_once_with(["--check"])


if __name__ == "__main__":
    unittest.main()
