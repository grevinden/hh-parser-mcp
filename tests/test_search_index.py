"""Tests for :mod:`hh_mcp.search_index` — the Upstash Search writer.

Every test drives a fake client, so nothing here can reach the live index; the
credentials are also cleared by ``conftest.py``. What is pinned here is the
document shape: an id that identifies the page, a single ``text`` content field
for the semantic search, and nothing else.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from hh_mcp import search_index
from hh_mcp.search_index import document_id, index_hh_page

MD = "# Ведущий программист 1С\n\nОпыт с 1С, удалённо."


def _ago(seconds: float) -> str:
    """Return an ISO 8601 timestamp *seconds* in the past."""
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


class FakeIndex:
    """Stand-in for ``client.index(...)`` that records upserts."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.upserted: list[Any] = []

    def upsert(self, *, documents: Any) -> None:
        self.upserted.extend(documents)


class FakeClient:
    """Stand-in for ``upstash_search.Search``."""

    def __init__(self, index: FakeIndex, indexes: list[str] | None = None) -> None:
        self._index = index
        self._indexes = ["hh_mcp"] if indexes is None else indexes
        self.requested: list[str] = []

    def index(self, name: str) -> FakeIndex:
        self.requested.append(name)
        # Mirror the real client: the index it hands out is the named one.
        self._index.name = name
        return self._index

    def list_indexes(self) -> list[str]:
        return list(self._indexes)


@pytest.fixture
def fake_index() -> FakeIndex:
    return FakeIndex("hh_mcp")


def _wire(monkeypatch: pytest.MonkeyPatch, client) -> None:
    """Point the module at *client* with credentials present."""
    monkeypatch.setenv("UPSTASH_SEARCH_REST_URL", "https://example.invalid")
    monkeypatch.setenv("UPSTASH_SEARCH_REST_TOKEN", "token-not-real")
    monkeypatch.setattr(search_index, "_build_client", lambda: client)
    monkeypatch.setattr(search_index, "_client", lambda: client)


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch, fake_index: FakeIndex) -> FakeIndex:
    """A fake client whose index records every upsert."""
    _wire(monkeypatch, FakeClient(fake_index))
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

    def test_write_is_logged(self, wired: FakeIndex, caplog):
        with caplog.at_level("INFO", logger="hh_mcp.search_index"):
            index_hh_page(doc_type="vacancy", doc_id=38185674, md=MD)
        assert "db cache write" in caplog.text
        assert "vacancy/38185674" in caplog.text

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


class TestStatus:
    """``status()`` turns a silent failure into a readable state."""

    def test_missing_credentials(self, monkeypatch):
        monkeypatch.delenv("UPSTASH_SEARCH_REST_URL", raising=False)
        monkeypatch.delenv("UPSTASH_SEARCH_REST_TOKEN", raising=False)
        assert search_index.status() == {"state": "missing", "error": None}

    def test_ready_when_endpoint_answers(self, monkeypatch, fake_index):
        monkeypatch.setenv("UPSTASH_SEARCH_REST_URL", "https://example.invalid")
        monkeypatch.setenv("UPSTASH_SEARCH_REST_TOKEN", "token")
        monkeypatch.setattr(search_index, "_build_client", lambda: FakeClient(fake_index))
        assert search_index.status() == {"state": "ready", "error": None}

    def test_error_when_endpoint_refuses(self, monkeypatch, fake_index):
        class Refusing(FakeClient):
            def list_indexes(self):
                raise RuntimeError("401 unauthorized")

        monkeypatch.setenv("UPSTASH_SEARCH_REST_URL", "https://example.invalid")
        monkeypatch.setenv("UPSTASH_SEARCH_REST_TOKEN", "token")
        monkeypatch.setattr(
            search_index, "_build_client", lambda: Refusing(fake_index)
        )
        report = search_index.status()
        assert report["state"] == "error"
        assert "401 unauthorized" in report["error"]

    def test_unavailable_when_client_cannot_be_built(self, monkeypatch):
        def boom():
            raise ImportError("no module named upstash_search")

        monkeypatch.setenv("UPSTASH_SEARCH_REST_URL", "https://example.invalid")
        monkeypatch.setenv("UPSTASH_SEARCH_REST_TOKEN", "token")
        monkeypatch.setattr(search_index, "_build_client", boom)
        report = search_index.status()
        assert report["state"] == "unavailable"
        assert "ImportError" in report["error"]

    def test_status_writes_nothing(self, wired: FakeIndex):
        """The probe is a read: it must not create documents."""
        search_index.status()
        assert wired.upserted == []

    def test_write_failure_is_remembered(self, wired: FakeIndex):
        def boom(**_kwargs):
            raise RuntimeError("502 bad gateway")

        wired.upsert = boom
        index_hh_page(doc_type="vacancy", doc_id=1, md=MD)  # no raise
        assert "502 bad gateway" in search_index.last_error()

    def test_client_failure_is_remembered(self, monkeypatch):
        def boom():
            raise RuntimeError("no credentials in this environment")

        monkeypatch.setattr(search_index, "_build_client", boom)
        assert search_index._client() is None
        assert "no credentials" in search_index.last_error()


