"""Orchestrator: fetch service, public API entry points, logging."""

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
    """Return a logger named ``hh_mcp.fetch``."""
    return logging.getLogger("hh_mcp.fetch")


def _is_vacancy_url(url: str) -> bool:
    """Return ``True`` when *url* targets a vacancy page (path contains ``/vacancy/``)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    return "/vacancy/" in (parts.path or "").lower()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class FetchService:
    """Composed fetch service — coordinates guard, transport, sanitizer, and converter."""

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
        """Fetch a page and return raw bytes."""
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
        """Fetch *url* and return its main content as Markdown."""
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

        # Prefer the sanitizer title; skip the prefix line when the first
        # Markdown line is a heading that already duplicates it.
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
        """Return ``True`` when *heading_text* duplicates *title*."""
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
        """Return *markdown* enriched with an employee-page card."""
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
        """Convert HTML to Markdown without making any network request."""
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
    """Fetch *url* and return its main content as Markdown."""
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
    """Fetch a page and return raw bytes."""
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
    """Convert HTML to Markdown without any network request."""
    cfg = config or default_config()
    log = logger or _default_logger()
    svc = FetchService(
        config=cfg,
        transport=default_transport(cfg, log),
        converter=converter or default_converter(log),
        logger=log,
    )
    return svc.html_to_markdown(html, base_url=base_url, max_chars=max_chars)