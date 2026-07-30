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
        metadata = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["project"]["version"], "0.7.0")
        self.assertEqual(metadata["project"]["requires-python"], ">=3.10")
        self.assertIn("web", metadata["project"]["optional-dependencies"])
        package_data = metadata["tool"]["setuptools"]["package-data"][
            "blind_sqli"
        ]
        self.assertIn("webui/*.html", package_data)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            "git clone https://github.com/IsdarlinM/imr-sqliblind.git",
            readme,
        )
        self.assertIn("sqliblind update --check", readme)
        self.assertIn("safe.directory", readme)
        self.assertIn("Remote HTTP access", readme)
        self.assertIn("Interactive graph", readme)
        self.assertIn("Optimized exact inference", readme)
        self.assertIn("sqliblind --inference-mode adaptive", readme)
        self.assertIn("sqliblind --progress live map", readme)
        self.assertIn("sqliblind web", readme)

    def test_scripts_and_javascript_are_valid(self) -> None:
        scripts = [ROOT / "install.sh", ROOT / "uninstall.sh"]
        if all(script.exists() for script in scripts):
            subprocess.run(
                ["bash", "-n", *(str(script) for script in scripts)],
                check=True,
            )
        webui = ROOT / "src" / "blind_sqli" / "webui"
        for javascript in ("app.js", "inference-options.js"):
            subprocess.run(
                ["node", "--check", str(webui / javascript)],
                check=True,
            )
        html = (webui / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('src="http://', html)
        self.assertNotIn('src="https://', html)
        self.assertNotIn('href="http://', html)
        self.assertNotIn('href="https://', html)


if __name__ == "__main__":
    unittest.main()
