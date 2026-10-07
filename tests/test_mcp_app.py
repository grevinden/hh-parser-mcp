"""Tests for the hh-mcp FastMCPApp (MCP tools + UI entry-points).

Uses the in-memory ``FastMCPTransport`` client (no network, no HTTP server).
``fetch_as_markdown`` is always monkeypatched — the real fetch is covered
by ``tests/test_orchestrator.py``.

DevApp route tests use ``httpx2.ASGITransport`` — same ASGI app, no TCP port.
"""

from __future__ import annotations

import asyncio

import httpx2
import mcp_types
import pytest
from fastmcp.exceptions import ToolError
from fastmcp import FastMCP
from fastmcp.client import Client
from fastmcp.client.transports.memory import FastMCPTransport
from prefab_ui.components import Button, Column

import hh_mcp.app as app_module
from hh_mcp.app import employer_app, get_employer, get_vacancy, vacancy_app
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


# --- __main__ CLI ----------------------------------------------------------------


class TestCli:
    """src/hh_mcp/__main__.py — argument parsing (no server start)."""

    def test_defaults(self):
        from hh_mcp.__main__ import build_parser

        args = build_parser().parse_args([])
        assert args.transport is None
        assert args.host == "127.0.0.1"
        assert args.port == 8000

    def test_http_flags(self):
        from hh_mcp.__main__ import build_parser

        args = build_parser().parse_args(
            ["--transport", "http", "--host", "0.0.0.0", "--port", "9999"]
        )
        assert args.transport == "http"
        assert args.host == "0.0.0.0"
        assert args.port == 9999

    def test_invalid_transport_rejected(self):
        from hh_mcp.__main__ import build_parser

        with pytest.raises(SystemExit):
            build_parser().parse_args(["--transport", "websocket"])

    def test_dev_defaults(self):
        from hh_mcp.__main__ import build_parser

        args = build_parser().parse_args(["--dev"])
        assert args.dev is True
        assert args.mcp_port is None  # main() applies DEFAULT_MCP_PORT at dispatch
        assert args.dev_port is None  # main() applies DEFAULT_DEV_PORT at dispatch
        assert args.host == "127.0.0.1"

    def test_dev_flags(self):
        from hh_mcp.__main__ import build_parser

        args = build_parser().parse_args(
            ["--dev", "--mcp-port", "9000", "--dev-port", "9080", "--host", "0.0.0.0"]
        )
        assert args.dev is True
        assert args.mcp_port == 9000
        assert args.dev_port == 9080
        assert args.host == "0.0.0.0"


# --- DevApp routes (ASGITransport, no TCP) ------------------------------------


class FakeClient:
    """In-memory MCP client shaped like the mcp-types vocabulary.

    Used by :class:`TestDevApp` to replace the ``client_factory`` of
    :class:`McpBackend` so no real MCP server is needed.
    """

    def __init__(self, url: str) -> None:  # noqa: ARG002
        self._connected = True
        self._server_info: mcp_types.Implementation | None = None
        self._protocol_version: str | None = None

    # --- internal helpers (used by tests to set up scenarios) ---

    def set_connected(self, state: bool) -> None:
        self._connected = state

    def set_server_info(
        self, name: str | None, version: str | None = None, *, title: str | None = None
    ) -> None:
        if name is None:
            self._server_info = None
            return
        self._server_info = mcp_types.Implementation(
            name=name, version=version or "0.0.0", title=title
        )

    def set_protocol_version(self, version: str) -> None:
        self._protocol_version = version

    def _require_live(self) -> None:
        """Fail like a real client when there is no live session."""
        if not self._connected:
            raise ConnectionError("MCP session not initialized")

    # --- mcp-types vocabulary (called by _ClientProxy / McpBackend) ---

    @property
    def server_info(self) -> mcp_types.Implementation | None:
        return self._server_info

    @property
    def protocol_version(self) -> str | None:
        return self._protocol_version

    def is_connected(self) -> bool:
        return self._connected

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def close(self) -> None:
        pass

    async def list_tools(self) -> list[mcp_types.Tool]:
        self._require_live()
        return [
            mcp_types.Tool(
                name="get_vacancy",
                title="Get vacancy details",
                description="Fetch a hh.ru vacancy by ID",
                input_schema={"type": "object", "properties": {"id": {"type": "integer"}}},
            ),
        ]

    async def list_resources(self) -> list[mcp_types.Resource]:
        self._require_live()
        return []

    async def list_prompts(self) -> list[mcp_types.Prompt]:
        self._require_live()
        return []

    async def call_tool(
        self, name: str, arguments: dict[str, object], **kwargs: object
    ) -> mcp_types.CallToolResult:
        self._require_live()
        if name == "fail":
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text="failed")],
                is_error=True,
            )
        return mcp_types.CallToolResult(
            content=[
                mcp_types.TextContent(
                    type="text", text="tool %s called with %s" % (name, arguments)
                )
            ],
            is_error=False,
        )


