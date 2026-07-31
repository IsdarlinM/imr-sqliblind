from __future__ import annotations

import json
import os
import secrets
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .auth import UserStore
from .service_config import atomic_write_json, load_config


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


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_state(path: str | Path) -> dict[str, Any] | None:
    state_path = Path(path)
    try:
        value = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
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
    url = str(state.get("control_url", "")).rstrip("/") + path
    token = str(state.get("control_token", ""))
    if not url or not token:
        return None
    request = urllib.request.Request(
        url,
        method=method,
        headers={"X-SQLIBLIND-SERVICE-CONTROL": token},
    )
    context = ssl._create_unverified_context() if url.startswith("https://") else None
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            payload = response.read(64_000)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError):
        return None
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def service_status(config_path: str | Path | None = None) -> dict[str, Any]:
    path, config = load_config(config_path)
    state = _read_state(config.state_file)
    if not state:
        return {"status": "stopped", "config": str(path)}
    try:
        pid = int(state.get("pid", 0))
    except (TypeError, ValueError):
        pid = 0
    if not _pid_running(pid):
        _remove_state(config.state_file)
        return {
            "status": "stopped",
            "config": str(path),
            "stale_state_removed": True,
        }
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
    if foreground:
        run_service(path, host=config.host, port=config.port)
        return {"status": "stopped", "foreground": True, "config": str(path)}

    log_path = Path(config.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
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
    popen_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    else:
        popen_kwargs.update(start_new_session=True, close_fds=True)
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
    if not _pid_running(pid):
        _remove_state(config.state_file)
        return {
            "status": "stopped",
            "stale_state_removed": True,
            "config": str(path),
        }
    response = _control_request(state, "/api/service/shutdown", method="POST")
    if not response or response.get("status") != "stopping":
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
    atomic_write_json(config.state_file, state)
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
    print(f"imr-sqliblind service listening at {url}", flush=True)
    try:
        server.run()
    finally:
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
