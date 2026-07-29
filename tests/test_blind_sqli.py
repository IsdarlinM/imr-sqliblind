from __future__ import annotations

import importlib
import unittest
from unittest.mock import patch


class ImportTests(unittest.TestCase):
    def test_imports_do_not_issue_requests(self) -> None:
        with patch("requests.Session.get") as mocked_get:
            for module in (
                "blind_sqli",
                "blind_sqli.cli",
                "blind_sqli.client",
                "blind_sqli.dialects",
                "blind_sqli.extractor",
                "blind_sqli.graph",
                "blind_sqli.models",
                "blind_sqli.oracle",
            ):
                importlib.import_module(module)
            mocked_get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
