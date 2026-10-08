"""Tests for the HTML sanitizer (noise removal, title extraction)."""

from __future__ import annotations

import logging

import pytest

from hh_mcp.fetch.config import default_config, default_noise_policy, NoisePolicy
from hh_mcp.fetch.html import SanitizedDocument, Sanitizer, sanitize_document

LOGGER = logging.getLogger("test")


class TestSanitizedDocument:
    """Data class for sanitization results."""

    def test_defaults(self) -> None:
        doc = SanitizedDocument()
        assert doc.html == ""
        assert doc.title is None
        assert doc.removed == 0

    def test_empty(self) -> None:
        doc = SanitizedDocument.empty()
        assert doc.html == ""
        assert doc.title is None
        assert doc.removed == 0

    def test_frozen(self) -> None:
        doc = SanitizedDocument(html="<p>hi</p>")
        with pytest.raises(AttributeError):
            doc.html = ""  # type: ignore[misc]


class TestSanitizer:
    """Spec §3.6 — noise removal, title extraction, link resolution."""

    @pytest.fixture
    def sanitizer(self) -> Sanitizer:
        return Sanitizer(noise=default_noise_policy(), logger=LOGGER)

    @pytest.fixture
    def custom_sanitizer(self) -> Sanitizer:
        noise = NoisePolicy(remove_elements=frozenset({"iframe", "noscript"}))
        return Sanitizer(noise=noise, logger=LOGGER)

    # --- Script/style removal (always) ---

    def test_script_removed(self, sanitizer: Sanitizer) -> None:
        html = "<p>hello</p><script>alert(1)</script>"
        result = sanitizer.sanitize(html)
        assert "script" not in result.html
        assert "hello" in result.html

    def test_style_removed(self, sanitizer: Sanitizer) -> None:
        html = "<p>text</p><style>body {}</style>"
        result = sanitizer.sanitize(html)
        assert "style" not in result.html
        assert "text" in result.html

    def test_nested_script_removed(self, sanitizer: Sanitizer) -> None:
        html = "<div><script>alert(1)</script><p>text</p></div>"
        result = sanitizer.sanitize(html)
        assert "script" not in result.html
        assert "text" in result.html

    # --- Noise element removal (configurable) ---

    def test_iframe_removed(self, custom_sanitizer: Sanitizer) -> None:
        html = "<p>text</p><iframe src='ad.html'></iframe>"
        result = custom_sanitizer.sanitize(html)
        assert "iframe" not in result.html

    def test_noscript_removed(self, custom_sanitizer: Sanitizer) -> None:
        html = "<p>text</p><noscript>JS off</noscript>"
        result = custom_sanitizer.sanitize(html)
        assert "noscript" not in result.html

    def test_nav_removed_via_default_noise(self, sanitizer: Sanitizer) -> None:
        """Default noise policy removes nav elements."""
        html = "<nav><ul><li>menu</li></ul></nav><p>content</p>"
        result = sanitizer.sanitize(html)
        assert "nav" not in result.html
        assert "content" in result.html

    def test_chameleon_item_company_info_address_kept(self, sanitizer: Sanitizer) -> None:
        """F1: chameleon-item is not noise — the address block survives."""
        html = (
            "<main>"
            '<div class="chameleon-item--q732_IJ2RMDA6xaH"'
            ' data-qa="company-info-address">'
            "<span>地址: 125164, г. Москва, Ленинградский пр., 69с1</span>"
            "</div>"
            "</main>"
        )
        result = sanitizer.sanitize(html)
        assert "company-info-address" in result.html
        assert "125164" in result.html

    def test_cta_vacancy_response_link_dropped(self, sanitizer: Sanitizer) -> None:
        """F2: anchors into the vacancy-response CTA are dropped with
        their text; ordinary anchors are kept."""
        html = (
            "<main>"
            '<a class="magritte-button" href="/applicant/vacancy_response'
            '?vacancyId=138156968">Откликнуться</a>'
            '<a class="vacancy-link" href="/vacancy/138156968">Карточка</a>'
            "</main>"
        )
        result = sanitizer.sanitize(html)
        assert "vacancy_response" not in result.html
        assert "Откликнуться" not in result.html
        assert "/vacancy/138156968" in result.html
        assert "Карточка" in result.html

    def test_data_qa_noise_separator_dropped(self, sanitizer: Sanitizer) -> None:
        """F5: the reviews-badges separator element is dropped."""
        html = (
            "<main>"
            '<div data-qa="employer-page-reviews-badges-separator">·</div>'
            '<div data-qa="company-info-site">https://site.example</div>'
            "</main>"
        )
        result = sanitizer.sanitize(html)
        assert "badges-separator" not in result.html
        assert "·" not in result.html
        assert "company-info-site" in result.html

    def test_employer_fact_card_dropped(self, sanitizer: Sanitizer) -> None:
        """The employer-page right column (fact cells) is dropped whole.

        ``data-qa="employer-page-company-info"`` wraps the "Город" /
        "Сферы деятельности" / "Тип регистрации" cells; without it they
        survive as the glued text "МоскваГородЛесная промышленность…".
        The company description (``div.g-user-content``) must survive.
        """
        html = (
            "<main>"
            '<div data-qa="employer-view-widget-description">'
            '<div class="g-user-content">Описание компании</div>'
            "</div>"
            '<div data-qa="employer-page-company-info">'
            '<div data-qa="company-info-address">'
            '<span data-qa="cell-text-content">Москва</span>'
            '<span data-qa="cell-text-content">Город</span>'
            "</div>"
            '<div data-qa="company-info-industries">'
            '<span data-qa="cell-text-content">Лесная промышленность</span>'
            '<span data-qa="cell-text-content">Сферы деятельности</span>'
            "</div>"
            "</div>"
            "</main>"
        )
        result = sanitizer.sanitize(html)
        assert "employer-page-company-info" not in result.html
        assert "company-info-address" not in result.html
        assert "Город" not in result.html
        assert "Сферы деятельности" not in result.html
        assert "Лесная промышленность" not in result.html
        # The description is content, not noise.
        assert "Описание компании" in result.html

    def test_sidebar_company_site_kept(self, sanitizer: Sanitizer) -> None:
        """The employer's website card is content: the link survives.

        The caption span is a fact-cell label handled by the orphan rule
        (:func:`test_orphan_fact_caption_dropped`), but the URL itself
        must stay in the output — callers want the employer's website.
        """
        html = (
            "<main>"
            '<div data-qa="sidebar-company-site">'
            '<a href="https://example.ru">https://example.ru</a>'
            '<span data-qa="cell-text-content">Сайт</span>'
            "</div>"
            "<p>Описание</p>"
            "</main>"
        )
        result = sanitizer.sanitize(html)
        assert "https://example.ru" in result.html
        assert "Описание" in result.html

    def test_competitor_companies_widget_dropped(self, sanitizer: Sanitizer) -> None:
        """The "Ещё компании для вас" widget is dropped whole.

        Its cards only carry an employer link, so keeping them would yield
        the label noise "Посмотреть13 активных вакансий" once
        ``remove_internal_links`` strips the URL.
        """
        html = (
            "<main>"
            '<div data-qa="competitor-companies-title">Еще компании для вас</div>'
            '<div data-qa="competitor-companies-hint-activator">ⓘ</div>'
            '<div data-qa="branded-employer-gallery">'
            '<div class="branded-employers-wizard-gallery-card">'
            '<div class="branded-employers-wizard-company-name">BAON</div>'
            "13 активных вакансий"
            '<a href="https://hh.ru/employer/1014">Посмотреть</a>'
            "</div>"
            "</div>"
            "<p>Описание</p>"
            "</main>"
        )
        result = sanitizer.sanitize(html)
        assert "competitor-companies-title" not in result.html
        assert "competitor-companies-hint-activator" not in result.html
        assert "branded-employer-gallery" not in result.html
        assert "Посмотреть" not in result.html
        assert "активных вакансий" not in result.html
        assert "Описание" in result.html

    def test_removed_count(self, custom_sanitizer: Sanitizer) -> None:
        html = "<p>ok</p><iframe src='a'></iframe><div><iframe src='b'></iframe></div>"
        result = custom_sanitizer.sanitize(html)
        assert result.removed >= 1  # top-level iframe
        assert "ok" in result.html

    def test_orphan_fact_caption_dropped(self, sanitizer: Sanitizer) -> None:
        """A fact caption that outlives its card ("Сайт" inside the
        description widget) is dropped instead of dangling in the output."""
        html = (
            "<main>"
            '<div data-qa="employer-view-widget-description">'
            '<div class="g-user-content">Описание компании</div>'
            '<div data-qa="cell">'
            '<div data-qa="cell-left-side"></div>'
            '<div data-qa="cell-text">'
            '<span data-qa="cell-text-content">Сайт</span>'
            "</div>"
            "</div>"
            "</div>"
            "</main>"
        )
        result = sanitizer.sanitize(html)
        assert "Сайт" not in result.html
        assert "cell-text-content" not in result.html
        assert "Описание компании" in result.html

    def test_fact_cell_value_kept(self, sanitizer: Sanitizer) -> None:
        """Fact *values* survive (only captions are orphans), even when the
        cell wraps its text in another tag."""
        html = (
            "<main>"
            '<div data-qa="cell-text">'
            '<span data-qa="cell-text-content"><div>Москва</div></span>'
            "</div>"
            '<div data-qa="cell-text">'
            '<span data-qa="cell-text-content">Республика Татарстан</span>'
            "</div>"
            "</main>"
        )
        result = sanitizer.sanitize(html)
        assert "Москва" in result.html
        assert "Республика Татарстан" in result.html
        # The nested markup is normalised to a flat span.
        assert "<div>Москва</div>" not in result.html

    # --- Main-block extraction (default noise policy) ---

    def test_main_extraction_keeps_only_main(self, sanitizer: Sanitizer) -> None:
        """Pre-main (header/nav) and post-main (footer) content is dropped."""
        html = (
            "<header>site menu</header>"
            "<nav>navigation</nav>"
            "<main><h1>vacancy title</h1><p>description text</p></main>"
            "<footer>site footer</footer>"
        )
        result = sanitizer.sanitize(html)
        assert "vacancy title" in result.html
        assert "description text" in result.html
        assert "site menu" not in result.html
        assert "navigation" not in result.html
        assert "site footer" not in result.html
        assert "<nav>" not in result.html

    def test_main_extraction_no_main_lenient(self, sanitizer: Sanitizer) -> None:
        """Documents without <main> pass through unchanged (lenient)."""
        html = "<html><head></head><body><p>before</p><p>after</p></body></html>"
        result = sanitizer.sanitize(html)
        assert "before" in result.html
        assert "after" in result.html

    def test_main_extraction_disabled(self) -> None:
        """main_extraction=False keeps the whole document (minus noise)."""
        noise = NoisePolicy(main_extraction=False)
        sanitizer = Sanitizer(noise=noise, logger=LOGGER)
        html = "<body><header>menu</header><p>content</p></body>"
        result = sanitizer.sanitize(html)
        # <header> is still noise (remove_elements), but <body> content
        # outside a <main> is now preserved.
        assert "content" in result.html
        assert "menu" not in result.html

    def test_second_main_ignored(self, sanitizer: Sanitizer) -> None:
        """The first <main> wins: once </main> is seen the state machine
        goes to ``post``, so a second <main> block and any content after
        the first main is dropped."""
        html = (
            "<main><p>first block</p></main>"
            "<main><p>second block</p></main>"
            "<p>after all mains</p>"
        )
        result = sanitizer.sanitize(html)
        assert "first block" in result.html
        assert "second block" not in result.html
        assert "after all mains" not in result.html

    def test_main_inside_noise_ignored(self, sanitizer: Sanitizer) -> None:
        """A <main> nested in a noise subtree is not the extraction anchor."""
        html = (
            "<div class='hidden'><main><p>fake content</p></main></div>"
            "<main><p>real content</p></main>"
        )
        result = sanitizer.sanitize(html)
        assert "fake content" not in result.html
        assert "real content" in result.html

    # --- Element reconstruction edge cases ---

    def test_img_without_src_dropped(self, sanitizer: Sanitizer) -> None:
        """Contentless <img> (React CSS sprites) is dropped; the
        surrounding <a href> keeps the target URL."""
        html = '<div><img class="icon"><a href="https://x.ru/">link</a></div>'
        result = sanitizer.sanitize(html)
        assert "<img" not in result.html
        assert 'href="https://x.ru/"' in result.html

    def test_img_with_src_dropped(self, sanitizer: Sanitizer) -> None:
        """A picture is never content: both markup shapes go away.

        hh.ru emits the same ``<img>`` in HTML5 form (``<img src=...>``)
        and XHTML form (``<img src=... />``); both must disappear.
        """
        html = (
            '<div class="keeper"><img src="logo.png" alt="Logo"></div>'
            '<div class="keeper"><img src="photo.jpg" alt="Photo" />'
        )
        result = sanitizer.sanitize(html)
        assert "<img" not in result.html
        assert "logo.png" not in result.html
        assert "photo.jpg" not in result.html

    def test_img_alt_text_does_not_leak(self, sanitizer: Sanitizer) -> None:
        """The alt text dies with the tag.

        It is an attribute, so keeping the picture would mean leaving a
        caption for something the reader cannot see.
        """
        html = (
            "<main><p>До</p>"
            '<img src="https://hhcdn.ru/i.png" alt="Мужчина и женщина">'
            "<p>После</p></main>"
        )
        result = sanitizer.sanitize(html)
        assert "Мужчина и женщина" not in result.html
        assert "До" in result.html
        assert "После" in result.html

    def test_picture_and_source_dropped(self, sanitizer: Sanitizer) -> None:
        """``<picture>``/``<source>`` only ever hold one more variant of
        the same picture, so they are noise as well."""
        html = (
            "<main><p>До</p>"
            '<picture><source srcset="https://hhcdn.ru/a.webp" type="image/webp">'
            '<img src="https://hhcdn.ru/a.jpg" alt="A"></picture>'
            "<p>После</p></main>"
        )
        result = sanitizer.sanitize(html)
        assert "<picture" not in result.html
        assert "<source" not in result.html
        assert "hhcdn.ru" not in result.html
        assert "До" in result.html
        assert "После" in result.html

    def test_img_inside_anchor_keeps_anchor(self, sanitizer: Sanitizer) -> None:
        """A picture wrapped in a link leaves the link, not an empty one."""
        html = (
            "<main>"
            '<a href="https://example.com/gallery">'
            '<img src="https://hhcdn.ru/a.jpg" alt="Фото">'
            "</a>"
            "</main>"
        )
        result = sanitizer.sanitize(html)
        assert "<img" not in result.html
        assert 'href="https://example.com/gallery"' in result.html

    def test_void_noise_does_not_silence_the_rest(self, sanitizer: Sanitizer) -> None:
        """Regression: a void noise element must not be pushed on the
        suppression stack.

        ``<img>``/``<input>`` are noise *and* void — they have no end tag,
        so a pushed entry would never be popped and would swallow
        everything that follows.
        """
        html = (
            "<main><p>before</p>"
            '<form data-qa="auth-form"><input name="login"></form>'
            "<p>after form</p>"
            '<img src="https://hhcdn.ru/a.jpg" alt="A">'
            "<p>after image</p>"
            "</main>"
        )
        result = sanitizer.sanitize(html)
        assert "<img" not in result.html
        assert "<input" not in result.html
        assert "before" in result.html
        assert "after form" in result.html
        assert "after image" in result.html

    def test_self_close_tag_reconstructed(self, sanitizer: Sanitizer) -> None:
        html = "<p>line one<br/>line two</p>"
        result = sanitizer.sanitize(html)
        assert "<br/>" in result.html

    def test_attr_values_escaped(self, sanitizer: Sanitizer) -> None:
        """Ampersands in attribute values are escaped on reconstruction."""
        html = '<div data-note="a & b">x</div>'
        result = sanitizer.sanitize(html)
        # _escape_attr: & -> & (entity assembled via adjacent literals).
        expected = 'data-note="a &' + "amp; b\""
        assert expected in result.html

    def test_tracking_params_cleaned_end_to_end(self, sanitizer: Sanitizer) -> None:
        """sanitize(base_url=...) drops utm_* params from resolved links."""
        html = '<a href="/vacancy/123?utm_source=hh&ref=x">work</a>'
        result = sanitizer.sanitize(html, base_url="https://hh.ru")
        assert "utm_source" not in result.html
        assert "https://hh.ru/vacancy/123" in result.html

    # --- Title extraction ---

    def test_title_extracted(self, sanitizer: Sanitizer) -> None:
        html = "<html><head><title>My Page</title></head><body><p>hello</p></body></html>"
        result = sanitizer.sanitize(html)
        assert result.title == "My Page"

    def test_title_stripped(self, sanitizer: Sanitizer) -> None:
        html = "<title>  Spaced Title  </title>"
        result = sanitizer.sanitize(html)
        assert result.title == "Spaced Title"

    def test_title_not_present(self, sanitizer: Sanitizer) -> None:
        html = "<html><body><p>hello</p></body></html>"
        result = sanitizer.sanitize(html)
        assert result.title is None

    def test_title_content_in_html_removed(self, sanitizer: Sanitizer) -> None:
        """The <title> tag itself should not appear in the cleaned HTML."""
        html = "<title>Title</title><p>body</p>"
        result = sanitizer.sanitize(html)
        assert "title" not in result.html
        assert "Title" not in result.html
        assert "body" in result.html

    def test_first_title_only(self, sanitizer: Sanitizer) -> None:
        """Only the first <title> is captured; subsequent ones are ignored."""
        html = "<title>First</title><title>Second</title>"
        result = sanitizer.sanitize(html)
        assert result.title == "First"

    # --- Comment and DOCTYPE suppression ---

    def test_comments_suppressed(self, sanitizer: Sanitizer) -> None:
        html = "<p>text</p><!-- comment --><p>more</p>"
        result = sanitizer.sanitize(html)
        assert "comment" not in result.html
        assert "<!--" not in result.html

    def test_doctype_suppressed(self, sanitizer: Sanitizer) -> None:
        html = "<!DOCTYPE html><html><p>hello</p></html>"
        result = sanitizer.sanitize(html)
        assert "DOCTYPE" not in result.html

    # --- Link resolution via base_url ---

    def test_links_resolved(self, sanitizer: Sanitizer) -> None:
        html = '<a href="/page">link</a>'
        result = sanitizer.sanitize(html, base_url="https://example.com")
        assert "/page" not in result.html or "https://example.com/page" in result.html

    # --- Lenient parsing ---

    def test_malformed_html(self, sanitizer: Sanitizer) -> None:
        """Malformed HTML never raises; best-effort pass-through."""
        html = "<<<unparseable>>>"
        result = sanitizer.sanitize(html)
        assert isinstance(result, SanitizedDocument)
        # Should at least not crash

    def test_empty_html(self, sanitizer: Sanitizer) -> None:
        result = sanitizer.sanitize("")
        assert result.html == ""
        assert result.title is None
        assert result.removed == 0

    def test_large_html(self, sanitizer: Sanitizer) -> None:
        """Large documents should not cause memory issues."""
        html = "<p>" + "hello world " * 10000 + "</p>"
        result = sanitizer.sanitize(html)
        assert len(result.html) > 0

    def test_script_with_html_inside(self, sanitizer: Sanitizer) -> None:
        """HTML inside script tags (treated as raw text by html.parser)."""
        html = "<script>var x = '<div>html</div>';</script><p>ok</p>"
        result = sanitizer.sanitize(html)
        assert "script" not in result.html
        assert "ok" in result.html


class TestSanitizeDocument:
    """Convenience function."""

    def test_basic(self) -> None:
        config = default_config()
        result = sanitize_document(
            "<title>Test</title>", base_url=None, config=config, logger=LOGGER
        )
        assert result.title == "Test"