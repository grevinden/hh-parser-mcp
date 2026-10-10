"""Build identity of the running hh-mcp server.

The project version lives in exactly one place — ``[project].version`` in
``pyproject.toml`` — and is read straight from that file, so it cannot drift
from what is declared. The application is not built or installed (see
``[tool.uv] package = false``), so there is no distribution metadata to read.
The short commit is appended only when the source tree happens to be a git
checkout; a deployed artifact carries no ``.git``, so it reports the plain
version and that number alone identifies the running build.

``serverInfo.version`` in the MCP handshake is the standard place for this
value, so any client can tell which build it is talking to without asking a
tool.
"""

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
    """Return the project version declared in ``pyproject.toml``.

    The application is not built or installed (``[tool.uv] package = false``),
    so there is no distribution metadata to read; ``[project].version`` in
    ``pyproject.toml`` is the single source of truth.

    Returns
    -------
    str
        Value of ``[project].version``, or ``"0.0.0+unknown"`` when the file
        is missing or unreadable.
    """
    try:
        with open(_pyproject_path(), "rb") as fh:
            data = tomllib.load(fh)
        return str(data["project"]["version"])
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError):
        return f"0.0.0+{UNKNOWN}"


def short_commit() -> str:
    """Return the short HEAD commit hash of the source checkout.

    The lookup runs against the repository root derived from this file, not
    the process working directory, so it works from anywhere. Any failure —
    no ``git`` binary, no ``.git`` directory, no commits yet — yields
    :data:`UNKNOWN` instead of raising, because a deployed artifact must not
    fail to start over a cosmetic detail.

    Returns
    -------
    str
        Seven-character commit hash, or :data:`UNKNOWN`.
    """
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
    """Return the build identifier reported as ``serverInfo.version``.

    Returns
    -------
    str
        ``"<version>+<commit>"`` for a git checkout (``"0.2.0+113e522"``), or
        the bare package version elsewhere (``"0.2.0"``).
    """
    version = package_version()
    commit = short_commit()
    return version if commit == UNKNOWN else f"{version}+{commit}"


def runtime_info() -> dict[str, Any]:
    """Return the facts a deployment check needs.

    Returns
    -------
    dict[str, Any]
        Keys ``version``, ``commit``, ``build``, ``python`` and ``fastmcp``.
        ``version`` is the package version and ``build`` is :data:`BUILD_ID`;
        they differ only inside a git checkout.
    """
    return {
        "version": package_version(),
        "commit": short_commit(),
        "build": BUILD_ID,
        "python": ".".join(str(part) for part in sys.version_info[:3]),
        "fastmcp": _distribution_version("fastmcp"),
    }


# --- Internals -------------------------------------------------------------


def _repository_root():
    """Return the repository root inferred from this file's location.

    Returns
    -------
    pathlib.Path
        ``src/hh_mcp/version.py`` → ``src/hh_mcp`` → ``src`` → repository root.
        The path is not required to exist; callers treat a missing directory as
        :data:`UNKNOWN`.
    """
    from pathlib import Path

    return Path(__file__).resolve().parents[2]


def _pyproject_path():
    """Return the path to this repository's ``pyproject.toml``.

    Returns
    -------
    pathlib.Path
        ``<repository root>/pyproject.toml``. Not required to exist; a missing
        file is treated as :data:`UNKNOWN`.
    """
    return _repository_root() / "pyproject.toml"


BUILD_ID: str = build_id()
"""Build identifier computed once per process, at import time."""


def _distribution_version(name: str) -> str:
    """Return the version of an installed distribution, or :data:`UNKNOWN`.

    Parameters
    ----------
    name:
        Distribution name, e.g. ``"fastmcp"``.

    Returns
    -------
    str
        Installed version, or :data:`UNKNOWN` when it is absent.
    """
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return UNKNOWN