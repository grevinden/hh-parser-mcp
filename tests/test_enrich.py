"""Unit tests for the employer-card enrichment pure functions.

All functions under test are pure (no network): the orchestrator stays
the only component with I/O (DIP).
"""

from __future__ import annotations

import pytest

from hh_mcp.fetch.enrich import (
    clean_employer_markdown,
    embed_employer_card,
    extract_company_name,
    extract_employer_ref,
    remove_internal_links,
)

# ---------------------------------------------------------------------------
# extract_employer_ref
# ---------------------------------------------------------------------------


class TestExtractEmployerRef:
    """Spec §1 — locate the employer reference in a vacancy card."""

    def test_markdown_link_basic(self) -> None:
        md = "Компания: [ООО Ромашка](https://hh.ru/employer/11620617)."
        assert extract_employer_ref(md) == ("https://hh.ru/employer/11620617", "ООО Ромашка")

    def test_markdown_link_subdomain_host(self) -> None:
        md = "[Acme](https://kolomna.hh.ru/employer/2163044)"
        assert extract_employer_ref(md) == ("https://kolomna.hh.ru/employer/2163044", "Acme")

    def test_markdown_link_with_query(self) -> None:
        md = "[Ромашка](https://hh.ru/employer/11620617?hhtmfrom=search)"
        assert extract_employer_ref(md)[0] == "https://hh.ru/employer/11620617?hhtmfrom=search"

    def test_first_internal_link_wins(self) -> None:
        md = (
            "[потенциальный](https://example.com/employer/999) "
            "на самом деле [ООО Ромашка](https://hh.ru/employer/11620617) "
            "и [ООО Восьми](https://hh.ru/employer/2163044)"
        )
        ref = extract_employer_ref(md)
        assert ref is not None
        assert ref[0] == "https://hh.ru/employer/11620617"
        assert ref[1] == "ООО Ромашка"

    def test_external_employer_url_skipped(self) -> None:
        """A /employer/ path on a non-hh.ru host is NOT a valid reference."""
        md = "[Acme](https://example.com/employer/12345)"
        assert extract_employer_ref(md) is None

    def test_external_link_then_internal_bare(self) -> None:
        md = "ср а [Acme](https://example.com/employer/1) https://hh.ru/employer/5 bare"
        assert extract_employer_ref(md) == ("https://hh.ru/employer/5", "5")

    def test_bare_url_fallback(self) -> None:
        md = "Работодатель: https://hh.ru/employer/11620617"
        assert extract_employer_ref(md) == ("https://hh.ru/employer/11620617", "11620617")

    def test_bare_url_subdomain(self) -> None:
        md = "страх https://kolomna.hh.ru/employer/2163044/"
        assert extract_employer_ref(md) == ("https://kolomna.hh.ru/employer/2163044/", "2163044")

    def test_bare_url_token_stops_at_paren(self) -> None:
        """The token stops at ``)`` — the URL itself is a valid ref."""
        assert extract_employer_ref("https://hh.ru/employer/12345)") == (
            "https://hh.ru/employer/12345",
            "12345",
        )

    def test_non_employer_paths_not_matched(self) -> None:
        """A longer ``/employer/<id>`` path segment is not an employer page."""
        md = "https://hh.ru/employer/12345/x https://hh.ru/vacancy/1"
        assert extract_employer_ref(md) is None

    def test_no_reference(self) -> None:
        assert extract_employer_ref("Просто текст без ссылок") is None

    def test_empty(self) -> None:
        assert extract_employer_ref("") is None

    def test_link_text_stripped(self) -> None:
        md = "[  Ромашка  ](https://hh.ru/employer/11620617)"
        assert extract_employer_ref(md)[1] == "Ромашка"

    def test_multiple_lines(self) -> None:
        md = "line 1\nline 2 [Company](https://hh.ru/employer/77)\nline 3"
        assert extract_employer_ref(md) == ("https://hh.ru/employer/77", "Company")

    def test_http_scheme(self) -> None:
        md = "[http](https://hh.ru/employer/11620617)"
        assert extract_employer_ref("http://hh.ru/employer/11620617") == (
            "http://hh.ru/employer/11620617",
            "11620617",
        )


# ---------------------------------------------------------------------------
# extract_company_name
# ---------------------------------------------------------------------------


