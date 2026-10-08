"""Orchestrator: fetch service, public API entry points, logging.

The only component that composes guards, transport, sanitizer, and
converter together.  Imports no ``httpx2`` or ``markitdown`` (DIP).

Default DI objects are created **per call** by plain factories — no
module-level singletons, no cached global clients.
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

from .config import (
    EMPLOYER_FETCH_MAX_CHARS,
    PUBLIC_DEFAULT_MAX_CHARS,
    PUBLIC_MAX_TIMEOUT,
    PUBLIC_MIN_TIMEOUT,
    RequestConfig,
    default_config,
)
from .converter import (
    MarkdownConverter,
    default_converter,
    normalize_markdown,
)
from .enrich import (
    clean_employer_markdown,
    embed_employer_card,
    extract_company_name,
    extract_employer_ref,
    remove_internal_links,
)
from .errors import FetchError, ParseError
from .guards import UrlGuard
from .html import Sanitizer, sanitize_document
from .transport import FetchTransport, default_transport

__all__ = [
    "FetchService",
    "fetch_as_markdown",
    "fetch_page",
    "html_to_markdown",
]


# ---------------------------------------------------------------------------
# Default logger factory
# ---------------------------------------------------------------------------


def _default_logger() -> logging.Logger:
    """Return a logger named ``hh_mcp.fetch``.

    No ``basicConfig`` call: the consumer (MCP server) is expected to
    have configured its own logging (stdout is MCP JSON-RPC).
    """
    return logging.getLogger("hh_mcp.fetch")


def _is_vacancy_url(url: str) -> bool:
    """Return ``True`` when *url* targets a vacancy page (path contains
    ``/vacancy/``).

    This is the enrichment gate: only vacancy cards are enriched with an
    employer card.  The gate is path-based (``/vacancy/``) so it works for
    any hh.ru host; employer pages (``/employer/``) and other pages are
    *not* enriched, which also makes the enrichment exactly 1 level deep
    (the employee reference found inside a fetched employee page points at
    an ``/employer/`` URL, never a ``/vacancy/`` one).
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    return "/vacancy/" in (parts.path or "").lower()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class FetchService:
    """Composed fetch service — coordinates guard, transport, sanitizer,
    and converter.

    All dependencies are injected explicitly (no globals, no state outside
    this instance).  The service itself is stateful only in its references;
    it is safe to reuse across calls.
    """

    def __init__(
        self,
        *,
        config: RequestConfig,
        transport: FetchTransport,
        converter: MarkdownConverter,
        guard: UrlGuard | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._converter = converter
        self._guard = guard or UrlGuard()
        self._logger = (logger or _default_logger()).getChild("service")

    # -----------------------------------------------------------------
    # Public methods
    # -----------------------------------------------------------------

    def fetch_page(self, url: str, *, timeout: float | None = None) -> bytes:
        """Fetch a page and return raw bytes.

        Args:
            url:
                Absolute ``http://`` or ``https://`` URL.
            timeout:
                Optional per-call timeout override (clamped to
                ``[PUBLIC_MIN_TIMEOUT, PUBLIC_MAX_TIMEOUT]``).

        Returns:
            bytes
                Raw response body.

        Raises:
            SSRError:
                On SSRF guard rejection.
            InvalidURLError:
                On malformed URL.
            TransportError:
                On network/HTTP failure.
            ResponseTooLargeError:
                On 4 MiB cap exceed.
        """
        validated_url = self._guard.validate(url)
        cfg = self._config
        if timeout is not None:
            if timeout <= 0:
                timeout = PUBLIC_MIN_TIMEOUT
            elif timeout > PUBLIC_MAX_TIMEOUT:
                timeout = PUBLIC_MAX_TIMEOUT
            # Frozen dataclass: create a modified copy
            cfg = RequestConfig(
                user_agent=cfg.user_agent,
                timeout=float(timeout),
                max_body_bytes=cfg.max_body_bytes,
                max_redirects=cfg.max_redirects,
                max_connections=cfg.max_connections,
                max_keepalive=cfg.max_keepalive,
                verify_tls=cfg.verify_tls,
                strict_content_type=cfg.strict_content_type,
                noise=cfg.noise,
            )
        return self._transport.fetch(validated_url, config=cfg)

    def fetch_as_markdown(
        self,
        url: str,
        *,
        timeout: int | float | None = None,
        max_chars: int = PUBLIC_DEFAULT_MAX_CHARS,
    ) -> str:
        """Fetch *url* and return its main content as Markdown.

        Steps:
        1. Guard validate.
        2. Transport fetch.
        3. Decode bytes as UTF-8 (with BOM strip).
        4. Sanitize (main-block extraction, noise removal, link
           resolution with tracking-param cleanup, title extraction).
        5. Converter: HTML → Markdown.
        6. Post-process: blank-line collapse / strip, title
           deduplication, title prefix ``# <title>\\n\\n``.
        7. Vacancy-page enrichment (``/vacancy/`` URLs only): the
           employer referenced by the card is fetched through the same
           pipeline, reduced to a compact employer card and embedded
           under ``## About the employer: <name>``; any employer-side
           failure degrades gracefully to the unenriched card.  Exactly
           one level deep (employee pages carry ``/employer/`` paths, so
           recursion is impossible by construction).
        8. Link stripping (all pages): internal hh.ru Markdown/URL links
           are removed (visible text is kept); external links are
           preserved.  No image ever reaches this stage — the Sanitizer
           drops the image elements and step 6 strips Markdown picture
           syntax.
        9. Truncation at *max_chars* with ``...truncated...`` suffix.

        Args:
            url:
                Absolute ``http://`` or ``https://`` URL.
            timeout:
                HTTP timeout in seconds (clamped to ``[1.0, 120.0]``).
                When ``None`` the default from configuration is used.
            max_chars:
                Maximum Markdown characters to return.

        Returns:
            str
                Markdown text, optionally title-prefixed and truncated.

        Raises:
            SSRError, InvalidURLError:
                On URL validation failure.
            TransportError, FetchTimeoutError, ResponseTooLargeError:
                On HTTP/transport failure.
            ConversionError:
                On converter failure.
        """
        html_bytes = self.fetch_page(url, timeout=float(timeout) if timeout is not None else None)

        # Decode (UTF-8 with BOM strip)
        try:
            html_text = html_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ParseError(f"invalid UTF-8 in response body: {exc}") from exc

        # Sanitize
        sanitized = sanitize_document(
            html_text,
            base_url=url,
            config=self._config,
            logger=self._logger,
        )

        # Convert
        result = self._converter.convert(sanitized.html, base_url=url)

        # Post-process: collapse blank-line runs, strip edges.
        md = normalize_markdown(result.markdown)

        # Title: prefer sanitizer title, fallback to converter title.
        # If the first line of the markdown is a heading that already
        # duplicates the title (exact match, or one containing the other
        # — e.g. the page's own ``<h1>`` under a prefixed og:title) do
        # not duplicate it with a prefix line.
        title = sanitized.title or result.title

        out: str
        if title:
            first_line = md.split("\n", 1)[0].strip() if md else ""
            if first_line.startswith("# ") and self._heading_overlaps_title(
                first_line[2:], title
            ):
                out = md
            else:
                out = f"# {title}\n\n{md}"
        else:
            out = md

        out = normalize_markdown(out)

        # Vacancy pages only: embed a compact employer card fetched from
        # the card's own employer link (1 level deep; any employer-side
        # failure degrades to the unenriched card).
        out = self._enrich_vacancy_card(out, url, timeout=timeout)

        # Strip every internal hh.ru link/URL from the final output
        # (external links are preserved).
        out = remove_internal_links(out)

        # Truncation
        if len(out) > max_chars:
            out = out[:max_chars] + "\n\n...truncated..."

        return out

    @staticmethod
    def _heading_overlaps_title(heading_text: str, title: str) -> bool:
        """Return ``True`` when *heading_text* duplicates *title*.

        The comparison is case-insensitive and treats the two strings as
        overlapping when one contains the other (a short page ``<h1>``
        under a prefixed og:title, or a shorter title under a fuller
        heading). Very short strings are ignored to avoid false
        positives on trivial text.

        Args:
            heading_text:
                Text of the first heading line (without the ``# ``
                marker).
            title:
                Document title to be prefixed.

        Returns:
            bool
                ``True`` when the heading duplicates the title.
        """
        h = heading_text.strip()
        t = title.strip()
        if len(h) < 3 or len(t) < 3:
            return False
        h = h.casefold()
        t = t.casefold()
        return h == t or h in t or t in h

    def _enrich_vacancy_card(
        self,
        markdown: str,
        url: str,
        *,
        timeout: int | float | None = None,
    ) -> str:
        """Return *markdown* enriched with an employee-page card.

        Only fires when *url* is a vacancy page (``_is_vacancy_url``) and
        the card holds an employer reference (:func:`extract_employer_ref`).
        In that case the employee page is fetched through the same pipeline
        (same guard/transport — the employee URL must pass ``UrlGuard``) and
        (capped at ``EMPLOYER_FETCH_MAX_CHARS``), then reduced to a compact
        card (:func:`clean_employer_markdown`) and embedded under an
        ``## About the employer: <name>`` heading
        (:func:`embed_employer_card`).

        The name is taken from the employee page
        (:func:`extract_company_name`).  When absent, it falls back to the
        link text found in the vacancy card.

        Graceful degradation: any failure of the employee fetch
        (:class:`FetchError` — transport / parse / conversion, or
        :class:`ValueError` — SSRF guard) or an empty cleaned card is a
        non-fatal *input*; a warning is logged and the original vacancy
        Markdown is returned unchanged.  The employee card is cleaned, but
        its own employee link (1 level) is not followed.

        Args:
            markdown:
                Normalized vacancy Markdown (with any title prefix).
            url:
                The original employee URL (drives the vacancy gate).
            timeout:
                Per-call timeout override for the employee fetch
                (clamped by :meth:`fetch_page`).

        Returns:
            str
                The enriched Markdown, or *markdown* unchanged when the
                card has no employer reference or the enrichment hit the
                degradation path.
        """
        if not _is_vacancy_url(url):
            return markdown

        ref = extract_employer_ref(markdown)
        if ref is None:
            return markdown
        employer_url, link_name = ref

        try:
            employer_md = self.fetch_as_markdown(
                employer_url,
                timeout=timeout,
                max_chars=EMPLOYER_FETCH_MAX_CHARS,
            )
        except (FetchError, ValueError) as exc:
            self._logger.warning(
                "Employee-page fetch for %s failed (degrading to unenriched vacancy card): %s",
                employer_url,
                exc,
            )
            return markdown

        name = extract_company_name(employer_md) or link_name
        card_body = clean_employer_markdown(employer_md)
        if not card_body:
            self._logger.warning(
                "Empty clean employee card for %s (degrading to unenriched vacancy card)",
                employer_url,
            )
            return markdown

        return embed_employer_card(markdown, name=name, card_body=card_body)

    def html_to_markdown(
        self,
        html: bytes | str,
        *,
        base_url: str | None = None,
        max_chars: int | None = None,
    ) -> str:
        """Convert HTML to Markdown without making any network request.

        This is the "offline" path — the new capability
        (requirement 2 of the redesign).

        Args:
            html:
                HTML content.  ``str`` is assumed UTF-8; ``bytes`` are
                decoded as UTF-8 (``ParseError`` on invalid bytes).
            base_url:
                Base URL for relative-link resolution.  When ``None``
                links are left as-is.
            max_chars:
                Maximum Markdown characters to return.  When ``None``
                no truncation is applied (pure conversion).

        Returns:
            str
                Markdown text, optionally truncated.

        Raises:
            ParseError:
                On invalid UTF-8 bytes.
            ConversionError:
                On converter failure.
        """
        if isinstance(html, bytes):
            try:
                html_text = html.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ParseError(f"invalid UTF-8 in input: {exc}") from exc
        else:
            html_text = html

        if not html_text:
            return ""

        # Sanitize (link resolution if base_url is given)
        sanitized = sanitize_document(
            html_text,
            base_url=base_url,
            config=self._config,
            logger=self._logger,
        )

        # Convert
        result = self._converter.convert(sanitized.html, base_url=base_url)

        # Post-process: collapse blank-line runs, strip edges.
        out = normalize_markdown(result.markdown)

        if max_chars is not None and len(out) > max_chars:
            out = out[:max_chars] + "\n\n...truncated..."

        return out


# ---------------------------------------------------------------------------
# Public API (back-compat signatures + optional DI kwargs)
# ---------------------------------------------------------------------------


def fetch_as_markdown(
    url: str,
    *,
    timeout: int = 30,
    max_chars: int = PUBLIC_DEFAULT_MAX_CHARS,
    config: RequestConfig | None = None,
    transport: FetchTransport | None = None,
    converter: MarkdownConverter | None = None,
    guard: UrlGuard | None = None,
    logger: logging.Logger | None = None,
) -> str:
    """Fetch *url* and return its main content as Markdown.

    Back-compat signature — the first three positional/keyword parameters
    match the old ``fetch_as_markdown(url, *, timeout=30, max_chars=120_000)``.
    New optional DI parameters (all ``None``-defaulted) follow.

    Parameters
    ----------
    url:
        Absolute ``http://`` or ``https://`` URL.
    timeout:
        HTTP timeout in seconds (default 30, max 120).
    max_chars:
        Maximum Markdown characters to return (default 120 000).
    config:
        Explicit :class:`RequestConfig`.  Default: ``default_config()``.
    transport:
        Explicit :class:`FetchTransport`.  Default: ``default_transport(...)``.
    converter:
        Explicit :class:`MarkdownConverter`.  Default:
        ``default_converter(...)``.
    guard:
        Explicit :class:`UrlGuard`.  Default: fresh ``UrlGuard()``.
    logger:
        Explicit logger.  Default: ``logging.getLogger("hh_mcp.fetch")``.

    Returns
    -------
    str
        Markdown text, optionally prefixed with ``# <title>``.
        Truncated with ``...truncated...`` if it exceeds *max_chars*.

    Raises
    ------
    SSRError
        If the URL targets a private or local address.
    FetchError
        On transport / parsing / conversion failure.
    """
    cfg = config or default_config()
    log = logger or _default_logger()
    svc = FetchService(
        config=cfg,
        transport=transport or default_transport(cfg, log),
        converter=converter or default_converter(log),
        guard=guard,
        logger=log,
    )
    return svc.fetch_as_markdown(url, timeout=timeout, max_chars=max_chars)


def fetch_page(
    url: str,
    *,
    timeout: float = 30.0,
    config: RequestConfig | None = None,
    transport: FetchTransport | None = None,
    logger: logging.Logger | None = None,
) -> bytes:
    """Fetch a page and return raw bytes.

    Back-compat signature — the first two parameters match the old
    ``fetch_page(url, *, timeout=30.0)``.

    Parameters
    ----------
    url:
        Absolute ``http://`` or ``https://`` URL.
    timeout:
        HTTP timeout in seconds (default 30, max 120 in the clamp,
        but the float type here accepts back-compat values).
    config:
        Explicit :class:`RequestConfig`.  Default: ``default_config()``.
    transport:
        Explicit :class:`FetchTransport`.  Default:
        ``default_transport(...)``.
    logger:
        Explicit logger.  Default: ``logging.getLogger("hh_mcp.fetch")``.

    Returns
    -------
    bytes
        Raw response body.

    Raises
    ------
    SSRError
        If the URL targets a private or local address.
    TransportError
        On network/HTTP failure.
    ResponseTooLargeError
        On 4 MiB cap exceed.
    """
    cfg = config or default_config()
    log = logger or _default_logger()
    svc = FetchService(
        config=cfg,
        transport=transport or default_transport(cfg, log),
        converter=default_converter(log),  # needed for the service ctor
        logger=log,
    )
    return svc.fetch_page(url, timeout=timeout)


def html_to_markdown(
    html: bytes | str,
    *,
    base_url: str | None = None,
    max_chars: int | None = None,
    config: RequestConfig | None = None,
    converter: MarkdownConverter | None = None,
    logger: logging.Logger | None = None,
) -> str:
    """Convert HTML to Markdown without any network request.

    Parameters
    ----------
    html:
        HTML content (``str`` or ``bytes``).  ``bytes`` are decoded as
        UTF-8; on error a :class:`ParseError` is raised.
    base_url:
        Base URL for relative-link resolution.  When ``None`` links are
        left as-is.
    max_chars:
        Maximum Markdown characters to return.  ``None`` = no truncation.
    config:
        Explicit :class:`RequestConfig` (used for noise policy).
    converter:
        Explicit :class:`MarkdownConverter`.
    logger:
        Explicit logger.

    Returns
    -------
    str
        Markdown text, optionally truncated.

    Raises
    ------
    ParseError
        On invalid UTF-8 bytes.
    ConversionError
        On converter failure.
    """
    cfg = config or default_config()
    log = logger or _default_logger()
    svc = FetchService(
        config=cfg,
        transport=default_transport(cfg, log),
        converter=converter or default_converter(log),
        logger=log,
    )
    return svc.html_to_markdown(html, base_url=base_url, max_chars=max_chars)