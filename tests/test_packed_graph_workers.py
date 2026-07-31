from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JAVASCRIPT = (
    ROOT / "src" / "blind_sqli" / "webui" / "inference-options.js"
).read_text(encoding="utf-8")


class DynamicGraphAndWorkerTests(unittest.TestCase):
    def test_graph_uses_random_collision_free_positions(self) -> None:
        self.assertIn("randomAvailableLayoutGraph", JAVASCRIPT)
        self.assertIn("randomAvailableGraphPosition", JAVASCRIPT)
        self.assertIn("randomGraphCandidate", JAVASCRIPT)
        self.assertIn("rectanglesOverlap", JAVASCRIPT)
        self.assertIn("dynamicGraphBounds", JAVASCRIPT)
        self.assertIn("Math.random()", JAVASCRIPT)
        self.assertIn("randomAttempts: 180", JAVASCRIPT)

    def test_graph_animates_and_auto_fits_as_nodes_arrive(self) -> None:
        self.assertIn("startDynamicGraphMotion", JAVASCRIPT)
        self.assertIn("dynamicGraphStep", JAVASCRIPT)
        self.assertIn("requestAnimationFrame", JAVASCRIPT)
        self.assertIn("applyCollisionForces", JAVASCRIPT)
        self.assertIn("applyRelationshipForces", JAVASCRIPT)
        self.assertIn("fitGraph(entities)", JAVASCRIPT)
        self.assertIn("pendingMotion", JAVASCRIPT)
        self.assertIn("movableIds", JAVASCRIPT)

    def test_activity_panel_only_renders_current_searches(self) -> None:
        self.assertIn("renderOnlyCurrentSearches", JAVASCRIPT)
        self.assertIn('activity.status !== "running"', JAVASCRIPT)
        self.assertIn('activity.kind === "batch"', JAVASCRIPT)
        self.assertIn("activity.active === false", JAVASCRIPT)
        self.assertIn("state.scan?.config?.workers", JAVASCRIPT)
        self.assertIn(".slice(0, workerLimit)", JAVASCRIPT)
        self.assertIn('empty.textContent = "No active searches."', JAVASCRIPT)


if __name__ == "__main__":
    unittest.main()
