"""HTTP transport.

The only module that owns the ``httpx2`` import (DIP: the orchestrator
depends on the :class:`FetchTransport` Protocol, never on ``httpx2``).

:class:`HttpxTransport` creates a per-request client (no pool reuse across
calls — same trade-off as the old module; pooling would require a
long-lived handle / global state).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Protocol

import httpx2 as httpx

from .config import RequestConfig
from .errors import (
    FetchError,
    FetchTimeoutError,
    ResponseTooLargeError,
    TransportError,
    UnsupportedContentTypeError,
)

__all__ = [
    "FetchTransport",
    "HttpxTransport",
    "default_transport",
    "create_mock_transport",
]


# ---------------------------------------------------------------------------
# Abstract transport
# ---------------------------------------------------------------------------


class FetchTransport(Protocol):
    """One-shot fetch of a URL to raw bytes (ISP: narrow interface)."""

    def fetch(self, url: str, *, config: RequestConfig) -> bytes:
        """Fetch *url* and return the raw response body.

        Args:
            url:
                A validated absolute URL.
            config:
                Transport configuration to use for this call.

        Returns:
            bytes
                Raw response body.

        Raises:
            TransportError:
                On network/HTTP failure (``__cause__`` is the original
                ``httpx2`` exception).
            FetchTimeoutError:
                On timeout.
            ResponseTooLargeError:
                If the body exceeds ``config.max_body_bytes``.
        """
        ...


# ---------------------------------------------------------------------------
# httpx2 implementation
# ---------------------------------------------------------------------------


class HttpxTransport:
    """httpx2-based default transport.

    No pool reuse across calls (per-request Client); all parameters come
    from :class:`RequestConfig`.
    """

    def __init__(
        self,
        *,
        config: RequestConfig,
        logger: logging.Logger,
        client_factory: Callable[..., httpx.Client] | None = None,
    ) -> None:
        """Initialize the transport.

        Args:
            config:
                Default configuration used when :meth:`fetch` is called
                without an explicit *config*.
            logger:
                Logger instance (sub-child ``transport`` is used).
            client_factory:
                Optional callable used to build the client (DI hook for
                tests: it may return a client bound to
                ``httpx2.MockTransport``). Called with the same keyword
                arguments as :meth:`_build_client` defaults.
        """
        self._config = config
        self._logger = logger.getChild("transport")
        self._client_factory = client_factory

    def _build_client(self, config: RequestConfig) -> httpx.Client:
        """Build a per-request client from *config*.

        Args:
            config:
                Configuration for the client pool/timeout/limits.

        Returns:
            httpx.Client
                A new client, not yet used.
        """
        kwargs: dict[str, object] = {
            "http2": True,
            "follow_redirects": config.max_redirects > 0,
            "max_redirects": config.max_redirects,
            "timeout": config.timeout,
            "limits": httpx.Limits(
                max_connections=config.max_connections,
                max_keepalive_connections=config.max_keepalive,
            ),
            "headers": {"User-Agent": config.user_agent},
            "verify": config.verify_tls,
        }
        if self._client_factory is not None:
            return self._client_factory(**kwargs)
        return httpx.Client(**kwargs)  # type: ignore[arg-type]

    def fetch(self, url: str, *, config: RequestConfig | None = None) -> bytes:
        """Fetch *url* and return the raw response body.

        Args:
            url:
                A validated absolute URL.
            config:
                Optional per-call configuration override; defaults to the
                transport's configuration.

        Returns:
            bytes
                Raw response body.

        Raises:
            FetchTimeoutError:
                On any ``httpx2.TimeoutException``.
            ResponseTooLargeError:
                If the body exceeds ``config.max_body_bytes``.
            UnsupportedContentTypeError:
                If the strict content-type check is enabled (off by
                default) and the response Content-Type is not HTML.
            TransportError:
                On any other ``httpx2`` error (HTTP status errors,
                transport errors, protocol errors); ``__cause__`` is the
                original exception.
        """
        cfg = config or self._config
        host = str(httpx.URL(url).host)
        started = time.perf_counter()

        with self._build_client(cfg) as client:
            try:
                response = client.get(url)
                response.raise_for_status()
                content = response.read()
            except httpx.TimeoutException as exc:
                raise FetchTimeoutError(f"timeout fetching {host}: {exc}") from exc
            except httpx.HTTPStatusError as exc:
                raise TransportError(
                    f"HTTP {exc.response.status_code} fetching {host}: {exc}"
                ) from exc
            except httpx.HTTPError as exc:
                raise TransportError(f"HTTP failure fetching {host}: {exc}") from exc

            content_type = str(response.headers.get("content-type", "")).lower()
            if content_type and not (
                content_type.startswith("text/html")
                or content_type.startswith("application/xhtml")
            ):
                if cfg.strict_content_type:
                    raise UnsupportedContentTypeError(
                        f"unsupported Content-Type {content_type!r} for {host}"
                    )
                # OQ2: content-type check is off by default; when it does
                # not match we only warn (back-compat: the old code assumed
                # text/html unconditionally via markitdown).
                self._logger.warning(
                    "non-HTML content-type",
                    extra={"host": host, "content_type": content_type},
                )

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self._logger.debug(
            "fetch ok",
            extra={
                "host": host,
                "status": response.status_code,
                "bytes": len(content),
                "elapsed_ms": round(elapsed_ms, 1),
            },
        )

        if len(content) > cfg.max_body_bytes:
            raise ResponseTooLargeError(
                f"response body exceeds {cfg.max_body_bytes} bytes for {host} "
                f"(got {len(content)})"
            )
        return content


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def default_transport(
    config: RequestConfig, logger: logging.Logger
) -> FetchTransport:
    """Create the default :class:`HttpxTransport`.

    Args:
        config:
            Default configuration for the transport.
        logger:
            Logger instance.

    Returns:
        FetchTransport
        A new transport instance (no shared state).
    """
    return HttpxTransport(config=config, logger=logger)


def create_mock_transport(
    handler: Callable[[httpx.Request], httpx.Response]
) -> httpx.MockTransport:
    """Create an ``httpx2.MockTransport`` for tests.

    Args:
        handler:
            Request handler (sync).

    Returns:
        httpx.MockTransport
    """
    return httpx.MockTransport(handler)
