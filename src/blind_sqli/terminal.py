from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, TextIO

_COLOR_MODES = {"auto", "always", "never"}
_BANNER_WIDTH = 50
_ANSI_SEQUENCE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_COMMAND_LINE = re.compile(
    r"^(?P<indent>\s{2,})(?P<command>"
    r"(?:-{1,2}[\w-]+|\{[^}]+\}|schemas|tables|columns|extract|probe|rows|map|"
    r"graph|schema-map|web|start|stop|restart|status|users|config|update))(?=\s|$)"
)
_LIST_ITEM = re.compile(r"^(?P<indent>\s*)(?P<index>\[\d+\])(?P<rest>.*)$")
_LABEL_LINE = re.compile(
    r"^(?P<label>Installed version|Available version|Repository|Source|"
    r"Updated service configuration|Service configuration|Service|Oracle calibrated|"
    r"Report written|Home|Python|Command|Native)(?P<separator>:\s*)(?P<value>.*)$",
    re.IGNORECASE,
)

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
GREEN = "\x1b[38;5;114m"
BRIGHT_GREEN = "\x1b[38;5;120m"
CYAN = "\x1b[38;5;80m"
BLUE = "\x1b[38;5;75m"
VIOLET = "\x1b[38;5;141m"
YELLOW = "\x1b[38;5;186m"
RED = "\x1b[38;5;174m"
GRAY = "\x1b[38;5;245m"


class TerminalOptionError(ValueError):
    """Raised when a terminal presentation option is invalid."""


@dataclass(frozen=True, slots=True)
class TerminalOptions:
    color: str = "auto"
    show_banner: bool = True


@dataclass(slots=True)
class TerminalSession:
    options: TerminalOptions
    machine_output: bool
    stdout: TextIO
    stderr: TextIO
    stdout_color: bool
    stderr_color: bool

    def print_banner(self, version: str) -> None:
        if self.machine_output or not self.options.show_banner:
            return
        if not _isatty(self.stdout):
            return
        banner = build_banner(version)
        if self.stdout_color:
            banner = paint(banner, BOLD, BRIGHT_GREEN)
        self.stdout.write(banner + "\n")
        self.stdout.flush()


def build_banner(version: str) -> str:
    """Return the compact, fixed-width imr-sqliblind banner."""

    lines = [
        "+" + ("-" * _BANNER_WIDTH) + "+",
        "|" + "Blind SQL Injection".center(_BANNER_WIDTH) + "|",
        "|" + "imr-sqliblind".center(_BANNER_WIDTH) + "|",
        "|" + f"imr :: v{version}".center(_BANNER_WIDTH) + "|",
        "+" + ("-" * _BANNER_WIDTH) + "+",
    ]
    return "\n".join(lines)


def paint(text: str, *codes: str) -> str:
    return "".join(codes) + text + RESET


def extract_terminal_options(
    argv: Sequence[str],
) -> tuple[list[str], TerminalOptions]:
    """Remove global terminal options while preserving all command arguments."""

    configured = os.environ.get("SQLIBLIND_COLOR", "auto").strip().casefold()
    if configured not in _COLOR_MODES:
        configured = "auto"
    color = (
        "never"
        if "NO_COLOR" in os.environ and configured == "auto"
        else configured
    )
    show_banner = True
    cleaned: list[str] = []
    index = 0
    values = list(argv)
    while index < len(values):
        value = values[index]
        if value == "--no-color":
            color = "never"
        elif value == "--no-banner":
            show_banner = False
        elif value == "--color":
            index += 1
            if index >= len(values):
                raise TerminalOptionError("--color requires auto, always, or never")
            color = values[index].strip().casefold()
            if color not in _COLOR_MODES:
                raise TerminalOptionError("--color must be auto, always, or never")
        elif value.startswith("--color="):
            color = value.split("=", 1)[1].strip().casefold()
            if color not in _COLOR_MODES:
                raise TerminalOptionError("--color must be auto, always, or never")
        else:
            cleaned.append(value)
        index += 1
    return cleaned, TerminalOptions(color=color, show_banner=show_banner)


def is_machine_output(argv: Sequence[str]) -> bool:
    """Detect command modes whose stdout must remain byte-clean."""

    values = list(argv)
    if "--json" in values or "_service-run" in values or "--version" in values:
        return True
    if len(values) >= 2 and values[0] == "config" and values[1] == "show":
        return True
    for index, value in enumerate(values):
        if value == "--format" and index + 1 < len(values):
            if values[index + 1].casefold() == "json":
                return True
        elif value.casefold() == "--format=json":
            return True
    return False


def _isatty(stream: TextIO) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, OSError):
        return False


def _enable_windows_ansi(stream: TextIO) -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes

        file_descriptor = stream.fileno()
        standard_handle = -11 if file_descriptor == 1 else -12
        kernel32 = getattr(ctypes, "windll").kernel32
        handle = kernel32.GetStdHandle(standard_handle)
        mode = ctypes.c_uint()
        if handle in (0, -1) or not kernel32.GetConsoleMode(
            handle,
            ctypes.byref(mode),
        ):
            return False
        enable_virtual_terminal_processing = 0x0004
        return bool(
            kernel32.SetConsoleMode(
                handle,
                mode.value | enable_virtual_terminal_processing,
            )
        )
    except (AttributeError, OSError, ValueError):
        return False


def _color_enabled(mode: str, stream: TextIO) -> bool:
    if mode == "never":
        return False
    if mode == "always":
        return True
    if "NO_COLOR" in os.environ:
        return False
    if os.environ.get("TERM", "").casefold() == "dumb":
        return False
    return _isatty(stream) and _enable_windows_ansi(stream)


