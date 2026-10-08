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

The endpoint URL is normalized (:func:`normalize_url`) because a value copied
between a shell, a ``.env`` file and a deployment's environment editor loses its
scheme or arrives wrapped in quotes, and httpx then refuses it at request time —
the reason a live deployment wrote nothing while its tools kept working.

Indexing never breaks a tool call, but a swallowed failure is indistinguishable
from a healthy server that simply had nothing to index — a deployment with no
credentials looked fine while writing nothing. Failures are therefore recorded
and :func:`status` exposes them: the ``version`` tool reports the state, so a
broken backend is one call away instead of invisible.

This module is both the semantic index and the second cache tier: the same
documents are read back by id (:func:`read_page`) when a page is missing on
disk, so hh.ru is only contacted for a page neither tier knows. Every step is
logged — which tier answered, what was written, and why a document was skipped.

Indexing happens only on real fetches (not when a page came from a tier) because
it's called from :func:`hh_mcp.app._fetch_markdown` after a network fetch.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import PosixPath
from typing import Any
from urllib.parse import urlsplit

__all__ = [
    "configured",
    "document_id",
    "endpoint",
    "index_hh_page",
    "index_name",
    "last_error",
    "normalize_url",
    "read_page",
    "search_ttl_s",
    "status",
]

logger = logging.getLogger("hh_mcp.search_index")

DEFAULT_TTL_S: int = 86_400
"""How long a document may serve as a cache entry: one day (override via env)."""

_LAST_ERROR: str | None = None
"""Last failure seen while building the client or writing a document."""


def index_name() -> str:
    """Return the configured index name.

    Returns
    -------
    str
        Value of ``UPSTASH_SEARCH_INDEX``, or ``"hh_mcp"``.
    """
    return os.environ.get("UPSTASH_SEARCH_INDEX", "hh_mcp")


def search_ttl_s() -> int:
    """Return how long a stored document may answer a cache miss.

    Returns
    -------
    int
        Value of ``HH_MCP_SEARCH_TTL_S``, or :data:`DEFAULT_TTL_S`. A document
        without a readable ``fetched_at`` is treated as stale: freshness has to
        be provable, not assumed.
    """
    raw = os.environ.get("HH_MCP_SEARCH_TTL_S")
    if raw is None:
        return DEFAULT_TTL_S
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning("HH_MCP_SEARCH_TTL_S=%r is not a number, using default", raw)
        return DEFAULT_TTL_S


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


def _strip_wrapping(value: str) -> str:
    """Return *value* without whitespace or quotes wrapped around it.

    Parameters
    ----------
    value:
        Raw environment value.

    Returns
    -------
    str
        The same value with surrounding whitespace and ``"``/``'`` removed.
    """
    return value.strip().strip("\"'").strip()


def normalize_url(raw: str) -> str:
    """Return an absolute ``http(s)`` URL for the Upstash REST endpoint.

    The value reaches this process from three unrelated places — a shell
    ``export``, a ``.env`` file, and a deployment's environment-variable
    editor — and each mangles it differently. The committed ``.env`` keeps the
    URL in quotes, ``.env`` readers disagree about stripping them, and a UI
    field tends to lose the scheme. httpx accepts none of those, and the
    rejection surfaces as ``UnsupportedProtocol`` at the first request, long
    after the typo: that is how a deployment wrote nothing while every tool
    still answered. Normalizing once, here, turns that silent outage into a
    working one, and :func:`endpoint` shows what was understood.

    Parameters
    ----------
    raw:
        Value of ``UPSTASH_SEARCH_REST_URL``, in any of the shapes above.

    Returns
    -------
    str
        An absolute URL without a trailing slash, e.g.
        ``"https://db-1.upstash.io"``. Empty input yields ``""``.
    """
    value = _strip_wrapping(raw)
    if not value:
        return ""
    if "://" not in value and ":/" in value:
        # A dropped slash ("https:/host") is the same typo, one character out.
        value = value.replace(":/", "://", 1)
    scheme, separator, rest = value.partition("://")
    if separator and scheme.lower() in {"http", "https"}:
        value = f"{scheme.lower()}://{rest}"
    else:
        value = f"https://{value}"
    return value.rstrip("/")


