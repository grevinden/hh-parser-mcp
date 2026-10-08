"""hh-mcp tools and resources — hh.ru vacancies and companies.

Three text tools — :func:`vacancy`, :func:`company` and :func:`search` — and two
resources that carry no hh.ru data: :func:`search_guide` (how to compose the
``search`` query) and :func:`version` (which build is running, so a deployment
can be verified against the commit that was pushed).

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
import logging
import re
from urllib.parse import quote_plus, urlencode

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult

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
from hh_mcp.search_guide import SEARCH_GUIDE_MD, SEARCH_GUIDE_URI
from hh_mcp.search_index import index_hh_page, read_page, search_ttl_s
from hh_mcp.version import BUILD_ID, runtime_info

__all__ = [
    "mcp",
    "vacancy",
    "company",
    "search",
    "search_guide",
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

They are applied to every :func:`search` call and are deliberately *not*
exposed as tool arguments: an agent that passes them through ``text`` only
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

NOT_FOUND_HINT = (
    "the id is wrong, the page was deleted, or the vacancy is closed and "
    "hh.ru stopped serving it"
)
"""What a 404 from hh.ru actually means for a vacancy or employer page."""


def _http_status_message(status: int, subject: str | None) -> str:
    """Explain an HTTP status in the words the caller needs.

    The raw ``httpx`` text is not usable: it carries the post-redirect URL (a
    regional host for a page that does not exist) and a link to the MDN, which
    makes a missing vacancy look like a broken server.

    Parameters
    ----------
    status:
        Numeric HTTP status.
    subject:
        What was being fetched, e.g. ``"vacancy 38185674"``. ``None`` for the
        search endpoint, where the subject is the query itself.

    Returns
    -------
    str
        Human-readable sentence, no URLs.
    """
    what = subject or "the page"
    if status == 404:
        return f"{what} was not found on hh.ru (HTTP 404) — {NOT_FOUND_HINT}."
    if status == 400:
        return f"hh.ru rejected the request for {what} (HTTP 400) — check the id."
    if status == 401:
        return f"hh.ru requires authorization for {what} (HTTP 401)."
    if status == 403:
        return f"hh.ru blocked the request for {what} (HTTP 403) — too many requests."
    if status == 429:
        return f"hh.ru rate-limited the request for {what} (HTTP 429) — retry later."
    if 500 <= status < 600:
        return f"hh.ru failed to serve {what} (HTTP {status}) — retry later."
    return f"Unexpected HTTP status {status} from hh.ru for {what}."


def _tool_error(exc: Exception, *, subject: str | None = None) -> ToolError:
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
    noun = "vacancy" if doc_type == "vacancy" else "employer page"
    return f"{noun} {doc_id}"


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

    subject = _page_subject(doc_type, doc_id)
    try:
        md = fetch_as_markdown(url, timeout=TIMEOUT_S, max_chars=MAX_CHARS)
    except (SSRError, InvalidURLError, FetchError) as exc:
        raise _tool_error(exc, subject=subject) from None

    logger.info("page fetched from hh.ru: url=%s chars=%d", url, len(md))

    if len(_markdown_body(md)) < MIN_CONTENT_CHARS:
        raise ToolError(
            f"hh.ru served no usable content for {subject or url} (HTTP 200): "
            "the response is a landing or lead form, not the page you asked "
            "for — the vacancy is closed or archived"
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

    url = _search_url(text, page)

    # Raw HTML (the IDs live in data-qa attributes), same transport and SSRF
    # guard as fetch_as_markdown.
    try:
        html = fetch_page(url, timeout=TIMEOUT_S).decode("utf-8", errors="replace")
    except (SSRError, InvalidURLError, FetchError) as exc:
        raise _tool_error(exc, subject="the vacancy search") from None
    except Exception as exc:
        raise ToolError(f"Unexpected error: {exc}") from None

    ids = [int(m.group(1)) for m in VACANCY_ID_RE.finditer(html)]

    if ids:
        joined = ", ".join(str(i) for i in ids)
        summary = f"Найдено {len(ids)} вакансий (страница {page}): {joined}"
    else:
        summary = (
            f"Ничего не найдено по запросу «{text.strip()}» (страница {page}). "
            "Поиск идёт только по вакансиям с зарплатой 2 раза в месяц, "
            "полной занятостью, опытом от 1 года, без агентств и ГПХ; "
            "формат работы — удалённо, в офисе или гибрид. "
            "Если фильтры — не часть задачи, ослабьте запрос: уберите операторы "
            "NOT, кавычки и поля вида NAME:, и попробуйте более общее слово."
        )

    return ToolResult(content=summary)


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