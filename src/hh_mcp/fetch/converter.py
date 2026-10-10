"""Markdown converter abstraction.

The only module that imports ``markitdown`` (DIP: the orchestrator depends
on the :class:`MarkdownConverter` Protocol, never on ``markitdown``).

:class:`MarkItDownConverter` is the default; any other converter only needs
to implement :class:`MarkdownConverter` and may be injected via
``FetchService(converter=...)``.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .config import MARKDOWN_CONVERT_TAGS
from .errors import ConversionError

__all__ = [
    "MarkdownResult",
    "MarkdownConverter",
    "MarkItDownConverter",
    "default_converter",
    "normalize_markdown",
    "normalize_spaces",
    "strip_images",
]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


#: Three or more consecutive newlines (markdownify often emits extra blank
#: lines around removed blocks) are collapsed into a single blank line.
_BLANK_LINES_RE = re.compile(r"\n{3,}")

#: Bare CommonMark autolinks ``<https://...>`` (markdownify emits them when
#: an anchor's text equals its href, e.g. the company "site" link that
#: renders the URL as its own label) are rewritten to explicit Markdown
#: links ``[url](url)``.
_ANGLED_URL_RE = re.compile(r"<(https?://[^>\s]+)>")

#: Markdown image ``![alt](src)``, with an optional title
#: (``![alt](src "title")``).  ``alt`` may be empty (``![](src)``).
#: The whole construct is removed, ``alt`` included: the alt text of a
#: picture is a caption for something the reader cannot see.
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")

#: Raw ``<img ...>`` markup left in the text by a converter that passes HTML
#: through instead of unwrapping it.
_RAW_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)

#: An anchor with an empty label ``[](url)`` — the shape an image-only link
#: (``[![alt](pic)](target)``) collapses into once the picture is removed.
_EMPTY_LINK_RE = re.compile(r"\[\s*\]\([^)]*\)")

#: Unicode space characters that are not the ASCII space (``U+0020``) but
#: occupy the same slot.  hh.ru leans on them heavily: ``NO-BREAK SPACE``
#: (``U+00A0``, written ``&nbsp;`` in the markup) appears throughout every
#: description — a single vacancy carries ~55 — and ``NARROW NO-BREAK SPACE``
#: (``U+202F``) separates an amount from its unit in salary strings
#: ("100 000 ₽ за месяц").  The converter passes them through verbatim; left
#: in place they defeat plain-text search, line wrapping and copy-paste, so
#: every one is folded to a regular space.  ``U+2007`` (FIGURE SPACE) is the
#: same no-break family.
_NO_BREAK_SPACE_RE = re.compile(r"[\u00a0\u2007\u202f]")


@dataclass(frozen=True, slots=True)
class MarkdownResult:
    """Result of a conversion.

    Attributes:
        markdown:
            The converted Markdown text.
        title:
            Optional title extracted from the document.
    """

    markdown: str
    title: str | None = None


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class MarkdownConverter(Protocol):
    """Convert a clean HTML document to Markdown.

    Implementations of this protocol:
    - MUST return :class:`MarkdownResult`.
    - MUST raise :class:`ConversionError` on failure.
    - MUST NOT perform I/O.
    """

    def convert(self, html: str, *, base_url: str | None) -> MarkdownResult:
        """Convert HTML to Markdown.

        Args:
            html:
                A UTF-8 HTML string, already sanitised (noise removed,
                links resolved).
            base_url:
                Original source URL (provided to the converter for
                further resolution if the implementation supports it).

        Returns:
            MarkdownResult
                The converted Markdown and optionally a title.

        Raises:
            ConversionError:
                On any conversion failure.
        """
        ...


# ---------------------------------------------------------------------------
# Default: MarkItDown
# ---------------------------------------------------------------------------


class MarkItDownConverter:
    """Default converter wrapping ``markitdown.MarkItDown``.

    The import is isolated here; this is the only place ``markitdown``
    is imported (version lock / upgrade boundary, per AGENTS.md).
    """

    def __init__(self, *, logger: logging.Logger) -> None:
        self._logger = logger.getChild("convert")

    def convert(self, html: str, *, base_url: str | None) -> MarkdownResult:
        try:
            from markitdown import MarkItDown, StreamInfo

            md = MarkItDown()
            stream_info = StreamInfo(
                mimetype="text/html",
                extension=".html",
                charset="utf-8",
                url=base_url or None,
            )
            result = md.convert_stream(
                io.BytesIO(html.encode("utf-8")),
                stream_info=stream_info,
                convert=list(MARKDOWN_CONVERT_TAGS),
            )
            title: str | None = result.title
            return MarkdownResult(markdown=result.markdown, title=title)
        except RecursionError as exc:
            # markitdown may hit recursion on deeply-nested HTML; the spec
            # says to log a WARNING and return plain-text fallback.
            # MarkItDown itself handles this via BeautifulSoup.get_text(),
            # so we shouldn't see it here, but guard just in case.
            self._logger.warning(
                "markitdown RecursionError, falling back to plain text",
                exc_info=True,
            )
            return MarkdownResult(markdown=html, title=None)
        except Exception as exc:
            raise ConversionError(
                f"markitdown conversion failed: {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------


def strip_images(markdown: str) -> str:
    """Remove every picture from *markdown*.

    Three shapes are handled, in this order:

    - Markdown images ``![alt](src)`` (also ``![](src)`` and
      ``![alt](src "title")``) — removed whole, ``alt`` text included.
    - Raw ``<img ...>`` markup left behind by a converter that passes HTML
      through.
    - An anchor left with an empty label (``[](url)``), the shape an
      image-only link ``[![alt](pic)](target)`` collapses into once its
      picture is gone.

    The Sanitizer removes image elements from the HTML long before this
    point, so with the default converter there is normally nothing to
    strip: this function is the *output-level* guarantee, which holds for
    every :class:`MarkdownConverter` implementation (DIP).

    The function is pure and idempotent; whitespace around a removed image
    is left as-is (collapsing it would touch indented code blocks).

    Args:
        markdown:
            Markdown text.

    Returns:
        str
            Markdown text without images.
    """
    if not markdown:
        return markdown
    out = _MD_IMAGE_RE.sub("", markdown)
    out = _RAW_IMG_RE.sub("", out)
    return _EMPTY_LINK_RE.sub("", out)


def normalize_spaces(text: str) -> str:
    """Fold Unicode no-break spaces in *text* to a regular ASCII space.

    The characters folded are ``U+00A0`` (NO-BREAK SPACE, hh.ru's ``&nbsp;``),
    ``U+202F`` (NARROW NO-BREAK SPACE, used in salary strings) and ``U+2007``
    (FIGURE SPACE).  They look like a space in a plain-text reader but are not
    one, so they break word search, line wrapping and copy-paste; the output
    carries ASCII spaces only.

    The function is pure and idempotent; it never raises.

    Args:
        text:
            Markdown or plain text.

    Returns:
        str
            *text* with every no-break space replaced by a regular space.
    """
    if not text:
        return text
    return _NO_BREAK_SPACE_RE.sub(" ", text)


def normalize_markdown(markdown: str) -> str:
    """Post-process converted Markdown before it is returned to the caller.

    - Remove every image (:func:`strip_images`).
    - Fold Unicode no-break spaces to regular spaces (:func:`normalize_spaces`).
    - Collapse runs of 3+ consecutive newlines into a single blank line
      (``\\n\\n``).
    - Rewrite bare CommonMark autolinks ``<https://...>`` into explicit
      Markdown links ``[url](url)`` (readability in plain-text viewers;
      rendering is identical).
    - Strip leading and trailing whitespace.

    The function is pure and idempotent; it never raises.

    Args:
        markdown:
            Raw Markdown text produced by the converter.

    Returns:
        str
            Normalized Markdown text.
    """
    # Images first: a removed picture may leave a blank line behind, which
    # the blank-line collapse then folds away.
    markdown = strip_images(markdown)
    markdown = normalize_spaces(markdown)
    markdown = _BLANK_LINES_RE.sub("\\n\\n", markdown).strip()
    return _ANGLED_URL_RE.sub(r"[\1](\1)", markdown)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def default_converter(logger: logging.Logger) -> MarkdownConverter:
    """Create the default :class:`MarkItDownConverter`.

    Args:
        logger:
            Logger instance.

    Returns:
        MarkdownConverter
            A new converter instance (no shared state).
    """
    return MarkItDownConverter(logger=logger)