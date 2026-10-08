"""hh-mcp tools — hh.ru vacancies and companies.

Four text tools: :func:`vacancy`, :func:`company`, :func:`search` and
:func:`version`.

Every tool returns :class:`ToolResult` with ``content`` and nothing else, so
the response carries the payload exactly once. That is deliberate: a
``-> str`` return would make fastmcp mirror the text into
``structuredContent.result`` (the "wrap-result" behaviour), and a Prefab view
would embed the same text a second time — a client walking twenty vacancy IDs
would then pay for forty pages. See ``docs/apps_mode.md`` for the full
reasoning and for how to bring the browser UI back.

``version`` is not hh.ru data: it reports which build is running so a
deployment can be verified against the commit that was pushed.
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote_plus

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult

from hh_mcp.fetch import (
    ConversionError,
    FetchError,
    FetchTimeoutError,
    InvalidURLError,
    ParseError,
    ResponseTooLargeError,
    SSRError,
    TransportError,
    UnsupportedContentTypeError,
    fetch_as_markdown,
    fetch_page,
)
from hh_mcp.search_index import index_hh_page, read_page, search_ttl_s
from hh_mcp.version import BUILD_ID, runtime_info

__all__ = [
    "mcp",
    "vacancy",
    "company",
    "search",
    "version",
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
"""

# --- Logging ----------------------------------------------------------------

logger = logging.getLogger("hh_mcp.app")

# --- Application -----------------------------------------------------------

# ``version`` is the standard MCP handshake field: every client learns which
# build it is talking to without calling a tool.
mcp: FastMCP = FastMCP("hh-mcp", version=BUILD_ID)

VACANCY_ID_RE = re.compile(
    r'data-qa="serp-item__title"[^>]*href="[^"]*/vacancy/(\d+)', re.M
)


# --- Error mapping ---------------------------------------------------------