def _split_control_prefix(value: str) -> tuple[str, str]:
    position = 0
    while position < len(value):
        match = _ANSI_SEQUENCE.match(value[position:])
        if match is None:
            break
        position += match.end()
    return value[:position], value[position:]


def _paint_label(line: str) -> str | None:
    match = _LABEL_LINE.match(line)
    if match is None:
        return None
    label = paint(match.group("label"), BOLD, CYAN)
    value = match.group("value")
    if match.group("label").casefold() == "service":
        normalized = value.casefold()
        if normalized == "running":
            value = paint(value, BOLD, GREEN)
        elif normalized in {"stopped", "unknown"}:
            value = paint(value, BOLD, YELLOW)
        else:
            value = paint(value, BOLD, RED)
    return label + match.group("separator") + value


def _style_visible_line(line: str) -> str:
    if not line or _ANSI_SEQUENCE.search(line):
        return line
    stripped = line.lstrip()
    if not stripped:
        return line

    lowered = stripped.casefold()
    if lowered.startswith(("error:", "update error:", "[x]", "fatal:")):
        return paint(line, BOLD, RED)
    if lowered.startswith(("interrupted by user", "warning:", "[!]")):
        return paint(line, BOLD, YELLOW)
    if stripped.startswith("SQLIBLIND ACTIVITY"):
        return paint(line, BOLD, GREEN)
    if stripped.startswith("Findings:"):
        return paint(line, YELLOW)
    if stripped[0] in "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏":
        return paint(line, GREEN)
    if stripped.startswith("✓"):
        return paint(line, GREEN)
    if stripped.startswith("×"):
        return paint(line, RED)
    if stripped.startswith("→"):
        return paint(line, CYAN)
    if stripped.startswith("Requests:"):
        return paint(line, DIM, CYAN)
    if stripped == "USERNAME                      ROLE      STATE       EXPIRES":
        return paint(line, BOLD, GREEN)
    if lowered.startswith("usage:"):
        return paint(line, BOLD, GREEN)
    if stripped.endswith(":") and lowered in {
        "options:",
        "positional arguments:",
        "additional commands:",
        "service examples:",
        "update examples:",
        "terminal presentation:",
    }:
        return paint(line, BOLD, GREEN)

    label_line = _paint_label(line)
    if label_line is not None:
        return label_line

    command = _COMMAND_LINE.match(line)
    if command is not None:
        start, end = command.span("command")
        return line[:start] + paint(line[start:end], BOLD, CYAN) + line[end:]

    item = _LIST_ITEM.match(line)
    if item is not None:
        return (
            item.group("indent")
            + paint(item.group("index"), BOLD, GREEN)
            + item.group("rest")
        )

    if lowered.startswith("update available:"):
        return paint(line, BOLD, YELLOW)
    if lowered.startswith(
        (
            "created user ",
            "enabled ",
            "disabled ",
            "deleted ",
            "password reset ",
            "set ",
            "updated expiration ",
            "updated imr-sqliblind ",
            "imr-sqliblind ",
            "installation completed",
        )
    ):
        return paint(line, GREEN)
    if lowered.startswith(
        (
            "bootstrap login ",
            "the service was already ",
            "open a new ",
        )
    ):
        return paint(line, YELLOW)
    return line


class SemanticColorStream:
    """Color semantic terminal lines while preserving the original text content."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def write(self, value: str) -> int:
        if not value:
            self._stream.write(value)
            return 0
        rendered: list[str] = []
        for part in value.splitlines(keepends=True):
            if part.endswith("\r\n"):
                body, ending = part[:-2], "\r\n"
            elif part.endswith(("\n", "\r")):
                body, ending = part[:-1], part[-1]
            else:
                body, ending = part, ""
            control, visible = _split_control_prefix(body)
            rendered.append(control + _style_visible_line(visible) + ending)
        self._stream.write("".join(rendered))
        return len(value)

    def flush(self) -> None:
        self._stream.flush()

    def isatty(self) -> bool:
        return _isatty(self._stream)

    def fileno(self) -> int:
        return self._stream.fileno()

    @property
    def encoding(self) -> str | None:
        return getattr(self._stream, "encoding", None)

    @property
    def errors(self) -> str | None:
        return getattr(self._stream, "errors", None)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


@contextmanager
def terminal_session(
    options: TerminalOptions,
    *,
    machine_output: bool = False,
) -> Iterator[TerminalSession]:
    """Temporarily install semantic stdout/stderr coloring for one CLI invocation."""

    original_stdout = sys.stdout
    original_stderr = sys.stderr
    stdout_color = (
        not machine_output and _color_enabled(options.color, original_stdout)
    )
    stderr_color = (
        not machine_output and _color_enabled(options.color, original_stderr)
    )
    if stdout_color:
        sys.stdout = SemanticColorStream(original_stdout)  # type: ignore[assignment]
    if stderr_color:
        sys.stderr = SemanticColorStream(original_stderr)  # type: ignore[assignment]
    session = TerminalSession(
        options=options,
        machine_output=machine_output,
        stdout=sys.stdout,
        stderr=sys.stderr,
        stdout_color=stdout_color,
        stderr_color=stderr_color,
    )
    try:
        yield session
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr


__all__ = [
    "BRIGHT_GREEN",
    "RED",
    "RESET",
    "SemanticColorStream",
    "TerminalOptionError",
    "TerminalOptions",
    "TerminalSession",
    "build_banner",
    "extract_terminal_options",
    "is_machine_output",
    "paint",
    "terminal_session",
]
