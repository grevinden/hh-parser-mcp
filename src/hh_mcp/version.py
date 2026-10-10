"""Build identity of the running hh-mcp server."""

from __future__ import annotations

import importlib.metadata
import subprocess
import sys
import tomllib
from typing import Any

__all__ = [
    "BUILD_ID",
    "DIST_NAME",
    "UNKNOWN",
    "build_id",
    "package_version",
    "runtime_info",
    "short_commit",
]

# --- Configuration ---------------------------------------------------------

DIST_NAME: str = "hh-mcp"
"""Project name (``[project].name``), the key this file's version lives under."""

UNKNOWN: str = "unknown"
"""Placeholder for a fact that is unavailable in this environment."""


# --- Version facts ---------------------------------------------------------


def package_version() -> str:
    """Return the project version declared in ``pyproject.toml``."""
    try:
        with open(_pyproject_path(), "rb") as fh:
            data = tomllib.load(fh)
        return str(data["project"]["version"])
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError):
        return f"0.0.0+{UNKNOWN}"


def short_commit() -> str:
    """Return the short HEAD commit hash of the source checkout."""
    root = _repository_root()
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN
    return proc.stdout.strip() or UNKNOWN


def build_id() -> str:
    """Return the build identifier reported as ``serverInfo.version``."""
    version = package_version()
    commit = short_commit()
    return version if commit == UNKNOWN else f"{version}+{commit}"


def runtime_info() -> dict[str, Any]:
    """Return the facts a deployment check needs."""
    return {
        "version": package_version(),
        "commit": short_commit(),
        "build": BUILD_ID,
        "python": ".".join(str(part) for part in sys.version_info[:3]),
        "fastmcp": _distribution_version("fastmcp"),
    }


# --- Internals -------------------------------------------------------------


def _repository_root():
    """Return the repository root inferred from this file's location."""
    from pathlib import Path

    return Path(__file__).resolve().parents[2]


def _pyproject_path():
    """Return the path to this repository's ``pyproject.toml``."""
    return _repository_root() / "pyproject.toml"


BUILD_ID: str = build_id()
"""Build identifier computed once per process, at import time."""


def _distribution_version(name: str) -> str:
    """Return the version of an installed distribution, or :data:`UNKNOWN`."""
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return UNKNOWN
