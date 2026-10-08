"""Tests for the two cache tiers and the logging that makes them visible.

Order under test: the disk cache answers in the middleware, the search
database answers inside the tool, and only a miss in both reaches hh.ru. The
log lines matter as much as the behaviour — a silent tier is indistinguishable
from a working one, which is exactly the failure this suite was written for.
"""

from __future__ import annotations

import pytest

import hh_mcp.app as app_module
from hh_mcp.app import company, vacancy

BODY = "# Вакансия\n" + ("Тело страницы. " * 40)


class _Recorder:
    """Stand-in for ``search_index.read_page`` with a scripted answer."""

    def __init__(self, answer: str | None) -> None:
        self.answer = answer
        self.calls: list[dict[str, object]] = []

    def __call__(self, *, doc_type: str, doc_id: int, max_age_s=None) -> str | None:
        self.calls.append({"doc_type": doc_type, "doc_id": doc_id, "max_age_s": max_age_s})
        return self.answer


class TestTierOrder:
    """Disk first (middleware), then the database, then hh.ru."""

    def test_database_hit_skips_hh_ru(self, monkeypatch):
        calls: list[str] = []
        monkeypatch.setattr(app_module, "read_page", _Recorder(BODY))

        def fetch(url: str, **kwargs: object) -> str:
            calls.append(url)
            return BODY

        monkeypatch.setattr(app_module, "fetch_as_markdown", fetch)
        assert vacancy(38185674).content[0].text == BODY
        assert calls == []

    def test_database_miss_reaches_hh_ru(self, monkeypatch):
        calls: list[str] = []
        monkeypatch.setattr(app_module, "read_page", _Recorder(None))
        monkeypatch.setattr(
            app_module,
            "fetch_as_markdown",
            lambda url, **kw: calls.append(url) or BODY,
        )
        vacancy(38185674)
        assert calls == ["https://hh.ru/vacancy/38185674"]

    def test_stored_stub_is_rejected_like_a_fetched_one(self, monkeypatch):
        """A document too short to be a page must not become the answer."""
        calls: list[str] = []
        monkeypatch.setattr(app_module, "read_page", _Recorder("# HeadHunter"))
        monkeypatch.setattr(
            app_module,
            "fetch_as_markdown",
            lambda url, **kw: calls.append(url) or BODY,
        )
        vacancy(38185674)
        assert calls == ["https://hh.ru/vacancy/38185674"]

    def test_database_is_asked_with_type_and_id(self, monkeypatch):
        recorder = _Recorder(None)
        monkeypatch.setattr(app_module, "read_page", recorder)
        monkeypatch.setattr(app_module, "fetch_as_markdown", lambda url, **kw: BODY)
        company(671766)
        assert recorder.calls == [
            {"doc_type": "employer", "doc_id": 671766, "max_age_s": recorder.calls[0]["max_age_s"]}
        ]

    def test_ttl_is_applied(self, monkeypatch):
        recorder = _Recorder(None)
        monkeypatch.setattr(app_module, "read_page", recorder)
        monkeypatch.setenv("HH_MCP_SEARCH_TTL_S", "120")
        monkeypatch.setattr(app_module, "fetch_as_markdown", lambda url, **kw: BODY)
        vacancy(38185674)
        assert recorder.calls[0]["max_age_s"] == 120

    def test_database_hit_is_not_rewritten(self, monkeypatch, indexed_pages):
        """Serving from the database changes nothing, so nothing is written."""
        monkeypatch.setattr(app_module, "read_page", _Recorder(BODY))
        monkeypatch.setattr(app_module, "fetch_as_markdown", lambda url, **kw: BODY)
        vacancy(38185674)
        assert indexed_pages == []

    def test_fetch_is_written_to_the_database(self, monkeypatch, indexed_pages):
        monkeypatch.setattr(app_module, "read_page", _Recorder(None))
        monkeypatch.setattr(app_module, "fetch_as_markdown", lambda url, **kw: BODY)
        vacancy(38185674)
        assert len(indexed_pages) == 1

    def test_unfetchable_page_never_asks_the_database(self, monkeypatch):
        """Validation happens before any tier is consulted."""
        recorder = _Recorder(BODY)
        monkeypatch.setattr(app_module, "read_page", recorder)
        with pytest.raises(Exception, match="Invalid ID"):
            vacancy(0)
        assert recorder.calls == []


class TestTierLogging:
    """Each step says which tier answered, by id and size — never by content."""

    def test_database_hit_is_logged(self, monkeypatch, caplog):
        monkeypatch.setattr(app_module, "read_page", _Recorder(BODY))
        monkeypatch.setattr(app_module, "fetch_as_markdown", lambda url, **kw: BODY)
        with caplog.at_level("INFO", logger="hh_mcp.app"):
            vacancy(38185674)
        assert "page served from db tier" in caplog.text
        assert "https://hh.ru/vacancy/38185674" in caplog.text

    def test_hh_ru_fallback_is_logged(self, monkeypatch, caplog):
        monkeypatch.setattr(app_module, "read_page", _Recorder(None))
        monkeypatch.setattr(app_module, "fetch_as_markdown", lambda url, **kw: BODY)
        with caplog.at_level("INFO", logger="hh_mcp.app"):
            vacancy(38185674)
        assert "page not in db tier" in caplog.text
        assert "page fetched from hh.ru" in caplog.text
        assert "chars=" in caplog.text

    def test_page_text_is_never_logged(self, monkeypatch, caplog):
        """A vacancy description is data, not a log line."""
        monkeypatch.setattr(app_module, "read_page", _Recorder(None))
        monkeypatch.setattr(app_module, "fetch_as_markdown", lambda url, **kw: BODY)
        with caplog.at_level("DEBUG"):
            vacancy(38185674)
        assert "Тело страницы" not in caplog.text