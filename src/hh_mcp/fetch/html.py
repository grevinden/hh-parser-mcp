"""HTML sanitizer: noise removal, main-block extraction, title
extraction, and link resolution.

Stdlib ``html.parser``-based cleaner. Single-pass, no DOM tree, no
BeautifulSoup dependency.  Malformed HTML is parsed best-effort and
never raises an exception.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from html import escape, unescape
from html.parser import HTMLParser

from .config import FACT_CELL_QA, ORPHAN_FACT_LABELS, NoisePolicy, RequestConfig
from .links import resolve_relative_links

__all__ = [
    "SanitizedDocument",
    "Sanitizer",
    "sanitize_document",
]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SanitizedDocument:
    """Result of a sanitization pass.

    Attributes:
        html:
            Cleaned UTF-8 text; links already resolved to absolute when
            a *base_url* was provided.
        title:
            Text content of the first ``<title>`` tag, **or** ``None``
            if absent.  Stripped of leading/trailing whitespace.
        removed:
            Number of top-level noise elements that were removed (grand-
            children are counted as part of the parent — this is a count
            of *removal operations*, not individual tags).
    """

    html: str = ""
    title: str | None = None
    removed: int = 0

    @staticmethod
    def empty() -> SanitizedDocument:
        """Return a safe empty document (no HTML, no title, zero removals).

        Returns:
            SanitizedDocument
        """
        return SanitizedDocument(html="", title=None, removed=0)


def attrs_have_src(attrs: list[tuple[str, str | None]]) -> bool:
    """Return True if *attrs* contains a non-empty ``src`` attribute.

    Args:
        attrs:
            Raw attribute list as produced by
            :meth:`html.parser.HTMLParser.handle_starttag`.

    Returns:
        True if a ``src`` attribute with a non-empty value is present.
    """
    return any(name.lower() == "src" and value for name, value in attrs)


# ---------------------------------------------------------------------------
# Sanitizer
# ---------------------------------------------------------------------------


class _ReconstructingHtmlParser(HTMLParser):
    """HTML parser that reconstructs the cleaned document while filtering
    noise elements and collecting the first ``<title>``.

    ``html.parser`` already treats ``<script>``, ``<style>``, and
    ``<title>`` as *literal* elements: their raw content is passed to
    ``handle_data`` as a single chunk rather than being parsed as tags.
    This simplifies script/style removal and title extraction.

    Suppression is tracked with a *stack* of booleans (``True`` =
    regular element, ``False`` = noise subtree), so that closing tags of
    regular elements nested inside noise (e.g. ``<ul>`` inside ``<nav>``)
    keep the stack consistent and never leak into the output.

    When :attr:`NoisePolicy.main_extraction` is enabled (default) the
    parser additionally runs a three-phase state machine
    (``pre`` / ``in`` / ``post``) around the first ``<main>`` element:
    everything before ``<main>`` (header / navigation / cookie banners)
    and everything after ``</main>`` (footer) is dropped.  A document
    without ``<main>`` passes through unchanged (lenient).
    """

    #: Elements whose entire content is treated as raw text by HTMLParser.
    LITERAL_ELEMENTS = frozenset({"script", "style"})

    #: Void elements never push onto the stack (they have no end tag).
    _VOID_ELEMENTS = frozenset(
        {
            "area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr",
        }
    )

    def __init__(self, noise: NoisePolicy) -> None:
        super().__init__(convert_charrefs=False)
        self._noise = noise
        self._stack: list[bool] = []
        self._literal_tag: str | None = None
        self._title_parts: list[str] = []
        self._in_title: bool = False
        self._title_taken: bool = False
        self._removed_count: int = 0
        self._pre_parts: list[str] = []
        self._out_parts: list[str] = []
        self._main_state: str = "pre" if noise.main_extraction else "in"
        self._main_depth: int = 0
        # Fact-cell buffering: depth > 0 while inside a
        # ``data-qa="cell-text-content"`` span (see _flush_fact_cell).
        self._cell_depth: int = 0
        self._cell_parts: list[str] = []

    # -- helpers ----------------------------------------------------------

    @property
    def _inside_noise(self) -> bool:
        return False in self._stack

    @property
    def _inside_main(self) -> bool:
        return self._main_state == "in"

    def _emit(self, chunk: str) -> None:
        self._route(chunk)

    def _route(self, chunk: str) -> None:
        if self._inside_noise or self._literal_tag is not None:
            return
        if self._main_state == "in":
            self._out_parts.append(chunk)
        elif self._main_state == "pre":
            self._pre_parts.append(chunk)

    def _push_suppressed(self) -> None:
        self._stack.append(False)
        if len(self._stack) == 1:
            self._removed_count += 1

    def _reconstruct(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        *,
        self_close: bool = False,
    ) -> str:
        parts = [f"<{tag}"]
        for name, value in attrs:
            if value is None:
                parts.append(f" {name}")
            else:
                parts.append(f' {name}="{self._escape_attr(value)}"')
        parts.append("/>" if self_close else ">")
        return "".join(parts)

    # -- handlers ---------------------------------------------------------

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        tag_lower = tag.lower()

        if self._literal_tag is not None:
            return

        # Fact cells (``data-qa="cell-text-content"``) are buffered instead of
        # being streamed: an employer-sidebar caption ("Сайт") may outlive the
        # card it belongs to, and the dangling word is dropped at flush time.
        if self._cell_depth:
            if tag_lower not in self._VOID_ELEMENTS:
                self._cell_depth += 1
            return
        if tag_lower == "span" and dict(attrs).get("data-qa") == FACT_CELL_QA:
            self._cell_depth = 1
            self._cell_parts = []
            return

        if tag_lower in self.LITERAL_ELEMENTS:
            # Script/style: always removed, content is raw text.
            self._literal_tag = tag_lower
            self._removed_count += 1
            return

        if tag_lower == "title":
            # Title: always removed from the document; only the first
            # occurrence is captured.
            self._literal_tag = "title"
            if not self._title_taken:
                self._title_parts = []
                self._in_title = True
            self._title_taken = True
            self._removed_count += 1
            return

        if self._noise.is_noise(tag_lower, dict(attrs)):
            self._push_suppressed()
            return

        if tag_lower == "img" and not attrs_have_src(attrs):
            # Contentless <img> (no src): a CSS-driven placeholder/sprite
            # in React markup — no content to keep, and the surrounding
            # <a href> already carries the target URL.
            return

        if (
            tag_lower == "main"
            and self._main_state == "pre"
            and not self._inside_noise
        ):
            # Enter the main block: the first <main> wins, pre-main
            # content (header / nav / cookie banners) is dropped.
            self._main_state = "in"
            self._main_depth = 1
        elif (
            tag_lower == "main"
            and self._main_state == "in"
            and self._main_depth > 0
            and not self._inside_noise
        ):
            # Nested <main>: only depth tracking is needed (the closing
            # tag below restores the ``post`` state when it balances out).
            self._main_depth += 1

        if tag_lower not in self._VOID_ELEMENTS:
            self._stack.append(True)
        self._emit(self._reconstruct(tag_lower, attrs))

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()

        if self._literal_tag is not None:
            # Closing tag of the literal element (script/style/title):
            # consumed by the parser, never emitted.
            if tag_lower == self._literal_tag:
                self._literal_tag = None
                self._in_title = False
            return

        if self._cell_depth:
            self._cell_depth -= 1
            if self._cell_depth == 0:
                self._flush_fact_cell()
            return

        if (
            tag_lower == "main"
            and self._main_state == "in"
            and self._main_depth > 0
        ):
            self._main_depth -= 1
            if self._main_depth == 0:
                self._main_state = "post"

        if self._stack:
            was_noisy = self._stack.pop()
            if not was_noisy:
                return
            if not self._inside_noise:
                self._emit(f"</{tag_lower}>")
        elif tag_lower not in self._VOID_ELEMENTS:
            # Lenient: stray closing tag with nothing to match — pass through.
            self._emit(f"</{tag_lower}>")

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        tag_lower = tag.lower()

        if self._literal_tag is not None:
            return

        if tag_lower in self.LITERAL_ELEMENTS or tag_lower == "title":
            self._removed_count += 1
            return

        if self._noise.is_noise(tag_lower, dict(attrs)):
            if not self._inside_noise:
                self._removed_count += 1
            return

        if tag_lower == "img" and not attrs_have_src(attrs):
            return

        if not self._inside_noise:
            self._emit(self._reconstruct(tag_lower, attrs, self_close=True))

    def handle_data(self, data: str) -> None:
        if self._literal_tag is not None:
            if self._literal_tag == "title" and self._in_title:
                self._title_parts.append(data)
            return
        if self._cell_depth:
            self._cell_parts.append(data)
            return
        self._route(data)

    def handle_entityref(self, name: str) -> None:
        text = f"&{name};"
        if self._literal_tag is not None:
            if self._literal_tag == "title" and self._in_title:
                self._title_parts.append(text)
            return
        if self._cell_depth:
            self._cell_parts.append(text)
            return
        self._route(text)

    def handle_charref(self, name: str) -> None:
        text = f"&#{name};"
        if self._literal_tag is not None:
            if self._literal_tag == "title" and self._in_title:
                self._title_parts.append(text)
            return
        if self._cell_depth:
            self._cell_parts.append(text)
            return
        self._route(text)

    def _flush_fact_cell(self) -> None:
        """Emit (or drop) the buffered ``cell-text-content`` span.

        hh.ru renders the employer sidebar as a value + caption pair per
        fact ("Москва" / "Город").  The cards holding those cells are
        removed wholesale (:data:`~hh_mcp.fetch.config.NOISE_DATA_QA`),
        but a caption can also be rendered *inside* the description widget
        (the "Сайт" cell) — such an orphan caption would otherwise survive
        as a dangling word at the end of the Markdown.  Captions listed in
        :data:`~hh_mcp.fetch.config.ORPHAN_FACT_LABELS` are therefore
        dropped; anything else (a real value such as "Москва", or free
        text) is re-emitted with its text content preserved and its
        original markup normalised to a flat span.
        """
        raw = "".join(self._cell_parts)
        text = " ".join(unescape(raw).split())
        if not text:
            return
        if text.casefold() in ORPHAN_FACT_LABELS:
            self._removed_count += 1
            return
        self._emit(f'<span data-qa="{FACT_CELL_QA}">{escape(text)}</span>')

    def handle_comment(self, data: str) -> None:
        # Comments are suppressed (rarely useful in the output).
        pass

    def handle_decl(self, decl: str) -> None:
        # <!DOCTYPE ...> and other declarations are suppressed.
        pass

    def handle_pi(self, data: str) -> None:
        pass


    @staticmethod
    def _escape_attr(value: str) -> str:
        """Minimal attribute-value escaping for reconstruction."""
        return value.replace("&", "&amp;").replace('"', "&quot;")

    @property
    def html(self) -> str:
        if self._main_state == "pre":
            return "".join(self._pre_parts)
        return "".join(self._out_parts)

    @property
    def title(self) -> str | None:
        text = unescape("".join(self._title_parts)).strip()
        return text if text else None

    @property
    def removed(self) -> int:
        return self._removed_count


class Sanitizer:
    """Stdlib ``html.parser``-based HTML cleaner.

    Lenient by construction: malformed HTML never raises (it is parsed
    as best-effort; unparseable content is passed through.
    """

    def __init__(self, *, noise: NoisePolicy, logger: logging.Logger) -> None:
        self._noise = noise
        self._logger = logger.getChild("sanitize")

    def sanitize(
        self, html: str, *, base_url: str | None = None
    ) -> SanitizedDocument:
        """Clean and transform HTML.

        1. When :attr:`NoisePolicy.main_extraction` is enabled, keep only
           the content of the first ``<main>`` element (a document without
           ``<main>`` passes through unchanged).
        2. Remove ``<script>``, ``<style>`` subtrees (always).
        3. Remove elements matching :attr:`NoisePolicy.is_noise`.
        4. Extract text content of the first ``<title>`` tag.
        5. Resolve relative links when *base_url* is given.

        Args:
            html:
                Input HTML (UTF-8 text).
            base_url:
                Base URL for relative link resolution.  When ``None``
                links are left as-is.

        Returns:
            SanitizedDocument
                Cleaned document with title and removal metadata.
        """
        parser = _ReconstructingHtmlParser(self._noise)
        try:
            parser.feed(html)
            parser.close()
        except Exception:
            # html.parser is lenient, but protect against edge cases.
            self._logger.warning(
                "sanitizer parse error, falling back to original",
                exc_info=True,
            )
            return SanitizedDocument(html=html, title=None, removed=0)

        cleaned = parser.html
        title = parser.title
        removed = parser.removed

        # Resolve relative links (after cleanup, before output).
        if base_url:
            cleaned = resolve_relative_links(cleaned, base_url)

        self._logger.debug(
            "sanitize ok",
            extra={
                "original_len": len(html),
                "cleaned_len": len(cleaned),
                "removed_nodes": removed,
            },
        )
        return SanitizedDocument(html=cleaned, title=title, removed=removed)


# ---------------------------------------------------------------------------
# Convenience (orchestrator-level)
# ---------------------------------------------------------------------------


def sanitize_document(
    html: str,
    *,
    base_url: str | None,
    config: RequestConfig,
    logger: logging.Logger,
) -> SanitizedDocument:
    """One-shot sanitization with the noise policy from *config*.

    Args:
        html:
            Input HTML.
        base_url:
            Base URL for link resolution.
        config:
            Request configuration (provides :attr:`RequestConfig.noise`).
        logger:
            Logger instance.

    Returns:
        SanitizedDocument
    """
    sanitizer = Sanitizer(noise=config.noise, logger=logger)
    return sanitizer.sanitize(html, base_url=base_url)