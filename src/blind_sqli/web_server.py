from __future__ import annotations

import secrets
import webbrowser
from pathlib import Path

from .manager import ScanManager
from .store import SessionStore
from .web_app import create_app
from .web_support import default_workspace, is_loopback


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
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    remote = not is_loopback(host)
    if remote and not allow_remote:
        raise ValueError("Non-loopback hosts require --allow-remote")
    if remote and not token:
        raise ValueError("Remote access requires an explicit --token")
    if bool(ssl_certfile) != bool(ssl_keyfile):
        raise ValueError("--ssl-certfile and --ssl-keyfile must be used together")
    if remote and not (ssl_certfile and ssl_keyfile):
        raise ValueError("Remote access requires TLS certificate and key files")
    for label, path in (("certificate", ssl_certfile), ("key", ssl_keyfile)):
        if path and not Path(path).expanduser().is_file():
            raise ValueError(f"TLS {label} file was not found")
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
        secure_cookies=bool(ssl_certfile and ssl_keyfile),
    )
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    scheme = "https" if ssl_certfile and ssl_keyfile else "http"
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
