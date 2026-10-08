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
        self.upserts: int = 0

    def upsert(self, *, documents: Any) -> None:
        self.upserts += 1
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

    def test_write_logs_characters_and_bytes(self, wired: FakeIndex, caplog):
        """Russian text: the two units differ, and both are named."""
        with caplog.at_level("INFO", logger="hh_mcp.search_index"):
            index_hh_page(doc_type="vacancy", doc_id=38185674, md="я" * 100)
        # 100 Cyrillic characters weigh 200 UTF-8 bytes: both are named.
        assert "chars=100 bytes=200" in caplog.text

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

    def __init__(
        self,
        text: str,
        fetched_at: str | None,
        *,
        parts: int | None = None,
    ) -> None:
        self.id = "vacancy/38185674"
        self.content = {"text": text} if text else {}
        self.metadata = {"fetched_at": fetched_at} if fetched_at else None
        if parts is not None:
            self.metadata = {**(self.metadata or {}), "parts": parts}


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
        assert f"chars={len(MD)}" in caplog.text

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


RUSSIAN_PAGE = (
    "# Вакансия\n\n"
    + ("Требуется опыт разработки на 1С и знание SQL. " * 150)
    + "\n\n# О компании\n\n"
    + ("Мы делаем продукты для клиентов. " * 200)
)
"""A page whose bytes outnumber its characters, like every real vacancy."""


class TestSplitForStorage:
    """Upstash refuses content over 4 KiB, so a page is split, not truncated."""

    def test_short_page_is_one_part(self):
        assert search_index.split_for_storage("короткая страница") == ["короткая страница"]

    def test_empty_page_is_one_empty_part(self):
        assert search_index.split_for_storage("") == [""]

    def test_page_over_the_limit_is_split(self):
        parts = search_index.split_for_storage(RUSSIAN_PAGE)
        assert len(parts) > 1

    def test_every_part_fits_the_limit(self):
        """The whole point: no part may be refused by Upstash."""
        for part in search_index.split_for_storage(RUSSIAN_PAGE):
            assert len(part.encode()) <= search_index.MAX_DOC_BYTES

    def test_parts_reassemble_the_page(self):
        parts = search_index.split_for_storage(RUSSIAN_PAGE)
        assert "".join(parts) == RUSSIAN_PAGE

    def test_limit_is_counted_in_bytes_not_characters(self):
        """A 3 000-character Russian text is 6 000 bytes and must be split."""
        page = "я" * 3_000
        assert len(page) < search_index.MAX_DOC_BYTES
        assert len(page.encode()) > search_index.MAX_DOC_BYTES
        assert len(search_index.split_for_storage(page)) > 1

    def test_parts_are_cut_on_a_paragraph_break_when_possible(self):
        page = "первый абзац.\n\n" * 300
        assert search_index.split_for_storage(page)[0].endswith("\n\n")

    def test_custom_limit_is_honoured(self):
        assert all(
            len(part.encode()) <= 100
            for part in search_index.split_for_storage(RUSSIAN_PAGE, max_bytes=100)
        )

    def test_a_character_wider_than_the_limit_does_not_hang(self):
        """One character over budget: Upstash's error, not an infinite loop."""
        parts = search_index.split_for_storage("界" * 3, max_bytes=1)
        assert "".join(parts) == "界界界"


class TestChunkId:
    """Part 1 keeps the page id; further parts are suffixed."""

    def test_first_part_is_the_page_id(self):
        assert search_index.chunk_id("vacancy/38185674", 1) == "vacancy/38185674"

    def test_further_parts_are_suffixed(self):
        assert search_index.chunk_id("vacancy/38185674", 2) == "vacancy/38185674~2"

    def test_part_one_for_any_number(self):
        assert search_index.chunk_id("employer/1", 0) == "employer/1"


