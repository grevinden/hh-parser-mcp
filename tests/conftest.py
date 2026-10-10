"""Shared test fixtures.

Importing ``server`` attaches the real response cache to the shared
``hh_mcp.app.mcp`` object and points it at ``~/.cache/hh-mcp``. Tests exercise
the disk cache explicitly (``test_caching.py`` builds its own middleware on a
tmp_path), so the global one stays off — otherwise a test module would change
the behaviour of every other test. ``HH_MCP_CACHE=0`` is set before the import
so the middleware is never attached.
"""

from __future__ import annotations

import logging
import os

import pytest

os.environ["HH_MCP_CACHE"] = "0"


@pytest.fixture(autouse=True)
def _capture_hh_mcp_logs() -> None:
    """Let pytest capture our own log records.

    ``server._configure_logging`` attaches a stderr handler to the ``hh_mcp``
    namespace and stops propagation, which is right for a deployment but would
    hide every record from ``caplog``. Resetting it per test keeps assertions on
    log content possible.
    """
    namespace = logging.getLogger("hh_mcp")
    namespace.propagate = True
    namespace.handlers.clear()
    namespace.setLevel(logging.DEBUG)
