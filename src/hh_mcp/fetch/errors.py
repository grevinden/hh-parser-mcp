"""Exception hierarchy for the fetch package.

The hierarchy is a module-owned contract:

- :class:`SSRError` (``ValueError``) — security rejection by the SSRF guard.
  Historically a ``ValueError``; MUST stay one (back-compat, LSP).
- :class:`InvalidURLError` (``ValueError``) — malformed address at the API
  boundary (non-string input, empty, absent scheme).
- :class:`FetchError` — umbrella of fetch-stage failures (transport, parse,
  conversion).

Callers: the MCP tool layer (future) catches :class:`FetchError` for
user-facing errors and ``ValueError`` for input errors — a clean split.
"""

from __future__ import annotations

__all__ = [
    "FetchError",
    "SSRError",
    "InvalidURLError",
    "TransportError",
    "FetchTimeoutError",
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
    """Raised when a URL targets a non-public (SSRF-risk) address.

    Back-compat: this class MUST remain a :class:`ValueError` subclass.
    It is deliberately NOT under :class:`FetchError`: it is a client/config
    error, not a fetch failure.
    """


class InvalidURLError(ValueError):
    """Raised when a URL is malformed (non-string, empty, absent scheme)."""


class TransportError(FetchError):
    """Network/HTTP failure.

    Wraps ``httpx2`` exceptions via ``raise ... from`` so ``__cause__``
    preserves the original exception.
    """


class FetchTimeoutError(TransportError):
    """Request timed out (wraps ``httpx2.TimeoutException``)."""


class ResponseTooLargeError(TransportError):
    """Response body exceeds the configured byte cap (default 4 MiB).

    Back-compat note: the old module raised a bare ``ValueError`` here; the
    new contract is a :class:`FetchError` (documented in the spec, §8).
    """


class UnsupportedContentTypeError(FetchError):
    """Response Content-Type is not an accepted HTML type.

    Raised only when the strict content-type check is enabled
    (off by default, per spec OQ2).
    """


class ParseError(FetchError):
    """Decode failure on the explicit decode path (invalid UTF-8 bytes).

    The HTML sanitizer itself is lenient by construction and never raises
    :class:`ParseError` for malformed markup.
    """


class ConversionError(FetchError):
    """Converter failure; wraps the original exception via ``__cause__``."""
