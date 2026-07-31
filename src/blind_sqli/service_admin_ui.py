import html
import secrets
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .auth import UserError, UserSession, UserStore, utc_now
from .service_gateway import USER_CSRF_COOKIE, USER_SESSION_COOKIE


def _form_data(body: bytes) -> dict[str, str]:
    parsed = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


def _duration(value: str) -> timedelta:
    raw = value.strip().casefold()
    if len(raw) < 2 or not raw[:-1].isdigit() or raw[-1] not in "mhdw":
        raise UserError("duration must use forms such as 30m, 12h, 7d, or 2w")
    amount = int(raw[:-1])
    if amount < 1:
        raise UserError("duration must be positive")
    units = {
        "m": timedelta(minutes=1),
        "h": timedelta(hours=1),
        "d": timedelta(days=1),
        "w": timedelta(weeks=1),
    }
    result = units[raw[-1]] * amount
    if result > timedelta(days=3650):
        raise UserError("duration cannot exceed 10 years")
    return result


def _redirect(message: str = "", error: str = "") -> RedirectResponse:
    parameters = []
    if message:
        parameters.append(f"message={quote(message[:500])}")
    if error:
        parameters.append(f"error={quote(error[:500])}")
    suffix = f"?{'&'.join(parameters)}" if parameters else ""
    return RedirectResponse(f"/admin/{suffix}", status_code=303)


def _session(request: Request, store: UserStore) -> UserSession | None:
    return store.resolve_session(request.cookies.get(USER_SESSION_COOKIE))


def _admin_session(request: Request, store: UserStore) -> UserSession:
    session = _session(request, store)
    if session is None or not session.user.is_admin:
        raise UserError("administrator session required")
    if session.user.must_change_password:
        raise UserError("password change required")
    return session


def _csrf_valid(request: Request, session: UserSession, supplied: str) -> bool:
    cookie = request.cookies.get(USER_CSRF_COOKIE, "")
    return bool(
        supplied
        and cookie
        and secrets.compare_digest(supplied, cookie)
        and secrets.compare_digest(supplied, session.csrf_token)
    )


def _page(
    users: list[dict[str, Any]],
    session: UserSession,
    *,
    nonce: str,
    message: str = "",
    error: str = "",
) -> str:
    rows = []
    csrf = html.escape(session.csrf_token, quote=True)
    for user in users:
        username = html.escape(str(user["username"]), quote=True)
        role = html.escape(str(user["role"]), quote=True)
        state = (
            "disabled"
            if not user["active"]
            else "expired"
            if user["expired"]
            else "active"
        )
        expires = html.escape(str(user["expires_at"] or "never"))
        must_change = "yes" if user["must_change_password"] else "no"
        activation = "enable" if not user["active"] else "disable"
        role_options = "".join(
            f'<option value="{candidate}"'
            f'{" selected" if candidate == user["role"] else ""}>'
            f"{candidate}</option>"
            for candidate in ("admin", "operator", "viewer")
        )
        rows.append(
            f"""
<tr>
<td><strong>{username}</strong></td><td>{role}</td><td>{state}</td>
<td>{expires}</td><td>{must_change}</td>
<td class="actions-cell">
<form method="post" action="/admin/action">
<input type="hidden" name="csrf" value="{csrf}">
<input type="hidden" name="username" value="{username}">
<input type="hidden" name="action" value="{activation}">
<button>{activation.title()}</button>
</form>
<form method="post" action="/admin/role">
<input type="hidden" name="csrf" value="{csrf}">
<input type="hidden" name="username" value="{username}">
<select name="role">{role_options}</select><button>Set role</button>
</form>
<form method="post" action="/admin/expiration">
<input type="hidden" name="csrf" value="{csrf}">
<input type="hidden" name="username" value="{username}">
<input name="expires_in" placeholder="12h / 7d"><button>Set expiry</button>
<button name="never" value="1">Never</button>
</form>
<form method="post" action="/admin/password">
<input type="hidden" name="csrf" value="{csrf}">
<input type="hidden" name="username" value="{username}">
<input type="password" name="password" autocomplete="new-password"
  placeholder="New password" required maxlength="512">
<label class="inline"><input type="checkbox" name="force_change" value="1" checked>
Force change</label><button>Reset</button>
</form>
<form method="post" action="/admin/action">
<input type="hidden" name="csrf" value="{csrf}">
<input type="hidden" name="username" value="{username}">
<input type="hidden" name="action" value="delete">
<button class="danger">Delete</button>
</form>
</td>
</tr>"""
        )
    message_html = (
        f'<p class="notice success">{html.escape(message)}</p>' if message else ""
    )
    error_html = f'<p class="notice error">{html.escape(error)}</p>' if error else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>User administration · imr-sqliblind</title>
