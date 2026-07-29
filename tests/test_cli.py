from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from blind_sqli import __version__
from blind_sqli.cli import (
    BASE_URL,
    _build_extractor,
    _parse_key_value,
    _parse_statuses,
    build_parser,
    main,
)
from blind_sqli.models import DatabaseMap, ProbeResult, Schema, Table


class FakeExtractor:
    def __init__(self) -> None:
        self.client = SimpleNamespace(requests_used=17)
        self.elapsed_seconds = 1.2345
        self.calls: list[tuple[object, ...]] = []
        self.raise_on: str | None = None

    def _record(self, name: str, *values: object) -> None:
        self.calls.append((name, *values))
        if self.raise_on == name:
            raise RuntimeError(f"failed {name}")

    def calibrate(self):
        self._record("calibrate")
        return (
            ProbeResult(True, 200, 100, 0.1, "https://test/true"),
            ProbeResult(False, 400, 20, 0.1, "https://test/false"),
        )

    def enumerate_schemas(self):
        self._record("schemas")
        return ["main", "audit"]

    def enumerate_tables(self, schema: str):
        self._record("tables", schema)
        return ["users", "sessions"]

    def enumerate_columns(self, schema: str, table: str):
        self._record("columns", schema, table)
        return ["id", "name"]

    def extract_string(self, expression: str):
        self._record("extract", expression)
        return "value"

    def probe_condition(self, condition: str):
        self._record("probe", condition)
        return ProbeResult(True, 200, 12, 0.05, "https://test/probe")

    def build_database_map(self, *, include_columns: bool = True):
        self._record("map", include_columns)
        columns = ["id", "name"] if include_columns else []
        return DatabaseMap([Schema("main", [Table("users", columns)])])


