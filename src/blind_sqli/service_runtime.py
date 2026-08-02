from __future__ import annotations

import json
import os
import secrets
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .auth import UserStore
from .service_config import atomic_write_json, load_config

_WINDOWS_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WINDOWS_ERROR_ACCESS_DENIED = 5
_WINDOWS_MAX_PID = 0xFFFFFFFF


def _service_python_executable() -> str:
    """Use the windowless Python launcher for detached Windows services."""

    executable = os.fspath(sys.executable)
    if os.name != "nt" or os.path.basename(executable).casefold() == "pythonw.exe":
        return executable
    windowless = os.path.join(os.path.dirname(executable), "pythonw.exe")
    return windowless if os.path.isfile(windowless) else executable


def _windows_process_options() -> tuple[int, Any | None]:
    """Return flags that detach the service and prevent a visible console window."""

    creationflags = (
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    startupinfo_factory = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_factory is None:
        return creationflags, None
    startupinfo = startupinfo_factory()
    startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    return creationflags, startupinfo


def add_inner_csrf_cookie_middleware(
    app: Any,
    *,
    csrf_token: str,
    secure: bool,
    session_hours: int,
) -> Any:
    @app.middleware("http")
    async def service_inner_csrf_cookie(request: Any, call_next: Any):
        response = await call_next(request)
        response.set_cookie(
            "sqliblind_csrf",
            csrf_token,
            httponly=False,
            secure=secure,
            samesite="strict",
            path="/",
            max_age=session_hours * 3600,
        )
        return response

    return app


def _windows_pid_running(pid: int) -> bool:
    """Check a Windows PID without using os.kill(pid, 0).

    CPython maps os.kill() to the Windows process termination API. Signal zero is
    therefore not a portable existence probe and may raise WinError 87 followed by
    SystemError. OpenProcess is the supported non-destructive check.
    """
    if pid <= 0 or pid > _WINDOWS_MAX_PID:
        return False

    import ctypes

    win_dll = getattr(ctypes, "WinDLL", None)
    get_last_error = getattr(ctypes, "get_last_error", None)
    if win_dll is None or get_last_error is None:  # pragma: no cover - defensive
        return False

    try:
        kernel32 = win_dll("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        open_process.restype = ctypes.c_void_p
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_int
        handle = open_process(
            _WINDOWS_PROCESS_QUERY_LIMITED_INFORMATION,
            0,
            pid,
        )
    except (AttributeError, OSError, TypeError, ValueError):
        return False

    if handle:
        try:
            return True
        finally:
            close_handle(handle)

    # Protected/system processes can deny query access while still existing.
    return int(get_last_error()) == _WINDOWS_ERROR_ACCESS_DENIED


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_running(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError, ValueError):
        return False
    return True


def _read_state(path: str | Path) -> dict[str, Any] | None:
    state_path = Path(path)
    try:
        value = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    return value


def _remove_state(path: str | Path, expected_token: str | None = None) -> None:
    state_path = Path(path)
    if expected_token is not None:
        current = _read_state(state_path)
        if current and current.get("control_token") != expected_token:
            return
    try:
        state_path.unlink(missing_ok=True)
    except OSError:
        pass


def _control_request(
    state: dict[str, Any],
    path: str,
    *,
    method: str = "GET",
    timeout: float = 2.0,
) -> dict[str, Any] | None:
    base_url = str(state.get("control_url", "")).strip().rstrip("/")
    token = str(state.get("control_token", "")).strip()
    if not base_url or not token:
        return None
    url = base_url + path
    request = urllib.request.Request(
        url,
        method=method,
        headers={"X-SQLIBLIND-SERVICE-CONTROL": token},
    )
    context = ssl._create_unverified_context() if url.startswith("https://") else None
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            payload = response.read(64_000)
    except (OSError, ValueError, urllib.error.URLError, urllib.error.HTTPError):
        return None
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _ensure_port_available(host: str, port: int) -> None:
    """Fail before spawning when the configured TCP endpoint is already reserved."""

    try:
        addresses = socket.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
            flags=socket.AI_PASSIVE,
        )
    except socket.gaierror as exc:
        raise RuntimeError(f"cannot resolve service host {host!r}: {exc}") from exc

    seen: set[tuple[int, int, int, tuple[Any, ...]]] = set()
    for family, socket_type, protocol, _, address in addresses:
        key = (family, socket_type, protocol, tuple(address))
        if key in seen:
            continue
        seen.add(key)
        probe = socket.socket(family, socket_type, protocol)
        try:
            # Match Uvicorn's POSIX socket behavior so a recently stopped
            # listener in TIME_WAIT does not look like a live port conflict.
            # Windows has different SO_REUSEADDR semantics, so keep the
            # exclusive default there.
            if os.name != "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(address)
            probe.listen(1)
        except OSError as exc:
            raise RuntimeError(
                f"service port {host}:{port} is already in use. "
                "No healthy imr-sqliblind service state was found. Stop the "
                "process using that port or choose another port with "
                "`sqliblind start --port PORT`."
            ) from exc
        finally:
            probe.close()


def _publish_state_after_start(
    server: Any,
    state_file: str | Path,
    state: dict[str, Any],
    stop_event: threading.Event,
    *,
    poll_interval: float = 0.02,
) -> bool:
    """Publish control state only after Uvicorn has successfully bound sockets."""

    while not stop_event.is_set():
        if bool(getattr(server, "started", False)):
            atomic_write_json(state_file, state)
            print(f"imr-sqliblind service listening at {state['url']}", flush=True)
            return True
        stop_event.wait(poll_interval)
    return False


def service_status(config_path: str | Path | None = None) -> dict[str, Any]:
    path, config = load_config(config_path)
    state = _read_state(config.state_file)
    if not state:
        return {"status": "stopped", "config": str(path)}
    try:
        pid = int(state.get("pid", 0))
    except (TypeError, ValueError):
        pid = 0

    # The authenticated control endpoint is authoritative and avoids relying on a
    # platform-specific PID probe for a healthy service.
    response = _control_request(state, "/api/service/status")
    if response and response.get("status") == "running":
        return {
            "status": "running",
            "pid": pid,
            "url": state.get("url"),
            "host": state.get("host"),
            "port": state.get("port"),
            "started_at": state.get("started_at"),
            "config": str(path),
            "log_file": state.get("log_file", config.log_file),
            "auth_database": state.get("auth_database", config.auth_database),
        }
    if not _pid_running(pid):
        _remove_state(config.state_file)
        return {
            "status": "stopped",
            "config": str(path),
            "stale_state_removed": True,
        }
    return {
        "status": "unresponsive",
        "pid": pid,
        "url": state.get("url"),
        "config": str(path),
        "log_file": state.get("log_file", config.log_file),
    }


def start_service(
    config_path: str | Path | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
    foreground: bool = False,
) -> dict[str, Any]:
    path, stored = load_config(config_path)
    config = stored.with_overrides(host=host, port=port)
    current = service_status(path)
    if current["status"] == "running":
        return {**current, "already_running": True}
    if current["status"] == "unresponsive":
        raise RuntimeError(
            "a service process exists but its control endpoint is unavailable; "
            "inspect the log and stop that process before starting another instance"
        )

    _ensure_port_available(config.host, config.port)
    if foreground:
        run_service(path, host=config.host, port=config.port)
        return {"status": "stopped", "foreground": True, "config": str(path)}

    log_path = Path(config.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        _service_python_executable(),
        "-m",
        "blind_sqli",
        "_service-run",
        "--config",
        str(path),
        "--host",
        config.host,
        "--port",
        str(config.port),
    ]
    creationflags = 0
    popen_kwargs: dict[str, Any] = {"close_fds": True}
    if os.name == "nt":
        creationflags, startupinfo = _windows_process_options()
        if startupinfo is not None:
            popen_kwargs["startupinfo"] = startupinfo
    else:
        popen_kwargs["start_new_session"] = True
    with log_path.open("ab", buffering=0) as log_handle:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            **popen_kwargs,
        )
    deadline = time.monotonic() + 12.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"service exited during startup with code {process.returncode}; "
                f"inspect {log_path}"
            )
        state = _read_state(config.state_file)
        if state:
            response = _control_request(state, "/api/service/status", timeout=0.5)
            if response and response.get("status") == "running":
                return service_status(path)
        time.sleep(0.1)
    raise RuntimeError(f"service did not become ready; inspect {log_path}")


