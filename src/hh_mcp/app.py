"""hh-mcp tools — hh.ru vacancies and companies.

Three tools (:func:`vacancy`, :func:`company`, :func:`search`) are registered
with ``app=PrefabAppConfig(visibility=["app", "model"])``. That single
declaration makes each tool visible to the model *and* to the Apps UI: fastmcp
synthesizes the Prefab renderer resource and the browser picker builds the
input form from the tool's own JSON schema.

Each tool returns :class:`ToolResult` — the documented way to serve both
audiences at once (gofastmcp.com/apps/prefab, "Giving the LLM context"):
``content`` is the text the model reasons about, ``structured_content`` is
the Prefab view the browser renders.
"""

from __future__ import annotations

import re
from urllib.parse import quote_plus

from fastmcp import FastMCP
from fastmcp.apps import PrefabAppConfig
from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult
from prefab_ui.components import Column, DataTable, DataTableColumn, Markdown, Muted

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
from hh_mcp.search_index import index_hh_page

__all__ = [
    "mcp",
    "vacancy",
    "company",
    "search",
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

UI_CONFIG: PrefabAppConfig = PrefabAppConfig(visibility=["app", "model"])
"""Renders the tool in the Apps UI and keeps it visible to the model."""

# --- Application -----------------------------------------------------------

mcp: FastMCP = FastMCP("hh-mcp")

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
    try:
        md = fetch_as_markdown(url, timeout=TIMEOUT_S, max_chars=MAX_CHARS)
    except (SSRError, InvalidURLError, FetchError) as exc:
        raise _tool_error(exc) from None

    if len(_markdown_body(md)) < MIN_CONTENT_CHARS:
        raise ToolError(
            f"hh.ru returned no vacancy content for {url} "
            "(closed or archived vacancy redirects to a landing page)"
        )

    if doc_type is not None and doc_id is not None:
        try:
            index_hh_page(doc_type=doc_type, doc_id=doc_id, url=url, md=md)
        except Exception:
            pass
    return md


# --- Tools -----------------------------------------------------------------


@mcp.tool(app=UI_CONFIG)
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
        ``content`` is the page in Markdown; ``structured_content`` renders
        the same text in the browser.

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

    with Column(gap=4, css_class="p-6 max-w-4xl mx-auto") as view:
        Markdown(md)

    return ToolResult(content=md, structured_content=view)


@mcp.tool(app=UI_CONFIG)
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
        ``content`` is the page in Markdown; ``structured_content`` renders
        the same text in the browser.

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

    with Column(gap=4, css_class="p-6 max-w-4xl mx-auto") as view:
        Markdown(md)

    return ToolResult(content=md, structured_content=view)


@mcp.tool(app=UI_CONFIG)
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
        ``content`` lists the vacancy IDs; ``structured_content`` renders them
        as a sortable table.
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
        # The view shows the IDs in the table, so its heading carries the count
        # only — repeating the list here would put every ID in the tool result
        # three times (content + heading + row) instead of two.
        heading = f"Найдено {len(ids)} вакансий (страница {page})"
    else:
        summary = heading = f"Ничего не найдено (страница {page})."

    with Column(gap=4, css_class="p-6 max-w-4xl mx-auto") as view:
        Muted(heading)
        DataTable(
            columns=[DataTableColumn(key="id", header="Vacancy ID", sortable=True)],
            rows=[{"id": i} for i in ids],
            search=True,
        )

    return ToolResult(content=summary, structured_content=view)