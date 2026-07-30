from __future__ import annotations

import unittest

from blind_sqli.graph import render_html, render_mermaid, render_relations, render_tree
from blind_sqli.models import DatabaseMap, Schema, Table


class GraphCompatibilityTests(unittest.TestCase):
    def test_all_formats_and_escaping(self) -> None:
        database = DatabaseMap([Schema("main", [Table("users", ["id", "name"])])])
        self.assertIn("[TABLE] users", render_tree(database))
        self.assertIn("flowchart LR", render_mermaid(database))
        self.assertIn('[COLUMN] "id"', render_relations(database))
        html = render_html(database, title="Lab map")
        self.assertIn("No external resources", html)
        self.assertNotIn("https://", html)
        unsafe = render_html(DatabaseMap([Schema("<script>alert(1)</script>")]))
        self.assertIn("&lt;script&gt;", unsafe)


if __name__ == "__main__":
    unittest.main()
