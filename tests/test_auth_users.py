from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from blind_sqli.auth import UserError, UserStore, utc_now


def test_bootstrap_admin_requires_change_and_persists(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "users.db")
    assert store.bootstrap_admin() is True
    assert store.bootstrap_admin() is False
    admin = store.authenticate("ADMIN", "admin")
    assert admin is not None
    assert admin.username == "admin"
    assert admin.role == "admin"
    assert admin.must_change_password is True


def test_password_change_invalidates_existing_sessions(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "users.db")
    store.bootstrap_admin()
    admin = store.authenticate("admin", "admin")
    assert admin is not None
    session = store.create_session(admin, ttl=timedelta(hours=1))
    assert store.resolve_session(session.token) is not None
    store.change_own_password("admin", "admin", "New-Admin-Password9")
    assert store.resolve_session(session.token) is None
    assert store.authenticate("admin", "admin") is None
    changed = store.authenticate("admin", "New-Admin-Password9")
    assert changed is not None
    assert changed.must_change_password is False


def test_temporary_expired_and_disabled_users_are_denied(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "users.db")
    store.bootstrap_admin()
    store.create_user(
        "temp.user",
        "Temporary-Password9",
        role="operator",
        expires_at=utc_now() + timedelta(minutes=5),
    )
    assert store.authenticate("temp.user", "Temporary-Password9") is not None
    store.set_active("temp.user", False)
    assert store.authenticate("temp.user", "Temporary-Password9") is None
    store.set_active("temp.user", True)
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE users SET expires_at='2000-01-01T00:00:00+00:00' "
            "WHERE username='temp.user'"
        )
    assert store.authenticate("temp.user", "Temporary-Password9") is None


def test_last_usable_administrator_is_protected(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "users.db")
    store.bootstrap_admin()
    with pytest.raises(UserError, match="last usable administrator"):
        store.set_active("admin", False)
    with pytest.raises(UserError, match="last usable administrator"):
        store.delete_user("admin")
    with pytest.raises(UserError, match="cannot be temporary"):
        store.set_expiration("admin", utc_now() + timedelta(days=1))

    store.create_user("backup", "Backup-Admin-Password9", role="admin")
    store.set_active("admin", False)
    assert store.get_user("admin")["active"] is False


def test_roles_and_password_policy(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "users.db")
    store.bootstrap_admin()
    with pytest.raises(UserError):
        store.create_user("bad name", "Strong-Password9")
    with pytest.raises(UserError):
        store.create_user("weak", "alllowercase")
    user = store.create_user("reader", "Reader-Password9", role="viewer")
    assert user["role"] == "viewer"
    store.set_role("reader", "operator")
    assert store.get_user("reader")["role"] == "operator"
