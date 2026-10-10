"""fetch — HTTP(S) page fetching and HTML-to-Markdown conversion."""

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