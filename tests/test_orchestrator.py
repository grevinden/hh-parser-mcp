"""Integration tests for FetchService and public API functions.

All tests use MockTransport (no real network).  The converter is either
the real MarkItDownConverter or a simple fake for isolation.
"""

from __future__ import annotations

import logging
import re

import httpx2 as httpx
import pytest

from hh_mcp.fetch.config import default_config, RequestConfig
from hh_mcp.fetch.converter import MarkdownResult, MarkdownConverter
from hh_mcp.fetch.errors import (
    ConversionError,
    FetchTimeoutError,
    InvalidURLError,
    ParseError,
    ResponseTooLargeError,
    SSRError,
    TransportError,
)
from hh_mcp.fetch.orchestrator import (
    FetchService,
    fetch_as_markdown,
    fetch_page,
    html_to_markdown,
)
from hh_mcp.fetch.transport import (
    HttpxTransport,
    create_mock_transport,
)

LOGGER = logging.getLogger("test")


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        text="<html><head><title>Test</title></head><body><p>Hello</p></body></html>",
        request=request,
    )


def _no_title_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        text="<html><body><p>No title here</p></body></html>",
        request=request,
    )


def _404_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(404, text="Not Found", request=request)


def _timeout_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.TimeoutException("timed out", request=request)


def _too_large_handler(request: httpx.Request) -> httpx.Response:
    body = b"x" * (4 * 1024 * 1024 + 1)
    return httpx.Response(200, content=body, request=request)


class FakeConverter:
    """Simple converter that returns the input as markdown."""

    def convert(self, html: str, *, base_url: str | None) -> MarkdownResult:
        return MarkdownResult(html, title=None)


class FakeConverterWithTitle:
    """Converter that returns a fixed title."""

    def convert(self, html: str, *, base_url: str | None) -> MarkdownResult:
        return MarkdownResult(html, title="FromConverter")


def _make_service(
    handler=_ok_handler,
    converter: MarkdownConverter | None = None,
    config: RequestConfig | None = None,
) -> FetchService:
    cfg = config or default_config()
    mock = create_mock_transport(handler)
    transport = HttpxTransport(
        config=cfg,
        logger=LOGGER,
        client_factory=lambda **kw: httpx.Client(**kw, transport=mock),
    )
    return FetchService(
        config=cfg,
        transport=transport,
        converter=converter or FakeConverter(),
        logger=LOGGER,
    )


# ---------------------------------------------------------------------------
# FetchService
# ---------------------------------------------------------------------------


class TestFetchServiceFetchPage:
    """Spec §3.8 — fetch_page."""

    def test_success(self) -> None:
        svc = _make_service(_ok_handler)
        result = svc.fetch_page("https://example.com")
        assert isinstance(result, bytes)
        assert b"Hello" in result

    def test_404_raises_transport_error(self) -> None:
        svc = _make_service(_404_handler)
        with pytest.raises(TransportError):
            svc.fetch_page("https://example.com")

    def test_timeout_raises_fetch_timeout_error(self) -> None:
        svc = _make_service(_timeout_handler)
        with pytest.raises(FetchTimeoutError):
            svc.fetch_page("https://example.com")

    def test_too_large_raises(self) -> None:
        svc = _make_service(_too_large_handler)
        with pytest.raises(ResponseTooLargeError):
            svc.fetch_page("https://example.com")

    def test_ssrf_rejection(self) -> None:
        svc = _make_service()
        with pytest.raises(SSRError):
            svc.fetch_page("http://localhost:8080")

    def test_invalid_url_rejection(self) -> None:
        svc = _make_service()
        with pytest.raises(InvalidURLError):
            svc.fetch_page("")  # type: ignore[arg-type]

    def test_timeout_override(self) -> None:
        """Timeout override is clamped and applied."""
        svc = _make_service(_ok_handler)
        result = svc.fetch_page("https://example.com", timeout=5.0)
        assert isinstance(result, bytes)
        assert b"Hello" in result


