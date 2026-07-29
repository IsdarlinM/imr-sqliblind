from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from blind_sqli.graph import (
    render_database_map,
    render_html,
    render_mermaid,
    render_relations,
    render_tree,
    write_report,
    write_text_report,
)
from blind_sqli.models import DatabaseMap, Schema, Table


def sample_map() -> DatabaseMap:
    database = DatabaseMap()
    main = database.add_schema(Schema("main"))
    users = main.add_table(Table("users", ["id", "name"]))
    users.add_column("NAME")
    main.add_table(Table("sessions", ["token", "user_id"]))
    database.add_schema(Schema("audit", [Table("events", ["event_id"])]))
    return database


class ModelTests(unittest.TestCase):
    def test_add_row_maps_values_to_columns(self) -> None:
        table = Table("users", ["id", "name"])
        table.add_row([1, "alice"])
        self.assertEqual(table.rows, [{"id": 1, "name": "alice"}])

    def test_add_row_rejects_wrong_width(self) -> None:
        with self.assertRaises(ValueError):
            Table("users", ["id"]).add_row([])

    def test_add_column_rejects_empty_name(self) -> None:
        with self.assertRaises(ValueError):
            Table("users").add_column("")

    def test_add_column_deduplicates_case_insensitively(self) -> None:
        table = Table("users", ["Name"])
        table.add_column("name")
        self.assertEqual(table.columns, ["Name"])

    def test_schema_merges_duplicate_table_columns(self) -> None:
        schema = Schema("main", [Table("Users", ["id"])])
        merged = schema.add_table(Table("users", ["name"]))
        self.assertEqual(merged.columns, ["id", "name"])
        self.assertEqual(len(schema.tables), 1)

    def test_database_merges_duplicate_schemas(self) -> None:
        database = DatabaseMap([Schema("Main", [Table("a")])])
        merged = database.add_schema(Schema("main", [Table("b")]))
        self.assertEqual([table.name for table in merged.tables], ["a", "b"])
        self.assertEqual(database.schema_count, 1)

    def test_database_summary_and_dict(self) -> None:
        database = sample_map()
        self.assertEqual(database.schema_count, 2)
        self.assertEqual(database.table_count, 3)
        self.assertEqual(database.column_count, 5)
        self.assertEqual(database.relationship_count, 8)
        self.assertEqual(database.to_dict()["summary"]["relationships"], 8)


class GraphTests(unittest.TestCase):
    def test_unicode_tree_contains_hierarchy_and_summary(self) -> None:
        output = render_tree(sample_map())
        self.assertIn("├── [SCHEMA] main", output)
        self.assertIn("[TABLE] users", output)
        self.assertIn("[COLUMN] id", output)
        self.assertIn("Relationships: 8", output)

    def test_ascii_tree_has_no_unicode_connectors(self) -> None:
        output = render_tree(sample_map(), ascii_only=True)
        self.assertIn("|-- [SCHEMA] main", output)
        self.assertNotIn("├", output)

    def test_empty_tree_is_explicit(self) -> None:
        self.assertIn("(no schemas found)", render_tree(DatabaseMap()))

    def test_tree_marks_unenumerated_columns(self) -> None:
        database = DatabaseMap([Schema("main", [Table("users")])])
        self.assertIn("columns not enumerated", render_tree(database))

    def test_relations_lists_schema_table_and_table_column_edges(self) -> None:
        output = render_relations(sample_map())
        self.assertIn('[SCHEMA] "main" -> [TABLE] "users"', output)
        self.assertIn('[TABLE] "main.users" -> [COLUMN] "id"', output)
        self.assertIn("Relationships: 8", output)

    def test_mermaid_has_unique_nodes_and_edges(self) -> None:
        output = render_mermaid(sample_map())
        self.assertTrue(output.startswith("flowchart LR"))
        self.assertIn('n0["schema: main"]', output)
        self.assertIn("n0 --> n1", output)
        self.assertIn("column: event_id", output)

    def test_mermaid_escapes_quotes_and_newlines(self) -> None:
        database = DatabaseMap([Schema('x"\ny')])
        output = render_mermaid(database)
        self.assertIn("x&quot; y", output)
        self.assertNotIn('x"\ny', output)

    def test_html_is_self_contained_and_interactive(self) -> None:
        output = render_html(sample_map(), title="Lab map")
        self.assertIn("<!doctype html>", output)
        self.assertIn("Content-Security-Policy", output)
        self.assertIn('id="search"', output)
        self.assertIn("Expand all", output)
        self.assertIn("No external resources", output)
        self.assertNotIn("https://", output)

    def test_html_escapes_discovered_names_and_title(self) -> None:
        database = DatabaseMap(
            [Schema("<script>alert(1)</script>", [Table('x" onclick="bad')])]
        )
        output = render_html(database, title="<b>unsafe</b>")
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", output)
        self.assertIn("&lt;b&gt;unsafe&lt;/b&gt;", output)
        self.assertNotIn("<script>alert(1)</script>", output)
        self.assertNotIn('onclick="bad"', output)

    def test_dispatches_all_formats(self) -> None:
        database = sample_map()
        self.assertIn("DATABASE STRUCTURE", render_database_map(database, output_format="tree"))
        self.assertIn("DATABASE RELATIONSHIPS", render_database_map(database, output_format="relations"))
        self.assertIn("flowchart LR", render_database_map(database, output_format="mermaid"))
        self.assertIn("<!doctype html>", render_database_map(database, output_format="html"))

    def test_invalid_format_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            render_database_map(sample_map(), output_format="png")

    def test_write_text_report_adds_txt_suffix_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_text_report(Path(directory) / "schema-map", "hello")
            self.assertEqual(path.suffix, ".txt")
            self.assertEqual(path.read_text(encoding="utf-8"), "hello\n")
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_write_report_uses_requested_html_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_report(
                Path(directory) / "schema-map", "<html></html>", default_suffix=".html"
            )
            self.assertEqual(path.name, "schema-map.html")
            self.assertIn("<html>", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
