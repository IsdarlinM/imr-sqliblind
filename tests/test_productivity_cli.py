from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from blind_sqli.productivity_cli import completion_main, run_jsonl_cli
from blind_sqli.productivity_common import ProductivityError, snapshot_diff
from blind_sqli.productivity_profiles import (
    ProfileStore,
    prepare_profile_arguments,
)
from blind_sqli.productivity_sessions import resume_arguments


class ProductivityCliTests(unittest.TestCase):
    def test_profile_store_is_non_secret_and_prepends_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with patch.dict(os.environ, {"IMR_SQLIBLIND_HOME": str(home)}):
                store = ProfileStore()
                store.save({"fast": ["--workers", "32", "map", "--metadata-only"]})
                self.assertEqual(
                    prepare_profile_arguments(["--profile", "fast", "--url", "https://lab/"]),
                    [
                        "--workers",
                        "32",
                        "--url",
                        "https://lab/",
                        "map",
                        "--metadata-only",
                    ],
                )
                with self.assertRaises(ProductivityError):
                    from blind_sqli.productivity_profiles import validate_profile_arguments

                    validate_profile_arguments(["--cookie", "session=secret"])

    def test_snapshot_diff_uses_canonical_hierarchy_paths(self) -> None:
        left = {
            "entities": [
                {"id": "s", "type": "schema", "name": "main", "parent_id": None, "data": {}},
                {"id": "t", "type": "table", "name": "users", "parent_id": "s", "data": {}},
            ]
        }
        right = {
            "entities": [
                {"id": "s2", "type": "schema", "name": "main", "parent_id": None, "data": {}},
                {
                    "id": "t2",
                    "type": "table",
                    "name": "users",
                    "parent_id": "s2",
                    "data": {"rows": 2},
                },
                {"id": "c", "type": "column", "name": "id", "parent_id": "t2", "data": {}},
            ]
        }
        result = snapshot_diff(left, right)
        self.assertEqual(result["removed"], [])
        self.assertIn("schema:main/table:users", result["changed"])
        self.assertIn("schema:main/table:users/column:id", result["added"])

    def test_resume_reconstructs_non_secret_configuration(self) -> None:
        class Args:
            url = None
            delay = None
            max_requests = None
            workers = None
            header = []
            cookie = []
            proxy = None
            phase = "map"
            schema = None
            table = None
            metadata_only = False
            include_data = False

        config = {
            "url": "https://lab/",
            "parameter": "id",
            "dialect": "sqlite",
            "oracle": "status",
            "true_statuses": [200],
            "workers": 16,
            "delay": 0,
            "max_requests": 100,
            "max_length": 64,
            "max_items": 64,
            "min_char_code": 32,
            "max_char_code": 126,
            "inference_mode": "turbo",
            "headers": {"Authorization": "***", "Accept": "text/html"},
            "cookies": {"session": "***"},
            "proxy": "configured",
            "include_data": False,
            "data_tables": [],
            "max_rows": 5,
            "max_data_columns": 10,
            "max_value_length": 128,
            "max_data_bytes": 10000,
        }
        command, warnings = resume_arguments(config, Args())
        self.assertIn("--metadata-only", command)
        self.assertIn("Accept:text/html", command)
        self.assertNotIn("Authorization:***", command)
        self.assertGreaterEqual(len(warnings), 3)

    def test_jsonl_output_is_one_record_per_result_plus_summary(self) -> None:
        def fake_cli(arguments):
            self.assertIn("--json", arguments)
            print(
                json.dumps(
                    {
                        "result": ["a", "b"],
                        "requests": 4,
                        "elapsed_seconds": 0.2,
                        "performance": {"mode": "turbo"},
                    }
                )
            )
            return 0

        output = io.StringIO()
        with redirect_stdout(output):
            code = run_jsonl_cli(["--jsonl", "schemas"], fake_cli)
        lines = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(code, 0)
        self.assertEqual([item["type"] for item in lines], ["result", "result", "summary"])

    def test_completion_supports_all_documented_shells(self) -> None:
        for shell in ("bash", "zsh", "powershell"):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(completion_main([shell]), 0)
            self.assertIn("sqliblind", output.getvalue())


if __name__ == "__main__":
    unittest.main()