class TestFetchServiceFetchAsMarkdown:
    """Spec §3.8 — fetch_as_markdown with title prefix and truncation."""

    def test_success_with_title(self) -> None:
        """Title from <title> tag is prefixed as # Title."""
        svc = _make_service(_ok_handler, FakeConverter())
        result = svc.fetch_as_markdown("https://example.com")
        assert "# Test" in result
        assert "Hello" in result

    def test_no_title(self) -> None:
        svc = _make_service(_no_title_handler, FakeConverter())
        result = svc.fetch_as_markdown("https://example.com")
        # No title prefix
        assert result.startswith("<html>") or result.startswith("<body>") or result.startswith("No title")

    def test_title_from_converter_fallback(self) -> None:
        """When sanitizer has no title, the converter's title is used."""
        svc = _make_service(_no_title_handler, FakeConverterWithTitle())
        result = svc.fetch_as_markdown("https://example.com")
        assert "# FromConverter" in result

    def test_truncation(self) -> None:
        """Result is truncated at max_chars (budget includes the suffix)."""
        suffix = "\n\n...truncated..."
        svc = _make_service(_ok_handler, FakeConverter())
        result = svc.fetch_as_markdown("https://example.com", max_chars=20)
        assert len(result) <= 20 + len(suffix)
        assert "...truncated..." in result

    def test_no_truncation_for_short_content(self) -> None:
        svc = _make_service(_ok_handler, FakeConverter())
        result = svc.fetch_as_markdown("https://example.com", max_chars=100000)
        assert "...truncated..." not in result

    def test_invalid_utf8_body(self) -> None:
        """Invalid UTF-8 response raises ParseError."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"\xff\xfe\x00\x01", request=request)
        svc = _make_service(handler, FakeConverter())
        with pytest.raises(ParseError):
            svc.fetch_as_markdown("https://example.com")


def _h1_handler(title: str, h1: str) -> httpx.Response:
    """Build a 200 handler whose page has an og-style ``<title>`` and an ``<h1>``."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            "<html><head>"
            f"<title>{title}</title>"
            "</head><body><main>\n"
            f"<h1>{h1}</h1>\n"
            "<p>Hello</p>\n"
            "</main></body></html>"
        )
        return httpx.Response(200, text=body, request=request)
    return handler


class FakeH1Converter:
    """Converter that renders ``<h1>``` as a Markdown ``# ```heading.

    ``FakeConverter`` passes HTML through verbatim, which can never produce a
    ``# ```first line; this fake turns tags into plain Markdown so the
    title-dedup path (first heading line vs title) is actually exercised.
    """

    def convert(self, html: str, *, base_url: str | None) -> MarkdownResult:
        md = re.sub(r"<h1>(.*?)</h1>", r"# \1", html, flags=re.DOTALL)
        md = re.sub(r"<[^>]+>", "", md).strip()
        return MarkdownResult(md, title=None)


def _make_h1_service(handler) -> FetchService:
    return _make_service(handler, FakeH1Converter())


