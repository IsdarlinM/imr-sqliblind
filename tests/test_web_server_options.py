from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from blind_sqli.web_server import _validate_server_options


class WebServerOptionTests(unittest.TestCase):
    def test_remote_http_is_allowed_with_explicit_token(self) -> None:
        remote = _validate_server_options(
            host="0.0.0.0",
            port=8088,
            allow_remote=True,
            token="test-token",
            ssl_certfile=None,
            ssl_keyfile=None,
        )

        self.assertTrue(remote)

    def test_remote_host_still_requires_allow_remote(self) -> None:
        with self.assertRaisesRegex(ValueError, "--allow-remote"):
            _validate_server_options(
                host="0.0.0.0",
                port=8088,
                allow_remote=False,
                token="test-token",
                ssl_certfile=None,
                ssl_keyfile=None,
            )

    def test_remote_host_still_requires_token(self) -> None:
        with self.assertRaisesRegex(ValueError, "explicit --token"):
            _validate_server_options(
                host="0.0.0.0",
                port=8088,
                allow_remote=True,
                token=None,
                ssl_certfile=None,
                ssl_keyfile=None,
            )

    def test_tls_files_must_be_supplied_as_a_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            certificate = Path(directory) / "server.crt"
            certificate.write_text("test", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be used together"):
                _validate_server_options(
                    host="0.0.0.0",
                    port=8088,
                    allow_remote=True,
                    token="test-token",
                    ssl_certfile=certificate,
                    ssl_keyfile=None,
                )

    def test_remote_tls_remains_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            certificate = Path(directory) / "server.crt"
            key = Path(directory) / "server.key"
            certificate.write_text("test", encoding="utf-8")
            key.write_text("test", encoding="utf-8")

            remote = _validate_server_options(
                host="0.0.0.0",
                port=8088,
                allow_remote=True,
                token="test-token",
                ssl_certfile=certificate,
                ssl_keyfile=key,
            )

        self.assertTrue(remote)


if __name__ == "__main__":
    unittest.main()
