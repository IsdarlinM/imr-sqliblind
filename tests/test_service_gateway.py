from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from blind_sqli.auth import UserStore
from blind_sqli.service_admin_ui import create_admin_ui
from blind_sqli.service_gateway import create_service_gateway
from blind_sqli.service_runtime import add_inner_csrf_cookie_middleware


def build_client(tmp_path: Path) -> tuple[TestClient, UserStore, list[bool]]:
    inner = FastAPI()

    @inner.get("/")
    async def index():
        return {"inner": True}

    @inner.post("/write")
    async def write():
        return {"written": True}

    store = UserStore(tmp_path / "users.db")
    store.bootstrap_admin()
    inner.mount("/admin", create_admin_ui(store))
    stopped: list[bool] = []
    app = create_service_gateway(
        inner,
        user_store=store,
        internal_token="internal-only-token",
        secure_cookies=False,
        session_hours=12,
        service_control_token="control-token",
        shutdown_callback=lambda: stopped.append(True),
    )
    return TestClient(app), store, stopped


def login_token(page) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', page.text)
    assert match is not None
    return match.group(1)


def login(client: TestClient, username: str, password: str):
    page = client.get("/login")
    csrf = login_token(page)
    return client.post(
        "/login",
        data={
            "username": username,
            "password": password,
            "csrf": csrf,
            "next": "/",
        },
        follow_redirects=False,
    )


def test_login_and_forced_bootstrap_password_change(tmp_path: Path) -> None:
    client, _, _ = build_client(tmp_path)
    assert client.get("/", follow_redirects=False).status_code == 303
    response = login(client, "admin", "admin")
    assert response.status_code == 303
    assert response.headers["location"] == "/account/password"
    blocked = client.get("/api/account")
    assert blocked.status_code == 428
    password_page = client.get("/account/password")
    assert password_page.status_code == 200
    csrf = client.cookies.get("sqliblind_user_csrf")
    changed = client.post(
        "/account/password",
        data={
            "csrf": csrf,
            "current_password": "admin",
            "new_password": "New-Admin-Password9",
            "confirm_password": "New-Admin-Password9",
        },
        follow_redirects=False,
    )
    assert changed.status_code == 303
    assert changed.headers["location"] == "/login"


def test_login_does_not_depend_on_browser_cookie_persistence(tmp_path: Path) -> None:
    client, _, _ = build_client(tmp_path)
    page = client.get("/login")
    csrf = login_token(page)

    assert client.cookies.get("sqliblind_login_csrf") is None
    client.cookies.clear()

    response = client.post(
        "/login",
        data={
            "username": "admin",
            "password": "admin",
            "csrf": csrf,
            "next": "/",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/account/password"


def test_login_request_token_is_one_time(tmp_path: Path) -> None:
    client, _, _ = build_client(tmp_path)
    csrf = login_token(client.get("/login"))
    payload = {
        "username": "admin",
        "password": "incorrect",
        "csrf": csrf,
        "next": "/",
    }

    assert client.post("/login", data=payload).status_code == 401
    replay = client.post("/login", data=payload)
    assert replay.status_code == 403
    assert "invalid or expired" in replay.text


def test_missing_login_request_token_is_rejected(tmp_path: Path) -> None:
    client, _, _ = build_client(tmp_path)
    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin", "next": "/"},
    )
    assert response.status_code == 403


def test_roles_and_user_api_csrf(tmp_path: Path) -> None:
    client, store, _ = build_client(tmp_path)
    store.change_own_password("admin", "admin", "New-Admin-Password9")
    assert login(client, "admin", "New-Admin-Password9").status_code == 303
    csrf = client.cookies.get("sqliblind_user_csrf")
    created = client.post(
        "/api/users",
        headers={"X-SQLIBLIND-USER-CSRF": csrf},
        json={
            "username": "viewer",
            "password": "Viewer-Password9",
            "role": "viewer",
        },
    )
    assert created.status_code == 201
    client.post(
        "/logout",
        data={"csrf": csrf},
        follow_redirects=False,
    )
    assert login(client, "viewer", "Viewer-Password9").status_code == 303
    assert client.get("/").status_code == 200
    assert client.post("/write").status_code == 403
    assert client.get("/api/users").status_code == 403


def test_control_endpoint_is_token_protected(tmp_path: Path) -> None:
    client, _, stopped = build_client(tmp_path)
    assert client.get("/api/service/status").status_code == 404
    assert (
        client.get(
            "/api/service/status",
            headers={"X-SQLIBLIND-SERVICE-CONTROL": "control-token"},
        ).json()["status"]
        == "running"
    )
    response = client.post(
        "/api/service/shutdown",
        headers={"X-SQLIBLIND-SERVICE-CONTROL": "control-token"},
    )
    assert response.status_code == 200
    assert stopped == [True]


def test_inner_csrf_cookie_middleware_supports_existing_console(
    tmp_path: Path,
) -> None:
    inner = FastAPI()

    @inner.get("/")
    async def index():
        return {"ok": True}

    add_inner_csrf_cookie_middleware(
        inner,
        csrf_token="inner-csrf-token",
        secure=False,
        session_hours=12,
    )
    client = TestClient(inner)
    response = client.get("/")
    assert response.status_code == 200
    assert client.cookies.get("sqliblind_csrf") == "inner-csrf-token"


def test_browser_admin_can_manage_users(tmp_path: Path) -> None:
    client, store, _ = build_client(tmp_path)
    store.change_own_password("admin", "admin", "New-Admin-Password9")
    assert login(client, "admin", "New-Admin-Password9").status_code == 303
    page = client.get("/admin/")
    assert page.status_code == 200
    assert "User administration" in page.text
    csrf = client.cookies.get("sqliblind_user_csrf")
    created = client.post(
        "/admin/create",
        data={
            "csrf": csrf,
            "username": "temporary.viewer",
            "password": "Temporary-Viewer9",
            "role": "viewer",
            "expires_in": "12h",
            "force_change": "1",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    user = store.get_user("temporary.viewer")
    assert user["role"] == "viewer"
    assert user["expires_at"] is not None
    assert user["must_change_password"] is True
