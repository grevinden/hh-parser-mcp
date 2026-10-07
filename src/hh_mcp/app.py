"""hh-mcp FastMCPApp — hh.ru pages as MCP tools and in-browser UI apps.

Implements the FastMCP Apps pattern (gofastmcp.com/apps/quickstart):
backend tools (:func:`get_vacancy`, :func:`get_employer`) return fetched
hh.ru pages as Markdown, while UI entry-points (:func:`vacancy_app`,
:func:`employer_app`) render Prefab components whose button calls the
backend tool from the in-browser app (:class:`CallTool`).
"""

from __future__ import annotations

from fastmcp import FastMCPApp
from fastmcp.exceptions import ToolError
from prefab_ui.actions import ShowToast
from prefab_ui.actions.mcp import CallTool
from prefab_ui.components import Button, Column, Heading, Input, Text

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
    "get_vacancy",
    "get_employer",
    "vacancy_app",
    "employer_app",
]

# --- Configuration ---------------------------------------------------------

TIMEOUT_S: int = 30
"""HTTP timeout passed to :func:`fetch_as_markdown` (seconds)."""

MAX_CHARS: int = 120_000
"""Maximum Markdown characters returned by :func:`fetch_as_markdown`."""

# --- Application -----------------------------------------------------------

app: FastMCPApp = FastMCPApp("hh-mcp")


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


# --- Backend tools ---------------------------------------------------------

@app.tool(model=True)
def get_vacancy(id: int) -> str:
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


@app.tool(model=True)
def get_employer(id: int) -> str:
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


# --- UI entry-points ---------------------------------------------------------

@app.ui()
def vacancy_app() -> Column:
    """Open the vacancy viewer panel.

    Returns
    -------
    Column
        Prefab component tree: heading, hint text, numeric ID input and a
        button that calls :func:`get_vacancy` via :class:`CallTool`.
    """
    id_input = Input(placeholder="ID вакансии…", name="vacancy_id")
    return Column(
        gap=4,
        css_class="p-6 max-w-3xl mx-auto",
        children=[
            Heading("Просмотр вакансии"),
            Text("Введите числовой ID вакансии и нажмите кнопку."),
            id_input,
            Button(
                "Получить вакансию",
                variant="default",
                on_click=CallTool(
                    tool="get_vacancy",
                    arguments={"id": "{{ vacancy_id }}"},
                    on_success=ShowToast("Готово", variant="success"),
                    on_error=ShowToast("{{ $error }}", variant="error"),
                ),
            ),
        ],
    )


@app.ui()
def employer_app() -> Column:
    """Open the employer viewer panel.

    Returns
    -------
    Column
        Prefab component tree: heading, hint text, numeric ID input and a
        button that calls :func:`get_employer` via :class:`CallTool`.
    """
    id_input = Input(placeholder="ID работодателя…", name="employer_id")
    return Column(
        gap=4,
        css_class="p-6 max-w-3xl mx-auto",
        children=[
            Heading("Просмотр работодателя"),
            Text("Введите числовой ID компании и нажмите кнопку."),
            id_input,
            Button(
                "Получить информацию",
                variant="default",
                on_click=CallTool(
                    tool="get_employer",
                    arguments={"id": "{{ employer_id }}"},
                    on_success=ShowToast("Готово", variant="success"),
                    on_error=ShowToast("{{ $error }}", variant="error"),
                ),
            ),
        ],
    )
