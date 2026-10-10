"""MCP surface of hh-mcp: three tools and two resources over hh.ru.

Three text tools — :func:`vacancy`, :func:`company` and :func:`search` — and two
resources that carry no hh.ru data: :func:`search_guide` (how to compose the
``search`` query) and :func:`version` (which build is running, so a deployment
can be verified against the commit that was pushed).

This module is the surface only: it validates arguments, calls the hh.ru
use-cases in :mod:`hh_mcp.service`, and shapes the MCP result. Fetching,
parsing and error wording live in ``service``; the network lives in
:mod:`hh_mcp.fetch`; caching in :mod:`hh_mcp.cache` — see ``server.py``.

What is a resource and what is a tool is not decoration. A tool is advertised
to the model with its full schema on every request: an agent pays for it in
every prompt and, as with ``version``, keeps calling it for an answer nobody
asked for. A resource is listed separately and read only on request. Anything
that is reference material or build metadata belongs here; anything that does
work on hh.ru belongs in a tool.

Every tool returns :class:`ToolResult` with ``content`` and nothing else, so
the response carries the payload exactly once. That is deliberate: a
``-> str`` return would make fastmcp mirror the text into
``structuredContent.result`` (the "wrap-result" behaviour), and a Prefab view
would embed the same text a second time — a client walking twenty vacancy IDs
would then pay for forty pages. See ``docs/apps_mode.md`` for the full
reasoning and for how to bring the browser UI back.
"""

from __future__ import annotations

import json

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult

from hh_mcp.search_guide import SEARCH_GUIDE_MD, SEARCH_GUIDE_URI
from hh_mcp.service import fetch_page_markdown, search_vacancy_ids
from hh_mcp.version import BUILD_ID, runtime_info

__all__ = [
    "mcp",
    "vacancy",
    "company",
    "search",
    "search_guide",
    "version",
]

# ``version`` is the standard MCP handshake field: every client learns which
# build it is talking to without calling a tool.
mcp: FastMCP = FastMCP("hh-mcp", version=BUILD_ID)


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
    md = fetch_page_markdown(
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
    md = fetch_page_markdown(
        f"https://hh.ru/employer/{id}", doc_type="employer", doc_id=id
    )

    return ToolResult(content=md)


@mcp.tool
def search(text: str, page: int = 0) -> ToolResult:
    """Search hh.ru vacancies and return a flat list of vacancy IDs.

    Read the ``hh-mcp://search-guide`` resource first: it documents the
    operators this query accepts (``AND``, ``OR``, ``NOT``, ``"``, ``~``,
    ``*``, ``NAME:``, ``COMPANY_NAME:``, ``DESCRIPTION:``) and the filters this
    server always applies, so an empty result is not a mystery.

    Parameters
    ----------
    text:
        Search query: plain keywords, optionally with hh.ru operators. Sent to
        hh.ru as-is, percent-encoded but otherwise unchanged.
    page:
        Zero-based page number for pagination (passed as ``&page=``).
        About 20 IDs per page. Beyond the last page the result is an empty
        list.

    Returns
    -------
    ToolResult
        ``content`` lists the vacancy IDs — once, with no UI copy. Use those
        IDs with :func:`vacancy` to read the pages themselves.
    """
    if not isinstance(text, str) or not text.strip():
        raise ToolError("Invalid text: non-empty string required")
    if not isinstance(page, int) or page < 0:
        raise ToolError(f"Invalid page: {page}")

    ids = search_vacancy_ids(text, page)

    if ids:
        joined = ", ".join(str(i) for i in ids)
        summary = f"Найдено {len(ids)} вакансий (страница {page}): {joined}"
    else:
        summary = (
            f"Ничего не найдено по запросу «{text.strip()}» (страница {page}). "
            "Поиск ограничен фильтрами: зарплата 2 раза в месяц, полная "
            "занятость, опыт от 1 года, без агентств и ГПХ, формат работы — "
            "удалённо, в офисе или гибрид."
        )

    return ToolResult(content=summary)


# --- Resources -------------------------------------------------------------


@mcp.resource(
    "hh-mcp://version",
    name="BuildInfo",
    title="Build info",
    description="Version, commit and runtime facts of the running server.",
    mime_type="application/json",
)
def version() -> str:
    """Report the running build: version, commit and runtime facts.

    A resource, not a tool. The build facts exist so a deployment can be
    verified after a push, and an agent has no use for them — as a tool it was
    advertised in every prompt, described, and occasionally called, spending
    tokens on an answer nobody asked for. A resource is read only when
    someone wants it. The same value is still published as
    ``serverInfo.version`` in the MCP handshake, so clients that read nothing
    at all still know which build is serving them.

    Returns
    -------
    str
        A one-line JSON object with the build facts.
    """
    return json.dumps(runtime_info(), ensure_ascii=False)


@mcp.resource(
    SEARCH_GUIDE_URI,
    name="SearchGuide",
    title="Search query guide",
    description=(
        "How to build the `text` argument of the search tool: the filters this "
        "server always applies, and the hh.ru query operators (AND, OR, NOT, "
        '"", ~, *, NAME:, COMPANY_NAME:, DESCRIPTION:). Read it before searching.'
    ),
    mime_type="text/markdown",
    tags={"guide", "search"},
)
def search_guide() -> str:
    """Return the hh.ru search-query guide as Markdown.

    Text lives in :mod:`hh_mcp.search_guide`; this function only registers it.
    It is a resource because it is reference material the agent reads once,
    before composing a query — not an action with an answer. See
    :data:`hh_mcp.search_guide.SEARCH_GUIDE_URI`.

    Returns
    -------
    str
        The guide in Markdown.
    """
    return SEARCH_GUIDE_MD
