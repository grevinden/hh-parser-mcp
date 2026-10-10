"""Employer-card enrichment and internal-link stripping (pure functions)."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from .config import (
    EMPLOYER_MAX_CHARS,
    INTERNAL_PATH_MARKERS,
    INTERNAL_ROOT_DOMAINS,
    _SEO_TITLE_HEADING_MARKERS,
    _VACANCIES_HEADING_MARKERS,
)

__all__ = [
    "extract_employer_ref",
    "extract_company_name",
    "clean_employer_markdown",
    "embed_employer_card",
    "remove_internal_links",
]

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

#: Markdown link to an employer page: ``[text](<scheme>://<host>/employer/<id>)``.
#: ``\s+?`` allows a lazy space between the URL and the closing paren (kept
#: out of the ``url`` group so the emitted reference is clean).
_EMPLOYER_MD_LINK_RE = re.compile(
    r"\[(?P<text>[^\]]+)\]\(\s*(?P<url>[^(\s)]*//[^\s)]*?/employer/[0-9]+[^)\s]*)\s*\)"
)

#: Markdown heading: ``#{1,6} <text>`` (CommonMark).
_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.*)$")

#: Markdown image: ``![alt](src)`` — the canonical `alt` part first, then a
#: no-bracket fallback for converter variants that omit a missing alt.
_IMAGE_RE = re.compile(r"!(?:\[[^\]]*\])?\((?P<src>[^)]*)\)")

#: Bare (autolink) URL token: the scheme, the host, an optional port and an
#: optional path/query/fragment that stops at whitespace and Markdown
#: brackets (``[ ] ( ) < >``) so the token stays inside surrounding syntax.
_BARE_URL_RE = re.compile(r"https?://[A-Za-z0-9.\-]+(?::\d+)?(?:[/?#][^\s<>()\[\]]*)?")

#: Any Markdown link with an absolute URL target (for link-style stripping).
_MD_LINK_RE = re.compile(r"\[(?P<text>[^\]]*)\]\(\s*(?P<url><?[^)\s>]+)>?\s*\)")

#: Atx heading *deepening* (max +3 levels, capped at H6).
_DEEPEN_HEADING_RE = re.compile(r"^(#{1,6})(\s)")

#: Empty-lines squeeze (the equivalent of ``normalize_markdown`` collapsing
#: runs of 3+ newlines, applied on a subset of lines here).
_SQUEEZE_RE = re.compile(r"\n{3,}")


def _host_is_internal(host: str) -> bool:
    """Return ``True`` when *host* belongs to an internal hh.ru domain."""
    host = host.strip().lower()
    return any(host == d or host.endswith("." + d) for d in INTERNAL_ROOT_DOMAINS)


def _registered_host(url: str) -> tuple[str, str]:
    """Return ``(netloc, path)`` of *url* (netloc lowercased, no userinfo)."""
    parts = urlsplit(url)
    netloc = parts.netloc.lower()
    if "@" in netloc:
        netloc = netloc.rsplit("@", 1)[-1]
    if ":" in netloc:  # drop an explicit port
        netloc = netloc.split(":", 1)[0]
    return netloc, parts.path or "/"


def _url_is_internal(url: str) -> bool:
    """Return ``True`` when *url* points at an internal hh.ru resource."""
    if not netloc_is_known(url):
        return False
    netloc, path = _registered_host(url)
    if not netloc:
        return False
    if not _host_is_internal(netloc):
        # A non-hh.ru host is internal only when it is a job site:
        # the registered (second-level) domain ends in ``hh.ru`` and the
        # path looks like a job page.
        second = ".".join(netloc.split(".")[-2:])
        if second != "hh.ru":
            return False
        return any(path.lower().startswith(m) for m in INTERNAL_PATH_MARKERS)
    return True


def _netloc_is_known(url: str) -> bool:
    """Return ``True`` when *url* parses as an absolute http(s) URL."""
    return url.lower().startswith(("http://", "https://"))


# ---------------------------------------------------------------------------
# Employer reference extraction
# ---------------------------------------------------------------------------


def extract_employer_ref(markdown: str) -> tuple[str, str] | None:
    """Locate the employer reference in a vacancy Markdown card."""
    if not markdown:
        return None

    for m in _EMPLOYER_MD_LINK_RE.finditer(markdown):
        url = m.group("url")
        if _is_employer_url(url):
            return url, m.group("text").strip()

    # Bare-URL fallback: a standalone employer URL not inside a link.
    for m in _BARE_URL_RE.finditer(markdown):
        url = m.group(0)
        if _is_employer_url(url):
            return url, _employer_id_from_url(url) or "employer"
    return None


def _is_employer_url(url: str) -> bool:
    """Return ``True`` when *url* is an hh.ru employer-page URL."""
    if not _url_is_internal(url):
        return False
    return _employer_id_from_url(url) is not None


def _employer_id_from_url(url: str) -> str | None:
    """Return the numeric employer id from an employer-page URL."""
    _, path = _registered_host(url)
    m = re.match(r"^/employer/(\d+)/?$", path)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Employer page cleaning
# ---------------------------------------------------------------------------


def extract_company_name(markdown: str) -> str | None:
    """Return the company name from an employer-page Markdown."""
    if not markdown:
        return None
    for line in markdown.splitlines():
        m = _HEADING_RE.match(line.strip())
        if m and len(m.group("hashes")) == 1:
            text = m.group("text").strip()
            if text and not _is_seo_title(text):
                return text
    return None


def _is_seo_title(text: str) -> bool:
    """Return ``True`` when a heading looks like an employer-page SEO title."""
    t = text.casefold()
    return any(m in t for m in _SEO_TITLE_HEADING_MARKERS)


def clean_employer_markdown(markdown: str, *, max_chars: int = EMPLOYER_MAX_CHARS) -> str:
    """Reduce a fetched employer-page Markdown to a compact card."""
    if not markdown:
        return ""

    lines = markdown.splitlines()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        hm = _HEADING_RE.match(stripped)
        if hm:
            level = len(hm.group("hashes"))
            if level == 1:
                # Drop every H1 (SEO title, company name). Never cut here: the
                # SEO title contains "вакансии" and would truncate the card.
                continue
            if _is_vacancies_heading(hm.group("text")):
                break  # the job-list section: cut everything below
            out.append("#" * min(level + 3, 6) + " " + hm.group("text").strip())
            continue
        if _IMAGE_RE.search(stripped):
            # Drop images; any text left on the line is kept.
            line = _IMAGE_RE.sub("", line)
            if not line.strip():
                continue
        out.append(line)

    card = _SQUEEZE_RE.sub("\n\n", "\n".join(out)).strip()
    if len(card) > max_chars:
        # Keep the body plus the 4-char ``\n...`` suffix within the cap.
        card = card[: max(0, max_chars - 4)].rstrip() + "\n..."
    return card


def _is_vacancies_heading(text: str) -> bool:
    """Return ``True`` when a heading starts the employer job-list section."""
    t = text.casefold()
    return any(m in t for m in _VACANCIES_HEADING_MARKERS)


# ---------------------------------------------------------------------------
# Card embedding
# ---------------------------------------------------------------------------


def embed_employer_card(
    vacancy_md: str,
    *,
    name: str,
    card_body: str,
) -> str:
    """Embed a cleaned employer card into a vacancy Markdown card."""
    if not vacancy_md:
        return ""
    if not name:
        name = "employer"

    # Replace only *internal* (hh.ru) employer links with the plain name,
    # keeping any trailing text on the line.
    def _repl(m: re.Match) -> str:
        if not _is_employer_url(m.group("url")):
            return m.group(0)
        return name

    replaced = _EMPLOYER_MD_LINK_RE.sub(_repl, vacancy_md)

    if not card_body:
        return replaced

    return _SQUEEZE_RE.sub(
        "\n\n",
        replaced.rstrip() + "\n\n## About the employer: " + name + "\n\n" + card_body.strip(),
    ).strip()


# ---------------------------------------------------------------------------
# Internal link stripping
# ---------------------------------------------------------------------------


def remove_internal_links(markdown: str) -> str:
    """Remove every internal (hh.ru) link from *markdown*."""
    if not markdown:
        return ""

    # 1. Internal images: drop the whole image. Must run BEFORE the link pass,
    # which would turn one into a ``!alt`` artifact the image pattern misses.
    def _img_repl(m: re.Match) -> str:
        src = m.group("src")
        if _url_is_internal(src):
            return ""
        return m.group(0)

    out = _IMAGE_RE.sub(_img_repl, markdown)

    # 2. Markdown links: keep the text, drop the internal URL.
    def _link_repl(m: re.Match) -> str:
        url = m.group("url")
        if not _url_is_internal(url):
            return m.group(0)  # external — keep
        return m.group("text")

    out = _MD_LINK_RE.sub(_link_repl, out)

    # 3. Bare / autolink URLs: drop internal ones (incl. ``<url>`` form).
    def _bare_repl(m: re.Match) -> str:
        url = m.group(0)
        if _url_is_internal(url):
            return ""
        return url

    # The bare-URL pattern matches the URL core; an optional surrounding
    # ``<``/``>`` is stripped with a second pass on the surrounding chars.
    out = _BARE_URL_RE.sub(_bare_repl, out)
    # Remove a now-orphaned autolink bracket left by a bare-URL drop.
    if "<" in out:
        out = re.sub(r"(<\s*>)", "", out)

    # Squeeze any blank-line runs created by removed links/images.
    return _SQUEEZE_RE.sub("\n\n", out).strip()


# ---------------------------------------------------------------------------
# Internal helpers (re-exported for tests)
# ---------------------------------------------------------------------------


def netloc_is_known(url: str) -> bool:  # noqa: D401 - internal helper
    """``True`` when *url* is an absolute http(s) URL (see ``_netloc_is_known``)."""
    return _netloc_is_known(url)
