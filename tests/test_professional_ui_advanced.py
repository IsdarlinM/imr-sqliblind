from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "src" / "blind_sqli" / "webui"


class AdvancedProfessionalUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.javascript = (WEBUI / "professional-ui-advanced.js").read_text(
            encoding="utf-8"
        )
        cls.styles = (WEBUI / "professional-ui-advanced.css").read_text(
            encoding="utf-8"
        )
        cls.support = (ROOT / "src" / "blind_sqli" / "web_support.py").read_text(
            encoding="utf-8"
        )

    def test_advanced_assets_load_after_base_professional_layer(self) -> None:
        self.assertIn('"professional-ui-advanced.css"', self.support)
        self.assertIn('"professional-ui-advanced.js"', self.support)
        self.assertLess(
            self.support.index('"professional-ui.css"'),
            self.support.index('"professional-ui-advanced.css"'),
        )
        self.assertLess(
            self.support.index('"professional-ui-runtime.js"'),
            self.support.index('"professional-ui-advanced.js"'),
        )

    def test_workspace_restores_view_and_complete_html_exports(self) -> None:
        self.assertIn("restoreWorkspaceWithActivePane", self.javascript)
        self.assertIn("tableViewHtmlReportComplete", self.javascript)
        self.assertIn("dispatchEvent(new Event(\"toggle\"))", self.javascript)

    def test_graph_minimap_filters_and_panel_resizers_exist(self) -> None:
        self.assertIn("renderGraphMinimap", self.javascript)
        self.assertIn("graphMinimap", self.javascript)
        self.assertIn("bindVerticalResize", self.javascript)
        self.assertIn("--activity-panel-height", self.javascript)
        self.assertIn("--graph-height", self.javascript)
        self.assertIn(".professional-graph-minimap", self.styles)
        self.assertIn(".professional-vertical-resizer", self.styles)

    def test_telemetry_uses_live_activity_and_bounded_eta(self) -> None:
        self.assertIn("renderLiveOperationalTelemetry", self.javascript)
        self.assertIn("telemetryEstimate", self.javascript)
        self.assertIn("activity.status === \"running\"", self.javascript)
        self.assertIn("Number(item.payload?.status_code) === 429", self.javascript)

    def test_no_unsafe_dynamic_html(self) -> None:
        self.assertNotIn("innerHTML", self.javascript)
        self.assertNotIn("insertAdjacentHTML", self.javascript)
        self.assertNotIn("eval(", self.javascript)


if __name__ == "__main__":
    unittest.main()
