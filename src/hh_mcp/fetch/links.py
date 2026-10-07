"""Relative-to-absolute link resolution and tracking-param cleanup.

Pure functions using ``urllib.parse``; no I/O, no DOM tree.
Idempotent for already-absolute hrefs.

Uses a single-pass ``html.parser`` to locate URL attributes and then
rewrites only the matching attribute values in the raw HTML string
(byte-level replacement preserves character references and entities).

:func:`clean_query_params` drops click-tracking / analytics query
parameters (``hhtmFrom``, ``backurl``, ``utm_*``, ...) from raw
entity-escaped attribute values.
"""

from __future__ import annotations

import re
from html import escape, unescape
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urljoin, urlencode, urlsplit

from .config import TRACKING_QUERY_KEYS, TRACKING_QUERY_KEY_PREFIXES

__all__ = [
    "resolve_relative_links",
    "clean_query_params",
]

#: Tags and the attribute names that hold URL references.
_URL_ATTRS: dict[str, tuple[str, ...]] = {
    "a": ("href",),
    "img": ("src",),
    "source": ("src",),
    "link": ("href",),
}

#: Pattern to find an attribute ``name="value"`` in a raw tag string.
_ATTR_RE = re.compile(
    r"""(?P<name>\w+)\s*=\s*(?P<q>['\"])(?P<value>.+?)(?P=q)""",
    re.ASCII,
)


def _is_tracking_param(name: str) -> bool:
    """Return ``True`` if *name* is a click-tracking query parameter.

    Exact matches against :data:`TRACKING_QUERY_KEYS` and prefix
    matches against :data:`TRACKING_QUERY_KEY_PREFIXES`, compared
    case-insensitively.
    """
    folded = name.casefold()
    if folded in TRACKING_QUERY_KEYS:
        return True
    return any(folded.startswith(p) for p in TRACKING_QUERY_KEY_PREFIXES)


def clean_query_params(url: str) -> str:
    """Drop click-tracking query parameters from *url*.

    *url* is the **raw (entity-escaped)** attribute value as it
    appears in the source HTML.  The function unescapes the value,
    drops parameters whose names are in :data:`TRACKING_QUERY_KEYS`
    or start with one of :data:`TRACKING_QUERY_KEY_PREFIXES`
    (``utm_*``) case-insensitively, then re-escapes the result so it
    is safe to embed in a double-quoted attribute.

    Idempotent: URLs without a query string, or without any tracking
    parameter, are returned verbatim (the original raw string).

    Args:
        url:
            Raw URL attribute value (possibly entity-escaped).

    Returns:
        str
            The cleaned value, safe to embed in an HTML attribute.
    """
    if "?" not in url:
        return url
    unescaped = unescape(url)
    parts = urlsplit(unescaped)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    kept = [(k, v) for k, v in pairs if not _is_tracking_param(k)]
    if len(kept) == len(pairs):
        return url
    query = urlencode(kept)
    cleaned = parts._replace(query=query).geturl()
    if not query and cleaned.endswith("?"):
        cleaned = cleaned[:-1]
    return escape(cleaned, quote=True)


def resolve_relative_links(html: str, base_url: str | None) -> str:
    """Rewrite ``a[href]`` / ``img[src]`` / ``source[src]`` / ``link[href]``
    attributes against *base_url* using ``urllib.parse.urljoin``.

    Idempotent: already-absolute URLs (including protocol-relative ``//``,
    scheme-full URLs like ``https://...``) pass through unchanged.

    The function is:
    - **Idempotent** — calling it twice with the same *base_url* produces
      the same output.
    - **Lenient** — malformed HTML is parsed best-effort; no exceptions
      on markup errors.
    - **Preserving** — character references and entities inside attribute
      values are left intact (the replacement operates on the raw string).

    Args:
        html:
            Input HTML string (UTF-8).
        base_url:
            Base URL for resolution.  When ``None`` or empty the document
            is returned unchanged.

    Returns:
        str
            The document with relative links resolved to absolute.
    """
    if not base_url:
        return html

    # --- 1. Collect attribute-value spans via a tracking HTMLParser ---
    # (start_char, end_char, raw_value) — offsets in the source string,
    # so non-ASCII content (e.g. Cyrillic paths) is handled correctly.
    spans: list[tuple[int, int, str]] = []

    class _LinkFinder(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self._prev_pos = 0  # char offset in html from last handle_starttag

        def handle_starttag(
            self, tag: str, attrs: list[tuple[str, str | None]]
        ) -> None:
            tag_lower = tag.lower()
            url_attrs = _URL_ATTRS.get(tag_lower)
            if not url_attrs:
                return
            raw_tag = self.get_starttag_text()
            if not raw_tag:
                return
            # Locate this raw_tag in the HTML after _prev_pos.
            pos = html.find(raw_tag, self._prev_pos)
            if pos < 0:
                return  # should not happen; skip
            self._prev_pos = pos + len(raw_tag)  # advance past this tag
            for match in _ATTR_RE.finditer(raw_tag):
                attr_name = match.group("name").lower()
                if attr_name in url_attrs:
                    val = match.group("value")
                    abs_start = pos + match.start("value")
                    abs_end = pos + match.end("value")
                    spans.append((abs_start, abs_end, val))

    finder = _LinkFinder()
    finder.feed(html)

    # --- 2. Rewrite spans in reverse order (stable offsets) ---
    result = html
    for start, end, raw_val in sorted(spans, key=lambda x: -x[0]):
        resolved = urljoin(base_url, raw_val)
        if "?" in resolved:
            resolved = clean_query_params(resolved)
        if resolved != raw_val:
            result = result[:start] + resolved + result[end:]

    return result
