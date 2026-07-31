from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from blind_sqli.cli import build_parser
from blind_sqli.graph import FORMATS, render_database_map, write_report
from blind_sqli.models import DatabaseMap, Schema, Table
from blind_sqli.table_reports import ascii_table


class TableReportTests(unittest.TestCase):
    def database(self) -> DatabaseMap:
        table = Table(
            "User_Profile%",
            ["id", "email_address", "_marker"],
            [
                {
                    "id": "1",
                    "email_address": "alpha@example.test",
                    "_marker": "%",
                },
                {
                    "id": "2",
                    "email_address": "<script>alert(1)</script>",
                    "_marker": "_",
                },
            ],
        )
        return DatabaseMap([Schema("main", [table])])

    def test_ascii_table_renderer_uses_ascii_borders_and_bounded_width(
        self,
    ) -> None:
        output = render_database_map(self.database(), output_format="tables")
        self.assertIn("DATABASE TABLE VIEW", output)
        self.assertIn("TABLE main.User_Profile%", output)
        self.assertIn("_marker", output)
        self.assertIn("%", output)
        self.assertNotIn("├", output)
        allowed = set(
            "+-| 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "abcdefghijklmnopqrstuvwxyz_%.@<>/()':"
        )
        for line in output.splitlines():
            self.assertLessEqual(len(line), 180)
            if line.startswith(("+", "|")):
                self.assertTrue(set(line) <= allowed)

    def test_html_table_renderer_escapes_values_and_is_self_contained(
        self,
    ) -> None:
        output = render_database_map(
            self.database(),
            output_format="html-tables",
            title="Table report",
        )
        self.assertIn("<table", output)
        self.assertIn("main.User_Profile%", output)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", output)
        self.assertNotIn("<script>alert(1)</script>", output)
        self.assertIn("default-src 'none'", output)
        self.assertNotIn("https://", output)

    def test_formats_and_cli_parser_include_table_exports(self) -> None:
        self.assertIn("tables", FORMATS)
        self.assertIn("html-tables", FORMATS)
        parser = build_parser()
        args = parser.parse_args(["map", "--format", "tables"])
        self.assertEqual(args.format, "tables")
        html_args = parser.parse_args(["map", "--format", "html-tables"])
        self.assertEqual(html_args.format, "html-tables")

    def test_ascii_table_flattens_multiline_values(self) -> None:
        output = ascii_table(
            ("Column", "Value"),
            [("note", "line one\nline two\tline three")],
            max_table_width=60,
        )
        self.assertIn("line one line two line three", output)
        self.assertNotIn("\t", output)

    def test_table_report_is_written_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_report(
                Path(directory) / "map",
                render_database_map(self.database(), output_format="tables"),
            )
            self.assertEqual(path.suffix, ".txt")
            self.assertIn(
                "User_Profile%",
                path.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
