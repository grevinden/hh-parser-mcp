"""MCP surface of hh-mcp: three tools and two resources over hh.ru."""

from __future__ import annotations

import json
from typing import Annotated

from fastmcp import FastMCP
from pydantic import NonNegativeInt, PositiveInt, StringConstraints

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


# --- Argument types --------------------------------------------------------


NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
"""A string that must carry text: padding is stripped, a blank one is rejected."""


# --- Tools -----------------------------------------------------------------


@mcp.tool
def vacancy(id: PositiveInt) -> str:
    """Fetch an hh.ru vacancy page as Markdown."""
    return fetch_page_markdown(
        f"https://hh.ru/vacancy/{id}", doc_type="vacancy", doc_id=id
    )


@mcp.tool
def company(id: PositiveInt) -> str:
    """Fetch an hh.ru company (employer) page as Markdown."""
    return fetch_page_markdown(
        f"https://hh.ru/employer/{id}", doc_type="employer", doc_id=id
    )


@mcp.tool
def search(
    text: NonBlankStr,
    page: NonNegativeInt = 0,
) -> list[int]:
    """Search hh.ru vacancies with this server's fixed filters.

    Returns the ids of one result page. The query language and the filters are
    documented in the ``hh-mcp://search-guide`` resource — read it before
    building ``text``.
    """
    return search_vacancy_ids(text, page)

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
