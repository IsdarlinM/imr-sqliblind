from __future__ import annotations

from pathlib import Path

from blind_sqli import service_runtime


def test_windows_service_uses_pythonw_when_available(
    monkeypatch,
    tmp_path: Path,
) -> None:
    python = tmp_path / "python.exe"
    pythonw = tmp_path / "pythonw.exe"
    python.write_bytes(b"")
    pythonw.write_bytes(b"")
    monkeypatch.setattr(service_runtime.os, "name", "nt")
    monkeypatch.setattr(service_runtime.sys, "executable", str(python))

    assert service_runtime._service_python_executable() == str(pythonw)


def test_windows_service_falls_back_when_pythonw_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    python = tmp_path / "python.exe"
    python.write_bytes(b"")
    monkeypatch.setattr(service_runtime.os, "name", "nt")
    monkeypatch.setattr(service_runtime.sys, "executable", str(python))

    assert service_runtime._service_python_executable() == str(python)


def test_windows_process_options_hide_and_detach_console(monkeypatch) -> None:
    class StartupInfo:
        def __init__(self) -> None:
            self.dwFlags = 2
            self.wShowWindow = -1

    monkeypatch.setattr(
        service_runtime.subprocess,
        "CREATE_NEW_PROCESS_GROUP",
        1,
        raising=False,
    )
    monkeypatch.setattr(
        service_runtime.subprocess,
        "DETACHED_PROCESS",
        2,
        raising=False,
    )
    monkeypatch.setattr(
        service_runtime.subprocess,
        "CREATE_NO_WINDOW",
        4,
        raising=False,
    )
    monkeypatch.setattr(
        service_runtime.subprocess,
        "STARTF_USESHOWWINDOW",
        8,
        raising=False,
    )
    monkeypatch.setattr(
        service_runtime.subprocess,
        "SW_HIDE",
        0,
        raising=False,
    )
    monkeypatch.setattr(
        service_runtime.subprocess,
        "STARTUPINFO",
        StartupInfo,
        raising=False,
    )

    flags, startupinfo = service_runtime._windows_process_options()

    assert flags == 7
    assert startupinfo is not None
    assert startupinfo.dwFlags == 10
    assert startupinfo.wShowWindow == 0


def test_non_windows_service_keeps_current_interpreter(
    monkeypatch,
    tmp_path: Path,
) -> None:
    python = tmp_path / "python"
    python.write_bytes(b"")
    monkeypatch.setattr(service_runtime.os, "name", "posix")
    monkeypatch.setattr(service_runtime.sys, "executable", str(python))

    assert service_runtime._service_python_executable() == str(python)