class TestExtractCompanyName:
    """Spec §2 — read the company name (first non-SEO H1)."""

    def test_single_h1(self) -> None:
        md = "# Some Company\n\nText"
        assert extract_company_name(md) == "Some Company"

    def test_seo_title_then_company(self) -> None:
        """The realistic hh.ru employer-page layout: SEO H1 then company H1."""
        md = "# Работа в компании «Ромашка»\n\n# ООО Ромашка\n\nText"
        assert extract_company_name(md) == "ООО Ромашка"

    def test_seo_titles_skipped(self) -> None:
        md = "# Работа в компании X\n\n# Current vacancies at X\n\n# Company X"
        assert extract_company_name(md) == "Company X"

    def test_only_seo_h1_returns_none(self) -> None:
        md = "# Работа в компании X\n\n# Job at X"
        assert extract_company_name(md) is None

    def test_lowercase_markers_matched(self) -> None:
        md = "# работа в компании X\n\n# X\n\nТекст"
        assert extract_company_name(md) == "X"

    def test_h2_h3_ignored(self) -> None:
        md = "## Company\n\n### Name"
        assert extract_company_name(md) is None

    def test_empty_heading_text_skipped(self) -> None:
        assert extract_company_name("# \n\n# Good Name") == "Good Name"

    def test_empty_string(self) -> None:
        assert extract_company_name("") is None

    def test_indented_h1_not_matched(self) -> None:
        """The regex anchors at line start (after strip of leading ws)."""
        assert extract_company_name("  # Indented") == "Indented"

    def test_headings_after_first_non_seo_ignored(self) -> None:
        md = "# First\n\n# Second"
        assert extract_company_name(md) == "First"


# ---------------------------------------------------------------------------
# clean_employer_markdown
# ---------------------------------------------------------------------------


_FULL_EMPLOYER_MD = """# Работа в компании «Ромашка»

# ООО Ромашка

## Описание компании

Мы делаем штуки.

##링크 item

## Описание компании

Мы делаем штуки.

## Работодатель-по-местности

text

## Актуальные вакансии

### [Менеджер](https://hh.ru/vacancy/138141302)

### [Инженер](https://hh.ru/vacancy/100)
"""


class TestCleanEmployerMarkdown:
    """Spec §2 — reduce an employer page to a compact card."""

    def test_full_profile_heading_dropped(self) -> None:
        md = "# Работа в компании X\n\n# Company X\n\n## About\n\nText"
        assert clean_employer_markdown(md) == "##### About\n\nText"

    def test_all_h1s_dropped(self) -> None:
        md = "# SEO\n\n# First\n\n# Second"
        out = clean_employer_markdown(md)
        assert "First" not in out
        assert "Second" not in out
        assert "SEO" not in out

    def test_vacancies_section_cut(self) -> None:
        out = clean_employer_markdown(_FULL_EMPLOYER_MD)
        assert "Актуальные вакансии" not in out
        assert "Менеджер" not in out
        assert "Инженер" not in out

    def test_vacancies_heading_cuts_rest_including_following_headings(self) -> None:
        md = "## About\n\nText\n\n## Актуальные вакансии\n\n## Still about the company"
        out = clean_employer_markdown(md)
        assert out == "##### About\n\nText"

    def test_en_heading_marker(self) -> None:
        md = "## About\n\nBody\n\n## Current Vacancies\n\nList"
        assert clean_employer_markdown(md) == "##### About\n\nBody"

    def test_heading_promotion_levels(self) -> None:
        md = "## H2\n\n### H3\n\n#### H4\n\n##### H5\n\n###### H6"
        out = clean_employer_markdown(md)
        assert "##### H2" in out
        assert "###### H3" in out
        assert "###### H4" in out
        assert "###### H5" in out
        assert "###### H6" in out

    def test_images_dropped_whole_line(self) -> None:
        md = "## About\n\n![logo](https://hhcdn.ru/img/logo.png)\n\ntext"
        out = clean_employer_markdown(md)
        assert "logo" not in out
        assert "text" in out

    def test_inline_image_dropped_text_kept(self) -> None:
        md = "## About\n\nSee ![icon](https://hhcdn.ru/i.png) and flow."
        assert clean_employer_markdown(md) == "##### About\n\nSee  and flow."

    def test_blank_runs_squeezed(self) -> None:
        md = "## About\n\n\n\n\nBody\n\n\n\n\nEnd"
        assert clean_employer_markdown(md) == "##### About\n\nBody\n\nEnd"

    def test_truncation(self) -> None:
        md = "## About\n\n" + "x" * 3000
        out = clean_employer_markdown(md, max_chars=500)
        assert len(out) <= 500
        assert out.endswith("...")

    def test_truncation_uses_default_cap(self) -> None:
        from hh_mcp.fetch.config import EMPLOYER_MAX_CHARS

        md = "## About\n\n" + "x" * (EMPLOYER_MAX_CHARS + 500)
        out = clean_employer_markdown(md)
        assert len(out) <= EMPLOYER_MAX_CHARS

    def test_empty_input(self) -> None:
        assert clean_employer_markdown("") == ""

    def test_only_h1s_produces_empty(self) -> None:
        assert clean_employer_markdown("# SEO\n\n# Company") == ""

    def test_full_profile_keeps_description(self) -> None:
        md = "# Работа в компании «Ромашка»\n\n# ООО Ромашка\n\n## Описание\n\nМы делаем штуки."
        out = clean_employer_markdown(md)
        assert out == "##### Описание\n\nМы делаем штуки."

    def test_truncation_headline_examples(self) -> None:
        """The default cap (2_500) is respected including the suffix."""
        from hh_mcp.fetch.config import EMPLOYER_MAX_CHARS

        md = "## About\n\n" + "y" * (EMPLOYER_MAX_CHARS * 2)
        out = clean_employer_markdown(md)
        assert len(out) == EMPLOYER_MAX_CHARS
        assert out.endswith("\n...")


