from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from blind_sqli.entrypoint import main
from blind_sqli.terminal import (
    BRIGHT_GREEN,
    RED,
    RESET,
    SemanticColorStream,
    TerminalOptionError,
    TerminalOptions,
    build_banner,
    extract_terminal_options,
    is_machine_output,
    terminal_session,
)


class TtyBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:
        return 1


class TerminalPresentationTests(unittest.TestCase):
    def test_banner_has_requested_branding_and_fixed_width(self) -> None:
        banner = build_banner("9.8.7")
        lines = banner.splitlines()
        self.assertEqual(lines[0], "+--------------------------------------------------+")
        self.assertEqual(lines[-1], "+--------------------------------------------------+")
        self.assertEqual(len(lines), 5)
        self.assertTrue(all(len(line) == 52 for line in lines))
        self.assertIn("Blind SQL Injection", lines[1])
        self.assertIn("imr-sqliblind", lines[2])
        self.assertIn("imr :: v9.8.7", lines[3])

    def test_terminal_options_are_global_and_removed_before_dispatch(self) -> None:
        arguments, options = extract_terminal_options(
            ["status", "--color", "always", "--no-banner"]
        )
        self.assertEqual(arguments, ["status"])
        self.assertEqual(options, TerminalOptions(color="always", show_banner=False))

        arguments, options = extract_terminal_options(
            ["--color=never", "schemas", "--no-color"]
        )
        self.assertEqual(arguments, ["schemas"])
        self.assertEqual(options.color, "never")

    def test_invalid_color_value_is_rejected(self) -> None:
        with self.assertRaises(TerminalOptionError):
            extract_terminal_options(["--color", "rainbow", "schemas"])
        with self.assertRaises(TerminalOptionError):
            extract_terminal_options(["--color"])

    def test_no_color_environment_is_respected_in_auto_mode(self) -> None:
        environment = {"NO_COLOR": "1", "SQLIBLIND_COLOR": "auto"}
        with patch.dict(os.environ, environment, clear=False):
            _, options = extract_terminal_options(["schemas"])
        self.assertEqual(options.color, "never")

    def test_machine_readable_modes_are_detected(self) -> None:
        self.assertTrue(is_machine_output(["--json", "map"]))
        self.assertTrue(is_machine_output(["config", "show"]))
        self.assertTrue(is_machine_output(["map", "--format", "json"]))
        self.assertTrue(is_machine_output(["--version"]))
        self.assertFalse(is_machine_output(["status"]))

    def test_semantic_stream_colors_errors_without_changing_text(self) -> None:
        destination = io.StringIO()
        stream = SemanticColorStream(destination)
        source = "Error: controlled failure\n"
        written = stream.write(source)
        rendered = destination.getvalue()
        plain = (
            rendered.replace(RED, "")
            .replace("\x1b[1m", "")
            .replace(RESET, "")
        )
        self.assertEqual(written, len(source))
        self.assertIn(RED, rendered)
        self.assertIn(RESET, rendered)
        self.assertEqual(plain, source)

    def test_forced_color_and_banner_are_rendered_in_a_tty(self) -> None:
        stdout = TtyBuffer()
        stderr = TtyBuffer()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            with terminal_session(TerminalOptions(color="always")) as session:
                session.print_banner("9.8.7")
                print("Created user analyst (viewer).")
        rendered = stdout.getvalue()
        self.assertIn(BRIGHT_GREEN, rendered)
        self.assertIn("Blind SQL Injection", rendered)
        self.assertIn("imr :: v9.8.7", rendered)
        self.assertIn("Created user analyst", rendered)
        self.assertIn("\x1b[", rendered)

    def test_machine_output_never_receives_ansi_or_banner(self) -> None:
        stdout = TtyBuffer()
        with redirect_stdout(stdout):
            with terminal_session(
                TerminalOptions(color="always"),
                machine_output=True,
            ) as session:
                session.print_banner("9.8.7")
                print('{"result": true}')
        self.assertEqual(stdout.getvalue(), '{"result": true}\n')

    def test_help_displays_green_banner_and_terminal_options(self) -> None:
        stdout = TtyBuffer()
        stderr = TtyBuffer()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(["--color", "always", "--help"])
        rendered = stdout.getvalue()
        self.assertEqual(result, 0)
        self.assertIn("Blind SQL Injection", rendered)
        self.assertIn("--color auto", rendered)
        self.assertIn("--no-banner", rendered)
        self.assertIn("\x1b[", rendered)

    def test_no_banner_option_keeps_help_available(self) -> None:
        stdout = TtyBuffer()
        with redirect_stdout(stdout):
            result = main(["--no-banner", "--color", "never", "--help"])
        self.assertEqual(result, 0)
        self.assertNotIn("Blind SQL Injection", stdout.getvalue())
        self.assertIn("usage:", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
