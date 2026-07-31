from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROLES = {"admin", "operator", "viewer"}
_PASSWORD_ITERATIONS = 310_000
_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_SESSION_BYTES = 32
_FAKE_PASSWORD_HASH = (
    "pbkdf2_sha256$310000$aW1yLXNxbGlibGluZC1mYWtl$"
    "fh4PzqNgW5aELAr9cPYC8VPiR7bQMInn2qdZRW0X5Og"
)


class UserError(ValueError):
    """Raised when a user-management operation is invalid."""


@dataclass(frozen=True)
class AuthenticatedUser:
    id: int
    username: str
    role: str
    must_change_password: bool
    expires_at: str | None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def can_operate(self) -> bool:
        return self.role in {"admin", "operator"}


@dataclass(frozen=True)
class UserSession:
    token: str
    csrf_token: str
    expires_at: str
    user: AuthenticatedUser


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_username(username: str) -> str:
    value = username.strip()
    if not _USERNAME_PATTERN.fullmatch(value):
        raise UserError(
            "username must contain 1-64 letters, digits, dots, dashes, or underscores"
        )
    return value.casefold()


def validate_password(password: str, *, allow_bootstrap: bool = False) -> None:
    minimum = 5 if allow_bootstrap else 10
    if not minimum <= len(password) <= 512:
        raise UserError(f"password must contain between {minimum} and 512 characters")
    if "\x00" in password or any(ord(character) < 32 for character in password):
        raise UserError("password cannot contain control characters")
    if not allow_bootstrap:
        categories = sum(
            (
                any(character.islower() for character in password),
                any(character.isupper() for character in password),
                any(character.isdigit() for character in password),
                any(not character.isalnum() for character in password),
            )
        )
        if categories < 3:
            raise UserError(
                "password must include at least three of: lowercase, uppercase, digits, symbols"
            )


def hash_password(password: str, *, allow_bootstrap: bool = False) -> str:
    validate_password(password, allow_bootstrap=allow_bootstrap)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _PASSWORD_ITERATIONS,
    )
    return "$".join(
        (
            "pbkdf2_sha256",
            str(_PASSWORD_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
            base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
        )
    )


def _decode_base64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * ((4 - len(value) % 4) % 4))


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        if iterations < 100_000 or iterations > 2_000_000:
            return False
        salt = _decode_base64(salt_text)
        expected = _decode_base64(digest_text)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        )
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()


