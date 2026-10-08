"""Tests for the hh-mcp FastMCPApp (MCP tools + UI entry-points).

Uses the in-memory ``FastMCPTransport`` client (no network, no HTTP server).
``fetch_as_markdown`` is always monkeypatched — the real fetch is covered
by ``tests/test_orchestrator.py``.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastmcp.exceptions import ToolError
from fastmcp import FastMCP
from fastmcp.client import Client
from fastmcp.client.transports.memory import FastMCPTransport
from prefab_ui.components import Button, Column

import hh_mcp.app as app_module
from hh_mcp.app import (
    RESULT_KEY,
    employer_app,
    get_employer,
    get_vacancy,
    search_app,
    vacancy_app,
)
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
    """Build a ``fetch_as_markdown`` replacement returning *ok_text*."""

    def fake(url: str, **kwargs: object) -> str:
        return f"{ok_text}: {url}"

    return fake


def _raising_fetch(exc: Exception):
    """Build a ``fetch_as_markdown`` replacement that raises *exc*."""

    def fake(url: str, **kwargs: object) -> str:
        raise exc

    return fake


def _call(tool: str, arguments: dict, *, app: object):
    """Connect the in-memory client and call *tool* (never raises on tool errors)."""
    server = FastMCP("hh-mcp-test")
    server.add_provider(app)

    async def _run():
        async with Client(FastMCPTransport(server)) as client:
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

    def test_get_vacancy_rejects_zero(self, monkeypatch):
        monkeypatch.setattr(app_module, "fetch_as_markdown", _fake_fetch())
        with pytest.raises(ToolError, match="Invalid ID: 0"):
            get_vacancy(0)

    def test_get_vacancy_rejects_negative(self, monkeypatch):
        monkeypatch.setattr(app_module, "fetch_as_markdown", _fake_fetch())
        with pytest.raises(ToolError, match="Invalid ID: -1"):
            get_vacancy(-1)

    def test_get_employer_rejects_zero(self, monkeypatch):
        monkeypatch.setattr(app_module, "fetch_as_markdown", _fake_fetch())
        with pytest.raises(ToolError, match="Invalid ID: 0"):
            get_employer(0)

    def test_ok_calls_fetch_with_url(self, monkeypatch):
        seen: dict[str, str] = {}

        def fake(url: str, **kwargs: object) -> str:
            seen["url"] = url
            return "markdown"

        monkeypatch.setattr(app_module, "fetch_as_markdown", fake)
        assert get_vacancy(38185674) == "markdown"
        assert seen["url"] == "https://hh.ru/vacancy/38185674"

        assert get_employer(9410116) == "markdown"
        assert seen["url"] == "https://hh.ru/employer/9410116"


# --- In-memory client over FastMCPTransport ---------------------------------


class TestMcpTools:
    """Full protocol round-trip: client → FastMCPTransport → app tools."""

    def test_tools_registered(self):
        async def _run():
            server = FastMCP("hh-mcp-test")
            server.add_provider(app_module.app)
            async with Client(FastMCPTransport(server)) as client:
                return {t.name for t in await client.list_tools()}

        assert asyncio.run(_run()) == {
            "get_vacancy",
            "get_employer",
            "vacancy_app",
            "employer_app",
            "search_vacancies",
            "search_app",
        }

    @pytest.mark.parametrize(
        ("tool", "id_", "url_frag"),
        [
            ("get_vacancy", 38185674, "vacancy/38185674"),
            ("get_employer", 9410116, "employer/9410116"),
        ],
    )
    def test_success(self, monkeypatch, tool, id_, url_frag):
        monkeypatch.setattr(app_module, "fetch_as_markdown", _fake_fetch("# Page"))
        result = _call(tool, {"id": id_}, app=app_module.app)
        assert result.is_error is False
        assert url_frag in result.content[0].text

    def test_invalid_id_zero(self, monkeypatch):
        monkeypatch.setattr(app_module, "fetch_as_markdown", _fake_fetch())
        result = _call("get_vacancy", {"id": 0}, app=app_module.app)
        assert result.is_error is True
        assert "Invalid ID: 0" in result.content[0].text

    def test_invalid_id_negative(self, monkeypatch):
        monkeypatch.setattr(app_module, "fetch_as_markdown", _fake_fetch())
        result = _call("get_employer", {"id": -1}, app=app_module.app)
        assert result.is_error is True
        assert "Invalid ID: -1" in result.content[0].text

    def test_ssre(self, monkeypatch):
        monkeypatch.setattr(app_module, "fetch_as_markdown", _raising_fetch(SSRError()))
        result = _call("get_vacancy", {"id": 123}, app=app_module.app)
        assert result.is_error is True
        assert "SSRF guard rejected the URL" in result.content[0].text

    def test_timeout(self, monkeypatch):
        monkeypatch.setattr(
            app_module,
            "fetch_as_markdown",
            _raising_fetch(FetchTimeoutError("timed out")),
        )
        result = _call("get_vacancy", {"id": 123}, app=app_module.app)
        assert result.is_error is True
        assert "Timeout after 30s" in result.content[0].text

    def test_transport_error(self, monkeypatch):
        monkeypatch.setattr(
            app_module,
            "fetch_as_markdown",
            _raising_fetch(TransportError("connection refused")),
        )
        result = _call("get_vacancy", {"id": 123}, app=app_module.app)
        assert result.is_error is True
        assert "Transport error: connection refused" in result.content[0].text

    def test_response_too_large(self, monkeypatch):
        monkeypatch.setattr(
            app_module,
            "fetch_as_markdown",
            _raising_fetch(ResponseTooLargeError("5 MiB > 4 MiB cap")),
        )
        result = _call("get_vacancy", {"id": 123}, app=app_module.app)
        assert result.is_error is True
        assert "Response too large > 120000" in result.content[0].text

    def test_missing_id_rejected(self):
        result = _call("get_vacancy", {}, app=app_module.app)
        assert result.is_error is True


# --- UI entry-points ----------------------------------------------------------


class TestUiEntryPoints:
    """@app.ui() tools: registration, visibility, and component output."""

    def test_ui_returns_column(self):
        col = vacancy_app()
        assert isinstance(col, Column)

    def test_ui_button_wired_to_backend_tool(self):
        col = vacancy_app()
        button = next(c for c in col.children if isinstance(c, Button))
        action = button.on_click
        assert action is not None
        assert getattr(action, "tool", None) == "get_vacancy"
        assert action.arguments == {"id": "{{ vacancy_id }}"}

        col = employer_app()
        button = next(c for c in col.children if isinstance(c, Button))
        action = button.on_click
        assert action is not None
        assert getattr(action, "tool", None) == "get_employer"
        assert action.arguments == {"id": "{{ employer_id }}"}

    def test_ui_serialization_roundtrip(self):
        # Plan §6.4: the component tree must be serializable to JSON.
        json_dict = vacancy_app().to_json()
        assert json_dict["type"] == "Column"
        assert json_dict["children"]

    def test_search_app_button_wired_to_search_tool(self):
        col = search_app()
        button = next(c for c in col.children if isinstance(c, Button))
        actions = button.on_click
        # on_click is a list: reset state, then the CallTool.
        assert isinstance(actions, list) and len(actions) == 2
        call = actions[1]
        assert getattr(call, "tool", None) == "search_vacancies"
        assert call.arguments == {"text": "{{ search_text }}", "page": "{{ search_page }}"}

    def test_search_app_renders_result_block(self):
        """Result is captured into client state and rendered, not only toasted."""
        d = search_app().to_json()
        serialized = json.dumps(d, ensure_ascii=False)
        # CallTool success handler stores the tool result under RESULT_KEY
        assert f'"key": "{RESULT_KEY}", "value": "{{{{ $result }}}}"' in serialized
        # A conditional block renders that state back to the user
        assert f'"content": "{{{{ {RESULT_KEY} }}}}"' in serialized

    def test_ui_registered_as_tool(self):
        async def _run():
            server = FastMCP("hh-mcp-test")
            server.add_provider(app_module.app)
            async with Client(FastMCPTransport(server)) as client:
                tools = {t.name: t for t in await client.list_tools()}
                return tools["vacancy_app"], tools["employer_app"]

        vacancy_tool, employer_tool = asyncio.run(_run())
        # Entry-point tools carry the Prefab renderer resource on the wire.
        assert "resourceUri" in vacancy_tool.meta["ui"]
        assert vacancy_tool.meta["ui"]["visibility"] == ["model"]
        assert "resourceUri" in employer_tool.meta["ui"]

    def test_ui_returns_structured_content(self, monkeypatch):
        """Model calls vacancy_app() → structured_content with UI metadata (§3.4)."""
        result = _call("vacancy_app", {}, app=app_module.app)
        assert result.is_error is False
        assert result.structured_content is not None
        assert "view" in result.structured_content


# --- Backend tool visibility ---------------------------------------------------


class TestVisibility:
    """meta.ui.visibility semantics: model=True vs @app.ui()."""

    def test_backend_tools_visible_to_model(self):
        async def _run():
            return await app_module.app._list_tools()

        tools = {t.name: t for t in asyncio.run(_run())}
        assert tools["get_vacancy"].meta["ui"]["visibility"] == ["app", "model"]
        assert tools["get_employer"].meta["ui"]["visibility"] == ["app", "model"]

    def test_ui_tools_model_only(self):
        async def _run():
            return await app_module.app._list_tools()

        tools = {t.name: t for t in asyncio.run(_run())}
        assert tools["vacancy_app"].meta["ui"]["visibility"] == ["model"]
        assert tools["employer_app"].meta["ui"]["visibility"] == ["model"]