def endpoint() -> str | None:
    """Return the Upstash host this process is configured to use.

    Returns
    -------
    str | None
        Host of the normalized endpoint URL, or ``None`` when it is unset or
        carries no host. Only the host is reported; the token stays in the
        environment.
    """
    url = normalize_url(os.environ.get("UPSTASH_SEARCH_REST_URL", ""))
    if not url:
        return None
    return urlsplit(url).netloc or None


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
    raw_url = os.environ["UPSTASH_SEARCH_REST_URL"]
    url = normalize_url(raw_url)
    if url != raw_url.strip():
        logger.warning(
            "UPSTASH_SEARCH_REST_URL is not a plain absolute URL (got %r); using %s",
            raw_url.strip(),
            url,
        )
    return Search(url=url, token=_strip_wrapping(os.environ["UPSTASH_SEARCH_REST_TOKEN"]))


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
        logger.info("db tier disabled: UPSTASH_SEARCH_REST_URL/TOKEN not set")
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
    key = document_id(doc_type, doc_id)
    client = _client()
    if client is None:
        logger.info("db tier write skipped: id=%s backend unavailable", key)
        return
    try:
        idx = client.index(index_name())
        document: dict[str, Any] = {
            "id": key,
            "content": {"text": md},
            "metadata": {"fetched_at": _fetched_at()},
        }
        idx.upsert(documents=[document])
    except Exception as exc:
        # Never propagate indexing errors to tool results, but keep them.
        logger.warning("db tier write failed: id=%s %s", key, _remember(exc))
        return
    logger.info("db cache write: id=%s bytes=%d", key, len(md))


def _age_seconds(metadata: dict[str, Any] | None) -> float | None:
    """Return the age of a stored document in seconds.

    Parameters
    ----------
    metadata:
        Document metadata, which should carry ``fetched_at``.

    Returns
    -------
    float | None
        Seconds since the document was written, or ``None`` when the timestamp
        is missing or unparsable.
    """
    raw = (metadata or {}).get("fetched_at")
    if not isinstance(raw, str):
        return None
    try:
        written = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if written.tzinfo is None:
        written = written.replace(tzinfo=UTC)
    return (datetime.now(UTC) - written).total_seconds()


def read_page(*, doc_type: str, doc_id: int, max_age_s: int | None = None) -> str | None:
    """Return a stored page, if the database can still answer for it.

    This is the second cache tier: the disk cache is checked first by the
    response-caching middleware, and only a miss here reaches hh.ru.

    Parameters
    ----------
    doc_type:
        One of ``"vacancy"`` or ``"employer"``.
    doc_id:
        Numeric identifier from hh.ru.
    max_age_s:
        Maximum age in seconds. ``None`` accepts any age; ``0`` rejects every
        document. A document whose ``fetched_at`` cannot be read counts as
        stale, so an unverifiable entry never serves a page.

    Returns
    -------
    str | None
        The Markdown page, or ``None`` when there is nothing usable.
    """
    key = document_id(doc_type, doc_id)
    client = _client()
    if client is None:
        logger.info("db cache miss: id=%s backend unavailable", key)
        return None
    try:
        documents = client.index(index_name()).fetch(ids=[key])
    except Exception as exc:
        logger.warning("db cache miss: id=%s read failed %s", key, _remember(exc))
        return None

    document = next((d for d in documents if d is not None), None)
    if document is None:
        logger.info("db cache miss: id=%s no document", key)
        return None

    text = str((document.content or {}).get("text") or "")
    if not text:
        logger.info("db cache miss: id=%s document has no text", key)
        return None

    age = _age_seconds(document.metadata)
    if age is None:
        logger.info("db cache miss: id=%s no readable fetched_at", key)
        return None
    if max_age_s is not None and age > max_age_s:
        logger.info(
            "db cache stale: id=%s age=%.0fs limit=%ss",
            key,
            age,
            max_age_s,
        )
        return None

    logger.info("db cache hit: id=%s bytes=%d age=%.0fs", key, len(text), age)
    return text