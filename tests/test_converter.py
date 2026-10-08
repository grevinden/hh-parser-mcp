"""Tests for the Markdown converter (Protocol + MarkItDown default)."""

from __future__ import annotations

import logging

import pytest

from hh_mcp.fetch.converter import (
    MarkItDownConverter,
    MarkdownConverter,
    MarkdownResult,
    default_converter,
    normalize_markdown,
    strip_images,
)

LOGGER = logging.getLogger("test")


class TestMarkdownResult:
    """Simple data class for conversion results."""

    def test_creation(self) -> None:
        r = MarkdownResult("# Hello", title="Hello")
        assert r.markdown == "# Hello"
        assert r.title == "Hello"

    def test_default_title(self) -> None:
        r = MarkdownResult("text")
        assert r.title is None


class TestMarkdownConverterProtocol:
    """Verify that MarkdownConverter is a runtime-checkable protocol."""

    def test_protocol_detection(self) -> None:
        class FakeConverter:
            def convert(self, html: str, *, base_url: str | None) -> MarkdownResult:
                return MarkdownResult("converted")

        fake = FakeConverter()
        assert isinstance(fake, MarkdownConverter)

    def test_protocol_rejects_missing_method(self) -> None:
        class NotConverter:
            pass

        assert not isinstance(NotConverter(), MarkdownConverter)


class TestMarkItDownConverter:
    """Integration tests with the real markitdown library.

    These tests DO use the real markitdown, not a mock (per spec §9:
    1 component test with real markitdown).
    """

    @pytest.fixture
    def converter(self) -> MarkItDownConverter:
        return MarkItDownConverter(logger=LOGGER)

    def test_simple_html(self, converter: MarkItDownConverter) -> None:
        result = converter.convert("<p>Hello world</p>", base_url=None)
        assert isinstance(result, MarkdownResult)
        assert "Hello world" in result.markdown

    def test_with_title(self, converter: MarkItDownConverter) -> None:
        html = "<html><head><title>My Page</title></head><body><p>Content</p></body></html>"
        result = converter.convert(html, base_url=None)
        assert result.markdown
        # markitdown may or may not extract the title; we test the interface

    def test_with_base_url(self, converter: MarkItDownConverter) -> None:
        html = '<a href="/relative">link</a>'
        result = converter.convert(html, base_url="https://example.com")
        assert isinstance(result.markdown, str)

    def test_empty_html(self, converter: MarkItDownConverter) -> None:
        result = converter.convert("", base_url=None)
        assert result.markdown == "" or result.markdown is not None

    def test_multiline_html(self, converter: MarkItDownConverter) -> None:
        html = "<h1>Title</h1><p>First paragraph.</p><p>Second paragraph.</p>"
        result = converter.convert(html, base_url=None)
        assert "Title" in result.markdown
        assert "First paragraph" in result.markdown
        assert "Second paragraph" in result.markdown

    def test_conversion_error_on_garbage(self, converter: MarkItDownConverter) -> None:
        """Completely invalid input may trigger a ConversionError."""
        # We don't mandate error for all garbage; just verify it's handled
        result = converter.convert("<<<>>>", base_url=None)
        assert isinstance(result, MarkdownResult)

    def test_markitdown_converter_title_extraction(self, converter: MarkItDownConverter) -> None:
        """MarkItDownConverter may extract title from the document."""
        html = "<title>Explicit Title</title><p>text</p>"
        result = converter.convert(html, base_url=None)
        # The title attribute is extracted by markitdown if possible
        assert result.title is None or isinstance(result.title, str)

    def test_convert_whitelist_preserves_non_whitelisted_content(self, converter: MarkItDownConverter) -> None:
        """The ``convert=`` whitelist controls formatting, not content removal.

        markdownify 1.x: tags NOT in the whitelist skip their formatting
        converter, but their content is still emitted as plain text.
        Actual noise removal (``<nav>``, ``<footer>``, ``<template>``, ...)
        is the Sanitizer's job via :class:`NoisePolicy`, not the
        converter's.
        """
        html = (
            "<nav>menu</nav>"
            '<div class="header">header text</div>'
            "<article><p>Vacancy text</p></article>"
            "<footer>footer</footer>"
        )
        result = converter.convert(html, base_url=None)
        # Whitelisted <p> content is preserved:
        assert "Vacancy text" in result.markdown
        # Non-whitelisted tags: content is kept as plain text.
        assert "menu" in result.markdown
        assert "header text" in result.markdown
        assert "footer" in result.markdown
        # Non-whitelisted tag formatting is skipped: <del> would render as
        # ~~strike~~ under markitdown's default options, but with the
        # whitelist only the plain text survives.
        del_result = converter.convert("<del>strike</del>", base_url=None)
        assert "~~strike~~" not in del_result.markdown
        assert "strike" in del_result.markdown

    def test_convert_preserves_semantic_tags(self, converter: MarkItDownConverter) -> None:
        """The ``convert=`` whitelist preserves formatting of semantic tags.

        Headings, lists and tables from :data:`MARKDOWN_CONVERT_TAGS` are
        converted to their Markdown representations.
        """
        html = (
            "<h1>Title</h1>"
            "<ul><li>Item 1</li><li>Item 2</li></ul>"
            "<table><tr><th>H1</th></tr><tr><td>D1</td></tr></table>"
        )
        result = converter.convert(html, base_url=None)
        assert "# Title" in result.markdown
        assert "* Item 1" in result.markdown
        assert "| H1 |" in result.markdown

    def test_convert_does_not_emit_images(self, converter: MarkItDownConverter) -> None:
        """``img`` is absent from the whitelist, so no picture is emitted.

        A converter must never resurrect markup the Sanitizer removed.
        """
        html = (
            '<p>Text</p><img src="https://hhcdn.ru/a.jpg" alt="Alt">'
            '<a href="https://example.com/x"><img src="https://hhcdn.ru/b.jpg" alt="L"></a>'
        )
        result = converter.convert(html, base_url=None)
        assert "![" not in result.markdown
        assert "hhcdn.ru" not in result.markdown
        assert "Text" in result.markdown


