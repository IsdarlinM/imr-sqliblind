from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "src" / "blind_sqli" / "webui"


class _DocumentInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.scripts: list[dict[str, str | None]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        values = dict(attrs)
        identifier = values.get("id")
        if identifier:
            self.ids.add(identifier)
        if tag == "script":
            self.scripts.append(values)


class WebUiFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (WEBUI / "index.html").read_text(encoding="utf-8")
        cls.css = (WEBUI / "app.css").read_text(encoding="utf-8")
        cls.javascript = (WEBUI / "app.js").read_text(encoding="utf-8")

    def test_responsive_layout_has_required_controls(self) -> None:
        inspector = _DocumentInspector()
        inspector.feed(self.html)
        expected = {
            "graph",
            "graphViewport",
            "graphZoomIn",
            "graphZoomOut",
            "graphFit",
            "graphReset",
            "drawerBackdrop",
            "filter",
        }
        self.assertTrue(expected.issubset(inspector.ids))
        self.assertEqual(
            [script.get("src") for script in inspector.scripts],
            ["/assets/app.js"],
        )

    def test_css_prevents_common_overflow_and_mobile_deformation(self) -> None:
        self.assertIn("min-width: 0", self.css)
        self.assertIn("overflow-wrap: anywhere", self.css)
        self.assertIn("max-width: 100%", self.css)
        self.assertIn("touch-action: none", self.css)
        self.assertRegex(self.css, r"@media\s*\(max-width:\s*860px\)")
        self.assertRegex(self.css, r"@media\s*\(max-width:\s*620px\)")
        self.assertIn("grid-template-columns: 1fr", self.css)

    def test_graph_is_unlimited_interactive_and_position_persistent(self) -> None:
        self.assertNotIn(".slice(0, 120)", self.javascript)
        self.assertNotIn(".slice(0,120)", self.javascript)
        self.assertIn("positions: new Map()", self.javascript)
        self.assertIn('addEventListener("pointerdown"', self.javascript)
        self.assertIn('addEventListener("pointermove"', self.javascript)
        self.assertIn('addEventListener(\n    "wheel"', self.javascript)
        self.assertIn("setPointerCapture", self.javascript)
        self.assertIn("updateGraphEdges()", self.javascript)
        self.assertIn("fitGraph", self.javascript)
        self.assertIn("layoutGraph", self.javascript)

    def test_graph_labels_are_wrapped_without_fixed_line_truncation(self) -> None:
        self.assertIn("wrapGraphLabel", self.javascript)
        self.assertIn('createSvg("tspan"', self.javascript)
        self.assertNotRegex(
            self.javascript,
            re.compile(r"entity\.name\.slice\s*\("),
        )

    def test_activity_snapshot_patch_is_integrated_in_main_javascript(self) -> None:
        self.assertIn("snapshot.activities || []", self.javascript)
        self.assertIn("started_at: startedAt", self.javascript)
        self.assertNotIn("const selectScanBase=selectScan", self.html)


if __name__ == "__main__":
    unittest.main()