class TestSplitPagesAreIndexed:
    """A long page reaches the index as several documents."""

    def test_parts_are_written_with_their_ids(self, wired: FakeIndex):
        index_hh_page(doc_type="vacancy", doc_id=138156968, md=RUSSIAN_PAGE)
        ids = [document["id"] for document in wired.upserted]
        assert ids[0] == "vacancy/138156968"
        assert len(ids) == len(search_index.split_for_storage(RUSSIAN_PAGE))
        assert ids[1] == "vacancy/138156968~2"

    def test_every_written_part_fits_the_limit(self, wired: FakeIndex):
        index_hh_page(doc_type="vacancy", doc_id=138156968, md=RUSSIAN_PAGE)
        for document in wired.upserted:
            assert len(document["content"]["text"].encode()) <= search_index.MAX_DOC_BYTES

    def test_parts_carry_their_numbers(self, wired: FakeIndex):
        index_hh_page(doc_type="vacancy", doc_id=138156968, md=RUSSIAN_PAGE)
        metadata = [document["metadata"] for document in wired.upserted]
        assert metadata[0]["part"] == 1
        assert metadata[0]["parts"] == len(wired.upserted)
        assert metadata[1]["part"] == 2

    def test_every_part_shares_one_fetched_at(self, wired: FakeIndex):
        index_hh_page(doc_type="vacancy", doc_id=138156968, md=RUSSIAN_PAGE)
        stamps = {document["metadata"]["fetched_at"] for document in wired.upserted}
        assert len(stamps) == 1

    def test_short_page_keeps_the_minimal_metadata(self, wired: FakeIndex):
        """One part means the documented shape: fetched_at and nothing else."""
        index_hh_page(doc_type="vacancy", doc_id=38185674, md=MD)
        assert len(wired.upserted) == 1
        assert set(wired.upserted[0]["metadata"]) == {"fetched_at"}

    def test_the_split_is_logged(self, wired: FakeIndex, caplog):
        with caplog.at_level("INFO", logger="hh_mcp.search_index"):
            index_hh_page(doc_type="vacancy", doc_id=138156968, md=RUSSIAN_PAGE)
        assert "parts=" in caplog.text
        assert "vacancy/138156968" in caplog.text

    def test_all_parts_are_written_in_one_upsert(self, wired: FakeIndex):
        """A partial write would leave the index inconsistent."""
        index_hh_page(doc_type="vacancy", doc_id=138156968, md=RUSSIAN_PAGE)
        assert wired.upserts == 1

    def test_a_failing_write_is_still_remembered(self, wired: FakeIndex):
        def boom(**_kwargs):
            raise RuntimeError("content too long")

        wired.upsert = boom
        index_hh_page(doc_type="vacancy", doc_id=138156968, md=RUSSIAN_PAGE)
        assert "content too long" in search_index.last_error()


class TestSplitPagesAreNotCached:
    """A cache answer must be the whole page, not its first 4 KiB."""

    def test_split_page_is_not_served_from_the_cache(self, monkeypatch):
        monkeypatch.setenv("UPSTASH_SEARCH_REST_URL", "https://example.invalid")
        monkeypatch.setenv("UPSTASH_SEARCH_REST_TOKEN", "token")

        class Doc:
            def fetch(self, *, ids):
                return [
                    FakeDocument(
                        search_index.split_for_storage(RUSSIAN_PAGE)[0],
                        _ago(5),
                        parts=len(search_index.split_for_storage(RUSSIAN_PAGE)),
                    )
                ]

        class Client:
            def index(self, _name):
                return Doc()

        monkeypatch.setattr(search_index, "_build_client", lambda: Client())
        assert (
            search_index.read_page(doc_type="vacancy", doc_id=138156968, max_age_s=3600)
            is None
        )

    def test_the_refusal_is_logged(self, monkeypatch, caplog):
        monkeypatch.setenv("UPSTASH_SEARCH_REST_URL", "https://example.invalid")
        monkeypatch.setenv("UPSTASH_SEARCH_REST_TOKEN", "token")

        class Doc:
            def fetch(self, *, ids):
                return [FakeDocument(MD, _ago(5), parts=3)]

        class Client:
            def index(self, _name):
                return Doc()

        monkeypatch.setattr(search_index, "_build_client", lambda: Client())
        with caplog.at_level("INFO", logger="hh_mcp.search_index"):
            search_index.read_page(doc_type="vacancy", doc_id=1, max_age_s=3600)
        assert "split into 3 parts" in caplog.text

    def test_unreadable_parts_value_does_not_break_the_read(self, monkeypatch):
        """Metadata can be written by anything; a tool call must not raise."""
        monkeypatch.setenv("UPSTASH_SEARCH_REST_URL", "https://example.invalid")
        monkeypatch.setenv("UPSTASH_SEARCH_REST_TOKEN", "token")

        class Doc:
            def fetch(self, *, ids):
                return [FakeDocument(MD, _ago(5), parts="много")]

        class Client:
            def index(self, _name):
                return Doc()

        monkeypatch.setattr(search_index, "_build_client", lambda: Client())
        assert search_index.read_page(doc_type="vacancy", doc_id=1, max_age_s=3600) == MD