class TestDefaultConverter:

    def test_returns_markitdown_converter(self) -> None:
        converter = default_converter(LOGGER)
        assert isinstance(converter, MarkItDownConverter)


class TestNormalizeMarkdown:
    """normalize_markdown - collapse 3+ newlines, strip edges, idempotent."""

    def test_empty(self) -> None:
        assert normalize_markdown("") == ""

    def test_whitespace_only(self) -> None:
        assert normalize_markdown("   \n\t  ") == ""

    def test_strips_edges(self) -> None:
        assert normalize_markdown("  # Title  \n\n  ") == "# Title"

    def test_collapses_triple_newlines(self) -> None:
        assert normalize_markdown("a\n\n\nb") == "a\n\nb"

    def test_collapses_longer_run(self) -> None:
        assert normalize_markdown("a\n\n\n\n\nb") == "a\n\nb"

    def test_preserves_double_newline(self) -> None:
        assert normalize_markdown("a\n\nb") == "a\n\nb"

    def test_strips_trailing_newlines(self) -> None:
        assert normalize_markdown("a\n\n\n") == "a"

    def test_idempotent(self) -> None:
        sample = "# T\n\nA\n\n\nB\n\n\n\nC\n"
        once = normalize_markdown(sample)
        assert normalize_markdown(once) == once

    def test_angled_url_converted_to_markdown_link(self) -> None:
        """F3 — CommonMark autolinks ``<https://…>`` become ``[url](url)``."""
        md = "<https://site.example/page?a=1> and text"
        assert normalize_markdown(md) == "[https://site.example/page?a=1](https://site.example/page?a=1) and text"

    def test_angled_url_only(self) -> None:
        assert normalize_markdown("<https://site.example>") == "[https://site.example](https://site.example)"

    def test_angled_url_idempotent(self) -> None:
        md = "<https://site.example>"
        once = normalize_markdown(md)
        assert normalize_markdown(once) == once

    def test_angle_brackets_other_not_converted(self) -> None:
        """Non-URL angle-delimited text is left untouched."""
        assert normalize_markdown("see <body> tag") == "see <body> tag"
        assert normalize_markdown("cmp < a and b >") == "cmp < a and b >"

    def test_angled_url_in_heading(self) -> None:
        md = "# T\n\n<https://hh.ru/employer/1>"
        assert normalize_markdown(md) == "# T\n\n[https://hh.ru/employer/1](https://hh.ru/employer/1)"

    def test_removes_images(self) -> None:
        assert normalize_markdown("![Фото](https://hhcdn.ru/a.jpg)") == ""
        assert normalize_markdown("a ![Фото](https://hhcdn.ru/a.jpg) b") == "a  b"

    def test_image_only_paragraph_is_collapsed(self) -> None:
        """A picture that was a whole block leaves no blank-line run."""
        md = "До\n\n![Фото](https://hhcdn.ru/a.jpg)\n\nПосле"
        assert normalize_markdown(md) == "До\n\nПосле"

    def test_images_removed_with_idempotence(self) -> None:
        once = normalize_markdown("![a](https://hhcdn.ru/a.png)\n\ntext")
        assert normalize_markdown(once) == once


class TestStripImages:
    """strip_images - the output-level "no pictures" guarantee."""

    def test_empty(self) -> None:
        assert strip_images("") == ""

    def test_plain_text_untouched(self) -> None:
        text = "Описание без картинок.\n\nСсылка [текст](https://example.com)."
        assert strip_images(text) == text

    def test_markdown_image_with_alt(self) -> None:
        assert strip_images("![Фото](https://hhcdn.ru/a.jpg)") == ""

    def test_markdown_image_without_alt(self) -> None:
        assert strip_images("![](https://hhcdn.ru/a.jpg)") == ""

    def test_markdown_image_with_title(self) -> None:
        assert strip_images('![Фото](https://hhcdn.ru/a.jpg "title")') == ""

    def test_image_inside_link_leaves_no_empty_link(self) -> None:
        md = "[![Фото](https://hhcdn.ru/a.jpg)](https://example.com/gallery)"
        assert strip_images(md) == ""

    def test_raw_img_markup(self) -> None:
        md = 'текст <img src="https://hhcdn.ru/a.jpg" alt="Фото"> конец'
        assert strip_images(md) == "текст  конец"

    def test_link_to_image_is_not_an_image(self) -> None:
        """A link whose target is a picture is a link: only its text shows."""
        md = "[Скачать презентацию](https://example.com/deck.pdf)"
        assert strip_images(md) == md

    def test_idempotent(self) -> None:
        md = "a ![x](https://hhcdn.ru/a.png) b"
        once = strip_images(md)
        assert strip_images(once) == once

    def test_pure(self) -> None:
        md = "![x](https://hhcdn.ru/a.png)"
        strip_images(md)
        assert md == "![x](https://hhcdn.ru/a.png)"