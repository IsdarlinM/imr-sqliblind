import html
import json
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import parse_qs, quote

from .auth import UserError, UserSession, UserStore, parse_iso

USER_SESSION_COOKIE = "sqliblind_user_session"
USER_CSRF_COOKIE = "sqliblind_user_csrf"
LOGIN_CSRF_COOKIE = "sqliblind_login_csrf"
_INTERNAL_TOKEN_HEADER = b"x-sqliblind-token"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_LOGIN_TOKEN_TTL_SECONDS = 600.0
_MAX_LOGIN_TOKENS = 2048


def _local_path(value: str | None, default: str = "/") -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return default
    return value[:2048]


def _form_data(body: bytes) -> dict[str, str]:
    parsed = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


def _parse_expiration(value: Any) -> datetime | None:
    if value in (None, "", "never"):
        return None
    if not isinstance(value, str):
        raise UserError("expires_at must be an ISO-8601 string or null")
    parsed = parse_iso(value)
    if parsed is None:
        return None
    if parsed <= datetime.now(timezone.utc):
        raise UserError("expiration must be in the future")
    return parsed


def _document(title: str, body: str, nonce: str) -> str:
    safe_title = html.escape(title)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_title}</title>
<style nonce="{html.escape(nonce, quote=True)}">
:root{{color-scheme:dark;background:#091017;color:#e7eef5;font:16px/1.45 system-ui,sans-serif}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px}}
main{{width:min(520px,100%);background:#111d27;border:1px solid #2a3b49;border-radius:16px;padding:28px;box-shadow:0 20px 70px #0008}}
h1{{margin:0 0 8px;font-size:1.55rem}}p{{color:#aebdca}}label{{display:grid;gap:6px;margin:14px 0}}
input,select{{width:100%;padding:11px 12px;border:1px solid #385063;border-radius:9px;background:#081119;color:#fff}}
button,a.button{{display:inline-block;border:0;border-radius:9px;padding:11px 15px;background:#48d597;color:#052014;font-weight:700;text-decoration:none;cursor:pointer}}
.actions{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:18px}}.error{{color:#ff9a9a}}.warning{{color:#ffd27c}}
code{{word-break:break-all}}small{{color:#91a4b5}}
</style>
</head><body><main>{body}</main></body></html>"""


class LoginLimiter:
    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        attempts = self._attempts[key]
        while attempts and now - attempts[0] > 300:
            attempts.popleft()
        if len(attempts) >= 10:
            return False
        attempts.append(now)
        return True

    def clear(self, key: str) -> None:
        self._attempts.pop(key, None)


class LoginTokenStore:
    """Issue bounded, one-time login CSRF tokens without relying on cookies."""

    def __init__(
        self,
        *,
        ttl_seconds: float = _LOGIN_TOKEN_TTL_SECONDS,
        max_tokens: int = _MAX_LOGIN_TOKENS,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_tokens = max_tokens
        self._tokens: dict[str, float] = {}

    def _prune(self, now: float) -> None:
        expired = [
            token for token, expires_at in self._tokens.items() if expires_at < now
        ]
        for token in expired:
            self._tokens.pop(token, None)

        overflow = len(self._tokens) - self._max_tokens
        if overflow > 0:
            oldest = sorted(self._tokens, key=self._tokens.__getitem__)[:overflow]
            for token in oldest:
                self._tokens.pop(token, None)

    def issue(self) -> str:
        now = time.monotonic()
        token = secrets.token_urlsafe(32)
        self._tokens[token] = now + self._ttl_seconds
        self._prune(now)
        return token

    def consume(self, token: str) -> bool:
        if not token:
            return False
        now = time.monotonic()
        expires_at = self._tokens.pop(token, None)
        self._prune(now)
        return expires_at is not None and expires_at >= now


def create_service_gateway(
    inner_app: Any,
    *,
    user_store: UserStore,
    internal_token: str,
    secure_cookies: bool,
    session_hours: int,
    service_control_token: str,
    shutdown_callback: Callable[[], None],
):
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Web dependencies are not installed") from exc

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    limiter = LoginLimiter()
    login_tokens = LoginTokenStore()

    def session_for(request: Request) -> UserSession | None:
        return user_store.resolve_session(request.cookies.get(USER_SESSION_COOKIE))

    def csrf_valid(request: Request, session: UserSession, supplied: str) -> bool:
        cookie = request.cookies.get(USER_CSRF_COOKIE, "")
        return bool(
            supplied
            and cookie
            and secrets.compare_digest(supplied, cookie)
            and secrets.compare_digest(supplied, session.csrf_token)
        )

    def require_json_csrf(request: Request, session: UserSession) -> Response | None:
        supplied = request.headers.get("X-SQLIBLIND-USER-CSRF", "")
        if not csrf_valid(request, session, supplied):
            return JSONResponse({"detail": "CSRF validation failed"}, status_code=403)
        return None

    def secure_response(response: Response, nonce: str) -> Response:
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
                    "default-src 'self'; connect-src 'self'; "
                    f"style-src 'self' 'nonce-{nonce}'; "
                    f"script-src 'self' 'nonce-{nonce}'; img-src 'self' data:; "
                    "font-src 'none'; object-src 'none'; base-uri 'none'; "
                    "frame-ancestors 'none'; form-action 'self'"
                ),
            }
        )
        return response

    @app.middleware("http")
    async def service_security(request: Request, call_next):
        request.state.csp_nonce = secrets.token_urlsafe(18)
        path = request.url.path
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > 2_000_000:
                    return secure_response(
                        JSONResponse(
                            {"detail": "Request body too large"}, status_code=413
                        ),
                        request.state.csp_nonce,
                    )
            except ValueError:
                return secure_response(
                    JSONResponse({"detail": "Invalid Content-Length"}, status_code=400),
                    request.state.csp_nonce,
                )
        public = path == "/login" or path.startswith("/api/service/")
        session = None if public else session_for(request)

        if not public:
            if session is None:
                if path.startswith("/api/"):
                    response: Response = JSONResponse(
                        {"detail": "Authentication required"}, status_code=401
                    )
                else:
                    destination = quote(_local_path(path), safe="/?:=&")
                    response = RedirectResponse(
                        f"/login?next={destination}", status_code=303
                    )
                return secure_response(response, request.state.csp_nonce)
            request.state.user_session = session
            if session.user.must_change_password and path not in {
                "/account/password",
                "/logout",
            }:
                if path.startswith("/api/"):
                    response = JSONResponse(
                        {"detail": "Password change required"}, status_code=428
                    )
                else:
                    response = RedirectResponse("/account/password", status_code=303)
                return secure_response(response, request.state.csp_nonce)
            if path.startswith("/api/users") or path.startswith("/api/audit"):
                if not session.user.is_admin:
                    response = JSONResponse(
                        {"detail": "Administrator required"}, status_code=403
                    )
                    return secure_response(response, request.state.csp_nonce)
            route_owned_by_gateway = (
                path.startswith("/api/account")
                or path.startswith("/api/users")
                or path.startswith("/api/audit")
                or path in {"/account/password", "/logout"}
            )
            if (
                not route_owned_by_gateway
                and request.method.upper() not in _SAFE_METHODS
                and not session.user.can_operate
            ):
                response = JSONResponse(
                    {"detail": "Operator role required"}, status_code=403
                )
                return secure_response(response, request.state.csp_nonce)

            if not route_owned_by_gateway:
                headers = [
                    (key, value)
                    for key, value in request.scope.get("headers", [])
                    if key.lower() != _INTERNAL_TOKEN_HEADER
                ]
                headers.append((_INTERNAL_TOKEN_HEADER, internal_token.encode("ascii")))
                request.scope["headers"] = headers

        response = await call_next(request)
        return secure_response(response, request.state.csp_nonce)

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request, next: str = "/"):
        current = session_for(request)
        if current and not current.user.must_change_password:
            return RedirectResponse(_local_path(next), status_code=303)
        login_csrf = login_tokens.issue()
        body = f"""
<h1>imr-sqliblind service</h1>
<p>Sign in to the realtime console.</p>
<form method="post" action="/login">
<input type="hidden" name="csrf" value="{html.escape(login_csrf, quote=True)}">
<input type="hidden" name="next" value="{html.escape(_local_path(next), quote=True)}">
<label>Username<input name="username" autocomplete="username" required maxlength="64"></label>
<label>Password<input name="password" type="password" autocomplete="current-password" required maxlength="512"></label>
<div class="actions"><button type="submit">Sign in</button></div>
</form>
<p class="warning"><strong>First start:</strong> use <code>admin</code> / <code>admin</code>. A password change is mandatory immediately after login.</p>
"""
        response = HTMLResponse(_document("Sign in", body, request.state.csp_nonce))
        response.delete_cookie(LOGIN_CSRF_COOKIE, path="/login")
        response.delete_cookie(LOGIN_CSRF_COOKIE, path="/")
        return response

    @app.post("/login")
    async def login(request: Request):
        form = _form_data(await request.body())
        supplied_csrf = form.get("csrf", "")
        if not login_tokens.consume(supplied_csrf):
            return HTMLResponse(
                _document(
                    "Sign in failed",
                    '<h1>Sign in failed</h1><p class="error">The request token is invalid or expired. Reload the sign-in page and try again.</p><a class="button" href="/login">Try again</a>',
                    request.state.csp_nonce,
                ),
                status_code=403,
            )
        client_host = request.client.host if request.client else "unknown"
        username = form.get("username", "")[:128]
        key = f"{client_host}:{username.casefold()}"
        if not limiter.allow(key):
            return HTMLResponse(
                _document(
                    "Sign in failed",
                    '<h1>Sign in failed</h1><p class="error">Too many attempts. Try again later.</p>',
                    request.state.csp_nonce,
                ),
                status_code=429,
            )
        user = user_store.authenticate(username, form.get("password", "")[:512])
        if user is None:
            return HTMLResponse(
                _document(
                    "Sign in failed",
                    '<h1>Sign in failed</h1><p class="error">Invalid username or password.</p><a class="button" href="/login">Try again</a>',
                    request.state.csp_nonce,
                ),
                status_code=401,
            )
        limiter.clear(key)
        session = user_store.create_session(
            user, ttl=timedelta(hours=session_hours)
        )
        destination = (
            "/account/password"
            if user.must_change_password
            else _local_path(form.get("next"))
        )
        response = RedirectResponse(destination, status_code=303)
        response.set_cookie(
            USER_SESSION_COOKIE,
            session.token,
            httponly=True,
            secure=secure_cookies,
            samesite="strict",
            path="/",
            max_age=session_hours * 3600,
        )
        response.set_cookie(
            USER_CSRF_COOKIE,
            session.csrf_token,
            httponly=False,
            secure=secure_cookies,
            samesite="strict",
            path="/",
            max_age=session_hours * 3600,
        )
        response.delete_cookie(LOGIN_CSRF_COOKIE, path="/login")
        response.delete_cookie(LOGIN_CSRF_COOKIE, path="/")
        return response

    @app.get("/account/password", response_class=HTMLResponse)
    async def password_page(request: Request):
        session: UserSession = request.state.user_session
        warning = (
            '<p class="warning">The bootstrap password must be replaced before the console can be used.</p>'
            if session.user.must_change_password
            else ""
        )
        body = f"""
<h1>Change password</h1>{warning}
<p>Signed in as <strong>{html.escape(session.user.username)}</strong> ({html.escape(session.user.role)}).</p>
<form method="post" action="/account/password">
<input type="hidden" name="csrf" value="{html.escape(session.csrf_token, quote=True)}">
<label>Current password<input name="current_password" type="password" autocomplete="current-password" required maxlength="512"></label>
<label>New password<input name="new_password" type="password" autocomplete="new-password" required maxlength="512"></label>
<label>Confirm password<input name="confirm_password" type="password" autocomplete="new-password" required maxlength="512"></label>
<small>Use 10+ characters and at least three character categories.</small>
<div class="actions"><button type="submit">Change password</button><a class="button" href="/">Console</a></div>
</form>
<form method="post" action="/logout" class="actions">
<input type="hidden" name="csrf" value="{html.escape(session.csrf_token, quote=True)}"><button type="submit">Sign out</button>
</form>
"""
        return HTMLResponse(
            _document("Change password", body, request.state.csp_nonce)
        )

    @app.post("/account/password")
    async def change_password(request: Request):
        session: UserSession = request.state.user_session
        form = _form_data(await request.body())
        if not csrf_valid(request, session, form.get("csrf", "")):
            return HTMLResponse(
                _document(
                    "Invalid request",
                    '<h1>Invalid request</h1><p class="error">CSRF validation failed.</p>',
                    request.state.csp_nonce,
                ),
                status_code=403,
            )
        if form.get("new_password") != form.get("confirm_password"):
            return HTMLResponse(
                _document(
                    "Password error",
                    '<h1>Password not changed</h1><p class="error">New passwords do not match.</p><a class="button" href="/account/password">Back</a>',
                    request.state.csp_nonce,
                ),
                status_code=422,
            )
        try:
            user_store.change_own_password(
                session.user.username,
                form.get("current_password", ""),
                form.get("new_password", ""),
            )
        except UserError as exc:
            message = html.escape(str(exc))
            return HTMLResponse(
                _document(
                    "Password error",
                    f'<h1>Password not changed</h1><p class="error">{message}</p><a class="button" href="/account/password">Back</a>',
                    request.state.csp_nonce,
                ),
                status_code=422,
            )
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(USER_SESSION_COOKIE, path="/")
        response.delete_cookie(USER_CSRF_COOKIE, path="/")
        return response

    @app.post("/logout")
    async def logout(request: Request):
        session: UserSession = request.state.user_session
        form = _form_data(await request.body())
        if not csrf_valid(request, session, form.get("csrf", "")):
            return JSONResponse({"detail": "CSRF validation failed"}, status_code=403)
        user_store.revoke_session(session.token)
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(USER_SESSION_COOKIE, path="/")
        response.delete_cookie(USER_CSRF_COOKIE, path="/")
        return response

    @app.get("/api/account")
    async def account(request: Request):
        session: UserSession = request.state.user_session
        return {
            "username": session.user.username,
            "role": session.user.role,
            "must_change_password": session.user.must_change_password,
            "expires_at": session.user.expires_at,
            "session_expires_at": session.expires_at,
        }

    @app.get("/api/users")
    async def list_users(request: Request):
        return user_store.list_users()

    @app.post("/api/users")
    async def create_user(request: Request):
        session: UserSession = request.state.user_session
        invalid = require_json_csrf(request, session)
        if invalid:
            return invalid
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise UserError("JSON object required")
            created = user_store.create_user(
                str(body.get("username", "")),
                str(body.get("password", "")),
                role=str(body.get("role", "viewer")),
                expires_at=_parse_expiration(body.get("expires_at")),
                must_change_password=bool(body.get("must_change_password", False)),
                actor=session.user.username,
            )
            return JSONResponse(created, status_code=201)
        except (json.JSONDecodeError, UserError, ValueError) as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.patch("/api/users/{username}")
    async def update_user(username: str, request: Request):
        session: UserSession = request.state.user_session
        invalid = require_json_csrf(request, session)
        if invalid:
            return invalid
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise UserError("JSON object required")
            allowed = {
                "active",
                "role",
                "expires_at",
                "password",
                "must_change_password",
            }
            unknown = sorted(set(body) - allowed)
            if unknown:
                raise UserError(f"unsupported fields: {', '.join(unknown)}")
            if "active" in body:
                user_store.set_active(
                    username, bool(body["active"]), actor=session.user.username
                )
            if "role" in body:
                user_store.set_role(
                    username, str(body["role"]), actor=session.user.username
                )
            if "expires_at" in body:
                user_store.set_expiration(
                    username,
                    _parse_expiration(body["expires_at"]),
                    actor=session.user.username,
                )
            if "password" in body:
                user_store.reset_password(
                    username,
                    str(body["password"]),
                    must_change_password=bool(
                        body.get("must_change_password", True)
                    ),
                    actor=session.user.username,
                )
            return user_store.get_user(username)
        except (json.JSONDecodeError, UserError, ValueError) as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.delete("/api/users/{username}")
    async def delete_user(username: str, request: Request):
        session: UserSession = request.state.user_session
        invalid = require_json_csrf(request, session)
        if invalid:
            return invalid
        try:
            user_store.delete_user(username, actor=session.user.username)
            return Response(status_code=204)
        except UserError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.get("/api/audit")
    async def audit(limit: int = 100):
        return user_store.audit_events(limit)

    def control_authorized(request: Request) -> bool:
        supplied = request.headers.get("X-SQLIBLIND-SERVICE-CONTROL", "")
        return bool(supplied) and secrets.compare_digest(
            supplied, service_control_token
        )

    @app.get("/api/service/status")
    async def service_status(request: Request):
        if not control_authorized(request):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        return {"status": "running"}

    @app.post("/api/service/shutdown")
    async def service_shutdown(request: Request):
        if not control_authorized(request):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        shutdown_callback()
        return {"status": "stopping"}

    app.mount("/", inner_app)
    return app