<style nonce="{html.escape(nonce, quote=True)}">
:root{{color-scheme:dark;background:#081018;color:#e7eef5;font:14px/1.45 system-ui}}
*{{box-sizing:border-box}}body{{margin:0;padding:24px}}main{{max-width:1500px;margin:auto}}
a{{color:#65e3ae}}h1{{margin-bottom:4px}}.top{{display:flex;gap:12px;flex-wrap:wrap}}
.panel{{background:#111d27;border:1px solid #2b3d4b;border-radius:14px;padding:18px;margin:18px 0}}
.grid{{display:grid;grid-template-columns:repeat(5,minmax(130px,1fr));gap:10px}}
input,select,button{{
  border:1px solid #385063;border-radius:8px;background:#081119;
  color:#fff;padding:9px
}}
button{{cursor:pointer;background:#244154}}
button:hover{{background:#31566f}}
button.danger{{background:#6d2631}}
.table-wrap{{overflow:auto}}table{{width:100%;border-collapse:collapse;min-width:1100px}}
th,td{{padding:9px;border-bottom:1px solid #263845;text-align:left;vertical-align:top}}
.actions-cell{{display:grid;gap:7px}}form{{display:flex;gap:7px;align-items:center;flex-wrap:wrap}}
.inline{{display:flex;align-items:center;gap:5px}}.inline input{{width:auto}}
.notice{{padding:10px;border-radius:8px}}.success{{background:#183d31}}.error{{background:#57242d}}
.muted{{color:#9db0bf}}@media(max-width:900px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><main>
<div class="top"><a href="/">← Console</a><a href="/account/password">Credentials</a></div>
<h1>User administration</h1>
<p class="muted">Signed in as {html.escape(session.user.username)}. Roles and credential
changes revoke active sessions immediately.</p>{message_html}{error_html}
<section class="panel"><h2>Create user</h2>
<form method="post" action="/admin/create" class="grid">
<input type="hidden" name="csrf" value="{csrf}">
<input name="username" placeholder="Username" required maxlength="64">
<input type="password" name="password" autocomplete="new-password"
  placeholder="Initial password" required maxlength="512">
<select name="role"><option>viewer</option><option>operator</option><option>admin</option></select>
<input name="expires_in" placeholder="Expiry: 12h, 7d, or blank">
<label class="inline"><input type="checkbox" name="force_change" value="1" checked>
Force change</label><button>Create</button>
</form></section>
<section class="panel"><h2>Users</h2><div class="table-wrap"><table>
<thead><tr><th>User</th><th>Role</th><th>State</th><th>Expires</th>
<th>Change password</th><th>Management</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div></section>
</main></body></html>"""


def create_admin_ui(user_store: UserStore) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/", response_class=HTMLResponse)
    async def users_page(request: Request, message: str = "", error: str = ""):
        try:
            session = _admin_session(request, user_store)
        except UserError:
            return RedirectResponse("/login", status_code=303)
        nonce = str(getattr(request.state, "csp_nonce", ""))
        return HTMLResponse(
            _page(
                user_store.list_users(),
                session,
                nonce=nonce,
                message=message[:500],
                error=error[:500],
            )
        )

    async def protected_form(request: Request) -> tuple[UserSession, dict[str, str]]:
        session = _admin_session(request, user_store)
        form = _form_data(await request.body())
        if not _csrf_valid(request, session, form.get("csrf", "")):
            raise UserError("CSRF validation failed")
        return session, form

    @app.post("/create")
    async def create(request: Request):
        try:
            session, form = await protected_form(request)
            expires = (
                utc_now() + _duration(form["expires_in"])
                if form.get("expires_in", "").strip()
                else None
            )
            user_store.create_user(
                form.get("username", ""),
                form.get("password", ""),
                role=form.get("role", "viewer"),
                expires_at=expires,
                must_change_password=form.get("force_change") == "1",
                actor=session.user.username,
            )
            return _redirect(message=f"Created {form.get('username', '')}.")
        except (KeyError, UserError, ValueError) as exc:
            return _redirect(error=str(exc))

    @app.post("/action")
    async def action(request: Request):
        try:
            session, form = await protected_form(request)
            username = form.get("username", "")
            operation = form.get("action", "")
            if operation == "enable":
                user_store.set_active(username, True, actor=session.user.username)
            elif operation == "disable":
                user_store.set_active(username, False, actor=session.user.username)
            elif operation == "delete":
                user_store.delete_user(username, actor=session.user.username)
            else:
                raise UserError("unsupported user action")
            return _redirect(message=f"Applied {operation} to {username}.")
        except UserError as exc:
            return _redirect(error=str(exc))

    @app.post("/role")
    async def role(request: Request):
        try:
            session, form = await protected_form(request)
            user_store.set_role(
                form.get("username", ""),
                form.get("role", ""),
                actor=session.user.username,
            )
            return _redirect(message=f"Updated role for {form.get('username', '')}.")
        except UserError as exc:
            return _redirect(error=str(exc))

    @app.post("/expiration")
    async def expiration(request: Request):
        try:
            session, form = await protected_form(request)
            expires = None
            if form.get("never") != "1":
                expires = utc_now() + _duration(form.get("expires_in", ""))
            user_store.set_expiration(
                form.get("username", ""),
                expires,
                actor=session.user.username,
            )
            return _redirect(message=f"Updated expiration for {form.get('username', '')}.")
        except UserError as exc:
            return _redirect(error=str(exc))

    @app.post("/password")
    async def password(request: Request):
        try:
            session, form = await protected_form(request)
            user_store.reset_password(
                form.get("username", ""),
                form.get("password", ""),
                must_change_password=form.get("force_change") == "1",
                actor=session.user.username,
            )
            return _redirect(message=f"Reset password for {form.get('username', '')}.")
        except UserError as exc:
            return _redirect(error=str(exc))

    return app


__all__ = ["create_admin_ui"]
