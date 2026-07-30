from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_metadata_resources_and_documentation(self) -> None:
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(metadata["project"]["version"], "0.5.0")
        self.assertEqual(metadata["project"]["requires-python"], ">=3.10")
        self.assertIn("web", metadata["project"]["optional-dependencies"])
        package_data = metadata["tool"]["setuptools"]["package-data"]["blind_sqli"]
        self.assertIn("webui/*.html", package_data)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("git clone https://github.com/IsdarlinM/imr-sqliblind.git", readme)
        self.assertIn("sqliblind --progress live map", readme)
        self.assertIn("sqliblind web", readme)

    def test_scripts_and_javascript_are_valid(self) -> None:
        subprocess.run(
            ["bash", "-n", str(ROOT / "install.sh"), str(ROOT / "uninstall.sh")],
            check=True,
        )
        javascript = ROOT / "src/blind_sqli/webui/app.js"
        subprocess.run(["node", "--check", str(javascript)], check=True)
        self.assertNotIn(
            "https://",
            (ROOT / "src/blind_sqli/webui/index.html").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
