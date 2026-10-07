"""Upstash Search indexing (best-effort).

Writes hh.ru pages (vacancy/employer) to Upstash Search so they can be
found semantically later. Uses environment variables:
- ``UPSTASH_SEARCH_REST_URL``
- ``UPSTASH_SEARCH_REST_TOKEN``
- ``UPSTASH_SEARCH_INDEX`` (default: ``hh_mcp``)

Indexing is best-effort: any error is swallowed and never breaks tool calls.
Indexing happens only on real fetches (not on cache hits) because it's called
from :func:`hh_mcp.app._fetch_markdown` after a successful network fetch.
"""

from __future__ import annotations

import os
import re
from typing import Any

__all__ = ["extract_title", "index_hh_page"]

TITLE_RE = re.compile(r"^#\s+(.*)$", re.M)


def extract_title(md: str) -> str | None:
    """Extract the first Markdown H1 title from *md* if present."""
    m = TITLE_RE.search(md)
    if m:
        return m.group(1).strip()[:200]
    return None


def _client():
    try:
        from upstash_search import Search  # type: ignore[import-not-found]

        url = os.environ.get("UPSTASH_SEARCH_REST_URL")
        token = os.environ.get("UPSTASH_SEARCH_REST_TOKEN")
        if not url or not token:
            return None
        return Search.from_env()
    except Exception:
        return None


def index_hh_page(*, doc_type: str, doc_id: int, url: str, md: str) -> None:
    """Upsert a single hh.ru page into Upstash Search (best-effort).

    Parameters
    ----------
    doc_type:
        One of ``"vacancy"`` or ``"employer"``.
    doc_id:
        Numeric identifier from hh.ru.
    url:
        Canonical page URL.
    md:
        Full page content as Markdown returned by the fetch pipeline.
    """
    client = _client()
    if client is None:
        return
    try:
        idx_name = os.environ.get("UPSTASH_SEARCH_INDEX", "hh_mcp")
        idx = client.index(idx_name)
        title = extract_title(md)
        content: dict[str, Any] = {"text": md, "type": doc_type}
        if title:
            content["title"] = title
        idx.upsert(
            documents=[
                {
                    "id": f"{doc_type}:{doc_id}",
                    "content": content,
                    "metadata": {
                        "id": str(doc_id),
                        "url": url,
                        "source": "hh.ru",
                        "type": doc_type,
                    },
                }
            ]
        )
    except Exception:
        # Never propagate indexing errors to tool results
        pass