def stop_service(
    config_path: str | Path | None = None,
    *,
    timeout: float = 12.0,
) -> dict[str, Any]:
    path, config = load_config(config_path)
    state = _read_state(config.state_file)
    if not state:
        return {
            "status": "stopped",
            "already_stopped": True,
            "config": str(path),
        }
    try:
        pid = int(state.get("pid", 0))
    except (TypeError, ValueError):
        pid = 0

    response = _control_request(state, "/api/service/shutdown", method="POST")
    if not response or response.get("status") != "stopping":
        if not _pid_running(pid):
            _remove_state(config.state_file)
            return {
                "status": "stopped",
                "stale_state_removed": True,
                "config": str(path),
            }
        raise RuntimeError(
            "service refused the authenticated shutdown request; inspect the service log"
        )
    deadline = time.monotonic() + max(1.0, min(timeout, 60.0))
    while time.monotonic() < deadline:
        if not _pid_running(pid):
            _remove_state(
                config.state_file,
                str(state.get("control_token", "")),
            )
            return {"status": "stopped", "pid": pid, "config": str(path)}
        time.sleep(0.1)
    raise RuntimeError("service did not stop cleanly before the shutdown timeout")


def restart_service(
    config_path: str | Path | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
) -> dict[str, Any]:
    status = service_status(config_path)
    if status["status"] in {"running", "unresponsive"}:
        stop_service(config_path)
    return start_service(config_path, host=host, port=port)


