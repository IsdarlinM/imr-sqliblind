from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from blind_sqli.manager import ScanManager
from blind_sqli.store import SessionStore
from blind_sqli.web_app import create_app
from blind_sqli.web_support import AUTH_COOKIE, CSRF_COOKIE


class WebDefaultProfileApiTests(unittest.TestCase):
    def test_default_profile_requires_auth_and_csrf_then_round_trips(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ImportError as exc:  # pragma: no cover
            self.skipTest(str(exc))

        with tempfile.TemporaryDirectory() as temporary:
            store = SessionStore(Path(temporary) / "sessions.sqlite3")
            manager = ScanManager(store)
            try:
                app = create_app(
                    manager,
                    auth_token="test-auth",
                    csrf_token="test-csrf",
                )
                with TestClient(app) as client:
                    unauthenticated = client.get("/api/settings/default-scan")
                    self.assertEqual(unauthenticated.status_code, 401)

                    client.cookies.set(AUTH_COOKIE, "test-auth")
                    client.cookies.set(CSRF_COOKIE, "test-csrf")
                    initial = client.get("/api/settings/default-scan")
                    self.assertEqual(initial.status_code, 200)
                    self.assertFalse(initial.json()["saved"])
                    self.assertEqual(initial.json()["config"]["workers"], 4)

                    missing_csrf = client.put(
                        "/api/settings/default-scan",
                        json={"workers": 6},
                    )
                    self.assertEqual(missing_csrf.status_code, 403)

                    saved = client.put(
                        "/api/settings/default-scan",
                        headers={"X-SQLIBLIND-CSRF": "test-csrf"},
                        json={
                            "workers": 6,
                            "dialect": "sqlite",
                            "headers": {
                                "X-Research": "imr",
                                "Authorization": "secret",
                            },
                            "cookies": {"session": "secret"},
                        },
                    )
                    self.assertEqual(saved.status_code, 200)
                    payload = saved.json()
                    self.assertTrue(payload["saved"])
                    self.assertEqual(payload["config"]["workers"], 6)
                    self.assertEqual(payload["config"]["dialect"], "sqlite")
                    self.assertEqual(
                        payload["config"]["headers"],
                        {"X-Research": "imr"},
                    )
                    self.assertEqual(payload["config"]["cookies"], {})

                    loaded = client.get("/api/settings/default-scan").json()
                    self.assertTrue(loaded["saved"])
                    self.assertEqual(loaded["config"]["workers"], 6)
            finally:
                manager.shutdown()
                store.close()


if __name__ == "__main__":
    unittest.main()
