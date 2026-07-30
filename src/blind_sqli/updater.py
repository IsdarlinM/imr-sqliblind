from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

import requests

from . import __version__

REPOSITORY_URL = "https://github.com/IsdarlinM/imr-sqliblind.git"
VERSION_URL = (
    "https://raw.githubusercontent.com/IsdarlinM/imr-sqliblind/"
    "main/src/blind_sqli/__init__.py"
)
_VERSION_PATTERN = re.compile(
    r'^__version__\s*=\s*["\'](\d+\.\d+\.\d+)["\']',
    re.MULTILINE,
)


class UpdateError(RuntimeError):
    pass


@dataclass(slots=True)
class UpdateStatus:
    installed_version: str
    available_version: str
    update_available: bool
    repository: str = REPOSITORY_URL
    source: str | None = None
    updated: bool = False
    message: str = ""


def parse_version(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value.strip())
    if match is None:
        raise UpdateError(f"Invalid semantic version: {value!r}")
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def fetch_available_version(*, timeout: float = 10.0) -> str:
    if timeout <= 0:
        raise UpdateError("timeout must be greater than zero")
    try:
        response = requests.get(
            VERSION_URL,
            timeout=timeout,
            allow_redirects=True,
            headers={"User-Agent": f"imr-sqliblind/{__version__} updater"},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise UpdateError(f"Unable to check GitHub for updates: {exc}") from exc
    match = _VERSION_PATTERN.search(response.text)
    if match is None:
        raise UpdateError("GitHub returned version metadata in an unexpected format")
    version = match.group(1)
    parse_version(version)
    return version


def check_for_updates(*, timeout: float = 10.0) -> UpdateStatus:
    available = fetch_available_version(timeout=timeout)
    update_available = parse_version(available) > parse_version(__version__)
    message = (
        f"Update available: {__version__} -> {available}"
        if update_available
        else f"imr-sqliblind {__version__} is up to date"
    )
    return UpdateStatus(
        installed_version=__version__,
        available_version=available,
        update_available=update_available,
        message=message,
    )


def _default_home() -> Path:
    configured = os.environ.get("IMR_SQLIBLIND_HOME")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "Programs" / "imr-sqliblind"
    data_home = os.environ.get("XDG_DATA_HOME")
    if data_home:
        return Path(data_home).expanduser() / "imr-sqliblind"
    return Path.home() / ".local" / "share" / "imr-sqliblind"


def _looks_like_checkout(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / ".git").exists()
        and (path / "pyproject.toml").is_file()
        and (path / "src" / "blind_sqli" / "__init__.py").is_file()
    )


def discover_source(explicit: str | Path | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit).expanduser())
    configured = os.environ.get("SQLIBLIND_SOURCE")
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend([Path.cwd(), _default_home() / "source"])
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if _looks_like_checkout(resolved):
            return resolved
    return None


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise UpdateError(f"Required executable not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise UpdateError(f"Command failed: {' '.join(command)}: {detail}") from exc


def _normalize_remote(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    if normalized.startswith("git@github.com:"):
        normalized = "https://github.com/" + normalized.split(":", 1)[1]
    return normalized.casefold()


def _validate_remote(source: Path, git: str) -> None:
    remote = _run(
        [git, "-C", str(source), "remote", "get-url", "origin"]
    ).stdout.strip()
    if _normalize_remote(remote) != _normalize_remote(REPOSITORY_URL):
        raise UpdateError(
            "Refusing to update from an unexpected repository origin: "
            f"{remote or '<empty>'}"
        )


def _ensure_clean(source: Path, git: str) -> None:
    status = _run(
        [git, "-C", str(source), "status", "--porcelain"]
    ).stdout.strip()
    if status:
        raise UpdateError(
            "The source checkout has local changes. Commit, stash, or discard them "
            "before running sqliblind update."
        )


def _prepare_source(source: Path | None) -> Path:
    git = shutil.which("git")
    if git is None:
        raise UpdateError("git is required to install updates")
    selected = source or (_default_home() / "source")
    selected = selected.expanduser().resolve()
    if selected.exists() and not _looks_like_checkout(selected):
        raise UpdateError(
            f"Update source exists but is not a valid Git checkout: {selected}"
        )
    if not selected.exists():
        selected.parent.mkdir(parents=True, exist_ok=True)
        _run(
            [
                git,
                "clone",
                "--branch",
                "main",
                "--single-branch",
                REPOSITORY_URL,
                str(selected),
            ]
        )
    _validate_remote(selected, git)
    _ensure_clean(selected, git)
    _run([git, "-C", str(selected), "fetch", "--prune", "origin", "main"])
    _run([git, "-C", str(selected), "checkout", "main"])
    _run([git, "-C", str(selected), "pull", "--ff-only", "origin", "main"])
    return selected


def _install_from_source(source: Path) -> str:
    _run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--upgrade",
            f"{source}[web]",
        ]
    )
    result = _run(
        [
            sys.executable,
            "-c",
            "from blind_sqli import __version__; print(__version__)",
        ]
    )
    installed = result.stdout.strip()
    parse_version(installed)
    return installed


def perform_update(
    *,
    source: str | Path | None = None,
    timeout: float = 10.0,
    force: bool = False,
) -> UpdateStatus:
    status = check_for_updates(timeout=timeout)
    discovered = discover_source(source)
    if not status.update_available and not force:
        status.source = str(discovered) if discovered else None
        return status
    requested = Path(source).expanduser() if source else None
    selected = _prepare_source(discovered or requested)
    installed = _install_from_source(selected)
    if parse_version(installed) < parse_version(status.available_version):
        raise UpdateError(
            f"Update verification failed: installed {installed}, expected at least "
            f"{status.available_version}"
        )
    status.installed_version = installed
    status.source = str(selected)
    status.updated = True
    status.update_available = (
        parse_version(status.available_version) > parse_version(installed)
    )
    status.message = f"Updated imr-sqliblind to {installed}"
    return status


def build_update_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sqliblind update",
        description=(
            "Check GitHub for a newer imr-sqliblind version or install it safely."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only show installed and available versions; do not modify files.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reinstall the latest version even when already up to date.",
    )
    parser.add_argument(
        "--source",
        metavar="PATH",
        help="Use this official Git checkout instead of automatic discovery.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="GitHub request timeout in seconds.",
    )
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser


def _status_document(status: UpdateStatus) -> dict[str, Any]:
    return asdict(status)


def update_main(argv: Sequence[str] | None = None) -> int:
    parser = build_update_parser()
    args = parser.parse_args(argv)
    try:
        status = (
            check_for_updates(timeout=args.timeout)
            if args.check
            else perform_update(
                source=args.source,
                timeout=args.timeout,
                force=args.force,
            )
        )
        if args.json_output:
            print(json.dumps(_status_document(status), indent=2, ensure_ascii=False))
        else:
            print(f"Installed version: {status.installed_version}")
            print(f"Available version: {status.available_version}")
            print(f"Repository: {status.repository}")
            if status.source:
                print(f"Source: {status.source}")
            print(status.message)
        return 0
    except UpdateError as exc:
        if args.json_output:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        else:
            print(f"Update error: {exc}", file=sys.stderr)
        return 1


__all__ = [
    "REPOSITORY_URL",
    "VERSION_URL",
    "UpdateError",
    "UpdateStatus",
    "build_update_parser",
    "check_for_updates",
    "discover_source",
    "fetch_available_version",
    "parse_version",
    "perform_update",
    "update_main",
]
