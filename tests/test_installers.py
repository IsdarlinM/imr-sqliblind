from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NativeInstallerTests(unittest.TestCase):
    def read(self, name: str) -> str:
        return (ROOT / name).read_text(encoding="utf-8")

    def test_all_native_installer_files_exist(self) -> None:
        for name in ("install.sh", "uninstall.sh", "install.cmd", "uninstall.cmd"):
            with self.subTest(name=name):
                self.assertTrue((ROOT / name).is_file())

    def test_linux_installer_declares_python_310_and_managed_fallback(self) -> None:
        content = self.read("install.sh")
        self.assertTrue(content.startswith("#!/usr/bin/env bash"))
        self.assertIn("MIN_PYTHON_MINOR=10", content)
        self.assertIn("MANAGED_PYTHON=\"3.12\"", content)
        self.assertIn("https://astral.sh/uv/install.sh", content)
        self.assertIn("python install", content)
        self.assertIn("-m venv", content)
        self.assertNotIn("sudo pip", content.casefold())

    def test_linux_installer_persists_user_environment(self) -> None:
        content = self.read("install.sh")
        self.assertIn("IMR_SQLIBLIND_HOME", content)
        self.assertIn("SQLIBLIND_PYTHON", content)
        self.assertIn("SQLIBLIND_BIN", content)
        self.assertIn("# >>> imr-sqliblind >>>", content)
        self.assertIn("$HOME/.profile", content)
        self.assertIn("$HOME/.bashrc", content)
        self.assertIn("$HOME/.zshrc", content)

    def test_windows_installer_declares_python_310_and_managed_fallback(self) -> None:
        content = self.read("install.cmd")
        self.assertTrue(content.casefold().startswith("@echo off"))
        self.assertIn("sys.version_info ^>= (3,10)", content)
        self.assertIn("MANAGED_PYTHON=3.12", content)
        self.assertIn("https://astral.sh/uv/install.ps1", content)
        self.assertIn("-m venv", content)
        self.assertIn("sqliblind.cmd", content)

    def test_windows_installer_updates_only_user_environment(self) -> None:
        content = self.read("install.cmd")
        self.assertIn("IMR_SQLIBLIND_HOME", content)
        self.assertIn("SQLIBLIND_PYTHON", content)
        self.assertIn("SQLIBLIND_BIN", content)
        self.assertIn("'User'", content)
        self.assertNotIn("'Machine'", content)

    def test_uninstallers_remove_wrappers_and_environment(self) -> None:
        linux = self.read("uninstall.sh")
        windows = self.read("uninstall.cmd")
        self.assertIn('rm -f "$BIN_DIR/sqliblind"', linux)
        self.assertIn("remove_profile_block", linux)
        self.assertIn("sqliblind.cmd", windows)
        self.assertIn("SetEnvironmentVariable('IMR_SQLIBLIND_HOME',$null,'User')", windows)
        self.assertIn("SetEnvironmentVariable('SQLIBLIND_PYTHON',$null,'User')", windows)
        self.assertIn("SetEnvironmentVariable('SQLIBLIND_BIN',$null,'User')", windows)

    @unittest.skipUnless(shutil.which("bash"), "bash is not available")
    def test_linux_scripts_pass_bash_syntax_check(self) -> None:
        subprocess.run(
            ["bash", "-n", str(ROOT / "install.sh"), str(ROOT / "uninstall.sh")],
            check=True,
            capture_output=True,
            text=True,
        )

    @unittest.skipUnless(shutil.which("bash"), "bash is not available")
    def test_linux_installer_help_is_side_effect_free(self) -> None:
        completed = subprocess.run(
            ["bash", str(ROOT / "install.sh"), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("Python 3.10+", completed.stdout)
        self.assertIn("--no-path", completed.stdout)


if __name__ == "__main__":
    unittest.main()