class TestFetchServiceExecuteH1Dedup:
    """F4 — a page ``<h1>`` that duplicates the title is not re-prefixed."""

    def test_h1_prefix_of_og_title_not_duplicated(self) -> None:
        """Vacancy case: H1 'X' under og:title 'Вакансия X в Y, ...'."""
        handler = _h1_handler("Вакансия Дженералист в Компании, работа в компании Компании", "Дженералист")
        svc = _make_h1_service(handler)
        result = svc.fetch_as_markdown("https://example.com")
        lines = [l for l in result.splitlines() if l.startswith("# ")]
        assert lines == ["# Дженералист"]
        assert "Hello" in result

    def test_identical_h1_and_title_not_duplicated(self) -> None:
        handler = _h1_handler("Testing QA Engineer", "Testing QA Engineer")
        svc = _make_h1_service(handler)
        result = svc.fetch_as_markdown("https://example.com")
        lines = [l for l in result.splitlines() if l.startswith("# ")]
        assert lines == ["# Testing QA Engineer"]

    def test_case_insensitive_overlap_is_deduped(self) -> None:
        handler = _h1_handler("Вакансия Backend Engineer", "backend engineer")
        svc = _make_h1_service(handler)
        result = svc.fetch_as_markdown("https://example.com")
        lines = [l for l in result.splitlines() if l.startswith("# ")]
        assert lines == ["# backend engineer"]

    def test_non_overlapping_h1_gets_prefix(self) -> None:
        handler = _h1_handler("Вакансия Backend Engineer в ООО", "ООО Концерн")
        svc = _make_h1_service(handler)
        result = svc.fetch_as_markdown("https://example.com")
        lines = [l for l in result.splitlines() if l.startswith("# ")]
        assert len(lines) == 2
        assert lines[0] == "# Вакансия Backend Engineer в ООО"
        assert lines[1] == "# ООО Концерн"

    def test_no_dedup_for_short_strings(self) -> None:
        """A too-short H1 never counts as an overlap (no false positive)."""
        handler = _h1_handler("AB", "AB Company")
        svc = _make_h1_service(handler)
        result = svc.fetch_as_markdown("https://example.com")
        lines = [l for l in result.splitlines() if l.startswith("# ")]
        assert len(lines) == 2
        assert lines[0] == "# AB"
        assert lines[1] == "# AB Company"


class TestFetchServiceHtmlToMarkdown:
    """Spec §3.8 — offline conversion."""

    def test_html_string(self) -> None:
        svc = _make_service(converter=FakeConverter())
        result = svc.html_to_markdown("<p>Hello</p>")
        assert "Hello" in result

    def test_html_bytes(self) -> None:
        svc = _make_service(converter=FakeConverter())
        result = svc.html_to_markdown(b"<p>Hello bytes</p>")
        assert "Hello bytes" in result

    def test_empty_string(self) -> None:
        svc = _make_service(converter=FakeConverter())
        result = svc.html_to_markdown("")
        assert result == ""

    def test_empty_bytes(self) -> None:
        svc = _make_service(converter=FakeConverter())
        result = svc.html_to_markdown(b"")
        assert result == ""

    def test_invalid_utf8_bytes(self) -> None:
        svc = _make_service(converter=FakeConverter())
        with pytest.raises(ParseError):
            svc.html_to_markdown(b"\xff\xfe\x00")

    def test_with_base_url(self) -> None:
        """Link resolution is applied when base_url is provided."""
        svc = _make_service(converter=FakeConverter())
        result = svc.html_to_markdown('<a href="page.html">link</a>', base_url="https://example.com")
        assert "https://example.com/page.html" in result

    def test_truncation(self) -> None:
        suffix = "\n\n...truncated..."
        svc = _make_service(converter=FakeConverter())
        result = svc.html_to_markdown("<p>" + "x" * 100 + "</p>", max_chars=10)
        assert len(result) <= 10 + len(suffix)
        assert suffix in result


# ---------------------------------------------------------------------------
# Public API (back-compat)
# ---------------------------------------------------------------------------


