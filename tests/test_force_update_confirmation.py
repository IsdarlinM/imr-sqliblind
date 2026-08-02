from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from blind_sqli.entrypoint import main as entrypoint_main


class ForcedUpdateConfirmationTests(unittest.TestCase):
    def test_force_update_warns_and_decline_skips_update(self) -> None:
        output = io.StringIO()
        errors = io.StringIO()
        with (
            patch("blind_sqli.entrypoint.sys.stdin", io.StringIO("n\n")),
            patch("blind_sqli.entrypoint.update_main") as update,
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            code = entrypoint_main(["--no-banner", "update", "--force"])

        self.assertEqual(code, 0)
        update.assert_not_called()
        warning = errors.getvalue()
        self.assertIn("Update warning.", warning)
        self.assertIn(
            "Saved changes could disappear during a forced update.",
            warning,
        )
        self.assertIn("Do you want to proceed? [y/N]:", warning)
        self.assertIn("Update cancelled.", warning)

    def test_force_update_accepts_yes_and_proceeds(self) -> None:
        errors = io.StringIO()
        with (
            patch("blind_sqli.entrypoint.sys.stdin", io.StringIO("yes\n")),
            patch("blind_sqli.entrypoint.update_main", return_value=7) as update,
            redirect_stdout(io.StringIO()),
            redirect_stderr(errors),
        ):
            code = entrypoint_main(["--no-banner", "update", "--force"])

        self.assertEqual(code, 7)
        update.assert_called_once_with(["--force"])
        self.assertIn("Update warning.", errors.getvalue())
        self.assertNotIn("Update cancelled.", errors.getvalue())

    def test_force_check_does_not_prompt(self) -> None:
        with (
            patch("blind_sqli.entrypoint._confirm_forced_update") as confirm,
            patch("blind_sqli.entrypoint.update_main", return_value=0) as update,
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            code = entrypoint_main(
                ["--no-banner", "update", "--check", "--force"]
            )

        self.assertEqual(code, 0)
        confirm.assert_not_called()
        update.assert_called_once_with(["--check", "--force"])

    def test_force_update_eof_cancels_safely(self) -> None:
        errors = io.StringIO()
        with (
            patch("blind_sqli.entrypoint.sys.stdin", io.StringIO("")),
            patch("blind_sqli.entrypoint.update_main") as update,
            redirect_stdout(io.StringIO()),
            redirect_stderr(errors),
        ):
            code = entrypoint_main(["--no-banner", "update", "--force"])

        self.assertEqual(code, 0)
        update.assert_not_called()
        self.assertIn("Update cancelled.", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