class UserStore:
    """SQLite-backed users, sessions, and security audit events."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        if os.name != "nt":
            try:
                self.path.chmod(0o600)
            except OSError:
                pass

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin','operator','viewer')),
                    active INTEGER NOT NULL DEFAULT 1,
                    must_change_password INTEGER NOT NULL DEFAULT 0,
                    expires_at TEXT,
                    auth_version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT
                );
                CREATE TABLE IF NOT EXISTS user_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    csrf_token TEXT NOT NULL,
                    auth_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_user_sessions_user
                    ON user_sessions(user_id);
                CREATE INDEX IF NOT EXISTS idx_user_sessions_expiry
                    ON user_sessions(expires_at);
                CREATE TABLE IF NOT EXISTS user_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target TEXT,
                    details TEXT
                );
                """
            )

    def _audit(
        self,
        connection: sqlite3.Connection,
        actor: str,
        action: str,
        target: str | None = None,
        details: str | None = None,
    ) -> None:
        connection.execute(
            "INSERT INTO user_audit(created_at,actor,action,target,details) VALUES(?,?,?,?,?)",
            (to_iso(utc_now()), actor[:128], action[:128], target, details),
        )

    def bootstrap_admin(self) -> bool:
        """Create admin/admin only when the user table is completely empty."""
        now = to_iso(utc_now())
        with self._connect() as connection:
            exists = connection.execute("SELECT 1 FROM users LIMIT 1").fetchone()
            if exists:
                return False
            connection.execute(
                """
                INSERT INTO users(
                    username,password_hash,role,active,must_change_password,
                    expires_at,auth_version,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    "admin",
                    hash_password("admin", allow_bootstrap=True),
                    "admin",
                    1,
                    1,
                    None,
                    1,
                    now,
                    now,
                ),
            )
            self._audit(connection, "system", "bootstrap-admin", "admin")
            return True

    def _row_to_user(self, row: sqlite3.Row) -> AuthenticatedUser:
        return AuthenticatedUser(
            id=int(row["id"]),
            username=str(row["username"]),
            role=str(row["role"]),
            must_change_password=bool(row["must_change_password"]),
            expires_at=row["expires_at"],
        )

    def _active_now(self, row: sqlite3.Row, now: datetime | None = None) -> bool:
        moment = now or utc_now()
        expires_at = parse_iso(row["expires_at"])
        return bool(row["active"]) and (expires_at is None or expires_at > moment)

    def _get_user_row(
        self,
        connection: sqlite3.Connection,
        username: str,
    ) -> sqlite3.Row:
        normalized = normalize_username(username)
        row = connection.execute(
            "SELECT * FROM users WHERE username=? COLLATE NOCASE",
            (normalized,),
        ).fetchone()
        if row is None:
            raise UserError("user not found")
        return row

    def _usable_admin_count(
        self,
        connection: sqlite3.Connection,
        *,
        excluding_id: int | None = None,
    ) -> int:
        rows = connection.execute(
            "SELECT id,active,expires_at FROM users WHERE role='admin'"
        ).fetchall()
        now = utc_now()
        return sum(
            1
            for row in rows
            if int(row["id"]) != excluding_id and self._active_now(row, now)
        )

    def create_user(
        self,
        username: str,
        password: str,
        *,
        role: str = "viewer",
        expires_at: datetime | None = None,
        must_change_password: bool = False,
        actor: str = "cli",
    ) -> dict[str, Any]:
        normalized = normalize_username(username)
        role = role.casefold()
        if role not in ROLES:
            raise UserError("role must be admin, operator, or viewer")
        if expires_at is not None:
            expires_at = expires_at.astimezone(timezone.utc)
            if expires_at <= utc_now():
                raise UserError("expiration must be in the future")
        encoded = hash_password(password)
        now = to_iso(utc_now())
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO users(
                        username,password_hash,role,active,must_change_password,
                        expires_at,auth_version,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        normalized,
                        encoded,
                        role,
                        1,
                        int(must_change_password),
                        to_iso(expires_at) if expires_at else None,
                        1,
                        now,
                        now,
                    ),
                )
                self._audit(connection, actor, "create-user", normalized, role)
        except sqlite3.IntegrityError as exc:
            raise UserError("user already exists") from exc
        return self.get_user(normalized)

    def get_user(self, username: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = self._get_user_row(connection, username)
            return self._public_row(row)

    def _public_row(self, row: sqlite3.Row) -> dict[str, Any]:
        now = utc_now()
        expires = parse_iso(row["expires_at"])
        return {
            "username": str(row["username"]),
            "role": str(row["role"]),
            "active": bool(row["active"]),
            "expired": expires is not None and expires <= now,
            "expires_at": row["expires_at"],
            "must_change_password": bool(row["must_change_password"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "last_login_at": row["last_login_at"],
        }

    def list_users(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM users ORDER BY username COLLATE NOCASE"
            ).fetchall()
            return [self._public_row(row) for row in rows]

    def authenticate(self, username: str, password: str) -> AuthenticatedUser | None:
        try:
            normalized = normalize_username(username)
        except UserError:
            normalized = ""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username=? COLLATE NOCASE",
                (normalized,),
            ).fetchone()
            encoded = str(row["password_hash"]) if row is not None else _FAKE_PASSWORD_HASH
            valid = verify_password(password, encoded)
            if row is None or not valid or not self._active_now(row):
                self._audit(connection, normalized or "invalid", "login-failed")
                return None
            now = to_iso(utc_now())
            connection.execute(
                "UPDATE users SET last_login_at=?,updated_at=? WHERE id=?",
                (now, now, row["id"]),
            )
            self._audit(connection, str(row["username"]), "login-success")
            return self._row_to_user(row)

    def create_session(
        self,
        user: AuthenticatedUser,
        *,
        ttl: timedelta,
    ) -> UserSession:
        if ttl <= timedelta(minutes=1) or ttl > timedelta(days=30):
            raise UserError("session lifetime must be between 1 minute and 30 days")
        token = secrets.token_urlsafe(_SESSION_BYTES)
        csrf_token = secrets.token_urlsafe(24)
        now = utc_now()
        expires_at = now + ttl
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE id=?",
                (user.id,),
            ).fetchone()
            if row is None or not self._active_now(row):
                raise UserError("user is not active")
            connection.execute(
                """
                INSERT INTO user_sessions(
                    token_hash,user_id,csrf_token,auth_version,
                    created_at,expires_at,last_seen_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    _token_hash(token),
                    user.id,
                    csrf_token,
                    int(row["auth_version"]),
                    to_iso(now),
                    to_iso(expires_at),
                    to_iso(now),
                ),
            )
        return UserSession(token, csrf_token, to_iso(expires_at), self._row_to_user(row))

    def resolve_session(self, token: str | None) -> UserSession | None:
        if not token or len(token) > 256:
            return None
        now = utc_now()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    s.csrf_token,s.expires_at AS session_expires,
                    s.auth_version AS session_version,
                    u.*
                FROM user_sessions AS s
                JOIN users AS u ON u.id=s.user_id
                WHERE s.token_hash=?
                """,
                (_token_hash(token),),
            ).fetchone()
            if row is None:
                return None
            session_expiry = parse_iso(row["session_expires"])
            valid = (
                session_expiry is not None
                and session_expiry > now
                and self._active_now(row, now)
                and int(row["session_version"]) == int(row["auth_version"])
            )
            if not valid:
                connection.execute(
                    "DELETE FROM user_sessions WHERE token_hash=?",
                    (_token_hash(token),),
                )
                return None
            connection.execute(
                "UPDATE user_sessions SET last_seen_at=? WHERE token_hash=?",
                (to_iso(now), _token_hash(token)),
            )
            return UserSession(
                token=token,
                csrf_token=str(row["csrf_token"]),
                expires_at=str(row["session_expires"]),
                user=self._row_to_user(row),
            )

    def revoke_session(self, token: str | None) -> None:
        if not token:
            return
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM user_sessions WHERE token_hash=?",
                (_token_hash(token),),
            )

    def cleanup_sessions(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM user_sessions WHERE expires_at<=?",
                (to_iso(utc_now()),),
            )
            return int(cursor.rowcount)

    def _replace_password(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        new_password: str,
        *,
        must_change_password: bool,
        actor: str,
        action: str,
    ) -> None:
        encoded = hash_password(new_password)
        now = to_iso(utc_now())
        connection.execute(
            """
            UPDATE users SET password_hash=?,must_change_password=?,
                auth_version=auth_version+1,updated_at=? WHERE id=?
            """,
            (encoded, int(must_change_password), now, row["id"]),
        )
        connection.execute("DELETE FROM user_sessions WHERE user_id=?", (row["id"],))
        self._audit(connection, actor, action, str(row["username"]))

    def change_own_password(
        self,
        username: str,
        current_password: str,
        new_password: str,
    ) -> None:
        normalized = normalize_username(username)
        with self._connect() as connection:
            row = self._get_user_row(connection, normalized)
            if not verify_password(current_password, str(row["password_hash"])):
                self._audit(connection, normalized, "password-change-failed", normalized)
                raise UserError("current password is invalid")
            self._replace_password(
                connection,
                row,
                new_password,
                must_change_password=False,
                actor=normalized,
                action="change-password",
            )

    def reset_password(
        self,
        username: str,
        new_password: str,
        *,
        must_change_password: bool = True,
        actor: str = "cli",
    ) -> None:
        with self._connect() as connection:
            row = self._get_user_row(connection, username)
            self._replace_password(
                connection,
                row,
                new_password,
                must_change_password=must_change_password,
                actor=actor,
                action="reset-password",
            )

    def set_active(self, username: str, active: bool, *, actor: str = "cli") -> None:
        with self._connect() as connection:
            row = self._get_user_row(connection, username)
            if not active and row["role"] == "admin":
                if self._usable_admin_count(connection, excluding_id=int(row["id"])) < 1:
                    raise UserError("cannot disable the last usable administrator")
            connection.execute(
                """
                UPDATE users SET active=?,auth_version=auth_version+1,updated_at=?
                WHERE id=?
                """,
                (int(active), to_iso(utc_now()), row["id"]),
            )
            if not active:
                connection.execute(
                    "DELETE FROM user_sessions WHERE user_id=?",
                    (row["id"],),
                )
            self._audit(
                connection,
                actor,
                "enable-user" if active else "disable-user",
                str(row["username"]),
            )

    def set_role(self, username: str, role: str, *, actor: str = "cli") -> None:
        role = role.casefold()
        if role not in ROLES:
            raise UserError("role must be admin, operator, or viewer")
        with self._connect() as connection:
            row = self._get_user_row(connection, username)
            if row["role"] == "admin" and role != "admin":
                if self._usable_admin_count(connection, excluding_id=int(row["id"])) < 1:
                    raise UserError("cannot demote the last usable administrator")
            connection.execute(
                """
                UPDATE users SET role=?,auth_version=auth_version+1,updated_at=?
                WHERE id=?
                """,
                (role, to_iso(utc_now()), row["id"]),
            )
            connection.execute("DELETE FROM user_sessions WHERE user_id=?", (row["id"],))
            self._audit(connection, actor, "set-role", str(row["username"]), role)

    def set_expiration(
        self,
        username: str,
        expires_at: datetime | None,
        *,
        actor: str = "cli",
    ) -> None:
        if expires_at is not None:
            expires_at = expires_at.astimezone(timezone.utc)
            if expires_at <= utc_now():
                raise UserError("expiration must be in the future")
        with self._connect() as connection:
            row = self._get_user_row(connection, username)
            if row["role"] == "admin" and expires_at is not None:
                if self._usable_admin_count(connection, excluding_id=int(row["id"])) < 1:
                    raise UserError("the last usable administrator cannot be temporary")
            connection.execute(
                """
                UPDATE users SET expires_at=?,auth_version=auth_version+1,updated_at=?
                WHERE id=?
                """,
                (
                    to_iso(expires_at) if expires_at else None,
                    to_iso(utc_now()),
                    row["id"],
                ),
            )
            connection.execute("DELETE FROM user_sessions WHERE user_id=?", (row["id"],))
            self._audit(
                connection,
                actor,
                "set-expiration",
                str(row["username"]),
                to_iso(expires_at) if expires_at else "never",
            )

    def delete_user(self, username: str, *, actor: str = "cli") -> None:
        with self._connect() as connection:
            row = self._get_user_row(connection, username)
            if row["role"] == "admin":
                if self._usable_admin_count(connection, excluding_id=int(row["id"])) < 1:
                    raise UserError("cannot delete the last usable administrator")
            connection.execute("DELETE FROM users WHERE id=?", (row["id"],))
            self._audit(connection, actor, "delete-user", str(row["username"]))

    def audit_events(self, limit: int = 100) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 1000))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT created_at,actor,action,target,details
                FROM user_audit ORDER BY id DESC LIMIT ?
                """,
                (bounded,),
            ).fetchall()
            return [dict(row) for row in rows]
