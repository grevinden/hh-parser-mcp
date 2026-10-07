"""fetch — HTTP(S) page fetching and HTML-to-Markdown conversion.

Public API (back-compat stable):
- :func:`fetch_as_markdown` — fetch URL → Markdown (title prefix,
  truncation, timeout clamp)
- :func:`fetch_page` — fetch URL → raw bytes (4 MiB cap, 10 redirects,
  http2, ``raise_for_status``)
- :func:`validate_url` — SSRF guard (raises :class:`SSRError`)
- :func:`html_to_markdown` — offline HTML→Markdown (new)

New classes exposed:
- :class:`FetchService` — fully-injectable orchestrator
- :class:`RequestConfig`, :class:`NoisePolicy` — immutable configuration
"""

from __future__ import annotations

from .errors import (
    ConversionError,
    FetchError,
    FetchTimeoutError,
    InvalidURLError,
    ParseError,
    ResponseTooLargeError,
    SSRError,
    TransportError,
    UnsupportedContentTypeError,
)
from .config import NoisePolicy, RequestConfig
from .guards import validate_url
from .orchestrator import (
    FetchService,
    fetch_as_markdown,
    fetch_page,
    html_to_markdown,
)

__all__ = [
    "fetch_as_markdown",
    "fetch_page",
    "html_to_markdown",
    "validate_url",
    "SSRError",
    "FetchError",
    "InvalidURLError",
    "TransportError",
    "ResponseTooLargeError",
    "UnsupportedContentTypeError",
    "ParseError",
    "ConversionError",
    "FetchTimeoutError",
    "RequestConfig",
    "NoisePolicy",
    "FetchService",
]