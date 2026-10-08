"""Shared test fixtures.

The Upstash Search index is a live, shared resource: writes from a test run
would put fixture text ("Тело страницы.", "PAGEMARKER") next to real hh.ru
pages and quietly poison semantic results. Tests must therefore never reach
it, whatever credentials the environment happens to carry.

The autouse fixture replaces :func:`hh_mcp.app.index_hh_page` — the single
call site — with a recorder, so a test can still assert *what would have been
indexed* without anything leaving the process. Requests to
:mod:`hh_mcp.search_index` are covered separately in ``test_search_index.py``
with a fake client.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import pytest

# Importing ``server`` attaches the real response cache to the shared
# ``hh_mcp.app.mcp`` object and points it at ``~/.cache/hh-mcp``. Tests exercise
# the disk cache explicitly (``test_caching.py`` builds its own middleware on a
# tmp_path), so the global one stays off — otherwise a test module would change
# the behaviour of every other test.
os.environ["HH_MCP_CACHE"] = "0"

import hh_mcp.app as app_module  # noqa: E402
from hh_mcp import search_index  # noqa: E402


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


@pytest.fixture(autouse=True)
def _fresh_search_error() -> None:
    """Start every test with no remembered indexing failure.

    ``search_index`` keeps the last failure in module state on purpose, so that
    ``version()`` can report a write that failed after a healthy probe. Without
    this, one test's failure would leak into the next one's report.
    """
    search_index._LAST_ERROR = None


@pytest.fixture(autouse=True)
def indexed_pages(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture indexing attempts instead of performing them.

    Returns
    -------
    list[dict[str, Any]]
        One entry per call, with the keys ``doc_type``, ``doc_id`` and ``md``.
        Empty means the tool served its data without indexing anything, which
        is what a cache hit must do.
    """
    calls: list[dict[str, Any]] = []

    def record(*, doc_type: str, doc_id: int, md: str) -> None:
        calls.append({"doc_type": doc_type, "doc_id": doc_id, "md": md})

    monkeypatch.setattr(app_module, "index_hh_page", record)
    return calls


@pytest.fixture(autouse=True)
def _no_live_search_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hide Upstash credentials so no test can reach the live index.

    A belt-and-braces guard: even if a new call site bypasses
    :func:`indexed_pages`, the client factory returns ``None`` and indexing is
    skipped.
    """
    for name in ("UPSTASH_SEARCH_REST_URL", "UPSTASH_SEARCH_REST_TOKEN"):
        monkeypatch.delenv(name, raising=False)