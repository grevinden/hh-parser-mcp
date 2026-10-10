"""Use-cases over hh.ru pages: fetch a page and map failures to a ToolError."""

from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus, urlencode

from fastmcp.exceptions import ToolError

from hh_mcp.fetch import (
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
    fetch_as_markdown,
    fetch_page,
)

__all__ = [
    "MAX_CHARS",
    "MIN_CONTENT_CHARS",
    "SEARCH_PARAMS",
    "TIMEOUT_S",
    "fetch_page_markdown",
    "search_vacancy_ids",
    "tool_error",
]

# --- Configuration ---------------------------------------------------------

TIMEOUT_S: int = 30
"""HTTP timeout passed to the fetch pipeline (seconds)."""

MAX_CHARS: int = 120_000
"""Maximum Markdown characters returned by :func:`fetch_as_markdown`."""

MIN_CONTENT_CHARS: int = 200
"""Minimum body length for a page to count as real content.

A closed vacancy is not a 404: hh.ru redirects it to a regional landing page
whose Markdown is a lone ``# HeadHunter`` title. Reporting that as the vacancy
would be a silent lie, so the tool fails instead — stating only that the page
has no content, not why.
"""

# --- Logging ---------------------------------------------------------------

logger = logging.getLogger("hh_mcp.service")

# --- hh.ru search ----------------------------------------------------------

VACANCY_ID_RE = re.compile(
    r'data-qa="serp-item__title"[^>]*href="[^"]*/vacancy/(\d+)', re.M
)

SEARCH_PARAMS: tuple[tuple[str, str], ...] = (
    ("salary_frequency", "TWICE_PER_MONTH"),
    ("employment_form", "FULL"),
    ("experience", "moreThan6"),
    ("experience", "between3And6"),
    ("experience", "between1And3"),
    ("label", "not_from_agency"),
    ("label", "accept_labor_contract"),
    ("search_field", "name"),
    ("search_field", "company_name"),
    ("search_field", "description"),
    ("work_format", "REMOTE"),
    ("work_format", "ON_SITE"),
    ("work_format", "HYBRID"),
    ("enable_snippets", "false"),
    ("hhtmSource", "vacancy_search_list"),
    ("hhtmSourceLabel", "vacancy_search_list"),
    ("hhtmFrom", "vacancy_search_list"),
    ("hhtmFromLabel", "drawer_filter"),
)
"""Fixed hh.ru search filters, in the order the site itself sends them.

Salary twice a month, full employment, a year of experience or more, direct
employers ready to sign a labour contract, any work format; searched across
title, company name and description. The order and the repeated keys are part
of the contract — a test compares the generated query pair by pair.
"""


def _search_url(text: str, page: int) -> str:
    """Build the hh.ru vacancy search URL for *text* on *page*."""
    q = quote_plus(text.strip(), safe=" ")
    return (
        f"https://hh.ru/search/vacancy?text={q}"
        f"&{urlencode(SEARCH_PARAMS)}"
        f"&page={page}"
    )


# --- Error mapping ---------------------------------------------------------


def _http_status_message(status: int, subject: str | None) -> str:
    """Say what the status means, in one sentence and no longer."""
    what = subject or "The requested page"
    if status in (400, 404):
        return f"{what} does not exist on hh.ru (HTTP {status})."
    if status == 401:
        return f"hh.ru requires authorization for {what.lower()} (HTTP 401)."
    if status == 403:
        return f"hh.ru blocked the request (HTTP 403): too many requests, retry later."
    if status == 429:
        return f"hh.ru rate-limited the request (HTTP 429): retry later."
    if 500 <= status < 600:
        return f"hh.ru failed to serve {what.lower()} (HTTP {status}): retry later."
    return f"Unexpected HTTP status {status} from hh.ru."


def tool_error(exc: Exception, *, subject: str | None = None) -> ToolError:
    """Map a fetch exception to a user-facing :class:`ToolError`."""
    if isinstance(exc, SSRError):
        return ToolError("SSRF guard rejected the URL")
    if isinstance(exc, InvalidURLError):
        return ToolError(f"Invalid URL: {exc}")
    if isinstance(exc, FetchTimeoutError):
        return ToolError(f"Timeout after {TIMEOUT_S}s")
    if isinstance(exc, ResponseTooLargeError):
        return ToolError(f"Response too large > {MAX_CHARS}")
    if isinstance(exc, HttpStatusError):
        return ToolError(_http_status_message(exc.status_code, subject))
    if isinstance(exc, (ParseError, ConversionError)):
        return ToolError(f"Parse error: {exc}")
    if isinstance(exc, UnsupportedContentTypeError):
        return ToolError(f"Unsupported content type: {exc}")
    if isinstance(exc, TransportError):
        return ToolError(f"Transport error: {exc}")
    if isinstance(exc, FetchError):
        return ToolError(str(exc))
    return ToolError(f"Unexpected error: {exc}")


def _markdown_body(md: str) -> str:
    """Return *md* without heading lines, for a content-length check."""
    return "\n".join(
        line for line in md.splitlines() if not line.lstrip().startswith("#")
    ).strip()


def _page_subject(doc_type: str | None, doc_id: int | None) -> str | None:
    """Name the page being fetched, for error messages (``None`` if unknown)."""
    if doc_type is None or doc_id is None:
        return None
    noun = "Vacancy" if doc_type == "vacancy" else "Employer page"
    return f"{noun} {doc_id}"


# --- Use-cases -------------------------------------------------------------


def fetch_page_markdown(
    url: str, *, doc_type: str | None = None, doc_id: int | None = None
) -> str:
    """Fetch *url* as Markdown with app-level error mapping."""
    subject = _page_subject(doc_type, doc_id)
    try:
        md = fetch_as_markdown(url, timeout=TIMEOUT_S, max_chars=MAX_CHARS)
    except (SSRError, InvalidURLError, FetchError) as exc:
        raise tool_error(exc, subject=subject) from None

    logger.info("page fetched from hh.ru: url=%s chars=%d", url, len(md))

    if len(_markdown_body(md)) < MIN_CONTENT_CHARS:
        raise ToolError(
            f"{subject or 'The requested page'} has no content on hh.ru."
        )
    return md


def search_vacancy_ids(text: str, page: int) -> list[int]:
    """Return the vacancy ids on one page of the filtered hh.ru search."""
    url = _search_url(text, page)
    try:
        html = fetch_page(url, timeout=TIMEOUT_S).decode("utf-8", errors="replace")
    except (SSRError, InvalidURLError, FetchError) as exc:
        raise tool_error(exc, subject="The vacancy search") from None
    except Exception as exc:
        raise ToolError(f"Unexpected error: {exc}") from None

    return [int(m.group(1)) for m in VACANCY_ID_RE.finditer(html)]