class TestNormalizeUrl:
    """The URL survives every way a human copies it between places."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # What a deployment's environment editor stores: no scheme.
            ("db-1.upstash.io", "https://db-1.upstash.io"),
            # What the committed .env stores: wrapped in quotes.
            ('"https://db-1.upstash.io"', "https://db-1.upstash.io"),
            ("'https://db-1.upstash.io'", "https://db-1.upstash.io"),
            # Both at once, which is what produced UnsupportedProtocol.
            ('"db-1.upstash.io"', "https://db-1.upstash.io"),
            # Quotes plus whitespace, plus a trailing slash.
            ('  "https://db-1.upstash.io/"  ', "https://db-1.upstash.io"),
            # A dropped slash, one character out.
            ("https:/db-1.upstash.io", "https://db-1.upstash.io"),
            # Already fine: unchanged.
            ("https://db-1.upstash.io", "https://db-1.upstash.io"),
            ("http://localhost:8080", "http://localhost:8080"),
            # Scheme case is normalized so the URL is canonical.
            ("HTTPS://DB-1.Upstash.IO", "https://DB-1.Upstash.IO"),
        ],
    )
    def test_produces_an_absolute_url(self, raw, expected):
        assert search_index.normalize_url(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", '""', "''"])
    def test_empty_stays_empty(self, raw):
        assert search_index.normalize_url(raw) == ""

    def test_result_is_usable_by_httpx(self):
        """The client's failure mode is a scheme-less URL — assert there is none."""
        from urllib.parse import urlsplit

        parsed = urlsplit(search_index.normalize_url("db-1.upstash.io"))
        assert parsed.scheme in {"http", "https"}
        assert parsed.netloc == "db-1.upstash.io"


class TestEndpoint:
    """``endpoint`` is the host a deployment actually writes to."""

    def test_host_only(self, monkeypatch):
        monkeypatch.setenv("UPSTASH_SEARCH_REST_URL", "https://db-1.upstash.io")
        assert search_index.endpoint() == "db-1.upstash.io"

    def test_normalized_host(self, monkeypatch):
        monkeypatch.setenv("UPSTASH_SEARCH_REST_URL", "db-1.upstash.io")
        assert search_index.endpoint() == "db-1.upstash.io"

    def test_port_is_kept(self, monkeypatch):
        monkeypatch.setenv("UPSTASH_SEARCH_REST_URL", "localhost:8080")
        assert search_index.endpoint() == "localhost:8080"

    def test_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("UPSTASH_SEARCH_REST_URL", raising=False)
        assert search_index.endpoint() is None

    def test_none_when_empty(self, monkeypatch):
        monkeypatch.setenv("UPSTASH_SEARCH_REST_URL", '""')
        assert search_index.endpoint() is None


class TestClientUsesNormalizedUrl:
    """The client must receive the repaired URL, not the raw environment value."""

    def test_scheme_is_added_before_the_request(self, monkeypatch):
        """Reproduces the deployment: no scheme in the environment variable."""
        import upstash_search

        seen: dict[str, str] = {}

        class FakeSearch:
            def __init__(self, *, url, token, **kwargs):
                seen["url"] = url
                seen["token"] = token

        monkeypatch.setenv("UPSTASH_SEARCH_REST_URL", "db-1.upstash.io")
        monkeypatch.setenv("UPSTASH_SEARCH_REST_TOKEN", "tok")
        monkeypatch.setattr(upstash_search, "Search", FakeSearch)

        client = search_index._build_client()
        assert client is not None
        assert seen["url"] == "https://db-1.upstash.io"
        assert seen["token"] == "tok"

    def test_quotes_are_stripped(self, monkeypatch):
        import upstash_search

        seen: dict[str, str] = {}

        class FakeSearch:
            def __init__(self, *, url, token, **kwargs):
                seen["url"] = url
                seen["token"] = token

        monkeypatch.setenv("UPSTASH_SEARCH_REST_URL", '"https://db-1.upstash.io"')
        monkeypatch.setenv("UPSTASH_SEARCH_REST_TOKEN", '"tok"')
        monkeypatch.setattr(upstash_search, "Search", FakeSearch)

        assert search_index._build_client() is not None
        assert seen["url"] == "https://db-1.upstash.io"
        assert seen["token"] == "tok"

    def test_a_repaired_url_is_reported(self, monkeypatch, caplog):
        """A silent repair is how this failure hid for a day."""
        import upstash_search

        class FakeSearch:
            def __init__(self, *, url, token, **kwargs):
                self.url = url

        monkeypatch.setenv("UPSTASH_SEARCH_REST_URL", "db-1.upstash.io")
        monkeypatch.setenv("UPSTASH_SEARCH_REST_TOKEN", "tok")
        monkeypatch.setattr(upstash_search, "Search", FakeSearch)

        with caplog.at_level("WARNING", logger="hh_mcp.search_index"):
            search_index._build_client()
        assert "not a plain absolute URL" in caplog.text
        assert "https://db-1.upstash.io" in caplog.text

    def test_a_plain_url_is_not_warned_about(self, monkeypatch, caplog):
        import upstash_search

        class FakeSearch:
            def __init__(self, *, url, token, **kwargs):
                self.url = url

        monkeypatch.setenv("UPSTASH_SEARCH_REST_URL", "https://db-1.upstash.io")
        monkeypatch.setenv("UPSTASH_SEARCH_REST_TOKEN", "tok")
        monkeypatch.setattr(upstash_search, "Search", FakeSearch)

        with caplog.at_level("WARNING", logger="hh_mcp.search_index"):
            search_index._build_client()
        assert "not a plain absolute URL" not in caplog.text


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