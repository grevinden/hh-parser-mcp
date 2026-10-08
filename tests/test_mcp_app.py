"""Tests for the hh-mcp tools (vacancy, company, search, version).

Covers error mapping, argument validation, and the response contract: a tool
returns a ``ToolResult`` with ``content`` only, so a payload reaches the client
exactly once — no Prefab view, no ``structuredContent.result`` mirror.

Uses the in-memory ``FastMCPTransport`` client (no network, no HTTP server).
``fetch_as_markdown`` is always monkeypatched — the real fetch is covered
by ``tests/test_orchestrator.py``.
"""

from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, parse_qsl, urlsplit

import pytest
from fastmcp.exceptions import ToolError
from fastmcp.client import Client
from fastmcp.client.transports.memory import FastMCPTransport

import hh_mcp.app as app_module
from hh_mcp.app import company, vacancy
from hh_mcp.fetch.errors import (
    ConversionError,
    FetchTimeoutError,
    HttpStatusError,
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


class TestHttpStatusErrors:
    """A 404 must read as 'no such page', not as an httpx stack message."""

    @staticmethod
    def _status_error(status: int) -> HttpStatusError:
        return HttpStatusError(status, "https://kolomna.hh.ru/vacancy/1", "hh.ru")

    @pytest.mark.parametrize(("status", "expected"), [
        (404, "was not found on hh.ru"),
        (400, "rejected the request"),
        (403, "blocked the request"),
        (429, "rate-limited"),
        (503, "failed to serve"),
        (418, "Unexpected HTTP status 418"),
    ])
    def test_status_is_explained(self, status, expected):
        err = app_module._tool_error(self._status_error(status))
        assert expected in str(err)

    def test_subject_names_the_page(self):
        err = app_module._tool_error(self._status_error(404), subject="vacancy 1")
        assert str(err) == (
            f"vacancy 1 was not found on hh.ru (HTTP 404) — {app_module.NOT_FOUND_HINT}."
        )

    def test_no_httpx_noise_in_message(self):
        """The raw httpx text carries the redirect host and an MDN link."""
        text = str(app_module._tool_error(self._status_error(404), subject="vacancy 1"))
        assert "kolomna" not in text
        assert "developer.mozilla.org" not in text
        assert "Client error" not in text

    def test_search_404_says_what_was_searched(self):
        err = app_module._tool_error(self._status_error(404), subject="the vacancy search")
        assert "the vacancy search was not found" in str(err)

    def test_vacancy_tool_reports_missing_page(self, monkeypatch):
        def boom(url, **kwargs):
            raise self._status_error(404)

        monkeypatch.setattr(app_module, "fetch_as_markdown", boom)
        with pytest.raises(ToolError, match="vacancy 38185674 was not found"):
            vacancy(38185674)

    def test_company_tool_reports_missing_page(self, monkeypatch):
        def boom(url, **kwargs):
            raise HttpStatusError(400, "https://kolomna.hh.ru/employer/1", "hh.ru")

        monkeypatch.setattr(app_module, "fetch_as_markdown", boom)
        with pytest.raises(ToolError, match="employer page 9410116"):
            company(9410116)

    def test_search_tool_reports_http_failure(self, monkeypatch):
        def boom(url, **kwargs):
            raise HttpStatusError(429, "https://hh.ru/search/vacancy", "hh.ru")

        monkeypatch.setattr(app_module, "fetch_page", boom)
        with pytest.raises(ToolError, match="rate-limited"):
            app_module.search("аналитик", page=0)


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

        # Text only: the payload must not be mirrored into a UI copy.
        result = vacancy(38185674)
        assert seen["url"] == "https://hh.ru/vacancy/38185674"
        assert result.content[0].text.startswith("markdown")
        assert result.structured_content is None

        result = company(9410116)
        assert seen["url"] == "https://hh.ru/employer/9410116"
        assert result.content[0].text.startswith("markdown")
        assert result.structured_content is None


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


# --- Response contract: the payload travels once ----------------------------


class TestSingleCopyResponse:
    """Nothing in the tool result repeats the payload.

    Two mechanisms used to double it: a ``-> str`` return, which fastmcp
    mirrors into ``structuredContent.result``, and a Prefab view, which embeds
    the same text for the browser. A client walking twenty vacancy IDs would
    then pay for forty pages, so both are gone and this pins that down.
    """

    MARKER = "PAGEMARKER"

    def _tools(self):
        async def _run():
            async with Client(FastMCPTransport(app_module.mcp)) as client:
                return {t.name: t for t in await client.list_tools()}

        return asyncio.run(_run())

    def test_three_tools_registered(self):
        assert set(self._tools()) == {"vacancy", "company", "search"}

    def test_version_is_not_a_tool(self):
        """Build metadata is a resource: an agent must not be offered a tool
        it has no use for, on every request, forever."""
        assert "version" not in self._tools()

    def test_no_ui_metadata(self):
        """Plain tools: no Prefab resourceUri and no visibility block."""
        for name, tool in self._tools().items():
            assert "ui" not in tool.meta, name

    def test_no_renderer_resources(self):
        async def _run():
            async with Client(FastMCPTransport(app_module.mcp)) as client:
                return [str(r.uri) for r in await client.list_resources()]

        assert not [u for u in asyncio.run(_run()) if u.startswith("ui://")]

    def test_page_tool_ships_one_copy(self, monkeypatch):
        monkeypatch.setattr(app_module, "fetch_as_markdown", _fake_fetch(self.MARKER))
        result = vacancy(38185674)
        assert result.model_dump_json().count(self.MARKER) == 1

    def test_search_ships_one_copy(self, monkeypatch):
        html = b'<div data-qa="serp-item__title" href="/vacancy/111"></div>'
        monkeypatch.setattr(app_module, "fetch_page", lambda url, **kw: html)
        result = app_module.search("DevOps", page=0)
        assert result.model_dump_json().count("111") == 1

    def test_handshake_reports_build(self):
        """serverInfo.version is where any MCP client reads the build from."""
        from hh_mcp.version import BUILD_ID, package_version

        assert app_module.mcp.name == "hh-mcp"
        assert app_module.mcp.version == BUILD_ID
        assert BUILD_ID.startswith(package_version())


# --- resources ---------------------------------------------------------------


def _resources() -> dict[str, str]:
    """Read every resource through a real MCP client."""

    async def _run() -> dict[str, str]:
        async with Client(FastMCPTransport(app_module.mcp)) as client:
            listed = await client.list_resources()
            return {
                str(r.uri): (await client.read_resource(str(r.uri)))[0].text
                for r in listed
            }

    return asyncio.run(_run())


class TestResources:
    """Reference material and build facts live outside the tool list."""

    def test_exactly_two_resources(self):
        assert set(_resources()) == {"hh-mcp://version", "hh-mcp://search-guide"}

    def test_version_resource_carries_build_facts(self):
        import json

        facts = json.loads(_resources()["hh-mcp://version"])
        assert {
            "version",
            "commit",
            "build",
            "python",
            "fastmcp",
            "search",
            "search_endpoint",
            "search_error",
        } <= set(facts)

    def test_search_guide_resource_is_markdown(self):
        guide = _resources()["hh-mcp://search-guide"]
        assert guide.startswith("# hh.ru search")
        assert guide == app_module.SEARCH_GUIDE_MD

    def test_search_tool_points_at_the_guide(self):
        """Without this line in the description, no agent reads the guide."""

        async def _run() -> str:
            async with Client(FastMCPTransport(app_module.mcp)) as client:
                for tool in await client.list_tools():
                    if tool.name == "search":
                        return tool.description or ""
                raise AssertionError("search tool is not registered")

        assert "hh-mcp://search-guide" in asyncio.run(_run())


class TestSearchGuideContent:
    """The guide must keep documenting every operator hh.ru supports."""

    GUIDE = app_module.SEARCH_GUIDE_MD

    @pytest.mark.parametrize("operator", [
        "AND", "OR", "NOT", "!", '"', "~", "*",
        "NAME:", "COMPANY_NAME:", "DESCRIPTION:", "!ID", "!COMPANY_ID",
    ])
    def test_documents_operator(self, operator):
        assert operator in self.GUIDE

    @pytest.mark.parametrize("filter_", [
        "salary_frequency=TWICE_PER_MONTH",
        "employment_form=FULL",
        "not_from_agency",
        "accept_labor_contract",
        "work_format",
    ])
    def test_documents_fixed_filter(self, filter_):
        """The guide has to state the filters: they decide why a search is empty."""
        assert filter_ in self.GUIDE

    def test_operators_match_the_constant(self):
        """A filter in the guide that is not in the URL, or the reverse, is a bug."""
        for _, value in app_module.SEARCH_PARAMS:
            if value in {"false", "vacancy_search_list", "drawer_filter"}:
                continue
            assert value in self.GUIDE, value

    def test_written_in_english(self):
        """Prose is for the agent and stays English; only the hh.ru query
        examples are Russian, because that is the language they are meant to be
        pasted in."""
        for phrase in (
            "Read this before calling the `search` tool.",
            "What this server already filters out",
            "Plain search, without operators",
            "Search inside one field",
            "Do not overconstrain",
            "## Workflow",
        ):
            assert phrase in self.GUIDE, phrase


# --- search: IDs for the model -----------------------------------------------


class TestEmptyPageGuard:
    """A closed vacancy must not be reported as a 12-character page."""

    def test_stub_page_is_rejected(self, monkeypatch):
        # hh.ru redirects closed vacancies to a landing page; after
        # sanitization only the layout title survives.
        monkeypatch.setattr(
            app_module, "fetch_as_markdown", lambda url, **kw: "# HeadHunter"
        )
        with pytest.raises(ToolError, match="closed or archived"):
            vacancy(137405648)

    def test_stub_page_message_names_the_vacancy(self, monkeypatch):
        monkeypatch.setattr(
            app_module, "fetch_as_markdown", lambda url, **kw: "# HeadHunter"
        )
        with pytest.raises(ToolError, match="vacancy 137405648"):
            vacancy(137405648)

    def test_short_page_with_company_name_is_rejected(self, monkeypatch):
        monkeypatch.setattr(
            app_module, "fetch_as_markdown", lambda url, **kw: "# ООО Ромашка"
        )
        with pytest.raises(ToolError, match="closed or archived"):
            company(12345)

    def test_real_page_passes(self, monkeypatch):
        monkeypatch.setattr(app_module, "fetch_as_markdown", _fake_fetch("# Page\n" + "x" * 500))
        assert "Page" in vacancy(138156968).content[0].text


class TestSearchTool:
    """search() returns a flat list of vacancy IDs."""

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

    def test_no_view_copy(self, monkeypatch):
        result = self._run(monkeypatch)
        assert result.structured_content is None

    def test_page_goes_to_query(self, monkeypatch):
        seen: dict[str, str] = {}

        def fake_page(url, **kwargs):
            seen["url"] = url
            return self.SERP_HTML

        monkeypatch.setattr(app_module, "fetch_page", fake_page)
        app_module.search("1С", page=7)
        assert "text=1%D0%A1" in seen["url"]
        assert seen["url"].endswith("&page=7")

    def test_url_has_the_exact_parameter_set(self, monkeypatch):
        """Every drawer filter, in order, with repeated keys intact."""
        seen: dict[str, str] = {}

        def fake_page(url, **kwargs):
            seen["url"] = url
            return self.SERP_HTML

        monkeypatch.setattr(app_module, "fetch_page", fake_page)
        app_module.search("аналитик", page=0)

        query = urlsplit(seen["url"]).query
        pairs = parse_qsl(query, keep_blank_values=True)
        assert pairs[0] == ("text", "аналитик")
        assert tuple(pairs[1:-1]) == app_module.SEARCH_PARAMS
        assert pairs[-1] == ("page", "0")

    def test_url_drops_legacy_params(self, monkeypatch):
        """The old chip-filter URL must not come back by accident."""
        seen: dict[str, str] = {}

        def fake_page(url, **kwargs):
            seen["url"] = url
            return self.SERP_HTML

        monkeypatch.setattr(app_module, "fetch_page", fake_page)
        app_module.search("аналитик", page=0)

        query = parse_qs(urlsplit(seen["url"]).query)
        assert "L_save_area" not in query
        assert query["hhtmFromLabel"] == ["drawer_filter"]
        assert query["hhtmFrom"] == ["vacancy_search_list"]

    def test_operators_survive_encoding(self, monkeypatch):
        """hh.ru query operators are percent-encoded, not mangled."""
        seen: dict[str, str] = {}

        def fake_page(url, **kwargs):
            seen["url"] = url
            return self.SERP_HTML

        monkeypatch.setattr(app_module, "fetch_page", fake_page)
        app_module.search('аналитик NOT продаж "точный фраз"~5 менедж* (ДМС OR ДМС+)', page=0)

        assert parse_qs(urlsplit(seen["url"]).query)["text"] == [
            'аналитик NOT продаж "точный фраз"~5 менедж* (ДМС OR ДМС+)'
        ]

    def test_each_id_appears_once(self, monkeypatch):
        """Every ID occurs in the result exactly once — text only, no table."""
        result = self._run(monkeypatch)
        payload = result.model_dump_json()
        assert payload.count("111") == 1
        assert payload.count("222") == 1

    def test_beyond_last_page_is_empty(self, monkeypatch):
        result = self._run(monkeypatch, html=b"<html></html>")
        assert "Ничего не найдено" in result.content[0].text

    def test_empty_result_explains_the_fixed_filters(self, monkeypatch):
        """An empty page is usually the filters, not a broken query."""
        text = self._run(monkeypatch, html=b"<html></html>").content[0].text
        assert "Программист 1С" in text
        assert "2 раза в месяц" in text
        assert "опытом от 1 года" in text

    @pytest.mark.parametrize(("text", "page", "message"), [
        ("", 0, "Invalid text"),
        ("   ", 0, "Invalid text"),
        ("ok", -1, "Invalid page: -1"),
    ])
    def test_validation(self, monkeypatch, text, page, message):
        with pytest.raises(ToolError, match=message):
            app_module.search(text, page)