class ParserHelperTests(unittest.TestCase):
    def test_base_url_is_preserved(self) -> None:
        self.assertEqual(
            BASE_URL,
            "https://08d9880a384777322d0e2df7db7e5215.ctf.hacker101.com/fetch",
        )
        args = build_parser().parse_args(["schemas"])
        self.assertEqual(args.url, BASE_URL)

    def test_parse_key_value_supports_colons_inside_value(self) -> None:
        self.assertEqual(
            _parse_key_value(["Authorization:Bearer:a:b"], ":", "--header"),
            {"Authorization": "Bearer:a:b"},
        )
        with self.assertRaises(ValueError):
            _parse_key_value(["broken"], ":", "--header")
        with self.assertRaises(ValueError):
            _parse_key_value([":value"], ":", "--header")

    def test_parse_statuses_validates_input(self) -> None:
        self.assertEqual(_parse_statuses("200, 302"), {200, 302})
        for value in ("", "abc", "99", "600"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _parse_statuses(value)

    def test_each_command_and_alias_parses(self) -> None:
        parser = build_parser()
        cases = [
            (["schemas"], "schemas"),
            (["tables", "--schema", "main"], "tables"),
            (["columns", "--schema", "main", "--table", "users"], "columns"),
            (["extract", "--expression", "SELECT 1"], "extract"),
            (["probe", "--condition", "1=1"], "probe"),
            (["map"], "map"),
            (["graph"], "graph"),
            (["schema-map"], "schema-map"),
        ]
        for argv, expected in cases:
            with self.subTest(argv=argv):
                self.assertEqual(parser.parse_args(argv).command, expected)

    def test_required_command_arguments_are_enforced(self) -> None:
        parser = build_parser()
        for argv in (
            ["tables"],
            ["columns", "--schema", "main"],
            ["extract"],
            ["probe"],
        ):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                parser.parse_args(argv)

    def test_all_global_and_map_arguments_are_wired(self) -> None:
        argv = [
            "--url", "https://lab.test/fetch?x=1",
            "--parameter", "item",
            "--url-template", "https://lab.test/?item={{PAYLOAD}}",
            "--dialect", "sqlite",
            "--oracle", "length",
            "--true-status", "200,302",
            "--true-marker", "OK",
            "--true-regex", "A+",
            "--true-length", "123",
            "--length-tolerance", "4",
            "--timeout", "7.5",
            "--retries", "3",
            "--delay", "0.25",
            "--max-requests", "900",
            "--workers", "8",
            "--max-length", "200",
            "--max-items", "50",
            "--min-char-code", "1",
            "--max-char-code", "255",
            "--header", "X-Test:yes",
            "--cookie", "session=abc",
            "--proxy", "http://127.0.0.1:8080",
            "--insecure",
            "--skip-calibration",
            "--json",
            "map",
            "--format", "html",
            "--output", "map.html",
            "--ascii",
            "--no-columns",
            "--title", "Lab report",
        ]
        args = build_parser().parse_args(argv)
        extractor = _build_extractor(args)
        config = extractor.client.config
        self.assertEqual(config.url, "https://lab.test/fetch?x=1")
        self.assertEqual(config.parameter, "item")
        self.assertEqual(config.url_template, "https://lab.test/?item={{PAYLOAD}}")
        self.assertEqual(config.timeout, 7.5)
        self.assertFalse(config.verify_tls)
        self.assertEqual(config.retries, 3)
        self.assertEqual(config.delay, 0.25)
        self.assertEqual(config.max_requests, 900)
        self.assertEqual(config.headers, {"X-Test": "yes"})
        self.assertEqual(config.cookies, {"session": "abc"})
        self.assertEqual(config.proxy, "http://127.0.0.1:8080")
        self.assertEqual(extractor.dialect.name, "sqlite")
        self.assertEqual(extractor.oracle.mode, "length")
        self.assertEqual(extractor.oracle.true_statuses, frozenset({200, 302}))
        self.assertEqual(extractor.oracle.marker, "OK")
        self.assertEqual(extractor.oracle.expected_length, 123)
        self.assertEqual(extractor.oracle.length_tolerance, 4)
        self.assertEqual(extractor.config.workers, 8)
        self.assertEqual(extractor.config.max_length, 200)
        self.assertEqual(extractor.config.max_items, 50)
        self.assertEqual(extractor.config.min_char_code, 1)
        self.assertEqual(extractor.config.max_char_code, 255)
        self.assertTrue(args.skip_calibration)
        self.assertTrue(args.json_output)
        self.assertEqual(args.format, "html")
        self.assertEqual(args.output, "map.html")
        self.assertTrue(args.ascii_only)
        self.assertTrue(args.no_columns)
        self.assertEqual(args.title, "Lab report")

    def test_all_graph_formats_parse(self) -> None:
        parser = build_parser()
        for output_format in ("tree", "relations", "mermaid", "html"):
            with self.subTest(output_format=output_format):
                args = parser.parse_args(["map", "--format", output_format])
                self.assertEqual(args.format, output_format)

    def test_version_argument(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            build_parser().parse_args(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn(__version__, stdout.getvalue())


class MainCommandTests(unittest.TestCase):
    def run_main(self, fake: FakeExtractor, argv: list[str]):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("blind_sqli.cli._build_extractor", return_value=fake):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_default_command_runs_schemas_and_calibrates(self) -> None:
        fake = FakeExtractor()
        code, stdout, _ = self.run_main(fake, [])
        self.assertEqual(code, 0)
        self.assertEqual(fake.calls[:2], [("calibrate",), ("schemas",)])
        self.assertIn("Oracle calibrated", stdout)
        self.assertIn("[1] main", stdout)

    def test_skip_calibration(self) -> None:
        fake = FakeExtractor()
        code, _, _ = self.run_main(fake, ["--skip-calibration", "schemas"])
        self.assertEqual(code, 0)
        self.assertNotIn(("calibrate",), fake.calls)

    def test_tables_columns_extract_and_probe_commands(self) -> None:
        cases = [
            (["--skip-calibration", "tables", "--schema", "main"], ("tables", "main"), "users"),
            (["--skip-calibration", "columns", "--schema", "main", "--table", "users"], ("columns", "main", "users"), "name"),
            (["--skip-calibration", "extract", "--expression", "SELECT 1"], ("extract", "SELECT 1"), "value"),
            (["--skip-calibration", "probe", "--condition", "1=1"], ("probe", "1=1"), "matched"),
        ]
        for argv, expected_call, expected_text in cases:
            fake = FakeExtractor()
            with self.subTest(argv=argv):
                code, stdout, _ = self.run_main(fake, argv)
                self.assertEqual(code, 0)
                self.assertIn(expected_call, fake.calls)
                self.assertIn(expected_text, stdout)

    def test_json_output_is_valid(self) -> None:
        fake = FakeExtractor()
        code, stdout, _ = self.run_main(
            fake, ["--skip-calibration", "--json", "schemas"]
        )
        self.assertEqual(code, 0)
        document = json.loads(stdout)
        self.assertEqual(document["result"], ["main", "audit"])
        self.assertEqual(document["requests"], 17)

    def test_map_tree_and_aliases(self) -> None:
        for command in ("map", "graph", "schema-map"):
            fake = FakeExtractor()
            with self.subTest(command=command):
                code, stdout, _ = self.run_main(
                    fake, ["--skip-calibration", command]
                )
                self.assertEqual(code, 0)
                self.assertIn("DATABASE STRUCTURE", stdout)
                self.assertIn(("map", True), fake.calls)

    def test_map_no_columns(self) -> None:
        fake = FakeExtractor()
        code, stdout, _ = self.run_main(
            fake, ["--skip-calibration", "map", "--no-columns", "--ascii"]
        )
        self.assertEqual(code, 0)
        self.assertIn(("map", False), fake.calls)
        self.assertIn("`--", stdout)

    def test_map_relations_and_mermaid(self) -> None:
        for output_format, marker in (
            ("relations", "DATABASE RELATIONSHIPS"),
            ("mermaid", "flowchart LR"),
        ):
            fake = FakeExtractor()
            with self.subTest(output_format=output_format):
                code, stdout, _ = self.run_main(
                    fake,
                    ["--skip-calibration", "map", "--format", output_format],
                )
                self.assertEqual(code, 0)
                self.assertIn(marker, stdout)

    def test_map_html_export(self) -> None:
        fake = FakeExtractor()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "schema-map.html"
            code, stdout, _ = self.run_main(
                fake,
                [
                    "--skip-calibration",
                    "map",
                    "--format", "html",
                    "--output", str(destination),
                    "--title", "Test map",
                ],
            )
            self.assertEqual(code, 0)
            self.assertTrue(destination.exists())
            content = destination.read_text(encoding="utf-8")
            self.assertIn("<!doctype html>", content)
            self.assertIn("Test map", content)
            self.assertIn("Report written:", stdout)

    def test_map_text_export_adds_suffix(self) -> None:
        fake = FakeExtractor()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "schema-map"
            code, stdout, _ = self.run_main(
                fake,
                ["--skip-calibration", "map", "--output", str(destination)],
            )
            self.assertEqual(code, 0)
            self.assertTrue(destination.with_suffix(".txt").exists())
            self.assertIn("Report written:", stdout)

    def test_map_json_export(self) -> None:
        fake = FakeExtractor()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "schema-map"
            code, stdout, _ = self.run_main(
                fake,
                [
                    "--skip-calibration",
                    "--json",
                    "map",
                    "--output", str(destination),
                ],
            )
            self.assertEqual(code, 0)
            json_path = destination.with_suffix(".json")
            self.assertTrue(json_path.exists())
            document = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(document["result"]["summary"]["schemas"], 1)
            self.assertIn("Report written:", stdout)

    def test_command_error_returns_one(self) -> None:
        fake = FakeExtractor()
        fake.raise_on = "schemas"
        code, _, stderr = self.run_main(
            fake, ["--skip-calibration", "schemas"]
        )
        self.assertEqual(code, 1)
        self.assertIn("Error: failed schemas", stderr)

    def test_keyboard_interrupt_returns_130(self) -> None:
        fake = FakeExtractor()
        with patch("blind_sqli.cli._build_extractor", side_effect=KeyboardInterrupt):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = main(["schemas"])
        self.assertEqual(code, 130)
        self.assertIn("Interrupted", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
