from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "src" / "blind_sqli" / "webui"


class ProfessionalUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.javascript = "\n".join(
            (WEBUI / name).read_text(encoding="utf-8")
            for name in ("professional-ui.js", "professional-ui-runtime.js")
        )
        cls.styles = (WEBUI / "professional-ui.css").read_text(encoding="utf-8")
        cls.support = (ROOT / "src" / "blind_sqli" / "web_support.py").read_text(
            encoding="utf-8"
        )

    def test_professional_assets_are_loaded_last(self) -> None:
        self.assertIn('"professional-ui.css"', self.support)
        self.assertIn('"professional-ui.js"', self.support)
        self.assertIn('"professional-ui-runtime.js"', self.support)
        self.assertLess(self.support.index('"table-view.css"'), self.support.index('"professional-ui.css"'))
        self.assertLess(self.support.index('"table-view-runtime.js"'), self.support.index('"professional-ui.js"'))

    def test_tree_and_tables_use_native_collapsible_controls(self) -> None:
        self.assertIn('document.createElement("details")', self.javascript)
        self.assertIn("renderProfessionalTree", self.javascript)
        self.assertIn("buildProfessionalTableCard", self.javascript)
        self.assertIn("body.dataset.loaded", self.javascript)
        self.assertIn("Expand visible", self.javascript)
        self.assertIn("Collapse all", self.javascript)

    def test_graph_drag_propagates_with_bounded_elastic_falloff(self) -> None:
        self.assertIn("professionalElasticCluster", self.javascript)
        self.assertIn("elasticWeights: Object.freeze([1, 0.58, 0.34, 0.2, 0.12])", self.javascript)
        self.assertIn("elasticMaxNodes: 120", self.javascript)
        self.assertIn("graph-edge-elastic", self.javascript)

    def test_virtualization_workspace_comparison_and_telemetry(self) -> None:
        self.assertIn("professionalVirtualList", self.javascript)
        self.assertIn("persistProfessionalWorkspace", self.javascript)
        self.assertIn("renderSessionDiff", self.javascript)
        self.assertIn("renderOperationalTelemetry", self.javascript)
        self.assertIn("isolateSelectedGraphContext", self.javascript)
        self.assertIn("professional-resize-handle", self.styles)

    def test_ui_avoids_unsafe_html_injection(self) -> None:
        self.assertNotIn("innerHTML", self.javascript)
        self.assertNotIn("insertAdjacentHTML", self.javascript)
        self.assertNotIn("eval(", self.javascript)

    def test_density_shortcuts_and_responsive_rules_exist(self) -> None:
        self.assertIn("sqliblind.ui.density", self.javascript)
        self.assertIn('event.key === "/"', self.javascript)
        self.assertIn("professional-tab-count", self.javascript)
        self.assertIn("ui-density-compact", self.styles)
        self.assertIn("@media (max-width: 860px)", self.styles)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.styles)


if __name__ == "__main__":
    unittest.main()
