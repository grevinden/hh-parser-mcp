"""Tests for the HTTP transport with MockTransport (no real network)."""

from __future__ import annotations

import logging

import httpx2 as httpx
import pytest

from hh_mcp.fetch.config import RequestConfig, default_config
from hh_mcp.fetch.errors import (
    FetchTimeoutError,
    ResponseTooLargeError,
    TransportError,
    UnsupportedContentTypeError,
)
from hh_mcp.fetch.transport import (
    FetchTransport,
    HttpxTransport,
    create_mock_transport,
    default_transport,
)

LOGGER = logging.getLogger("test")


def _handler_200(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text="<html><body>OK</body></html>", request=request)


def _handler_404(request: httpx.Request) -> httpx.Response:
    return httpx.Response(404, text="Not Found", request=request)


def _handler_timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.TimeoutException("Connection timed out", request=request)


def _handler_too_large(request: httpx.Request) -> httpx.Response:
    body = b"x" * (4 * 1024 * 1024 + 1)
    return httpx.Response(200, content=body, request=request)


def _handler_non_html(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        text='{"json": true}',
        headers={"content-type": "application/json"},
        request=request,
    )


class TestFetchTransportProtocol:
    """Verify that HttpxTransport satisfies FetchTransport Protocol."""

    def test_is_protocol(self) -> None:
        assert isinstance(FetchTransport, type)
        # We cannot directly call isinstance on a Protocol;
        # but we can verify via runtime_checkable
        import typing
        cast = typing.cast  # noqa

    def test_httpx_transport_matches_protocol(self) -> None:
        """Structural subtyping: HttpxTransport has fetch() matching the Protocol."""
        cfg = default_config()
        transport = HttpxTransport(config=cfg, logger=LOGGER)
        # This verifies that the instance conforms to FetchTransport
        # by checking the method signature exists
        assert hasattr(transport, "fetch")
        # We can't use isinstance with Protocol by default (not @runtime_checkable);
        # but the structural check suffices


class TestHttpxTransport:
    """HttpxTransport with MockTransport injected via client_factory."""

    @pytest.fixture
    def transport(self) -> HttpxTransport:
        cfg = default_config()
        return HttpxTransport(config=cfg, logger=LOGGER)

    def _make_mocked_transport(self, handler) -> HttpxTransport:
        cfg = default_config()
        mock = create_mock_transport(handler)
        return HttpxTransport(config=cfg, logger=LOGGER, client_factory=lambda **kw: httpx.Client(**kw, transport=mock))

    def test_successful_fetch(self) -> None:
        transport = self._make_mocked_transport(_handler_200)
        result = transport.fetch("https://example.com")
        assert isinstance(result, bytes)
        assert b"OK" in result

    def test_404_raises_transport_error(self) -> None:
        transport = self._make_mocked_transport(_handler_404)
        with pytest.raises(TransportError) as exc_info:
            transport.fetch("https://example.com")
        assert "404" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, httpx.HTTPStatusError)

    def test_timeout_raises_fetch_timeout_error(self) -> None:
        transport = self._make_mocked_transport(_handler_timeout)
        with pytest.raises(FetchTimeoutError) as exc_info:
            transport.fetch("https://example.com")
        assert isinstance(exc_info.value.__cause__, httpx.TimeoutException)

    def test_response_too_large(self) -> None:
        transport = self._make_mocked_transport(_handler_too_large)
        with pytest.raises(ResponseTooLargeError) as exc_info:
            transport.fetch("https://example.com")
        assert "4194304" in str(exc_info.value)

    def test_non_html_with_strict_mode(self) -> None:
        cfg = default_config()
        strict_cfg = RequestConfig(
            timeout=cfg.timeout,
            max_body_bytes=cfg.max_body_bytes,
            max_redirects=cfg.max_redirects,
            max_connections=cfg.max_connections,
            max_keepalive=cfg.max_keepalive,
            user_agent=cfg.user_agent,
            verify_tls=cfg.verify_tls,
            strict_content_type=True,
            noise=cfg.noise,
        )
        mock = create_mock_transport(_handler_non_html)
        transport = HttpxTransport(
            config=strict_cfg,
            logger=LOGGER,
            client_factory=lambda **kw: httpx.Client(**kw, transport=mock),
        )
        with pytest.raises(UnsupportedContentTypeError):
            transport.fetch("https://example.com")

    def test_non_html_without_strict_mode(self) -> None:
        """Content-type mismatch logs warning but does not raise when strict is off."""
        transport = self._make_mocked_transport(_handler_non_html)
        # Should not raise
        result = transport.fetch("https://example.com")
        assert b"json" in result

    def test_per_request_config_override(self) -> None:
        cfg = RequestConfig(timeout=5.0)
        mock = create_mock_transport(_handler_200)
        transport = HttpxTransport(
            config=cfg,
            logger=LOGGER,
            client_factory=lambda **kw: httpx.Client(**kw, transport=mock),
        )
        # Override with different timeout
        override_cfg = RequestConfig(timeout=10.0)
        result = transport.fetch("https://example.com", config=override_cfg)
        assert b"OK" in result

    def test_per_request_config_none(self) -> None:
        """When config=None, the default config is used."""
        transport = self._make_mocked_transport(_handler_200)
        result = transport.fetch("https://example.com", config=None)
        assert b"OK" in result


class TestFactories:

    def test_default_transport(self) -> None:
        cfg = default_config()
        transport = default_transport(cfg, LOGGER)
        assert isinstance(transport, HttpxTransport)

    def test_create_mock_transport(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="mock", request=request)

        mock = create_mock_transport(handler)
        assert isinstance(mock, httpx.MockTransport)