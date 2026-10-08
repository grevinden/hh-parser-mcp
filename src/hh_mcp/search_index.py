"""Upstash Search indexing (best-effort).

Writes hh.ru pages (vacancy/employer) to Upstash Search so they can be found
semantically later. Uses environment variables:
- ``UPSTASH_SEARCH_REST_URL``
- ``UPSTASH_SEARCH_REST_TOKEN``
- ``UPSTASH_SEARCH_INDEX`` (default: ``hh_mcp``)

A document carries only what a search needs:

- its **id** is the identity — ``vacancy/38185674`` — the path part of the hh.ru
  URL. A page is therefore found by number, an employer cannot collide with a
  vacancy of the same number, and the URL is just ``https://hh.ru/{id}``;
- its **content** is one field, ``text``, holding the Markdown the model reads.
  Upstash embeds every content field, so this *is* the semantic index;
- its **metadata** is one field, ``fetched_at`` — when the page was read from
  hh.ru. Nothing else: the type is already the first segment of the id and the
  URL is derived from the id, so a copy of either could only ever disagree.

Indexing is best-effort: any error is swallowed and never breaks tool calls.
Indexing happens only on real fetches (not on cache hits) because it's called
from :func:`hh_mcp.app._fetch_markdown` after a successful network fetch.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import PosixPath
from typing import Any

__all__ = ["configured", "document_id", "index_hh_page"]


def _fetched_at() -> str:
    """Return the current UTC timestamp in ISO 8601, for document metadata.

    Returns
    -------
    str
        e.g. ``"2026-10-08T16:20:31.482+00:00"``.
    """
    return datetime.now(UTC).isoformat()


def document_id(doc_type: str, doc_id: int) -> str:
    """Return the Upstash document id for an hh.ru page.

    The id is a POSIX path whose first segment is the page type, mirroring
    the hh.ru URL: ``vacancy/38185674`` → ``https://hh.ru/vacancy/38185674``.
    Upstash sends ids in request bodies rather than URL paths, so the separator
    is safe.

    Parameters
    ----------
    doc_type:
        One of ``"vacancy"`` or ``"employer"``.
    doc_id:
        Numeric identifier from hh.ru.

    Returns
    -------
    str
        e.g. ``"vacancy/38185674"``.
    """
    return str(PosixPath(doc_type) / str(doc_id))


def configured() -> bool:
    """Return whether semantic indexing is switched on for this process.

    Indexing is best-effort and fails silently, so a deployment with no
    credentials looks perfectly healthy while nothing is ever written. The
    ``version`` tool reports this flag to make that state visible.

    Returns
    -------
    bool
        ``True`` when both ``UPSTASH_SEARCH_REST_URL`` and
        ``UPSTASH_SEARCH_REST_TOKEN`` are set.
    """
    return bool(
        os.environ.get("UPSTASH_SEARCH_REST_URL")
        and os.environ.get("UPSTASH_SEARCH_REST_TOKEN")
    )


def _client():
    try:
        from upstash_search import Search  # type: ignore[import-not-found]

        if not configured():
            return None
        return Search.from_env()
    except Exception:
        return None


def index_hh_page(*, doc_type: str, doc_id: int, md: str) -> None:
    """Upsert a single hh.ru page into Upstash Search (best-effort).

    Parameters
    ----------
    doc_type:
        One of ``"vacancy"`` or ``"employer"``.
    doc_id:
        Numeric identifier from hh.ru.
    md:
        Full page content as Markdown returned by the fetch pipeline.
    """
    client = _client()
    if client is None:
        return
    try:
        idx = client.index(os.environ.get("UPSTASH_SEARCH_INDEX", "hh_mcp"))
        document: dict[str, Any] = {
            "id": document_id(doc_type, doc_id),
            "content": {"text": md},
            "metadata": {"fetched_at": _fetched_at()},
        }
        idx.upsert(documents=[document])
    except Exception:
        # Never propagate indexing errors to tool results
        pass