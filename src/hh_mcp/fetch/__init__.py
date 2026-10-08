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

Employer-card enrichment (pure post-conversion transforms, also exposed
on the package):
- :func:`extract_employer_ref` — locate the employer reference in a
  vacancy card
- :func:`extract_company_name` — read the company name from an
  employer page
- :func:`clean_employer_markdown` — reduce an employer page to a
  compact card
- :func:`embed_employer_card` — splice the card into the vacancy card
- :func:`remove_internal_links` — strip internal hh.ru links
"""

from __future__ import annotations

from .errors import (
    ConversionError,
    FetchError,
    FetchTimeoutError,
    HttpStatusError,
    InvalidURLError,
    ParseError,
    ResponseTooLargeError,
    SSRError,
    TransportError,
    UnsupportedContentTypeError,
)
from .config import NoisePolicy, RequestConfig
from .enrich import (
    clean_employer_markdown,
    embed_employer_card,
    extract_company_name,
    extract_employer_ref,
    remove_internal_links,
)
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
    "HttpStatusError",
    "ResponseTooLargeError",
    "UnsupportedContentTypeError",
    "ParseError",
    "ConversionError",
    "FetchTimeoutError",
    "RequestConfig",
    "NoisePolicy",
    "FetchService",
    "extract_employer_ref",
    "extract_company_name",
    "clean_employer_markdown",
    "embed_employer_card",
    "remove_internal_links",
]