class TestConfigured:
    """Whether indexing can work at all, reported by the ``version`` tool."""

    def test_both_variables_present(self, monkeypatch):
        monkeypatch.setenv("UPSTASH_SEARCH_REST_URL", "https://example.invalid")
        monkeypatch.setenv("UPSTASH_SEARCH_REST_TOKEN", "token")
        assert search_index.configured() is True

    @pytest.mark.parametrize(
        "missing", ["UPSTASH_SEARCH_REST_URL", "UPSTASH_SEARCH_REST_TOKEN"]
    )
    def test_one_missing_is_not_configured(self, monkeypatch, missing):
        monkeypatch.setenv("UPSTASH_SEARCH_REST_URL", "https://example.invalid")
        monkeypatch.setenv("UPSTASH_SEARCH_REST_TOKEN", "token")
        monkeypatch.delenv(missing)
        assert search_index.configured() is False

    def test_nothing_configured(self, monkeypatch):
        monkeypatch.delenv("UPSTASH_SEARCH_REST_URL", raising=False)
        monkeypatch.delenv("UPSTASH_SEARCH_REST_TOKEN", raising=False)
        assert search_index.configured() is False


class FakeDocument:
    """Stand-in for an ``upstash_search`` document."""

    def __init__(self, text: str, fetched_at: str | None) -> None:
        self.id = "vacancy/38185674"
        self.content = {"text": text} if text else {}
        self.metadata = {"fetched_at": fetched_at} if fetched_at else None


class TestReadPage:
    """The database doubles as the second cache tier, read by id."""

    def _client_returning(self, documents):
        class Doc:
            def fetch(self, *, ids):
                return list(documents)

        class Client:
            def index(self, _name):
                return Doc()

        return Client()

    def _wire(self, monkeypatch, documents):
        monkeypatch.setenv("UPSTASH_SEARCH_REST_URL", "https://example.invalid")
        monkeypatch.setenv("UPSTASH_SEARCH_REST_TOKEN", "token")
        monkeypatch.setattr(
            search_index, "_build_client", lambda: self._client_returning(documents)
        )

    def test_fresh_document_is_returned(self, monkeypatch):
        self._wire(monkeypatch, [FakeDocument(MD, _ago(60))])
        assert search_index.read_page(doc_type="vacancy", doc_id=38185674) == MD

    def test_stale_document_is_rejected(self, monkeypatch):
        self._wire(monkeypatch, [FakeDocument(MD, _ago(10_000))])
        assert (
            search_index.read_page(doc_type="vacancy", doc_id=38185674, max_age_s=3600)
            is None
        )

    def test_missing_document_is_none(self, monkeypatch):
        self._wire(monkeypatch, [None])
        assert search_index.read_page(doc_type="vacancy", doc_id=1) is None

    def test_empty_document_is_none(self, monkeypatch):
        self._wire(monkeypatch, [FakeDocument("", _ago(10))])
        assert search_index.read_page(doc_type="vacancy", doc_id=1) is None

    def test_unreadable_timestamp_counts_as_stale(self, monkeypatch):
        """Freshness has to be provable, not assumed."""
        self._wire(monkeypatch, [FakeDocument(MD, None)])
        assert (
            search_index.read_page(doc_type="vacancy", doc_id=1, max_age_s=3600)
            is None
        )

    def test_null_in_the_middle_is_skipped(self, monkeypatch):
        self._wire(monkeypatch, [None, FakeDocument(MD, _ago(5))])
        assert search_index.read_page(doc_type="vacancy", doc_id=1) == MD

    def test_backend_unavailable_is_none(self, monkeypatch):
        monkeypatch.delenv("UPSTASH_SEARCH_REST_URL", raising=False)
        monkeypatch.delenv("UPSTASH_SEARCH_REST_TOKEN", raising=False)
        assert search_index.read_page(doc_type="vacancy", doc_id=1) is None

    def test_read_error_is_remembered_and_swallowed(self, monkeypatch):
        class Broken:
            def index(self, _name):
                raise RuntimeError("connection reset")

        monkeypatch.setenv("UPSTASH_SEARCH_REST_URL", "https://example.invalid")
        monkeypatch.setenv("UPSTASH_SEARCH_REST_TOKEN", "token")
        monkeypatch.setattr(search_index, "_build_client", lambda: Broken())
        assert search_index.read_page(doc_type="vacancy", doc_id=1) is None
        assert "connection reset" in search_index.last_error()

    def test_hit_is_logged(self, monkeypatch, caplog):
        self._wire(monkeypatch, [FakeDocument(MD, _ago(30))])
        with caplog.at_level("INFO", logger="hh_mcp.search_index"):
            search_index.read_page(doc_type="vacancy", doc_id=38185674)
        assert "db cache hit" in caplog.text
        assert "vacancy/38185674" in caplog.text

    def test_miss_is_logged(self, monkeypatch, caplog):
        self._wire(monkeypatch, [None])
        with caplog.at_level("INFO", logger="hh_mcp.search_index"):
            search_index.read_page(doc_type="vacancy", doc_id=1)
        assert "db cache miss" in caplog.text


class TestSearchTtl:
    """``HH_MCP_SEARCH_TTL_S`` decides how long a document may answer."""

    def test_default(self, monkeypatch):
        monkeypatch.delenv("HH_MCP_SEARCH_TTL_S", raising=False)
        assert search_index.search_ttl_s() == search_index.DEFAULT_TTL_S

    def test_from_environment(self, monkeypatch):
        monkeypatch.setenv("HH_MCP_SEARCH_TTL_S", "600")
        assert search_index.search_ttl_s() == 600

    def test_negative_is_clamped(self, monkeypatch):
        monkeypatch.setenv("HH_MCP_SEARCH_TTL_S", "-5")
        assert search_index.search_ttl_s() == 0

    def test_garbage_falls_back_to_default(self, monkeypatch, caplog):
        monkeypatch.setenv("HH_MCP_SEARCH_TTL_S", "soon")
        with caplog.at_level("WARNING", logger="hh_mcp.search_index"):
            assert search_index.search_ttl_s() == search_index.DEFAULT_TTL_S
        assert "not a number" in caplog.text


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