
import asyncio
import html
import ipaddress
import json
import os
import secrets
import webbrowser
from importlib import resources
from pathlib import Path
from typing import Any

from . import __version__
from .manager import ScanManager, ScanSettings
from .store import SessionStore


TERMINAL_STATUSES = {"completed", "failed", "cancelled", "interrupted"}
AUTH_COOKIE = "sqliblind_session"
CSRF_COOKIE = "sqliblind_csrf"


def _is_loopback(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False



def _default_workspace() -> Path:
    configured = os.environ.get("IMR_SQLIBLIND_HOME")
    if configured:
        return Path(configured).expanduser() / "workspaces"
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        root = Path(local) if local else Path.home() / "AppData" / "Local"
        return root / "Programs" / "imr-sqliblind" / "workspaces"
    xdg = os.environ.get("XDG_DATA_HOME")
    root = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return root / "imr-sqliblind" / "workspaces"


def _load_ui(csrf_token: str, nonce: str) -> str:
    document = (
        resources.files("blind_sqli")
        .joinpath("webui/index.html")
        .read_text(encoding="utf-8")
    )
    return (
        document.replace("__CSRF__", html.escape(csrf_token, quote=True))
        .replace("__NONCE__", html.escape(nonce, quote=True))
        .replace("__VERSION__", html.escape(__version__, quote=True))
    )


def _load_asset(name: str) -> str:
    if name not in {"app.css", "app.js"}:
        raise ValueError("unsupported web asset")
    return (
        resources.files("blind_sqli")
        .joinpath(f"webui/{name}")
        .read_text(encoding="utf-8")
    )


def create_app(
    manager: ScanManager,
    *,
    auth_token: str,
    csrf_token: str | None = None,
    secure_cookies: bool = False,
):
    try:
        from fastapi import Depends, FastAPI, HTTPException, Query, Request
        from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
        from fastapi.responses import StreamingResponse
        from pydantic import BaseModel, Field
    except ImportError as exc:  # pragma: no cover - exercised when optional deps missing
        raise RuntimeError(
            "Web dependencies are not installed. Reinstall with: pip install 'imr-sqliblind[web]'"
        ) from exc

    csrf = csrf_token or secrets.token_urlsafe(32)
    app = FastAPI(
        title="imr-sqliblind",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    class ScanRequest(BaseModel):
        url: str = Field(min_length=1, max_length=4096)
        parameter: str = Field(default="id", min_length=1, max_length=128)
        url_template: str | None = Field(default=None, max_length=4096)
        dialect: str = "mysql"
        oracle: str = "status"
        true_statuses: str | list[int] = "200"
        true_marker: str | None = Field(default=None, max_length=1024)
        true_regex: str | None = Field(default=None, max_length=1024)
        true_length: int | None = Field(default=None, ge=0)
        length_tolerance: int = Field(default=0, ge=0, le=100000)
        timeout: float = Field(default=10.0, gt=0, le=120)
        retries: int = Field(default=1, ge=0, le=5)
        delay: float = Field(default=0.1, ge=0, le=60)
        max_requests: int = Field(default=5000, ge=1, le=1_000_000)
        workers: int = Field(default=4, ge=1, le=16)
        max_length: int = Field(default=128, ge=1, le=4096)
        max_items: int = Field(default=128, ge=1, le=4096)
        min_char_code: int = Field(default=32, ge=0, le=0x10FFFF)
        max_char_code: int = Field(default=126, ge=0, le=0x10FFFF)
        headers: dict[str, str] = Field(default_factory=dict)
        cookies: dict[str, str] = Field(default_factory=dict)
        proxy: str | None = Field(default=None, max_length=2048)
        insecure: bool = False
        skip_calibration: bool = False
        include_data: bool = False
        data_tables: str | list[str] = ""
        max_rows: int = Field(default=5, ge=1, le=25)
        max_data_columns: int = Field(default=10, ge=1, le=20)
        max_value_length: int = Field(default=128, ge=1, le=512)
        max_data_bytes: int = Field(default=10000, ge=1, le=50000)
        reveal_sensitive_values: bool = False

    def _authorized(request: Request) -> None:
        supplied = request.cookies.get(AUTH_COOKIE) or request.headers.get(
            "X-SQLIBLIND-TOKEN", ""
        )
        if not supplied or not secrets.compare_digest(supplied, auth_token):
            raise HTTPException(status_code=401, detail="Authentication required")

    def _csrf_protected(request: Request, _: None = Depends(_authorized)) -> None:
        header = request.headers.get("X-SQLIBLIND-CSRF", "")
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if (
            not header
            or not cookie
            or not secrets.compare_digest(header, csrf)
            or not secrets.compare_digest(cookie, csrf)
        ):
            raise HTTPException(status_code=403, detail="CSRF validation failed")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        request.state.csp_nonce = secrets.token_urlsafe(18)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; connect-src 'self'; style-src 'self'; "
            f"script-src 'self' 'nonce-{request.state.csp_nonce}'; "
            "img-src 'self' data:; font-src 'none'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'self'"
        )
        return response

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request, token: str | None = Query(default=None)):
        if token is not None:
            if not secrets.compare_digest(token, auth_token):
                raise HTTPException(status_code=401, detail="Invalid token")
            response = RedirectResponse(url="/", status_code=303)
            response.set_cookie(
                AUTH_COOKIE,
                auth_token,
                httponly=True,
                secure=secure_cookies,
                samesite="strict",
                path="/",
            )
            response.set_cookie(
                CSRF_COOKIE,
                csrf,
                httponly=False,
                secure=secure_cookies,
                samesite="strict",
                path="/",
            )
            return response
        _authorized(request)
        return HTMLResponse(_load_ui(csrf, request.state.csp_nonce))

    @app.get("/assets/app.css", include_in_schema=False)
    async def app_css(request: Request):
        _authorized(request)
        return Response(_load_asset("app.css"), media_type="text/css")

    @app.get("/assets/app.js", include_in_schema=False)
    async def app_js(request: Request):
        _authorized(request)
        return Response(_load_asset("app.js"), media_type="application/javascript")

    @app.get("/api/health", dependencies=[Depends(_authorized)])
    async def health() -> dict[str, object]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/scans", dependencies=[Depends(_authorized)])
    async def list_scans() -> list[dict[str, Any]]:
        return manager.store.list_scans()

    @app.post("/api/scans", dependencies=[Depends(_csrf_protected)])
    async def create_scan(body: ScanRequest) -> dict[str, str]:
        try:
            raw = body.model_dump() if hasattr(body, "model_dump") else body.dict()
            settings = ScanSettings.from_mapping(raw)
            scan_id = manager.start(settings)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"id": scan_id}

    @app.get("/api/scans/{scan_id}", dependencies=[Depends(_authorized)])
    async def get_scan(scan_id: str) -> dict[str, Any]:
        scan = manager.store.get_scan(scan_id)
        if scan is None:
            raise HTTPException(status_code=404, detail="Scan not found")
        return scan

    @app.get(
        "/api/scans/{scan_id}/snapshot", dependencies=[Depends(_authorized)]
    )
    async def snapshot(scan_id: str) -> dict[str, Any]:
        value = manager.store.snapshot(scan_id)
        if value is None:
            raise HTTPException(status_code=404, detail="Scan not found")
        return value

    @app.get("/api/scans/{scan_id}/events", dependencies=[Depends(_authorized)])
    async def events(
        scan_id: str,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> list[dict[str, Any]]:
        if manager.store.get_scan(scan_id) is None:
            raise HTTPException(status_code=404, detail="Scan not found")
        return manager.store.get_events(scan_id, after=after, limit=limit)

    @app.get("/api/scans/{scan_id}/stream", dependencies=[Depends(_authorized)])
    async def stream(
        scan_id: str, after: int = Query(default=0, ge=0)
    ):
        if manager.store.get_scan(scan_id) is None:
            raise HTTPException(status_code=404, detail="Scan not found")

        async def generate():
            cursor = after
            idle = 0
            while True:
                rows = manager.store.get_events(scan_id, after=cursor, limit=500)
                if rows:
                    idle = 0
                    for item in rows:
                        cursor = int(item["seq"])
                        yield "data: " + json.dumps(
                            item, ensure_ascii=False, separators=(",", ":")
                        ) + "\n\n"
                else:
                    idle += 1
                    if idle % 40 == 0:
                        yield ": heartbeat\n\n"
                scan = manager.store.get_scan(scan_id)
                if scan is None:
                    break
                if scan["status"] in TERMINAL_STATUSES and not rows:
                    break
                await asyncio.sleep(0.25)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    def _control(name: str, scan_id: str) -> JSONResponse:
        try:
            getattr(manager, name