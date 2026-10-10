"""HTTP transport."""

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
    HttpStatusError,
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
        """Fetch *url* and return the raw response body."""
        ...


# ---------------------------------------------------------------------------
# httpx2 implementation
# ---------------------------------------------------------------------------


class HttpxTransport:
    """httpx2-based default transport."""

    def __init__(
        self,
        *,
        config: RequestConfig,
        logger: logging.Logger,
        client_factory: Callable[..., httpx.Client] | None = None,
    ) -> None:
        """Initialize the transport."""
        self._config = config
        self._logger = logger.getChild("transport")
        self._client_factory = client_factory

    def _build_client(self, config: RequestConfig) -> httpx.Client:
        """Build a per-request client from *config*."""
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
        """Fetch *url* and return the raw response body."""
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
                raise HttpStatusError(
                    exc.response.status_code,
                    str(exc.response.url),
                    host,
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
    """Create the default :class:`HttpxTransport`."""
    return HttpxTransport(config=config, logger=logger)


def create_mock_transport(
    handler: Callable[[httpx.Request], httpx.Response]
) -> httpx.MockTransport:
    """Create an ``httpx2.MockTransport`` for tests."""
    return httpx.MockTransport(handler)
