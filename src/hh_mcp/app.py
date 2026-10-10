"""MCP surface of hh-mcp: three tools and two resources over hh.ru."""

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
    """Fetch an hh.ru vacancy page as Markdown."""
    if id <= 0:
        raise ToolError(f"Invalid ID: {id}")
    md = fetch_page_markdown(
        f"https://hh.ru/vacancy/{id}", doc_type="vacancy", doc_id=id
    )

    return ToolResult(content=md)


@mcp.tool
def company(id: int) -> ToolResult:
    """Fetch an hh.ru company (employer) page as Markdown."""
    if id <= 0:
        raise ToolError(f"Invalid ID: {id}")
    md = fetch_page_markdown(
        f"https://hh.ru/employer/{id}", doc_type="employer", doc_id=id
    )

    return ToolResult(content=md)


@mcp.tool
def search(text: str, page: int = 0) -> ToolResult:
    """Search hh.ru vacancies and return a flat list of vacancy IDs.

    Read ``hh-mcp://search-guide`` first: it documents the query operators and
    the filters this server always applies.
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
    """Report the running build: version, commit and runtime facts."""
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
    """Return the hh.ru search-query guide as Markdown."""
    return SEARCH_GUIDE_MD
