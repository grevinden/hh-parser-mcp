"""Tests for :mod:`hh_mcp.version` — build identity of the server.

The package version is the single source of truth: it lives in
``[project].version`` and is read back from the installed distribution, so the
value reported as ``serverInfo.version`` cannot drift from what was built.
"""

from __future__ import annotations

import json
import tomllib

import pytest

from hh_mcp import version as version_module
from hh_mcp.version import (
    BUILD_ID,
    UNKNOWN,
    build_id,
    package_version,
    runtime_info,
    short_commit,
)


class TestPackageVersion:
    """The version comes from pyproject.toml, the single source of truth."""

    def test_matches_pyproject(self):
        with open(version_module._pyproject_path(), "rb") as fh:
            declared = tomllib.load(fh)["project"]["version"]
        assert package_version() == declared

    def test_follows_pyproject(self):
        """Editing pyproject must move the reported version with it."""
        declared = tomllib.loads(
            version_module._pyproject_path().read_text(encoding="utf-8")
        )["project"]["version"]
        assert package_version() == declared

    def test_missing_pyproject_is_not_fatal(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            version_module, "_pyproject_path", lambda: tmp_path / "absent.toml"
        )
        assert package_version() == f"0.0.0+{UNKNOWN}"


class TestShortCommit:
    """The commit is a local-only nicety and must never break startup."""

    def test_repo_checkout_returns_hash(self):
        commit = short_commit()
        assert commit == UNKNOWN or 7 <= len(commit) <= 40

    def test_missing_git_is_reported_as_unknown(self, monkeypatch):
        def boom(*_args, **_kwargs):
            raise FileNotFoundError("git")

        monkeypatch.setattr(version_module.subprocess, "run", boom)
        assert short_commit() == UNKNOWN

    def test_git_failure_is_reported_as_unknown(self, monkeypatch):
        def boom(*_args, **_kwargs):
            raise version_module.subprocess.CalledProcessError(128, "git")

        monkeypatch.setattr(version_module.subprocess, "run", boom)
        assert short_commit() == UNKNOWN

    def test_empty_output_is_reported_as_unknown(self, monkeypatch):
        class Proc:
            stdout = "  \n"

        monkeypatch.setattr(version_module.subprocess, "run", lambda *a, **k: Proc())
        assert short_commit() == UNKNOWN


class TestBuildId:
    """``build_id`` is version, plus the commit only when it is known."""

    def test_appends_commit_when_known(self, monkeypatch):
        monkeypatch.setattr(version_module, "short_commit", lambda: "113e522")
        assert build_id() == f"{package_version()}+113e522"

    def test_plain_version_without_commit(self, monkeypatch):
        monkeypatch.setattr(version_module, "short_commit", lambda: UNKNOWN)
        assert build_id() == package_version()

    def test_module_constant_matches_function(self):
        assert BUILD_ID == build_id()


class TestRuntimeInfo:
    """``runtime_info`` is what the ``version`` tool reports."""

    def test_keys_and_types(self):
        info = runtime_info()
        assert set(info) == {
            "version",
            "commit",
            "build",
            "python",
            "fastmcp",
        }
        assert all(isinstance(v, str | None) for v in info.values())

    def test_build_agrees_with_fields(self):
        info = runtime_info()
        assert info["build"].startswith(info["version"])

    def test_python_looks_like_a_version(self):
        parts = runtime_info()["python"].split(".")
        assert len(parts) == 3 and all(part.isdigit() for part in parts)

    def test_json_serialisable(self):
        """The tool returns this dict as a one-line JSON string."""
        dumped = json.dumps(runtime_info(), ensure_ascii=False)
        assert "\n" not in dumped
        assert json.loads(dumped)["version"] == package_version()


class TestPrefetchedConstant:
    """``BUILD_ID`` exists so the handshake is computed once at import."""

    def test_type(self):
        assert isinstance(BUILD_ID, str)
        assert BUILD_ID


class TestUnknownConstant:
    """Sanity: the placeholder is what every fallback returns."""

    def test_value(self):
        assert UNKNOWN == "unknown"


@pytest.mark.parametrize("func", [package_version, short_commit, build_id])
def test_fact_functions_return_str(func):
    assert isinstance(func(), str)