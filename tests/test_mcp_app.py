"""Tests for the hh-mcp tools (vacancy, company, search).

Covers error mapping, argument validation, and the Apps UI contract: each tool
is declared with ``app=PrefabAppConfig(visibility=["app", "model"])`` and
returns a ``ToolResult`` whose ``structured_content`` the Prefab renderer draws
while the model reads ``content``.

Uses the in-memory ``FastMCPTransport`` client (no network, no HTTP server).
``fetch_as_markdown`` is always monkeypatched — the real fetch is covered
by ``tests/test_orchestrator.py``.
"""

from __future__ import annotations

import asyncio

import pytest
from fastmcp.exceptions import ToolError
from fastmcp.client import Client
from fastmcp.client.transports.memory import FastMCPTransport

import hh_mcp.app as app_module
from hh_mcp.app import company, vacancy
from hh_mcp.fetch.errors import (
    ConversionError,
    FetchTimeoutError,
    InvalidURLError,
    ParseError,
    ResponseTooLargeError,
    SSRError,
    TransportError,
    UnsupportedContentTypeError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_fetch(ok_text: str = "ok"):
    """Build a ``fetch_as_markdown`` replacement returning *ok_text*.

    The body is padded past :data:`hh_mcp.app.MIN_CONTENT_CHARS` so it looks
    like a real page — short bodies are rejected by the empty-page guard.
    """

    def fake(url: str, **kwargs: object) -> str:
        return f"{ok_text}: {url}\n" + ("Тело страницы. " * 40)

    return fake


def _raising_fetch(exc: Exception):
    """Build a ``fetch_as_markdown`` replacement that raises *exc*."""

    def fake(url: str, **kwargs: object) -> str:
        raise exc

    return fake


def _call(tool: str, arguments: dict):
    """Connect the in-memory client and call *tool* (never raises on tool errors)."""
    async def _run():
        async with Client(FastMCPTransport(app_module.mcp)) as client:
            return await client.call_tool(tool, arguments, raise_on_error=False)

    return asyncio.run(_run())


# --- Error mapping: _tool_error --------------------------------------------


class TestToolErrorMapping:
    """app._tool_error — fetch exceptions → user-facing ToolError messages."""

    def test_ssre(self):
        err = app_module._tool_error(SSRError("http://localhost"))
        assert str(err) == "SSRF guard rejected the URL"

    def test_invalid_url(self):
        err = app_module._tool_error(InvalidURLError("not a url"))
        assert str(err) == "Invalid URL: not a url"

    def test_timeout(self):
        err = app_module._tool_error(FetchTimeoutError("read timed out"))
        assert str(err) == "Timeout after 30s"

    def test_response_too_large(self):
        err = app_module._tool_error(ResponseTooLargeError("cap exceeded"))
        assert str(err) == "Response too large > 120000"

    def test_parse_error(self):
        err = app_module._tool_error(ParseError("bad utf-8"))
        assert str(err) == "Parse error: bad utf-8"

    def test_conversion_error(self):
        err = app_module._tool_error(ConversionError("converter crashed"))
        assert str(err) == "Parse error: converter crashed"

    def test_unsupported_content_type(self):
        err = app_module._tool_error(
            UnsupportedContentTypeError("application/json not accepted")
        )
        assert str(err) == "Unsupported content type: application/json not accepted"

    def test_transport_error(self):
        # FetchTimeoutError / ResponseTooLargeError are TransportError subclasses
        # but must NOT land in the generic transport branch.
        err = app_module._tool_error(TransportError("connection refused"))
        assert str(err) == "Transport error: connection refused"

    def test_generic_fetch_error(self):
        err = app_module._tool_error(Exception("boom"))
        assert str(err) == "Unexpected error: boom"


# --- Tool bodies (direct call) ----------------------------------------------


class TestToolValidation:
    """ID validation happens before any fetch call."""

    def test_vacancy_rejects_zero(self, monkeypatch):
        monkeypatch.setattr(app_module, "fetch_as_markdown", _fake_fetch())
        with pytest.raises(ToolError, match="Invalid ID: 0"):
            vacancy(0)

    def test_vacancy_rejects_negative(self, monkeypatch):
        monkeypatch.setattr(app_module, "fetch_as_markdown", _fake_fetch())
        with pytest.raises(ToolError, match="Invalid ID: -1"):
            vacancy(-1)

    def test_company_rejects_zero(self, monkeypatch):
        monkeypatch.setattr(app_module, "fetch_as_markdown", _fake_fetch())
        with pytest.raises(ToolError, match="Invalid ID: 0"):
            company(0)

    def test_ok_calls_fetch_with_url(self, monkeypatch):
        seen: dict[str, str] = {}

        def fake(url: str, **kwargs: object) -> str:
            seen["url"] = url
            return "markdown\n" + ("Тело страницы. " * 40)

        monkeypatch.setattr(app_module, "fetch_as_markdown", fake)

        # ToolResult serves both audiences: text for the model, Prefab view
        # for the browser (gofastmcp.com/apps/prefab).
        result = vacancy(38185674)
        assert seen["url"] == "https://hh.ru/vacancy/38185674"
        assert result.content[0].text.startswith("markdown")
        assert result.structured_content["$prefab"]["version"]
        # Prefab wraps the view in a root Div carrying pf-app-root.
        assert result.structured_content["view"]["type"] == "Div"

        result = company(9410116)
        assert seen["url"] == "https://hh.ru/employer/9410116"
        assert result.content[0].text.startswith("markdown")


# --- In-memory client over FastMCPTransport ---------------------------------


class TestMcpTools:
    """Full protocol round-trip: client → FastMCPTransport → app tools."""

    def test_tools_registered(self):
        async def _run():
            async with Client(FastMCPTransport(app_module.mcp)) as client:
                return {t.name for t in await client.list_tools()}

        assert asyncio.run(_run()) == {"vacancy", "company", "search"}

    @pytest.mark.parametrize(
        ("tool", "id_", "url_frag"),
        [
            ("vacancy", 38185674, "vacancy/38185674"),
            ("company", 9410116, "employer/9410116"),
        ],
    )
    def test_success(self, monkeypatch, tool, id_, url_frag):
        monkeypatch.setattr(app_module, "fetch_as_markdown", _fake_fetch("# Page"))
        result = _call(tool, {"id": id_})
        assert result.is_error is False
        assert url_frag in result.content[0].text

    def test_invalid_id_zero(self, monkeypatch):
        monkeypatch.setattr(app_module, "fetch_as_markdown", _fake_fetch())
        result = _call("vacancy", {"id": 0})
        assert result.is_error is True
        assert "Invalid ID: 0" in result.content[0].text

    def test_invalid_id_negative(self, monkeypatch):
        monkeypatch.setattr(app_module, "fetch_as_markdown", _fake_fetch())
        result = _call("company", {"id": -1})
        assert result.is_error is True
        assert "Invalid ID: -1" in result.content[0].text

    def test_ssre(self, monkeypatch):
        monkeypatch.setattr(app_module, "fetch_as_markdown", _raising_fetch(SSRError()))
        result = _call("vacancy", {"id": 123})
        assert result.is_error is True
        assert "SSRF guard rejected the URL" in result.content[0].text

    def test_timeout(self, monkeypatch):
        monkeypatch.setattr(
            app_module,
            "fetch_as_markdown",
            _raising_fetch(FetchTimeoutError("timed out")),
        )
        result = _call("vacancy", {"id": 123})
        assert result.is_error is True
        assert "Timeout after 30s" in result.content[0].text

    def test_transport_error(self, monkeypatch):
        monkeypatch.setattr(
            app_module,
            "fetch_as_markdown",
            _raising_fetch(TransportError("connection refused")),
        )
        result = _call("vacancy", {"id": 123})
        assert result.is_error is True
        assert "Transport error: connection refused" in result.content[0].text

    def test_response_too_large(self, monkeypatch):
        monkeypatch.setattr(
            app_module,
            "fetch_as_markdown",
            _raising_fetch(ResponseTooLargeError("5 MiB > 4 MiB cap")),
        )
        result = _call("vacancy", {"id": 123})
        assert result.is_error is True
        assert "Response too large > 120000" in result.content[0].text

    def test_missing_id_rejected(self):
        result = _call("vacancy", {})
        assert result.is_error is True


# --- Dual registration: one tool for model + browser ---------------------------


class TestDualRegistration:
    """Each tool serves the model AND the browser Apps picker at once."""

    def _tools(self):
        async def _run():
            async with Client(FastMCPTransport(app_module.mcp)) as client:
                return await client.list_tools()

        return {t.name: t for t in asyncio.run(_run())}

    def test_all_three_tools_registered(self):
        assert set(self._tools()) == {"vacancy", "company", "search"}

    def test_visible_to_model(self):
        for name, tool in self._tools().items():
            assert tool.meta["ui"]["visibility"] == ["app", "model"], name

    def test_reaches_browser_picker(self):
        """The picker lists only tools carrying a Prefab resourceUri.

        fastmcp rewrites the placeholder into a per-tool renderer URI at
        list_tools time, so the browser UI needs no separate entry-point tool.
        """
        for name, tool in self._tools().items():
            resource_uri = tool.meta["ui"]["resourceUri"]
            assert resource_uri.startswith("ui://prefab/tool/"), name
            assert resource_uri.endswith("/renderer.html"), name

    def test_renderer_resource_is_synthesized(self):
        async def _run():
            async with Client(FastMCPTransport(app_module.mcp)) as client:
                return [str(r.uri) for r in await client.list_resources()]

        resources = asyncio.run(_run())
        uris = {t.meta["ui"]["resourceUri"] for t in self._tools().values()}
        assert uris.issubset(set(resources))

    def test_input_schema_generated_for_browser_form(self):
        """The picker builds the browser form from the tool's own schema."""
        tools = self._tools()
        assert set(tools["vacancy"].input_schema["properties"]) == {"id"}
        assert set(tools["search"].input_schema["properties"]) == {"text", "page"}
        assert tools["search"].input_schema["required"] == ["text"]


# --- search: ToolResult with a DataTable view --------------------------------


class TestEmptyPageGuard:
    """A closed vacancy must not be reported as a 12-character page."""

    def test_stub_page_is_rejected(self, monkeypatch):
        # hh.ru redirects closed vacancies to a landing page; after
        # sanitization only the layout title survives.
        monkeypatch.setattr(
            app_module, "fetch_as_markdown", lambda url, **kw: "# HeadHunter"
        )
        with pytest.raises(ToolError, match="no vacancy content"):
            vacancy(137405648)

    def test_short_page_with_company_name_is_rejected(self, monkeypatch):
        monkeypatch.setattr(
            app_module, "fetch_as_markdown", lambda url, **kw: "# ООО Ромашка"
        )
        with pytest.raises(ToolError, match="no vacancy content"):
            company(12345)

    def test_real_page_passes(self, monkeypatch):
        monkeypatch.setattr(app_module, "fetch_as_markdown", _fake_fetch("# Page\n" + "x" * 500))
        assert "Page" in vacancy(138156968).content[0].text


class TestSearchTool:
    """search() returns IDs for the model and a sortable table for the browser."""

    SERP_HTML = (
        b'<div data-qa="serp-item__title" href="/vacancy/111"></div>'
        b'<div data-qa="serp-item__title" href="/vacancy/222"></div>'
        b'<a href="/vacancy/not-a-number"></a>'
    )

    def _run(self, monkeypatch, html=None):
        monkeypatch.setattr(
            app_module,
            "fetch_page",
            lambda url, **kwargs: html if html is not None else self.SERP_HTML,
        )
        return app_module.search("Программист 1С", page=1)

    def test_returns_ids_to_model(self, monkeypatch):
        result = self._run(monkeypatch)
        assert "111" in result.content[0].text
        assert "222" in result.content[0].text
        assert "страница 1" in result.content[0].text

    def test_renders_table_for_browser(self, monkeypatch):
        result = self._run(monkeypatch)
        view = str(result.structured_content["view"])
        assert "'type': 'DataTable'" in view
        assert "'id': 111" in view
        assert "'id': 222" in view

    def test_page_goes_to_query(self, monkeypatch):
        seen: dict[str, str] = {}

        def fake_page(url, **kwargs):
            seen["url"] = url
            return self.SERP_HTML

        monkeypatch.setattr(app_module, "fetch_page", fake_page)
        app_module.search("1С", page=7)
        assert "text=1%D0%A1" in seen["url"]
        assert seen["url"].endswith("&page=7")

    def test_beyond_last_page_is_empty(self, monkeypatch):
        result = self._run(monkeypatch, html=b"<html></html>")
        assert "Ничего не найдено" in result.content[0].text
        assert "DataTable" in str(result.structured_content["view"])

    @pytest.mark.parametrize(("text", "page", "message"), [
        ("", 0, "Invalid text"),
        ("   ", 0, "Invalid text"),
        ("ok", -1, "Invalid page: -1"),
    ])
    def test_validation(self, monkeypatch, text, page, message):
        with pytest.raises(ToolError, match=message):
            app_module.search(text, page)
