from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from blind_sqli.web_support import load_asset

ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "src" / "blind_sqli" / "webui"
JAVASCRIPT = WEBUI / "graph-interactions.js"
STYLESHEET = WEBUI / "graph-interactions.css"
HARNESS = ROOT / "tests" / "graph_interactions_harness.js"


class GraphRelationshipHighlightTests(unittest.TestCase):
    def test_javascript_is_valid_and_behavior_harness_passes(self) -> None:
        subprocess.run(["node", "--check", str(JAVASCRIPT)], check=True)
        subprocess.run(["node", str(HARNESS), str(JAVASCRIPT)], check=True)

    def test_direct_relationship_and_hover_features_are_present(self) -> None:
        javascript = JAVASCRIPT.read_text(encoding="utf-8")
        self.assertIn("directGraphContext", javascript)
        self.assertIn("relation.source_id === entityId", javascript)
        self.assertIn("relation.target_id === entityId", javascript)
        self.assertIn('addEventListener("pointerenter"', javascript)
        self.assertIn('addEventListener("pointerleave"', javascript)
        self.assertIn('addEventListener("pointerup"', javascript)
        self.assertIn("graph-node-tooltip", javascript)
        self.assertIn("textContent", javascript)
        self.assertNotIn("innerHTML", javascript)

    def test_highlight_styles_cover_nodes_edges_and_tooltip(self) -> None:
        stylesheet = STYLESHEET.read_text(encoding="utf-8")
        for selector in (
            ".graph-node-focused",
            ".graph-node-related",
            ".graph-node-muted",
            ".graph-edge-related",
            ".graph-edge-muted",
            ".graph-node-tooltip",
        ):
            self.assertIn(selector, stylesheet)

    def test_public_assets_include_graph_interaction_companions(self) -> None:
        self.assertIn(
            "renderGraphWithDirectRelations",
            load_asset("inference-options.js"),
        )
        self.assertIn(".graph-node-tooltip", load_asset("app.css"))


if __name__ == "__main__":
    unittest.main()
