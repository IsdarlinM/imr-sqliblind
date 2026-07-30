from __future__ import annotations

import secrets
import sys
import webbrowser
from pathlib import Path

from .manager import ScanManager
from .store import SessionStore
from .web_app import create_app
from .web_support import default_workspace, is_loopback


def _validate_server_options(
    *,
    host: str,
    port: int,
    allow_remote: bool,
    token: str | None,
    ssl_certfile: str | Path | None,
    ssl_keyfile: str | Path | None,
) -> bool:
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    remote = not is_loopback(host)
    if remote and not allow_remote:
        raise ValueError("Non-loopback hosts require --allow-remote")
    if remote and not token:
        raise ValueError("Remote access requires an explicit --token")
    if bool(ssl_certfile) != bool(ssl_keyfile):
        raise ValueError("--ssl-certfile and --ssl-keyfile must be used together")
    for label, path in (("certificate", ssl_certfile), ("key", ssl_keyfile)):
        if path and not Path(path).expanduser().is_file():
            raise ValueError(f"TLS {label} file was not found")
    return remote


def launch_web_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8088,
    workspace: str | Path | None = None,
    allow_remote: bool = False,
    token: str | None = None,
    ssl_certfile: str | Path | None = None,
    ssl_keyfile: str | Path | None = None,
    open_browser: bool = True,
) -> None:
    remote = _validate_server_options(
        host=host,
        port=port,
        allow_remote=allow_remote,
        token=token,
        ssl_certfile=ssl_certfile,
        ssl_keyfile=ssl_keyfile,
    )
    tls_enabled = bool(ssl_certfile and ssl_keyfile)
    if remote and not tls_enabled:
        print(
            "WARNING: Remote web access is running over unencrypted HTTP. "
            "The token, session metadata, and scan results may be visible to other "
            "devices on the network. Use only on a trusted network or enable TLS.",
            file=sys.stderr,
        )
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Web dependencies are not installed. Reinstall with the native installer."
        ) from exc

    auth_token = token or secrets.token_urlsafe(32)
    workspace_root = Path(workspace).expanduser() if workspace else default_workspace()
    workspace_root.mkdir(parents=True, exist_ok=True)
    store = SessionStore(workspace_root / "sessions.db")
    manager = ScanManager(store)
    app = create_app(
        manager,
        auth_token=auth_token,
        secure_cookies=tls_enabled,
    )
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    scheme = "https" if tls_enabled else "http"
    url = f"{scheme}://{browser_host}:{port}/?token={auth_token}"
    print("imr-sqliblind realtime console")
    print(f"Workspace: {store.path}")
    print(f"Open: {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level="info",
            access_log=False,
            ssl_certfile=str(Path(ssl_certfile).expanduser()) if ssl_certfile else None,
            ssl_keyfile=str(Path(ssl_keyfile).expanduser()) if ssl_keyfile else None,
        )
    finally:
        manager.shutdown()
        store.close()


__all__ = ["_validate_server_options", "launch_web_server"]