def _tool_error(exc: Exception) -> ToolError:
    """Map a fetch exception to a user-facing :class:`ToolError`.

    Branching order matters: ``FetchTimeoutError`` /
    ``ResponseTooLargeError`` are ``TransportError`` subclasses and are
    matched before the generic transport branch.

    Parameters
    ----------
    exc:
        Exception raised by the fetch pipeline.

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


def _fetch_markdown(url: str, *, doc_type: str | None = None, doc_id: int | None = None) -> str:
    """Fetch *url* as Markdown with app-level error mapping.

    Parameters
    ----------
    url:
        Absolute ``https://`` URL of the hh.ru page.
    doc_type:
        Optional document type for Upstash Search indexing (``"vacancy"``
        or ``"employer"``). Indexing runs only when both *doc_type* and
        *doc_id* are provided and the fetch succeeds.
    doc_id:
        Numeric hh.ru identifier for Upstash Search indexing.

    Returns
    -------
    str
        Page main content as Markdown (title-prefixed, truncated).

    Raises
    ------
    ToolError
        On any fetch failure — see :func:`_tool_error` for the mapping.
    """
    # Cache tiers, cheapest first: the disk cache is already consulted by the
    # response-caching middleware (a hit never reaches this function), so what
    # is left is the search database, and only then hh.ru itself.
    if doc_type is not None and doc_id is not None:
        stored = read_page(doc_type=doc_type, doc_id=doc_id, max_age_s=search_ttl_s())
        if stored is not None and len(_markdown_body(stored)) >= MIN_CONTENT_CHARS:
            logger.info("page served from db tier: url=%s", url)
            return stored
        logger.info("page not in db tier, going to hh.ru: url=%s", url)

    try:
        md = fetch_as_markdown(url, timeout=TIMEOUT_S, max_chars=MAX_CHARS)
    except (SSRError, InvalidURLError, FetchError) as exc:
        raise _tool_error(exc) from None

    logger.info("page fetched from hh.ru: url=%s chars=%d", url, len(md))

    if len(_markdown_body(md)) < MIN_CONTENT_CHARS:
        raise ToolError(
            f"hh.ru returned no vacancy content for {url} "
            "(closed or archived vacancy redirects to a landing page)"
        )

    if doc_type is not None and doc_id is not None:
        try:
            index_hh_page(doc_type=doc_type, doc_id=doc_id, md=md)
        except Exception:
            pass
    return md


# --- Tools -----------------------------------------------------------------


@mcp.tool
def vacancy(id: int) -> ToolResult:
    """Fetch an hh.ru vacancy page as Markdown.

    Parameters
    ----------
    id:
        Numeric vacancy identifier, e.g. ``38185674``. Must be a positive
        integer.

    Returns
    -------
    ToolResult
        ``content`` is the page in Markdown — once, with no UI copy.

    Raises
    ------
    ToolError
        If *id* is not positive or the fetch fails.
    """
    if id <= 0:
        raise ToolError(f"Invalid ID: {id}")
    md = _fetch_markdown(
        f"https://hh.ru/vacancy/{id}", doc_type="vacancy", doc_id=id
    )

    return ToolResult(content=md)


@mcp.tool
def company(id: int) -> ToolResult:
    """Fetch an hh.ru company (employer) page as Markdown.

    Parameters
    ----------
    id:
        Numeric employer identifier, e.g. ``9410116``. Must be a positive
        integer.

    Returns
    -------
    ToolResult
        ``content`` is the page in Markdown — once, with no UI copy.

    Raises
    ------
    ToolError
        If *id* is not positive or the fetch fails.
    """
    if id <= 0:
        raise ToolError(f"Invalid ID: {id}")
    md = _fetch_markdown(
        f"https://hh.ru/employer/{id}", doc_type="employer", doc_id=id
    )

    return ToolResult(content=md)


@mcp.tool
def search(text: str, page: int = 0) -> ToolResult:
    """Search hh.ru vacancies and return a flat list of vacancy IDs.

    Parameters
    ----------
    text:
        Search query (keywords, title fragments).
    page:
        Zero-based page number for pagination (passed as ``&page=``).
        Beyond the last page the result is an empty list.

    Returns
    -------
    ToolResult
        ``content`` lists the vacancy IDs — once, with no UI copy.
    """
    if not isinstance(text, str) or not text.strip():
        raise ToolError("Invalid text: non-empty string required")
    if not isinstance(page, int) or page < 0:
        raise ToolError(f"Invalid page: {page}")

    q = quote_plus(text.strip(), safe=" ")
    url = (
        "https://hh.ru/search/vacancy"
        f"?text={q}"
        "&search_field=name&search_field=company_name&search_field=description"
        "&enable_snippets=false&hhtmFromLabel=chip_filter"
        "&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list"
        "&L_save_area=true"
        f"&page={page}"
    )

    # Raw HTML (the IDs live in data-qa attributes), same transport and SSRF
    # guard as fetch_as_markdown.
    try:
        html = fetch_page(url, timeout=TIMEOUT_S).decode("utf-8", errors="replace")
    except (SSRError, InvalidURLError, FetchError) as exc:
        raise _tool_error(exc) from None
    except Exception as exc:
        raise ToolError(f"Unexpected error: {exc}") from None

    ids = [int(m.group(1)) for m in VACANCY_ID_RE.finditer(html)]

    if ids:
        joined = ", ".join(str(i) for i in ids)
        summary = f"Найдено {len(ids)} вакансий (страница {page}): {joined}"
    else:
        summary = f"Ничего не найдено (страница {page})."

    return ToolResult(content=summary)


@mcp.tool
def version() -> ToolResult:
    """Report the running build: version, commit and runtime facts.

    Exists so a deployment can be verified: after a push the host redeploys on
    its own, and this tool is the cheapest way to tell which commit is actually
    serving traffic. The same value is published as ``serverInfo.version`` in
    the MCP handshake, so clients that never call tools can read it too.

    Returns
    -------
    ToolResult
        ``content`` is a one-line JSON object with the build facts.
    """
    return ToolResult(content=json.dumps(runtime_info(), ensure_ascii=False))