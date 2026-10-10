"""Exception hierarchy for the fetch package."""

from __future__ import annotations

__all__ = [
    "FetchError",
    "SSRError",
    "InvalidURLError",
    "TransportError",
    "FetchTimeoutError",
    "HttpStatusError",
    "ResponseTooLargeError",
    "UnsupportedContentTypeError",
    "ParseError",
    "ConversionError",
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FetchError(Exception):
    """Base class for fetch-stage failures (transport, parse, conversion)."""


class SSRError(ValueError):
    """Raised when a URL targets a non-public (SSRF-risk) address."""


class InvalidURLError(ValueError):
    """Raised when a URL is malformed (non-string, empty, absent scheme)."""


class TransportError(FetchError):
    """Network/HTTP failure."""


class HttpStatusError(TransportError):
    """The server answered with a 4xx/5xx status."""

    def __init__(self, status_code: int, url: str, host: str) -> None:
        """Build the error from the facts httpx already knows."""
        self.status_code = status_code
        self.url = url
        self.host = host
        super().__init__(f"HTTP {status_code} fetching {host}: {url}")


class FetchTimeoutError(TransportError):
    """Request timed out (wraps ``httpx2.TimeoutException``)."""


class ResponseTooLargeError(TransportError):
    """Response body exceeds the configured byte cap (default 4 MiB)."""


class UnsupportedContentTypeError(FetchError):
    """Response Content-Type is not an accepted HTML type."""


class ParseError(FetchError):
    """Decode failure on the explicit decode path (invalid UTF-8 bytes)."""


class ConversionError(FetchError):
    """Converter failure; wraps the original exception via ``__cause__``."""
