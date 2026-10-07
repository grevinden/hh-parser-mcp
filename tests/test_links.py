"""Tests for relative-to-absolute link resolution."""

from __future__ import annotations

from hh_mcp.fetch.links import clean_query_params, resolve_relative_links


class TestResolveRelativeLinks:
    """Spec §3.5 — idempotent link resolution using urljoin."""

    BASE = "https://example.com/sub/"

    def test_absolute_href_preserved(self) -> None:
        """Already-absolute URLs pass through unchanged."""
        html = '<a href="https://other.com/page">link</a>'
        result = resolve_relative_links(html, self.BASE)
        assert result == html

    def test_relative_href_resolved(self) -> None:
        html = '<a href="page.html">link</a>'
        result = resolve_relative_links(html, self.BASE)
        assert 'href="https://example.com/sub/page.html"' in result

    def test_relative_src_resolved(self) -> None:
        html = '<img src="img/photo.jpg">'
        result = resolve_relative_links(html, self.BASE)
        assert 'src="https://example.com/sub/img/photo.jpg"' in result

    def test_source_src_resolved(self) -> None:
        html = '<source src="video.mp4" type="video/mp4">'
        result = resolve_relative_links(html, self.BASE)
        assert 'src="https://example.com/sub/video.mp4"' in result

    def test_link_href_resolved(self) -> None:
        html = '<link href="styles.css" rel="stylesheet">'
        result = resolve_relative_links(html, self.BASE)
        assert 'href="https://example.com/sub/styles.css"' in result

    def test_multiple_links_in_document(self) -> None:
        html = (
            '<a href="a.html">A</a>\n'
            '<img src="img/b.png">\n'
            '<a href="https://other.com/c">C</a>'
        )
        result = resolve_relative_links(html, self.BASE)
        assert 'href="https://example.com/sub/a.html"' in result
        assert 'src="https://example.com/sub/img/b.png"' in result
        assert 'href="https://other.com/c"' in result
        assert result.count("https://example.com") == 2

    def test_no_url_attrs(self) -> None:
        """Tags without URL attributes are left untouched."""
        html = '<p class="intro">Hello</p><div id="main">Content</div>'
        result = resolve_relative_links(html, self.BASE)
        assert result == html

    def test_empty_base_url(self) -> None:
        html = '<a href="page.html">link</a>'
        assert resolve_relative_links(html, None) == html
        assert resolve_relative_links(html, "") == html

    def test_idempotent(self) -> None:
        """Calling twice with the same base_url produces the same output."""
        html = '<a href="page.html"><img src="img.png"></a>'
        once = resolve_relative_links(html, self.BASE)
        twice = resolve_relative_links(once, self.BASE)
        assert once == twice

    def test_protocol_relative_url(self) -> None:
        """Protocol-relative URLs (//...) are idempotent (urljoin handles them)."""
        html = '<a href="//cdn.example.com/lib.js">js</a>'
        result = resolve_relative_links(html, self.BASE)
        # urljoin keeps protocol-relative as-is
        assert "//cdn.example.com/lib.js" in result

    def test_root_relative_href(self) -> None:
        html = '<a href="/absolute/path">root</a>'
        result = resolve_relative_links(html, self.BASE)
        assert 'href="https://example.com/absolute/path"' in result

    def test_query_and_fragment(self) -> None:
        html = '<a href="page.html?q=1#section">link</a>'
        result = resolve_relative_links(html, self.BASE)
        assert result.count("https://example.com/sub/page.html?q=1#section") == 1

    def test_cyrillic_path(self) -> None:
        """Non-ASCII URL paths are handled correctly."""
        html = '<a href="страница.html">link</a>'
        result = resolve_relative_links(html, self.BASE)
        # The path is percent-encoded by urljoin or kept as-is depending
        # on the library; we just verify the link was resolved.
        assert "страница.html" in result
        assert "example.com" in result

    def test_malformed_html_structure(self) -> None:
        """Malformed HTML is parsed best-effort; no exception."""
        html = '<a href="page.html">link</a><div><p>unclosed'
        result = resolve_relative_links(html, self.BASE)
        assert isinstance(result, str)

    def test_multiple_attrs_on_same_tag(self) -> None:
        html = '<a href="page.html" class="link" id="l1">link</a>'
        result = resolve_relative_links(html, self.BASE)
        assert 'href="https://example.com/sub/page.html"' in result
        assert 'class="link"' in result
        assert 'id="l1"' in result


class TestCleanQueryParams:
    """Spec 3.5 - drop click-tracking query params (utm_*, hh.ru keys)."""

    def test_no_query_verbatim(self) -> None:
        assert clean_query_params("https://hh.ru/vacancy/1") == "https://hh.ru/vacancy/1"

    def test_no_tracking_params_verbatim(self) -> None:
        assert clean_query_params("https://hh.ru/page?q=1") == "https://hh.ru/page?q=1"

    def test_utm_removed(self) -> None:
        url = "https://hh.ru/page?utm_source=hh&utm_medium=organic&q=1"
        assert clean_query_params(url) == "https://hh.ru/page?q=1"

    def test_exact_match_keys_case_insensitive(self) -> None:
        url = "https://hh.ru/page?hhtmFrom=x&FROM=y&ref=z"
        assert clean_query_params(url) == "https://hh.ru/page"

    def test_all_removed_drops_question_mark(self) -> None:
        url = "https://hh.ru/page?aff=1&backurl=abc"
        assert clean_query_params(url) == "https://hh.ru/page"

    def test_prefix_case_insensitive(self) -> None:
        url = "https://hh.ru/page?UTM_SOURCE=x&q=1"
        assert clean_query_params(url) == "https://hh.ru/page?q=1"

    def test_non_tracking_key_kept(self) -> None:
        # form and refx (no exact / utm_ prefix match) are kept.
        url = "https://hh.ru/page?form=1&refx=2"
        assert clean_query_params(url) == "https://hh.ru/page?form=1&refx=2"

    def test_entity_escaped_reescaped(self) -> None:
        """Input is entity-escaped; the output re-escapes the & separator."""
        # The input is the raw (entity-escaped) attribute value; the
        # cleaned output must be escaped again for a double-quoted attr.
        amp = "&" "amp;"
        url = "https://hh.ru/page?utm_s=x" + amp + "q=1" + amp + "r=2"
        expected = "https://hh.ru/page?q=1" + amp + "r=2"
        assert clean_query_params(url) == expected