def run_service(
    config_path: str | Path | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
) -> None:
    path, stored = load_config(config_path)
    config = stored.with_overrides(host=host, port=port)
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Web dependencies are not installed. Reinstall with the native installer."
        ) from exc

    # Repeat the parent-side check in the detached child to close the race between
    # process creation and socket binding. State is still published only after the
    # server reports that binding succeeded.
    _ensure_port_available(config.host, config.port)

    from .manager import ScanManager
    from .service_admin_ui import create_admin_ui
    from .service_gateway import create_service_gateway
    from .store import SessionStore
    from .web_app import create_app

    workspace = Path(config.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    store = SessionStore(workspace / "sessions.db")
    manager = ScanManager(store)
    users = UserStore(config.auth_database)
    bootstrapped = users.bootstrap_admin()
    users.cleanup_sessions()

    internal_token = secrets.token_urlsafe(32)
    internal_csrf_token = secrets.token_urlsafe(32)
    control_token = secrets.token_urlsafe(32)
    tls_enabled = bool(config.ssl_certfile and config.ssl_keyfile)
    inner = create_app(
        manager,
        auth_token=internal_token,
        csrf_token=internal_csrf_token,
        secure_cookies=tls_enabled,
    )
    inner.mount("/admin", create_admin_ui(users))
    add_inner_csrf_cookie_middleware(
        inner,
        csrf_token=internal_csrf_token,
        secure=tls_enabled,
        session_hours=config.session_hours,
    )
    server_holder: dict[str, Any] = {}

    def shutdown() -> None:
        server = server_holder.get("server")
        if server is not None:
            server.should_exit = True

    gateway = create_service_gateway(
        inner,
        user_store=users,
        internal_token=internal_token,
        secure_cookies=tls_enabled,
        session_hours=config.session_hours,
        service_control_token=control_token,
        shutdown_callback=shutdown,
    )
    uvicorn_config = uvicorn.Config(
        gateway,
        host=config.host,
        port=config.port,
        log_level="info",
        access_log=False,
        ssl_certfile=config.ssl_certfile,
        ssl_keyfile=config.ssl_keyfile,
    )
    server = uvicorn.Server(uvicorn_config)
    server_holder["server"] = server
    browser_host = (
        "127.0.0.1" if config.host in {"0.0.0.0", "::"} else config.host
    )
    display_host = f"[{browser_host}]" if ":" in browser_host else browser_host
    scheme = "https" if tls_enabled else "http"
    url = f"{scheme}://{display_host}:{config.port}/"
    control_url = f"{scheme}://{display_host}:{config.port}"
    state = {
        "pid": os.getpid(),
        "host": config.host,
        "port": config.port,
        "url": url,
        "control_url": control_url,
        "control_token": control_token,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": str(path),
        "log_file": config.log_file,
        "auth_database": config.auth_database,
        "workspace": config.workspace,
    }
    publisher_stop = threading.Event()
    publisher = threading.Thread(
        target=_publish_state_after_start,
        args=(server, config.state_file, state, publisher_stop),
        name="sqliblind-service-state",
        daemon=True,
    )
    publisher.start()
    if bootstrapped:
        print(
            "SECURITY NOTICE: created bootstrap administrator admin/admin. "
            "The web console requires an immediate password change.",
            file=sys.stderr,
            flush=True,
        )
    if config.host not in {"127.0.0.1", "localhost", "::1"} and not tls_enabled:
        print(
            "WARNING: service is exposed remotely over unencrypted HTTP.",
            file=sys.stderr,
            flush=True,
        )
    try:
        server.run()
    finally:
        publisher_stop.set()
        publisher.join(timeout=1.0)
        _remove_state(config.state_file, control_token)
        manager.shutdown()
        store.close()


__all__ = [
    "add_inner_csrf_cookie_middleware",
    "restart_service",
    "run_service",
    "service_status",
    "start_service",
    "stop_service",
]
