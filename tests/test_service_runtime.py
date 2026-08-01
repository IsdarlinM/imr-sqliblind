from __future__ import annotations

import ctypes
from pathlib import Path
from types import SimpleNamespace

import pytest

from blind_sqli import service_runtime


class _FakeFunction:
    def __init__(self, result):
        self.result = result
        self.calls = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.calls.append(args)
        return self.result


class _FakeKernel32:
    def __init__(self, open_result):
        self.OpenProcess = _FakeFunction(open_result)
        self.CloseHandle = _FakeFunction(1)


def test_windows_pid_probe_uses_openprocess_not_os_kill(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(service_runtime.os, "name", "nt")
    monkeypatch.setattr(
        service_runtime,
        "_windows_pid_running",
        lambda pid: calls.append(pid) or True,
    )

    def fail_kill(*_args):
        raise AssertionError("os.kill must not be called on Windows")

    monkeypatch.setattr(service_runtime.os, "kill", fail_kill)
    assert service_runtime._pid_running(1234) is True
    assert calls == [1234]


@pytest.mark.parametrize(
    ("open_result", "last_error", "expected"),
    [
        (123, 0, True),
        (None, 5, True),
        (None, 87, False),
    ],
)
def test_windows_pid_probe_interprets_native_results(
    monkeypatch,
    open_result,
    last_error,
    expected,
) -> None:
    kernel32 = _FakeKernel32(open_result)
    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda *_args, **_kwargs: kernel32,
        raising=False,
    )
    monkeypatch.setattr(
        ctypes,
        "get_last_error",
        lambda: last_error,
        raising=False,
    )

    assert service_runtime._windows_pid_running(4321) is expected
    if open_result:
        assert kernel32.CloseHandle.calls == [(open_result,)]


def test_control_request_rejects_incomplete_state_without_opening_url(monkeypatch) -> None:
    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("urlopen must not receive a relative control URL")

    monkeypatch.setattr(service_runtime.urllib.request, "urlopen", fail_urlopen)
    assert (
        service_runtime._control_request(
            {"control_token": "token-without-url"},
            "/api/service/status",
        )
        is None
    )


def test_service_status_trusts_authenticated_control_before_pid_probe(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = SimpleNamespace(
        state_file=str(tmp_path / "state.json"),
        log_file=str(tmp_path / "service.log"),
        auth_database=str(tmp_path / "users.db"),
    )
    state = {
        "pid": 9001,
        "url": "http://127.0.0.1:43127/",
        "host": "127.0.0.1",
        "port": 43127,
        "control_url": "http://127.0.0.1:43127",
        "control_token": "secret",
    }
    monkeypatch.setattr(
        service_runtime,
        "load_config",
        lambda _path: (tmp_path / "service.json", config),
    )
    monkeypatch.setattr(service_runtime, "_read_state", lambda _path: state)
    monkeypatch.setattr(
        service_runtime,
        "_control_request",
        lambda *_args, **_kwargs: {"status": "running"},
    )

    def fail_pid_probe(_pid):
        raise AssertionError("healthy service must not require a PID probe")

    monkeypatch.setattr(service_runtime, "_pid_running", fail_pid_probe)
    result = service_runtime.service_status(tmp_path / "service.json")
    assert result["status"] == "running"
    assert result["pid"] == 9001
