import asyncio
import json
import secrets
from typing import Any

from . import __version__
from .manager import ScanManager, ScanSettings
from .web_support import (
    AUTH_COOKIE,
    CSRF_COOKIE,
    TERMINAL_STATUSES,
    load_asset,
    load_ui,
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
        from fastapi.responses import (
            HTMLResponse,
            JSONResponse,
            RedirectResponse,
            Response,
            StreamingResponse,
        )
        from pydantic import BaseModel, Field
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Web dependencies are not installed. Reinstall with: "
            "pip install 'imr-sqliblind[web]'"
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
        length_tolerance: int = Field(default=0, ge=0, le=100_000)
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
        max_data_bytes: int = Field(default=10_000, ge=1, le=50_000)
        reveal_sensitive_values: bool = False
        inference_mode: str = "adaptive"
        parallel_characters: bool = True
        adaptive_confirmation: bool = True
        adaptive_concurrency: bool = True
        request_event_sample: int = Field(default=20, ge=1, le=1000)

    def authorized(request: Request) -> None:
        supplied = request.cookies.get(AUTH_COOKIE) or request.headers.get(
            "X-SQLIBLIND-TOKEN",
            "",
        )
        if not supplied or not secrets.compare_digest(supplied, auth_token):
            raise HTTPException(status_code=401, detail="Authentication required")

    def csrf_protected(
        request: Request,
        _: None = Depends(authorized),
    ) -> None:
        header = request.headers.get("X-SQLIBLIND-CSRF", "")
        cookie = request.cookies.get(CSRF_COOKIE, "")
        valid = (
            header
            and cookie
            and secrets.compare_digest(header, csrf)
            and secrets.compare_digest(cookie, csrf)
        )
        if not valid:
            raise HTTPException(status_code=403, detail="CSRF validation failed")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        request.state.csp_nonce = secrets.token_urlsafe(18)
        response = await call_next(request)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Permissions-Policy": (
                    "camera=(), microphone=(), geolocation=(), payment=()"
                ),
                "Cache-Control": "no-store",
                "Content-Security-Policy": (
                    "default-src 'self'; connect-src 'self'; style-src 'self'; "
                    f"script-src 'self' 'nonce-{request.state.csp_nonce}'; "
                    "img-src 'self' data:; font-src 'none'; object-src 'none'; "
                    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
                ),
            }
        )
        return response

    @app.get("/", response_class=HTMLResponse)
    async def index(
        request: Request,
        token: str | None = Query(default=None),
    ):
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
        authorized(request)
        return HTMLResponse(load_ui(csrf, request.state.csp_nonce))

    @app.get("/assets/{name}", include_in_schema=False)
    async def asset(name: str, request: Request):
        authorized(request)
        try:
            content = load_asset(name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Asset not found") from exc
        media_type = "text/css" if name.endswith(".css") else "application/javascript"
        return Response(content, media_type=media_type)

    @app.get("/api/health", dependencies=[Depends(authorized)])
    async def health() -> dict[str, object]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/scans", dependencies=[Depends(authorized)])
    async def list_scans() -> list[dict[str, Any]]:
        return manager.store.list_scans()

    @app.post("/api/scans", dependencies=[Depends(csrf_protected)])
    async def create_scan(body: ScanRequest) -> dict[str, str]:
        try:
            raw = body.model_dump() if hasattr(body, "model_dump") else body.dict()
            return {"id": manager.start(ScanSettings.from_mapping(raw))}
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def require_scan(scan_id: str) -> dict[str, Any]:
        scan = manager.store.get_scan(scan_id)
        if scan is None:
            raise HTTPException(status_code=404, detail="Scan not found")
        return scan

    @app.get("/api/scans/{scan_id}", dependencies=[Depends(authorized)])
    async def get_scan(scan_id: str) -> dict[str, Any]:
        return require_scan(scan_id)

    @app.get(
        "/api/scans/{scan_id}/snapshot",
        dependencies=[Depends(authorized)],
    )
    async def snapshot(scan_id: str) -> dict[str, Any]:
        value = manager.store.snapshot(scan_id)
        if value is None:
            raise HTTPException(status_code=404, detail="Scan not found")
        return value

    @app.get(
        "/api/scans/{scan_id}/events",
        dependencies=[Depends(authorized)],
    )
    async def events(
        scan_id: str,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> list[dict[str, Any]]:
        require_scan(scan_id)
        return manager.store.get_events(scan_id, after=after, limit=limit)

    @app.get(
        "/api/scans/{scan_id}/stream",
        dependencies=[Depends(authorized)],
    )
    async def stream(scan_id: str, after: int = Query(default=0, ge=0)):
        require_scan(scan_id)

        async def generate():
            cursor = after
            idle = 0
            while True:
                rows = manager.store.get_events(scan_id, after=cursor, limit=500)
                if rows:
                    idle = 0
                    for item in rows:
                        cursor = int(item["seq"])
                        payload = json.dumps(
                            item,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        yield f"data: {payload}\n\n"
                else:
                    idle += 1
                    if idle % 40 == 0:
                        yield ": heartbeat\n\n"
                scan = manager.store.get_scan(scan_id)
                terminal = scan is None or scan["status"] in TERMINAL_STATUSES
                if terminal and not rows:
                    break
                await asyncio.sleep(0.25)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    def control(name: str, scan_id: str) -> JSONResponse:
        try:
            getattr(manager, name)(scan_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=409,
                detail="Scan is not active in this process",
            ) from exc
        return JSONResponse({"status": name})

    @app.post(
        "/api/scans/{scan_id}/pause",
        dependencies=[Depends(csrf_protected)],
    )
    async def pause(scan_id: str):
        return control("pause", scan_id)

    @app.post(
        "/api/scans/{scan_id}/resume",
        dependencies=[Depends(csrf_protected)],
    )
    async def resume(scan_id: str):
        return control("resume", scan_id)

    @app.post(
        "/api/scans/{scan_id}/stop",
        dependencies=[Depends(csrf_protected)],
    )
    async def stop(scan_id: str):
        return control("stop", scan_id)

    @app.get(
        "/api/scans/{scan_id}/export",
        dependencies=[Depends(authorized)],
    )
    async def export_scan(scan_id: str, format: str = "json"):
        try:
            content, media_type = manager.export(scan_id, format)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Scan not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        suffix = {"json": "json", "html": "html", "mermaid": "mmd"}.get(
            format,
            "txt",
        )
        return Response(
            content,
            media_type=media_type,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="sqliblind-{scan_id[:8]}.{suffix}"'
                )
            },
        )

    return app
