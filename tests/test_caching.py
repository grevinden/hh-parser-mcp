"""Tests for the file-backed response cache wired in ``server.py``.

Verifies that repeating a backend tool call with the same id is served from
the cache and does NOT call ``fetch_as_markdown`` again (i.e. does not hit
hh.ru twice). Uses the same setup as the server entry-point —
``ResponseCachingMiddleware`` + ``FileTreeStore`` — and the in-memory
``FastMCPTransport`` client (no network).
"""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import FastMCP
from fastmcp.client import Client
from fastmcp.client.transports.memory import FastMCPTransport
from fastmcp.server.middleware.caching import ResponseCachingMiddleware
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)

import hh_mcp.app as app_module
from hh_mcp.app import app

CACHED_TOOLS: list[str] = ["get_vacancy", "get_employer"]
"""Same tool allowlist as ``server.CACHED_TOOLS``."""


def _counting_fetch(calls: list[str]):
    """Build a ``fetch_as_markdown`` replacement recording every URL."""

    def fake(url: str, **kwargs: object) -> str:
        calls.append(url)
        return f"# Page {len(calls)}: {url}"

    return fake


def _build_server(cache_dir, *, included_tools: list[str] | None = None) -> FastMCP:
    """FastMCP + provider + ResponseCachingMiddleware(FileTreeStore) like server.py."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    store = FileTreeStore(
        data_directory=cache_dir,
        key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(cache_dir),
        collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(
            cache_dir
        ),
    )
    server = FastMCP("hh-mcp-cache-test")
    server.add_provider(app)
    server.add_middleware(
        ResponseCachingMiddleware(
            cache_storage=store,
            call_tool_settings={
                "ttl": 3600,
                "included_tools": included_tools or CACHED_TOOLS,
            },
        )
    )
    return server


def _call_tool(server: FastMCP, tool: str, arguments: dict):
    """Connect the in-memory client and call *tool* on *server*."""

    async def _run():
        async with Client(FastMCPTransport(server)) as client:
            return await client.call_tool(tool, arguments, raise_on_error=False)

    return asyncio.run(_run())


class TestResponseCaching:
    """File-backed ResponseCachingMiddleware: repeat ids never re-fetch."""

    def test_repeat_vacancy_id_served_from_cache(self, tmp_path, monkeypatch):
        calls: list[str] = []
        monkeypatch.setattr(app_module, "fetch_as_markdown", _counting_fetch(calls))
        server = _build_server(tmp_path / "cache")

        first = _call_tool(server, "get_vacancy", {"id": 138156968})
        second = _call_tool(server, "get_vacancy", {"id": 138156968})
        other = _call_tool(server, "get_vacancy", {"id": 137911901})

        assert first.is_error is False
        assert second.is_error is False
        assert other.is_error is False
        # Same id twice → fetch ran once; a different id always fetches.
        assert calls == [
            "https://hh.ru/vacancy/138156968",
            "https://hh.ru/vacancy/137911901",
        ]
        assert first.content[0].text == second.content[0].text

    def test_repeat_employer_id_served_from_cache(self, tmp_path, monkeypatch):
        calls: list[str] = []
        monkeypatch.setattr(app_module, "fetch_as_markdown", _counting_fetch(calls))
        server = _build_server(tmp_path / "cache")

        first = _call_tool(server, "get_employer", {"id": 9410116})
        second = _call_tool(server, "get_employer", {"id": 9410116})

        assert first.is_error is False
        assert second.is_error is False
        assert calls == ["https://hh.ru/employer/9410116"]
        assert first.content[0].text == second.content[0].text

    def test_tool_outside_allowlist_not_cached(self, tmp_path, monkeypatch):
        # get_employer is NOT on this server's cached-tools allowlist —
        # repeating it must call fetch every time.
        calls: list[str] = []
        monkeypatch.setattr(app_module, "fetch_as_markdown", _counting_fetch(calls))
        server = _build_server(
            tmp_path / "cache", included_tools=["get_vacancy"]
        )

        first = _call_tool(server, "get_employer", {"id": 9410116})
        second = _call_tool(server, "get_employer", {"id": 9410116})

        assert first.is_error is False
        assert second.is_error is False
        assert calls == [
            "https://hh.ru/employer/9410116",
            "https://hh.ru/employer/9410116",
        ]

    def test_cache_survives_server_restart(self, tmp_path, monkeypatch):
        # A NEW server instance over the SAME directory serves the second call
        # from disk — the file-backed store persists across restarts.
        calls: list[str] = []
        monkeypatch.setattr(app_module, "fetch_as_markdown", _counting_fetch(calls))

        server1 = _build_server(tmp_path / "cache")
        first = _call_tool(server1, "get_vacancy", {"id": 138156968})

        server2 = _build_server(tmp_path / "cache")
        second = _call_tool(server2, "get_vacancy", {"id": 138156968})

        assert calls == ["https://hh.ru/vacancy/138156968"]
        assert first.content[0].text == second.content[0].text