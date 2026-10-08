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

Indexing never breaks a tool call, but a swallowed failure is indistinguishable
from a healthy server that simply had nothing to index — a deployment with no
credentials looked fine while writing nothing. Failures are therefore recorded
and :func:`status` exposes them: the ``version`` tool reports the state, so a
broken backend is one call away instead of invisible.

Indexing happens only on real fetches (not on cache hits) because it's called
from :func:`hh_mcp.app._fetch_markdown` after a successful network fetch.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import PosixPath
from typing import Any

__all__ = ["configured", "document_id", "index_hh_page", "last_error", "status"]

_LAST_ERROR: str | None = None
"""Last failure seen while building the client or writing a document."""


def _remember(exc: BaseException) -> str:
    """Record *exc* as the last indexing failure and return its description.

    Parameters
    ----------
    exc:
        Exception raised by the client factory or by an Upstash request.

    Returns
    -------
    str
        ``"<ExceptionType>: <message>"`` — short, safe to show, no secrets
        because Upstash keeps the token in the environment, not in messages.
    """
    global _LAST_ERROR
    _LAST_ERROR = f"{type(exc).__name__}: {exc}"
    return _LAST_ERROR


def last_error() -> str | None:
    """Return the last indexing failure, or ``None`` if there was none.

    Returns
    -------
    str | None
        Description of the most recent client-build or write failure.
    """
    return _LAST_ERROR


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
    """Return whether indexing credentials are present in the environment.

    Returns
    -------
    bool
        ``True`` when both ``UPSTASH_SEARCH_REST_URL`` and
        ``UPSTASH_SEARCH_REST_TOKEN`` are set. Says nothing about whether the
        client library is importable or the endpoint reachable — use
        :func:`status` for that.
    """
    return bool(
        os.environ.get("UPSTASH_SEARCH_REST_URL")
        and os.environ.get("UPSTASH_SEARCH_REST_TOKEN")
    )


def _build_client():
    """Return an Upstash client, or raise.

    Returns
    -------
    upstash_search.Search
        Client built from the environment.

    Raises
    ------
    ImportError
        If ``upstash_search`` is not installed in this environment.
    RuntimeError
        If the credentials are not set.
    """
    from upstash_search import Search  # type: ignore[import-not-found]

    if not configured():
        raise RuntimeError("UPSTASH_SEARCH_REST_URL/TOKEN are not set")
    return Search.from_env()


def _client():
    """Return a client, or ``None`` when indexing is impossible.

    A failure here is recorded rather than dropped, so the ``version`` tool can
    report it.
    """
    try:
        return _build_client()
    except Exception as exc:
        _remember(exc)
        return None


def status() -> dict[str, Any]:
    """Report whether indexing can work, and why not when it cannot.

    The check is a read (``list_indexes``), not a write: it separates missing
    credentials from a missing library from an unreachable or rejecting
    endpoint without writing anything.

    Returns
    -------
    dict[str, Any]
        ``{"state": ..., "error": ...}`` where state is one of:

        - ``"missing"`` — no credentials in the environment;
        - ``"unavailable"`` — the client could not be built (import or env);
        - ``"error"`` — the endpoint refused the request (network or auth);
        - ``"ready"`` — credentials work and the endpoint answered.
    """
    if not configured():
        return {"state": "missing", "error": None}
    try:
        client = _build_client()
    except Exception as exc:
        return {"state": "unavailable", "error": _remember(exc)}
    try:
        client.list_indexes()
    except Exception as exc:
        return {"state": "error", "error": _remember(exc)}
    return {"state": "ready", "error": None}


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
    except Exception as exc:
        # Never propagate indexing errors to tool results, but keep them.
        _remember(exc)