# ---------------------------------------------------------------------------
# embed_employer_card
# ---------------------------------------------------------------------------


class TestEmbedEmployerCard:
    """Spec §3 — splice the card under ``## About the employer: <name>``."""

    def test_basic_embed(self) -> None:
        md = "Vacancy\n\nКомпания: [Acme](https://hh.ru/employer/11620617)"
        out = embed_employer_card(md, name="Acme Inc", card_body="##### About\n\nText")
        assert "Компания: Acme Inc" in out
        assert "https://hh.ru/employer/11620617" not in out
        assert "## About the employer: Acme Inc" in out
        assert out.endswith("##### About\n\nText")

    def test_section_appended_at_end(self) -> None:
        md = "start [Acme](https://hh.ru/employer/1) end"
        out = embed_employer_card(md, name="Acme", card_body="body")
        assert out.index("## About the employer: Acme") > out.index("start")

    def test_multiple_links_all_replaced(self) -> None:
        md = (
            "[A](https://hh.ru/employer/1)\n\n"
            "and [B](https://hh.ru/employer/2)"
        )
        out = embed_employer_card(md, name="A", card_body="body")
        assert "[A](https://hh.ru/employer/1)" not in out
        assert "[B](https://hh.ru/employer/2)" not in out
        assert out.count("https://") == 0

    def test_external_link_not_replaced(self) -> None:
        md = "site [Acme](https://example.com/employer/1) here"
        out = embed_employer_card(md, name="Acme", card_body="body")
        assert "[Acme](https://example.com/employer/1)" in out

    def test_external_bare_url_embedded_by_id(self) -> None:
        """The card section is keyed on the *name*, not the link presence
        (the section is appended unconditionally in the splicing step)."""
        md = "text https://example.com/employer/1"
        out = embed_employer_card(md, name="Acme", card_body="body")
        assert "## About the employer: Acme" in out
        assert "https://example.com/employer/1" in out

    def test_trailing_text_on_same_line_kept(self) -> None:
        md = "there [Acme](https://hh.ru/employer/1) is the firm."
        out = embed_employer_card(md, name="Acme", card_body="body")
        assert out == "there Acme is the firm.\n\n## About the employer: Acme\n\nbody"

    def test_empty_card_body_no_heading(self) -> None:
        md = "text [Acme](https://hh.ru/employer/1)"
        out = embed_employer_card(md, name="Acme", card_body="")
        assert "About the employer" not in out
        assert out == "text Acme"

    def test_empty_name_falls_back_to_employer(self) -> None:
        md = "text [link](https://hh.ru/employer/1)"
        out = embed_employer_card(md, name="", card_body="body")
        assert "## About the employer: employer" in out

    def test_empty_vacancy_md(self) -> None:
        assert embed_employer_card("", name="X", card_body="body") == ""

    def test_blank_lines_around_heading_normalized(self) -> None:
        md = "x\n\n\n\n[Acme](https://hh.ru/employer/1)"
        out = embed_employer_card(md, name="Acme", card_body="body")
        # The section is appended with a single blank line after the name line.
        assert "x\n\nAcme\n\n## About the employer: Acme\n\nbody" == out


# ---------------------------------------------------------------------------
# remove_internal_links
# ---------------------------------------------------------------------------


