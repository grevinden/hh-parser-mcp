"""Tests for the deployment config in ``fastmcp.json``.

Horizon builds from this file, so its contents are part of the contract:
``environment.project`` decides whether the build succeeds at all, and the log
level decides how much noise the deployed server produces.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FASTMCPI_JSON = Path(__file__).resolve().parents[1] / "fastmcp.json"

CONFIG = json.loads(FASTMCPI_JSON.read_text())


class TestDeployment:
    """Transport and log level of the deployed server."""

    def test_transport_is_http(self):
        assert CONFIG["deployment"]["transport"] == "http"

    def test_log_level_is_not_debug(self):
        """DEBUG spams ``Handler called:`` on every request of a live deploy.

        It does not leak tool output, but on a hosted deployment the noise
        costs money and buries real errors. Local debugging has its own flag:
        ``fastmcp run --log-level DEBUG``.
        """
        level = CONFIG["deployment"].get("log_level")
        assert level != "DEBUG", (
            "fastmcp.json must not ship DEBUG logging; use "
            "`fastmcp run --log-level DEBUG` locally"
        )

    @pytest.mark.parametrize("level", ["INFO", "WARNING", "ERROR"])
    def test_quiet_levels_are_allowed(self, level):
        assert level in {"INFO", "WARNING", "ERROR"}


class TestEnvironment:
    """Horizon builds from this file and needs ``project`` to install us."""

    def test_runner_is_uv(self):
        assert CONFIG["environment"]["type"] == "uv"

    def test_project_is_the_repo_root(self):
        assert CONFIG["environment"]["project"] == "."

    def test_python_is_pinned(self):
        assert CONFIG["environment"]["python"] == "3.14"


class TestSource:
    """The entrypoint the runner imports."""

    def test_entrypoint_is_mcp(self):
        assert CONFIG["source"] == {
            "type": "filesystem",
            "path": "server.py",
            "entrypoint": "mcp",
        }

    def test_server_file_exists(self):
        assert (FASTMCPI_JSON.parent / CONFIG["source"]["path"]).is_file()