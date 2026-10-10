"""Markdown converter abstraction."""

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


#: Three or more newlines collapse into one blank line.
_BLANK_LINES_RE = re.compile(r"\n{3,}")

#: Bare autolinks ``<https://...>`` (an anchor whose text is its href) become
#: explicit ``[url](url)``.
_ANGLED_URL_RE = re.compile(r"<(https?://[^>\s]+)>")

#: Markdown image ``![alt](src)``; removed whole, ``alt`` included.
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")

#: Raw ``<img ...>`` left by a converter that passes HTML through.
_RAW_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)

#: Empty-label anchor ``[](url)``, the shape an image-only link collapses into.
_EMPTY_LINK_RE = re.compile(r"\[\s*\]\([^)]*\)")

#: Non-ASCII spaces hh.ru leans on (``U+00A0`` ``&nbsp;`` throughout every
#: description, ``U+202F`` in salaries, ``U+2007``), folded to a regular space:
#: they defeat search, wrapping and copy-paste.
_NO_BREAK_SPACE_RE = re.compile(r"[\u00a0\u2007\u202f]")


@dataclass(frozen=True, slots=True)
class MarkdownResult:
    """Result of a conversion."""

    markdown: str
    title: str | None = None


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class MarkdownConverter(Protocol):
    """Convert a clean HTML document to Markdown."""

    def convert(self, html: str, *, base_url: str | None) -> MarkdownResult:
        """Convert HTML to Markdown."""
        ...


# ---------------------------------------------------------------------------
# Default: MarkItDown
# ---------------------------------------------------------------------------


class MarkItDownConverter:
    """Default converter wrapping ``markitdown.MarkItDown``."""

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
            # Deeply nested HTML may recurse; log and fall back to plain text.
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
    """Remove every picture from *markdown*."""
    if not markdown:
        return markdown
    out = _MD_IMAGE_RE.sub("", markdown)
    out = _RAW_IMG_RE.sub("", out)
    return _EMPTY_LINK_RE.sub("", out)


def normalize_spaces(text: str) -> str:
    """Fold Unicode no-break spaces in *text* to a regular ASCII space."""
    if not text:
        return text
    return _NO_BREAK_SPACE_RE.sub(" ", text)


def normalize_markdown(markdown: str) -> str:
    """Post-process converted Markdown before it is returned to the caller."""
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
    """Create the default :class:`MarkItDownConverter`."""
    return MarkItDownConverter(logger=logger)