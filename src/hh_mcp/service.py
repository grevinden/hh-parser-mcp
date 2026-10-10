"""Use-cases over hh.ru pages: fetch a page, and map failures to ToolError.

This is the layer between the two ends of the pipeline. Above it, ``app.py``
registers MCP tools and resources and knows nothing about HTTP; below it, the
:mod:`hh_mcp.fetch` package talks to the network and turns HTML into Markdown
and knows nothing about MCP. Everything that is *both* hh.ru-specific and
MCP-facing lives here:

* the concrete URLs (a vacancy, an employer, the filtered vacancy search);
* the fixed :data:`SEARCH_PARAMS` of that search;
* the mapping from a fetch exception to the one sentence a caller should read.

The split matters for error handling: an HTTP 404 for a missing vacancy and an
HTTP 400 for a missing employer are one fact ("there is no such page"), and the
message is composed here, once, instead of in each tool.
"""

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

A closed or archived vacancy is not a 404: hh.ru 302-redirects it to a regional
landing/lead page (e.g. ``kolomna.hh.ru/vrsurvey/...``) whose ``<main>`` holds
only an embedded JSON state dump. The sanitizer strips that and Markdown ends up
as a lone ``# HeadHunter`` title. Passing it off as the vacancy would be a silent
lie, so the tool reports a fetch failure instead.

The message states only what was observed — that the page has no content. Why
it has none is not the server's to guess at.
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
"""Fixed hh.ru search parameters, in the order the site itself sends them.

These are the filters of the drawer-filtered vacancy search: salary paid twice
a month, full employment, at least a year of experience, direct employers
(``not_from_agency``) ready to sign a labour contract, and any work format
(remote, on-site, hybrid) across title, company name and description.

They are applied to every :func:`search_vacancy_ids` call and are deliberately
*not* exposed as tool arguments: an agent that passes them through ``text`` only
wastes query width. The order and the repeated keys (``experience``,
``label``, ``work_format``, ``search_field``) are part of the contract — a
test compares the generated query pair by pair against this tuple.
"""


def _search_url(text: str, page: int) -> str:
    """Build the hh.ru vacancy search URL for *text* on *page*.

    Parameters
    ----------
    text:
        Raw user query, sent as ``text`` with ``quote_plus`` — the search
        operators of hh.ru (``!``, ``"``, ``~``, ``*``, ``AND``/``OR``/``NOT``)
        survive percent-encoding unchanged.
    page:
        Zero-based page number, appended last.

    Returns
    -------
    str
        Absolute ``https://hh.ru/search/vacancy`` URL.
    """
    q = quote_plus(text.strip(), safe=" ")
    return (
        f"https://hh.ru/search/vacancy?text={q}"
        f"&{urlencode(SEARCH_PARAMS)}"
        f"&page={page}"
    )


# --- Error mapping ---------------------------------------------------------


def _http_status_message(status: int, subject: str | None) -> str:
    """Say what the status means, in one sentence and no longer.

    The raw ``httpx`` text is unusable: it carries the post-redirect URL (a
    regional host for a page that does not exist) and a link to the MDN, which
    makes a missing vacancy look like a broken server.

    400 and 404 share one message on purpose. hh.ru answers an unknown vacancy
    with 404 and an unknown employer with 400, but both mean the same thing to
    the caller — there is no such page — so the agent gets one conclusion
    instead of two codes to interpret.

    Parameters
    ----------
    status:
        Numeric HTTP status.
    subject:
        The page, named so the sentence reads as a sentence: ``"Vacancy
        38185674"``. ``None`` falls back to a generic subject.

    Returns
    -------
    str
        One sentence, no URLs.
    """
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
    """Map a fetch exception to a user-facing :class:`ToolError`.

    Branching order matters: ``FetchTimeoutError`` / ``ResponseTooLargeError``
    / ``HttpStatusError`` are ``TransportError`` subclasses and are matched
    before the generic transport branch.

    Parameters
    ----------
    exc:
        Exception raised by the fetch pipeline.
    subject:
        What was being fetched, in English, e.g. ``"vacancy 38185674"``. Used
        by the HTTP-status branch to name the page instead of the host.

    Returns
    -------
    ToolError
        New error with a stable, user-facing message.
    """
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
    """Return *md* without heading lines, for a content-length check.

    Parameters
    ----------
    md:
        Markdown as produced by the fetch pipeline.

    Returns
    -------
    str
        Body text with ``#``-heading lines dropped.
    """
    return "\n".join(
        line for line in md.splitlines() if not line.lstrip().startswith("#")
    ).strip()


def _page_subject(doc_type: str | None, doc_id: int | None) -> str | None:
    """Name the page being fetched, for error messages.

    Parameters
    ----------
    doc_type:
        ``"vacancy"`` or ``"employer"``, or ``None`` for a plain URL.
    doc_id:
        Numeric hh.ru identifier.

    Returns
    -------
    str | None
        e.g. ``"vacancy 38185674"``, or ``None`` when the page is unknown.
    """
    if doc_type is None or doc_id is None:
        return None
    noun = "Vacancy" if doc_type == "vacancy" else "Employer page"
    return f"{noun} {doc_id}"


# --- Use-cases -------------------------------------------------------------


def fetch_page_markdown(
    url: str, *, doc_type: str | None = None, doc_id: int | None = None
) -> str:
    """Fetch *url* as Markdown with app-level error mapping.

    Parameters
    ----------
    url:
        Absolute ``https://`` URL of the hh.ru page.
    doc_type:
        Optional page type (``"vacancy"`` or ``"employer"``). Used only to
        name the page in error messages.
    doc_id:
        Numeric hh.ru identifier. Used only to name the page in error
        messages.

    Returns
    -------
    str
        Page main content as Markdown (title-prefixed, truncated).

    Raises
    ------
    ToolError
        On any fetch failure — see :func:`tool_error` for the mapping.
    """
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
    """Return the vacancy ids on one page of the filtered hh.ru search.

    The ids live in ``data-qa`` attributes of the raw HTML, so this fetches the
    page itself (same transport and SSRF guard as :func:`fetch_page_markdown`)
    instead of going through the Markdown converter.

    Parameters
    ----------
    text:
        Search query, sent to hh.ru as-is (percent-encoded, otherwise
        unchanged).
    page:
        Zero-based page number.

    Returns
    -------
    list[int]
        Vacancy ids in the order hh.ru lists them; empty past the last page.

    Raises
    ------
    ToolError
        On any fetch failure — see :func:`tool_error` for the mapping.
    """
    url = _search_url(text, page)
    try:
        html = fetch_page(url, timeout=TIMEOUT_S).decode("utf-8", errors="replace")
    except (SSRError, InvalidURLError, FetchError) as exc:
        raise tool_error(exc, subject="The vacancy search") from None
    except Exception as exc:
        raise ToolError(f"Unexpected error: {exc}") from None

    return [int(m.group(1)) for m in VACANCY_ID_RE.finditer(html)]
