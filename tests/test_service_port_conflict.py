from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from blind_sqli import service_runtime


def test_port_guard_rejects_an_active_listener() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = int(listener.getsockname()[1])
    try:
        with pytest.raises(RuntimeError, match="already in use"):
            service_runtime._ensure_port_available("127.0.0.1", port)
    finally:
        listener.close()


def test_port_guard_accepts_a_free_loopback_port() -> None:
    temporary = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    temporary.bind(("127.0.0.1", 0))
    port = int(temporary.getsockname()[1])
    temporary.close()

    service_runtime._ensure_port_available("127.0.0.1", port)


def test_state_is_not_published_before_server_binds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    server = SimpleNamespace(started=False)
    stop_event = threading.Event()
    writes: list[tuple[Path, dict[str, object]]] = []

    def capture(path: str | Path, state: dict[str, object]) -> Path:
        destination = Path(path)
        writes.append((destination, state))
        return destination

    monkeypatch.setattr(service_runtime, "atomic_write_json", capture)
    thread = threading.Thread(
        target=service_runtime._publish_state_after_start,
        args=(
            server,
            tmp_path / "service.json",
            {"url": "http://127.0.0.1:43127/"},
            stop_event,
        ),
        kwargs={"poll_interval": 0.005},
    )
    thread.start()
    time.sleep(0.03)
    assert writes == []

    server.started = True
    thread.join(timeout=1.0)
    assert not thread.is_alive()
    assert writes == [
        (
            tmp_path / "service.json",
            {"url": "http://127.0.0.1:43127/"},
        )
    ]


def test_failed_start_never_publishes_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    server = SimpleNamespace(started=False)
    stop_event = threading.Event()
    writes: list[object] = []
    monkeypatch.setattr(
        service_runtime,
        "atomic_write_json",
        lambda *_args, **_kwargs: writes.append(object()),
    )
    thread = threading.Thread(
        target=service_runtime._publish_state_after_start,
        args=(
            server,
            tmp_path / "service.json",
            {"url": "http://127.0.0.1:43127/"},
            stop_event,
        ),
        kwargs={"poll_interval": 0.005},
    )
    thread.start()
    stop_event.set()
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert writes == []