class TestDevApp:
    """Dev frontend routes (no TCP, via httpx2.ASGITransport)."""

    MCP_URL = "http://127.0.0.1:8000/mcp"

    @pytest.fixture
    def fake_client(self) -> FakeClient:
        return FakeClient(self.MCP_URL)

    @pytest.fixture
    def app(self, fake_client: FakeClient):
        from hh_mcp.devapp import create_app

        return create_app(self.MCP_URL, backend_factory=lambda url: fake_client)

    def _client(self, app):
        """Build an ASGI httpx2 transport for *app* (no TCP)."""
        transport = httpx2.ASGITransport(app=app)
        return httpx2.AsyncClient(
            transport=transport, base_url="http://testserver"
        )

    # --- GET /api/status ---

    def test_status_connected(self, fake_client: FakeClient, app):
        fake_client.set_connected(True)
        fake_client.set_server_info("hh-mcp", "1.0.0")
        fake_client.set_protocol_version("2026-07")

        async def _run():
            async with self._client(app) as client:
                response = await client.get("/api/status")
                assert response.status_code == 200
                return response.json()

        data = asyncio.run(_run())
        assert data["connected"] is True
        assert data["server"] == "hh-mcp"
        assert data["protocol_version"] == "2026-07"
        assert data["tool_count"] == 1
        assert data["mcp_url"] == self.MCP_URL

    def test_status_disconnected(self, fake_client: FakeClient, app):
        fake_client.set_connected(False)

        async def _run():
            async with self._client(app) as client:
                response = await client.get("/api/status")
                assert response.status_code == 200
                return response.json()

        data = asyncio.run(_run())
        assert data["connected"] is False
        assert data["server"] is None

    def test_status_fallback_no_server_info(self, fake_client: FakeClient, app):
        fake_client.set_connected(True)
        fake_client.set_server_info(None)  # type: ignore[arg-type]

        async def _run():
            async with self._client(app) as client:
                response = await client.get("/api/status")
                assert response.status_code == 200
                return response.json()

        data = asyncio.run(_run())
        assert data["connected"] is True
        assert data["server"] is None

    # --- GET /api/mcp ---

    def test_mcp_listing(self, fake_client: FakeClient, app):
        fake_client.set_connected(True)

        async def _run():
            async with self._client(app) as client:
                response = await client.get("/api/mcp")
                assert response.status_code == 200
                return response.json()

        data = asyncio.run(_run())
        assert len(data["tools"]) == 1
        assert data["tools"][0]["name"] == "get_vacancy"
        assert data["resources"] == []
        assert data["prompts"] == []

    def test_mcp_listing_disconnected(self, fake_client: FakeClient, app):
        fake_client.set_connected(False)

        async def _run():
            async with self._client(app) as client:
                response = await client.get("/api/mcp")
                return response.status_code, response.json()

        status, data = asyncio.run(_run())
        assert status == 503  # no connection
        assert "error" in data

    # --- POST /api/mcp/call ---

    def test_call_tool_success(self, fake_client: FakeClient, app):
        fake_client.set_connected(True)

        async def _run():
            async with self._client(app) as client:
                response = await client.post(
                    "/api/mcp/call",
                    json={"tool": "get_vacancy", "arguments": {"id": 123}},
                )
                assert response.status_code == 200
                return response.json()

        data = asyncio.run(_run())
        assert data["isError"] is False
        assert "tool get_vacancy called with" in data["content"][0]

    def test_call_tool_error(self, fake_client: FakeClient, app):
        fake_client.set_connected(True)

        async def _run():
            async with self._client(app) as client:
                response = await client.post(
                    "/api/mcp/call",
                    json={"tool": "fail", "arguments": {}},
                )
                assert response.status_code == 200  # tool error is NOT an HTTP error
                return response.json()

        data = asyncio.run(_run())
        assert data["isError"] is True

    def test_call_tool_invalid_body(self, fake_client: FakeClient, app):
        fake_client.set_connected(True)

        async def _run():
            async with self._client(app) as client:
                response = await client.post(
                    "/api/mcp/call",
                    content=b"not json",
                    headers={"Content-Type": "application/json"},
                )
                return response.status_code, response.json()

        status, data = asyncio.run(_run())
        assert status == 400
        assert "error" in data

    def test_call_tool_disconnected(self, fake_client: FakeClient, app):
        fake_client.set_connected(False)

        async def _run():
            async with self._client(app) as client:
                response = await client.post(
                    "/api/mcp/call",
                    json={"tool": "get_vacancy", "arguments": {"id": 123}},
                )
                return response.status_code, response.json()

        status, data = asyncio.run(_run())
        assert status == 503
        assert "error" in data

    # --- GET / ---

    def test_index_returns_html(self, app):
        async def _run():
            async with self._client(app) as client:
                response = await client.get("/")
                return response

        response = asyncio.run(_run())
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "hh-mcp" in response.text