class TestFetchAsMarkdownPublic:
    """Spec §8 — public API function with back-compat signature."""

    def test_basic(self) -> None:
        """Functions even with minimal arguments; uses MockTransport internally."""
        # Since the public function creates a real transport, we need to patch.
        # For this test we call it with explicit DI overrides.
        cfg = default_config()
        mock = create_mock_transport(_ok_handler)
        transport = HttpxTransport(
            config=cfg,
            logger=LOGGER,
            client_factory=lambda **kw: httpx.Client(**kw, transport=mock),
        )
        result = fetch_as_markdown(
            "https://example.com",
            config=cfg,
            transport=transport,
            converter=FakeConverter(),
            logger=LOGGER,
        )
        assert isinstance(result, str)
        assert "Hello" in result

    def test_back_compat_signature(self) -> None:
        """Old call style (url, *, timeout, max_chars) still works."""
        cfg = default_config()
        mock = create_mock_transport(_ok_handler)
        transport = HttpxTransport(
            config=cfg,
            logger=LOGGER,
            client_factory=lambda **kw: httpx.Client(**kw, transport=mock),
        )
        result = fetch_as_markdown(
            "https://example.com",
            timeout=10,
            max_chars=500,
            config=cfg,
            transport=transport,
            converter=FakeConverter(),
            logger=LOGGER,
        )
        assert isinstance(result, str)

    def test_ssrejection(self) -> None:
        cfg = default_config()
        mock = create_mock_transport(_ok_handler)
        transport = HttpxTransport(
            config=cfg,
            logger=LOGGER,
            client_factory=lambda **kw: httpx.Client(**kw, transport=mock),
        )
        with pytest.raises(SSRError):
            fetch_as_markdown(
                "http://localhost:3000",
                config=cfg,
                transport=transport,
                converter=FakeConverter(),
                logger=LOGGER,
            )


class TestFetchPagePublic:

    def test_basic(self) -> None:
        cfg = default_config()
        mock = create_mock_transport(_ok_handler)
        transport = HttpxTransport(
            config=cfg,
            logger=LOGGER,
            client_factory=lambda **kw: httpx.Client(**kw, transport=mock),
        )
        result = fetch_page(
            "https://example.com",
            config=cfg,
            transport=transport,
            logger=LOGGER,
        )
        assert isinstance(result, bytes)
        assert b"Hello" in result

    def test_back_compat_timeout(self) -> None:
        cfg = default_config()
        mock = create_mock_transport(_ok_handler)
        transport = HttpxTransport(
            config=cfg,
            logger=LOGGER,
            client_factory=lambda **kw: httpx.Client(**kw, transport=mock),
        )
        result = fetch_page(
            "https://example.com",
            timeout=30.0,
            config=cfg,
            transport=transport,
            logger=LOGGER,
        )
        assert isinstance(result, bytes)


class TestHtmlToMarkdownPublic:

    def test_basic(self) -> None:
        cfg = default_config()
        result = html_to_markdown(
            "<p>Hello</p>",
            config=cfg,
            converter=FakeConverter(),
            logger=LOGGER,
        )
        assert "Hello" in result

    def test_bytes_input(self) -> None:
        cfg = default_config()
        result = html_to_markdown(
            b"<p>Bytes</p>",
            config=cfg,
            converter=FakeConverter(),
            logger=LOGGER,
        )
        assert "Bytes" in result

    def test_parse_error_on_invalid_bytes(self) -> None:
        cfg = default_config()
        with pytest.raises(ParseError):
            html_to_markdown(
                b"\xff\xfe",
                config=cfg,
                converter=FakeConverter(),
                logger=LOGGER,
            )

    def test_truncation(self) -> None:
        cfg = default_config()
        result = html_to_markdown(
            "<p>" + "x" * 50 + "</p>",
            max_chars=10,
            config=cfg,
            converter=FakeConverter(),
            logger=LOGGER,
        )
        assert "...truncated..." in result


class TestBackCompatImport:
    """Spec §8 — verify the backward-compatible imports from the package."""

    def test_old_imports_exist(self) -> None:
        """All old names are importable from hh_mcp.fetch."""
        import hh_mcp.fetch as f
        assert callable(f.fetch_as_markdown)
        assert callable(f.fetch_page)
        assert callable(f.validate_url)
        assert issubclass(f.SSRError, ValueError)

    def test_html_to_markdown_is_new(self) -> None:
        """html_to_markdown is a new function (was not in old module)."""
        import hh_mcp.fetch as f
        assert hasattr(f, "html_to_markdown")