from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "src" / "blind_sqli" / "webui"


class WebAssetsRegressionTests(unittest.TestCase):
    def test_javascript_syntax_and_oracle_fields(self) -> None:
        javascript = (WEBUI / "app.js").read_text(encoding="utf-8")
        html = (WEBUI / "index.html").read_text(encoding="utf-8")
        subprocess.run(["node", "--check", str(WEBUI / "app.js")], check=True)
        self.assertIn('name="true_marker"', html)
        self.assertIn('name="true_regex"', html)
        self.assertIn('get("true_regex")', javascript)
        self.assertNotIn("svf.replaceChildren", javascript)
        self.assertNotIn("JSON.stringify/", javascript)


if __name__ == "__main__":
    unittest.main()
