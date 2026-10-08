"""hh-mcp FastMCPApp — hh.ru pages as MCP tools.

Three tools (:func:`vacancy`, :func:`company`, :func:`search`) serve **both**
audiences at once: they are visible to the model (``visibility: ["app",
"model"]``) and appear in the browser Apps picker, which generates the input
form from each tool's JSON schema. A tool gets into the picker by carrying the
Prefab renderer placeholder in ``meta["ui"]["resourceUri"]``; fastmcp then
synthesizes a per-tool renderer resource on the fly.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any
from urllib.parse import quote_plus

from fastmcp import FastMCPApp
from fastmcp.exceptions import ToolError
from fastmcp.server.providers.local_provider.decorators.tools import (
    PREFAB_RENDERER_URI,
)
from fastmcp.tools.base import Tool

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
)
from hh_mcp.search_index import index_hh_page

__all__ = [
    "app",
    "vacancy",
    "company",
    "search",
]

# --- Configuration ---------------------------------------------------------

TIMEOUT_S: int = 30
"""HTTP timeout passed to :func:`fetch_as_markdown` (seconds)."""

MAX_CHARS: int = 120_000
"""Maximum Markdown characters returned by :func:`fetch_as_markdown`."""

# --- Application -----------------------------------------------------------

app: FastMCPApp = FastMCPApp("hh-mcp")


# --- Dual registration (model + browser) -----------------------------------

def register_tool(name: str, fn: Callable[..., Any]) -> None:
    """Register *fn* as one tool usable by both the model and the web UI.

    The tool keeps ``visibility: ["app", "model"]`` — an LLM can call it over
    MCP, and the Apps picker lists it because its meta carries the Prefab
    renderer placeholder. fastmcp rewrites that placeholder into a per-tool
    ``ui://prefab/tool/<hash>/renderer.html`` resource at ``tools/list`` time,
    synthesizing the renderer HTML on demand. The picker then builds the input
    form from the tool's own JSON schema, so no separate UI entry-point tool is
    needed.

    Parameters
    ----------
    name:
        Tool name as exposed over MCP (e.g. ``"vacancy"``).
    fn:
        The tool function; its signature and return annotation drive the
        generated input/output schemas.
    """
    tool = Tool.from_function(
        fn,
        name=name,
        meta={
            "ui": {
                "resourceUri": PREFAB_RENDERER_URI,
                "visibility": ["app", "model"],
            }
        },
    )
    app.add_tool(tool)


# --- Error mapping ---------------------------------------------------------

def _tool_error(exc: Exception) -> ToolError:
    """Map a fetch exception to a user-facing :class:`ToolError`.

    Branching order matters: ``FetchTimeoutError`` /
    ``ResponseTooLargeError`` are ``TransportError`` subclasses and are
    matched before the generic transport branch.

    Parameters
    ----------
    exc:
        Exception raised by :func:`hh_mcp.fetch.fetch_as_markdown`.

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
    if doc_type is not None and doc_id is not None:
        try:
            index_hh_page(doc_type=doc_type, doc_id=doc_id, url=url, md=md)
        except Exception:
            pass
    return md


# --- Tools -----------------------------------------------------------------

def vacancy(id: int) -> str:
    """Fetch an hh.ru vacancy page as Markdown.

    Parameters
    ----------
    id:
        Numeric vacancy identifier, e.g. ``38185674``. Must be a positive
        integer.

    Returns
    -------
    str
        The page's main content in Markdown.

    Raises
    ------
    ToolError
        If *id* is not positive or the fetch fails.
    """
    if id <= 0:
        raise ToolError(f"Invalid ID: {id}")
    return _fetch_markdown(
        f"https://hh.ru/vacancy/{id}", doc_type="vacancy", doc_id=id
    )


def company(id: int) -> str:
    """Fetch an hh.ru employer (company) page as Markdown.

    Parameters
    ----------
    id:
        Numeric employer identifier, e.g. ``9410116``. Must be a positive
        integer.

    Returns
    -------
    str
        The page's main content in Markdown.

    Raises
    ------
    ToolError
        If *id* is not positive or the fetch fails.
    """
    if id <= 0:
        raise ToolError(f"Invalid ID: {id}")
    return _fetch_markdown(
        f"https://hh.ru/employer/{id}", doc_type="employer", doc_id=id
    )


VACANCY_ID_RE = re.compile(r'data-qa="serp-item__title"[^>]*href="[^"]*/vacancy/(\d+)', re.M)


def search(text: str, page: int = 0) -> list[int]:
    """Search hh.ru vacancies and return a flat list of vacancy IDs.

    Parameters
    ----------
    text:
        Search query (keywords, title fragments).
    page:
        Zero-based page number for pagination (passed as ``&page=``).

    Returns
    -------
    list[int]
        List of numeric vacancy identifiers for the requested page (only IDs).
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

    try:
        # Нужен сырой HTML (ID лежат в data-qa атрибутах серпа), поэтому берём
        # fetch_page — тот же транспорт и тот же SSRF-guard, что и fetch_as_markdown.
        from hh_mcp.fetch import fetch_page

        html_bytes = fetch_page(url, timeout=TIMEOUT_S)
        html = html_bytes.decode("utf-8", errors="replace")
    except (SSRError, InvalidURLError, FetchError) as exc:
        raise _tool_error(exc) from None
    except Exception as exc:
        raise ToolError(f"Unexpected error: {exc}") from None

    ids = []
    for m in VACANCY_ID_RE.finditer(html):
        try:
            ids.append(int(m.group(1)))
        except ValueError:
            continue
    return ids


# --- Registration (one tool for model + browser) -----------------------

register_tool("vacancy", vacancy)
register_tool("company", company)
register_tool("search", search)
