"""Tests for :mod:`hh_mcp.search_index` — the Upstash Search writer.

Every test drives a fake client, so nothing here can reach the live index; the
credentials are also cleared by ``conftest.py``. What is pinned here is the
document shape: an id that identifies the page, a single ``text`` content field
for the semantic search, and nothing else.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from hh_mcp import search_index
from hh_mcp.search_index import document_id, index_hh_page

MD = "# Ведущий программист 1С\n\nОпыт с 1С, удалённо."


class FakeIndex:
    """Stand-in for ``client.index(...)`` that records upserts."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.upserted: list[Any] = []

    def upsert(self, *, documents: Any) -> None:
        self.upserted.extend(documents)


class FakeClient:
    """Stand-in for ``upstash_search.Search``."""

    def __init__(self, index: FakeIndex) -> None:
        self._index = index
        self.requested: list[str] = []

    def index(self, name: str) -> FakeIndex:
        self.requested.append(name)
        # Mirror the real client: the index it hands out is the named one.
        self._index.name = name
        return self._index


@pytest.fixture
def fake_index() -> FakeIndex:
    return FakeIndex("hh_mcp")


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch, fake_index: FakeIndex) -> FakeIndex:
    """Point the module at a fake client with credentials present."""
    client = FakeClient(fake_index)
    monkeypatch.setenv("UPSTASH_SEARCH_REST_URL", "https://example.invalid")
    monkeypatch.setenv("UPSTASH_SEARCH_REST_TOKEN", "token-not-real")
    monkeypatch.setattr(search_index, "_client", lambda: client)
    return fake_index


class TestDocumentId:
    """The id is the path part of the hh.ru URL: type / number."""

    @pytest.mark.parametrize(
        ("doc_type", "doc_id", "expected"),
        [
            ("vacancy", 38185674, "vacancy/38185674"),
            ("employer", 671766, "employer/671766"),
        ],
    )
    def test_posix_path_by_type(self, doc_type, doc_id, expected):
        assert document_id(doc_type, doc_id) == expected

    def test_same_number_different_pages(self):
        """A vacancy and an employer can share a number without colliding."""
        assert document_id("vacancy", 42) != document_id("employer", 42)

    def test_id_completes_the_url(self):
        """https://hh.ru + id is the canonical page — nothing else to store."""
        assert f"https://hh.ru/{document_id('vacancy', 38185674)}" == (
            "https://hh.ru/vacancy/38185674"
        )


class TestDocumentShape:
    """Content is the text; metadata carries only the fetch timestamp."""

    def test_writes_single_document(self, wired: FakeIndex):
        index_hh_page(doc_type="vacancy", doc_id=38185674, md=MD)
        assert len(wired.upserted) == 1

    def test_id_is_the_url_path(self, wired: FakeIndex):
        index_hh_page(doc_type="vacancy", doc_id=38185674, md=MD)
        assert wired.upserted[0]["id"] == "vacancy/38185674"

    def test_content_is_only_the_text(self, wired: FakeIndex):
        index_hh_page(doc_type="vacancy", doc_id=38185674, md=MD)
        assert wired.upserted[0]["content"] == {"text": MD}

    def test_metadata_is_only_the_timestamp(self, wired: FakeIndex):
        index_hh_page(doc_type="vacancy", doc_id=38185674, md=MD)
        assert set(wired.upserted[0]["metadata"]) == {"fetched_at"}

    def test_no_url_or_source_or_type_duplicates(self, wired: FakeIndex):
        """Type is the id's first segment and the URL is derived from it."""
        index_hh_page(doc_type="employer", doc_id=671766, md=MD)
        blob = str(wired.upserted[0])
        assert "http" not in blob
        assert "source" not in blob
        assert "'type'" not in blob

    def test_timestamp_is_iso_utc(self, wired: FakeIndex):
        index_hh_page(doc_type="vacancy", doc_id=38185674, md=MD)
        stamp = wired.upserted[0]["metadata"]["fetched_at"]
        parsed = datetime.fromisoformat(stamp)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 0

    def test_index_name_from_environment(self, monkeypatch, wired: FakeIndex):
        monkeypatch.setenv("UPSTASH_SEARCH_INDEX", "custom_index")
        index_hh_page(doc_type="vacancy", doc_id=1, md=MD)
        assert wired.name == "custom_index"

    def test_upsert_replaces_previous_document(self, wired: FakeIndex):
        """Same id twice = one document with the newer text, not two rows."""
        index_hh_page(doc_type="vacancy", doc_id=38185674, md=MD)
        index_hh_page(doc_type="vacancy", doc_id=38185674, md=MD + " Обновлено.")
        ids = [d["id"] for d in wired.upserted]
        assert ids == ["vacancy/38185674", "vacancy/38185674"]


class TestBestEffort:
    """Indexing never breaks a tool call."""

    def test_no_credentials_writes_nothing(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("UPSTASH_SEARCH_REST_URL", raising=False)
        monkeypatch.delenv("UPSTASH_SEARCH_REST_TOKEN", raising=False)
        assert search_index._client() is None
        index_hh_page(doc_type="vacancy", doc_id=38185674, md=MD)  # no raise

    def test_upsert_error_is_swallowed(self, monkeypatch: pytest.MonkeyPatch):
        class Boom:
            def index(self, _name: str) -> Any:
                raise RuntimeError("upstash is down")

        monkeypatch.setattr(search_index, "_client", lambda: Boom())
        index_hh_page(doc_type="vacancy", doc_id=38185674, md=MD)  # no raise

    def test_missing_dependency_is_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setitem(
            __import__("sys").modules, "upstash_search", None
        )
        assert search_index._client() is None