from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JAVASCRIPT = (
    ROOT / "src" / "blind_sqli" / "webui" / "inference-options.js"
).read_text(encoding="utf-8")


class PackedGraphAndWorkerTests(unittest.TestCase):
    def test_graph_uses_two_dimensional_space_aware_packing(self) -> None:
        self.assertIn("packedLayoutGraph", JAVASCRIPT)
        self.assertIn("packedGraphColumns", JAVASCRIPT)
        self.assertIn("packedGraphOrder", JAVASCRIPT)
        self.assertIn("rectanglesOverlap", JAVASCRIPT)
        self.assertIn("graphViewportSize()", JAVASCRIPT)
        self.assertIn("horizontalGap: 14", JAVASCRIPT)
        self.assertIn("verticalGap: 12", JAVASCRIPT)
        self.assertNotIn("depth * COMPACT_GRAPH.horizontalGap", JAVASCRIPT)

    def test_graph_keeps_automatic_fit_until_manual_interaction(self) -> None:
        self.assertIn(
            "const preserveManualLayout = graphState.userTransformed && !force",
            JAVASCRIPT,
        )
        self.assertIn("graphState.positions.clear()", JAVASCRIPT)

    def test_activity_panel_only_renders_running_workers(self) -> None:
        self.assertIn("renderOnlyActiveWorkers", JAVASCRIPT)
        self.assertIn('activity.status === "running"', JAVASCRIPT)
        self.assertIn('empty.textContent = "No active workers."', JAVASCRIPT)


if __name__ == "__main__":
    unittest.main()
