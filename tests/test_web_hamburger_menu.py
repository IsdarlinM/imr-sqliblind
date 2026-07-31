from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from blind_sqli.web_support import load_asset

ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "src" / "blind_sqli" / "webui"
MENU_JS = WEBUI / "web-menu.js"
MENU_RUNTIME_JS = WEBUI / "web-menu-runtime.js"
MENU_CSS = WEBUI / "web-menu.css"


class WebHamburgerMenuTests(unittest.TestCase):
    def test_menu_javascript_is_valid(self) -> None:
        subprocess.run(["node", "--check", str(MENU_JS)], check=True)
        subprocess.run(["node", "--check", str(MENU_RUNTIME_JS)], check=True)

    def test_menu_has_sessions_defaults_and_temporary_custom_scan(self) -> None:
        javascript = MENU_JS.read_text(encoding="utf-8")
        for text in (
            '"sessions", "Sessions"',
            '"defaults", "Default configuration"',
            '"custom", "Custom scan"',
            'api("/api/settings/default-scan")',
            'method: "PUT"',
            'api("/api/scans"',
            "Custom scan started. Defaults were not changed.",
            "event.stopImmediatePropagation()",
        ):
            self.assertIn(text, javascript)
        self.assertIn("scanMenuState.customDraft", javascript)
        self.assertIn("scanMenuState.defaultDraft", javascript)
        self.assertNotIn("localStorage", javascript)

    def test_menu_styles_convert_sidebar_to_accessible_overlay(self) -> None:
        stylesheet = MENU_CSS.read_text(encoding="utf-8")
        for selector in (
            ".app-menu-toggle",
            ".app-menu.open",
            ".app-menu-backdrop",
            ".app-menu-navigation",
            ".scan-menu-actions",
            "body.web-menu-open",
        ):
            self.assertIn(selector, stylesheet)
        self.assertIn("transform: translateX(-104%)", stylesheet)
        self.assertIn("position: fixed", stylesheet)

    def test_existing_authenticated_assets_bundle_menu_companions(self) -> None:
        javascript = load_asset("inference-options.js")
        stylesheet = load_asset("app.css")
        self.assertIn("buildScanMenu();", javascript)
        self.assertIn("runTemporaryCustomScanAndReset", javascript)
        self.assertIn(".app-menu-toggle", stylesheet)
        self.assertIn(".graph-node-tooltip", stylesheet)


if __name__ == "__main__":
    unittest.main()
