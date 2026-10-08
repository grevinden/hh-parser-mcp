"""Build identity of the running hh-mcp server.

The package version lives in exactly one place — ``[project].version`` in
``pyproject.toml`` — and is read back through installed distribution metadata,
so it cannot drift from what was actually built. The short commit is appended
only when the source tree happens to be a git checkout; a deployed artifact
carries no ``.git``, so it reports the plain package version and that number
alone identifies the running build.

``serverInfo.version`` in the MCP handshake is the standard place for this
value, so any client can tell which build it is talking to without asking a
tool.
"""

from __future__ import annotations

import importlib.metadata
import subprocess
import sys
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
"""Distribution name to look up in the installed metadata."""

UNKNOWN: str = "unknown"
"""Placeholder for a fact that is unavailable in this environment."""


# --- Version facts ---------------------------------------------------------


def package_version() -> str:
    """Return the installed distribution version.

    Returns
    -------
    str
        Value of ``[project].version`` in ``pyproject.toml``, or
        ``"0.0.0+unknown"`` when the package is not installed (running from a
        source tree without metadata).
    """
    try:
        return importlib.metadata.version(DIST_NAME)
    except importlib.metadata.PackageNotFoundError:
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
        Keys ``version``, ``commit``, ``build``, ``python``, ``fastmcp``,
        ``search`` and ``search_error``. ``version`` is the package version
        and ``build`` is :data:`BUILD_ID`; they differ only inside a git
        checkout. ``search`` is one of ``missing``, ``unavailable``, ``error``
        or ``ready`` — see :func:`hh_mcp.search_index.status` — and
        ``search_error`` carries the reason, or the last write failure.
    """
    from hh_mcp.search_index import last_error, status

    search = status()
    return {
        "version": package_version(),
        "commit": short_commit(),
        "build": BUILD_ID,
        "python": ".".join(str(part) for part in sys.version_info[:3]),
        "fastmcp": _distribution_version("fastmcp"),
        "search": search["state"],
        "search_error": search["error"] or last_error(),
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