"""Indexing happens on real fetches — and never from a test or a cache hit.

The live Upstash index is shared production state. These tests pin both halves
of the rule: a genuine fetch indexes, and the suite itself cannot write to it
(the ``indexed_pages`` fixture from ``conftest.py`` replaces the call site, and
credentials are stripped from the environment).
"""

from __future__ import annotations

import pytest

import hh_mcp.app as app_module
from hh_mcp.app import company, vacancy


class TestToolIndexesRealFetch:
    """A successful fetch is indexed once, with type and number."""

    def test_vacancy_indexed(self, monkeypatch, indexed_pages):
        monkeypatch.setattr(
            app_module,
            "fetch_as_markdown",
            lambda url, **kw: "# Вакансия\n" + "Тело страницы. " * 40,
        )
        vacancy(38185674)
        assert len(indexed_pages) == 1
        assert indexed_pages[0]["doc_type"] == "vacancy"
        assert indexed_pages[0]["doc_id"] == 38185674
        assert "Вакансия" in indexed_pages[0]["md"]

    def test_company_indexed(self, monkeypatch, indexed_pages):
        monkeypatch.setattr(
            app_module,
            "fetch_as_markdown",
            lambda url, **kw: "# Компания\n" + "Тело страницы. " * 40,
        )
        company(671766)
        assert indexed_pages[0]["doc_type"] == "employer"
        assert indexed_pages[0]["doc_id"] == 671766

    def test_full_markdown_is_indexed(self, monkeypatch, indexed_pages):
        body = "# Вакансия\n" + "Тело страницы. " * 200
        monkeypatch.setattr(app_module, "fetch_as_markdown", lambda url, **kw: body)
        vacancy(38185674)
        assert indexed_pages[0]["md"] == body

    def test_index_argument_carries_no_url(self, monkeypatch, indexed_pages):
        """URL is derived from type and id — it is not passed to the writer."""
        monkeypatch.setattr(
            app_module,
            "fetch_as_markdown",
            lambda url, **kw: "# Вакансия\n" + "Тело страницы. " * 40,
        )
        vacancy(38185674)
        assert set(indexed_pages[0]) == {"doc_type", "doc_id", "md"}


class TestFailureIsNotIndexed:
    """A page that fails the guard never reaches the index."""

    def test_stub_page_not_indexed(self, monkeypatch, indexed_pages):
        monkeypatch.setattr(
            app_module, "fetch_as_markdown", lambda url, **kw: "# HeadHunter"
        )
        with pytest.raises(Exception):
            vacancy(137405648)
        assert indexed_pages == []

    def test_fetch_error_not_indexed(self, monkeypatch, indexed_pages):
        def boom(url, **kw):
            raise RuntimeError("network down")

        monkeypatch.setattr(app_module, "fetch_as_markdown", boom)
        with pytest.raises(Exception):
            vacancy(38185674)
        assert indexed_pages == []


class TestSuiteCannotReachLiveIndex:
    """Guards against re-introducing writes from the test suite."""

    def test_call_site_is_replaced(self):
        """The app's indexing symbol is the recorder, not the real writer."""
        from hh_mcp.search_index import index_hh_page as real_writer

        assert app_module.index_hh_page is not real_writer

    def test_credentials_are_hidden(self, monkeypatch):
        for name in ("UPSTASH_SEARCH_REST_URL", "UPSTASH_SEARCH_REST_TOKEN"):
            assert name not in monkeypatch._setitem  # nothing set by us
            import os

            assert name not in os.environ or os.environ[name] == ""