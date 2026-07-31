from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from blind_sqli.web_support import load_asset

ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "src" / "blind_sqli" / "webui"
TABLE_JS = WEBUI / "table-view.js"
TABLE_RUNTIME_JS = WEBUI / "table-view-runtime.js"
TABLE_CSS = WEBUI / "table-view.css"
HARNESS = ROOT / "tests" / "table_view_harness.js"


class WebTableViewTests(unittest.TestCase):
    def test_table_view_javascript_is_valid_and_harness_passes(self) -> None:
        subprocess.run(["node", "--check", str(TABLE_JS)], check=True)
        subprocess.run(["node", "--check", str(TABLE_RUNTIME_JS)], check=True)
        subprocess.run(
            ["node", str(HARNESS), str(TABLE_JS), str(TABLE_RUNTIME_JS)],
            check=True,
        )

    def test_table_view_uses_native_tables_and_safe_text_nodes(self) -> None:
        javascript = TABLE_JS.read_text(encoding="utf-8")
        for value in (
            'tableViewElement("table"',
            'document.createElement("thead")',
            'document.createElement("tbody")',
            'button.dataset.pane = "tables"',
            'option.value = value',
            '"tables", "html-tables"',
            "tableViewAsciiReport",
            "tableViewHtmlReport",
            "event.stopImmediatePropagation()",
        ):
            self.assertIn(value, javascript)
        self.assertIn("textContent", javascript)
        self.assertNotIn("innerHTML", javascript)

    def test_table_view_is_lazy_and_responsive(self) -> None:
        runtime = TABLE_RUNTIME_JS.read_text(encoding="utf-8")
        stylesheet = TABLE_CSS.read_text(encoding="utf-8")
        self.assertIn('state.activePane !== "tables"', runtime)
        self.assertIn("content-visibility: auto", stylesheet)
        self.assertIn("overflow: auto", stylesheet)
        self.assertIn("@media (max-width: 620px)", stylesheet)

    def test_authenticated_assets_bundle_table_view(self) -> None:
        javascript = load_asset("inference-options.js")
        stylesheet = load_asset("app.css")
        self.assertIn("buildTableView();", javascript)
        self.assertIn("renderTableViewWhenVisible", javascript)
        self.assertIn(".entity-table-card", stylesheet)
        self.assertIn(".graph-node-tooltip", stylesheet)
        self.assertIn(".app-menu-toggle", stylesheet)


if __name__ == "__main__":
    unittest.main()