class TestRemoveInternalLinks:
    """Spec §4 — strip every hh.ru link, keep external (incl. hhcdn.ru)."""

    def test_internal_md_link_keeps_text(self) -> None:
        md = "listed [Менеджер по продажам](https://hh.ru/vacancy/138141302)"
        assert remove_internal_links(md) == "listed Менеджер по продажам"

    def test_subdomain_internal_link(self) -> None:
        md = "[Менеджер](https://kolomna.hh.ru/vacancy/138141302)"
        assert remove_internal_links(md) == "Менеджер"

    def test_intent_jobpath_host(self) -> None:
        md = "[v](https://vacancy11620617.hh.ru/vacancy/138141302)"
        assert remove_internal_links(md) == "v"

    def test_intern_path_on_foreign_host_is_external(self) -> None:
        md = "[v](https://example.com/vacancy/12345)"
        assert remove_internal_links(md) == "[v](https://example.com/vacancy/12345)"

    def test_external_link_kept(self) -> None:
        md = "portfolio [Acme](https://acme.example/page?x=1)"
        assert remove_internal_links(md) == md

    def test_hhcdn_image_kept(self) -> None:
        md = "![logo](https://hhcdn.ru/employer/11620617/logo.png)"
        assert remove_internal_links(md) == md

    def test_internal_image_dropped(self) -> None:
        md = "before ![logo](https://hh.ru/img/x.png) after"
        assert remove_internal_links(md) == "before  after"

    def test_internal_image_dropped_subdomain(self) -> None:
        md = "![img](https://fake.hh.ru/x)"
        assert remove_internal_links(md) == ""

    def test_external_image_kept(self) -> None:
        md = "![i](https://cdn.example.com/logo.png)"
        assert remove_internal_links(md) == md

    def test_bare_internal_url_dropped(self) -> None:
        md = "ссылка https://hh.ru/employer/11620617 есть"
        assert remove_internal_links(md) == "ссылка  есть"

    def test_bare_external_url_kept(self) -> None:
        md = "go https://example.com/path?q=1 to"
        assert remove_internal_links(md) == md

    def test_autolink_brackets_removed(self) -> None:
        md = "see <https://hh.ru/vacancy/1> ok"
        out = remove_internal_links(md)
        assert "<" not in out
        assert "see  ok" in out or "see ok" in out

    def test_internal_bare_url_subdomain(self) -> None:
        md = "https://kolomna.hh.ru/employer/7"
        assert remove_internal_links(md) == ""

    def test_protocol_relative_non_internal(self) -> None:
        md = "x //example.com/path"
        assert remove_internal_links(md) == "x //example.com/path"

    def test_non_http_urls_untouched(self) -> None:
        md = "tel: +7 999 000-00-00"
        assert remove_internal_links(md) == md

    def test_idempotent(self) -> None:
        md = (
            "[a](https://hh.ru/employer/1) [b](https://example.com) ![i](https://hhcdn.ru/x.gif) "
            "https://hh.ru/vacancy/2"
        )
        once = remove_internal_links(md)
        assert remove_internal_links(once) == once

    def test_empty(self) -> None:
        assert remove_internal_links("") == ""

    def test_multiple_internal_links(self) -> None:
        md = "[a](https://hh.ru/vacancy/1) и [b](https://hh.ru/employer/2) и [c](https://hh.ru/company/3)"
        assert remove_internal_links(md) == "a и b и c"

    def test_link_text_in_heading_kept(self) -> None:
        md = "## [Компания](https://hh.ru/employer/1)\n\ntext"
        assert remove_internal_links(md) == "## Компания\n\ntext"

    def test_follows_employer_page_after_inner_link_removed(self) -> None:
        # After the inner employer link is removed, the remaining text
        # on the line stays; the scan must not re-match it as a new ref.
        md = "after https://hh.ru/employer/11620617"
        assert remove_internal_links(md) == "after"


# ---------------------------------------------------------------------------
# package-level exports (spec §8)
# ---------------------------------------------------------------------------


class TestPackageExports:
    """Spec §8 — enrich functions are exported from the package."""

    def test_exports(self) -> None:
        import hh_mcp.fetch as fetch

        for name in (
            "extract_employer_ref",
            "extract_company_name",
            "clean_employer_markdown",
            "embed_employer_card",
            "remove_internal_links",
        ):
            assert hasattr(fetch, name)
            assert name in fetch.__all__

    def test_export_is_same_object(self) -> None:
        import hh_mcp.fetch as fetch
        from hh_mcp.fetch.enrich import extract_employer_ref as direct

        assert fetch.extract_employer_ref is direct


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
