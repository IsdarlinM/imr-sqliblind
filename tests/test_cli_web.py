from __future__ import annotations

import unittest
from unittest.mock import patch

from blind_sqli.cli import build_parser, main
from blind_sqli.web import _default_workspace, _is_loopback, launch_web_server


class CliWebTests(unittest.TestCase):
    def test_web_and_rows_arguments_parse(self) -> None:
        parser = build_parser()
        web = parser.parse_args(
            ["web", "--host", "127.0.0.1", "--port", "9000", "--no-open-browser"]
        )
        self.assertEqual(web.command, "web")
        self.assertEqual(web.port, 9000)
        remote = parser.parse_args(
            [
                "web",
                "--host",
                "0.0.0.0",
                "--allow-remote",
                "--token",
                "secret",
                "--ssl-certfile",
                "server.crt",
                "--ssl-keyfile",
                "server.key",
                "--workspace",
                "sessions",
            ]
        )
        self.assertTrue(remote.allow_remote)
        self.assertEqual(remote.ssl_certfile, "server.crt")
        self.assertEqual(remote.ssl_keyfile, "server.key")
        self.assertEqual(remote.workspace, "sessions")
        rows = parser.parse_args(
            [
                "rows",
                "--schema",
                "main",
                "--table",
                "users",
                "--max-rows",
                "3",
            ]
        )
        self.assertEqual(rows.command, "rows")
        self.assertEqual(rows.max_rows, 3)
        mapping = parser.parse_args(
            [
                "map",
                "--include-data",
                "--data-table",
                "main.users",
                "--max-value-length",
                "64",
            ]
        )
        self.assertTrue(mapping.include_data)
        self.assertEqual(mapping.data_table, ["main.users"])

    def test_main_routes_web_without_building_http_extractor(self) -> None:
        with patch("blind_sqli.web.launch_web_server") as launch:
            code = main(["web", "--no-open-browser"])
        self.assertEqual(code, 0)
        launch.assert_called_once()

    def test_default_workspace_uses_configured_install_home(self) -> None:
        with patch.dict("os.environ", {"IMR_SQLIBLIND_HOME": "/tmp/sqliblind-home"}):
            self.assertEqual(
                _default_workspace().as_posix(),
                "/tmp/sqliblind-home/workspaces",
            )

    def test_remote_binding_requires_explicit_controls(self) -> None:
        self.assertTrue(_is_loopback("127.0.0.1"))
        self.assertTrue(_is_loopback("::1"))
        self.assertFalse(_is_loopback("0.0.0.0"))
        with self.assertRaises(ValueError):
            launch_web_server(host="0.0.0.0", open_browser=False)
        with self.assertRaises(ValueError):
            launch_web_server(
                host="0.0.0.0", allow_remote=True, open_browser=False
            )
        with self.assertRaises(ValueError):
            launch_web_server(
                host="0.0.0.0",
                allow_remote=True,
                token="secret",
                open_browser=False,
            )


if __name__ == "__main__":
    unittest.main()
