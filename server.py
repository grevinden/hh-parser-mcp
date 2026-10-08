"""hh-mcp server entry-point for the native launcher.

Run from the repository root::

    uv run fastmcp run          # reads fastmcp.json (transport http, /mcp)
    uv run fastmcp dev apps .   # dev preview: MCP server + browser UI

The launcher imports this module and picks up :data:`mcp` (the
``entrypoint`` declared in ``fastmcp.json``). The tools themselves live in
``hh_mcp.app``; here we only add cross-cutting middleware.

The server enables :class:`ResponseCachingMiddleware` with a **file-backed**
store (``FileTreeStore`` from ``py-key-value-aio``): repeating a tool call
with the same argument (e.g. the same vacancy id) is served from the cache
instead of hitting hh.ru again.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastmcp.server.middleware.caching import ResponseCachingMiddleware
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)

from hh_mcp.app import mcp

__all__ = ["mcp"]

# --- Response cache ---------------------------------------------------------

CACHE_DIR: Path = Path(
    os.environ.get("HH_MCP_CACHE_DIR", "~/.cache/hh-mcp")
).expanduser()
"""Directory for the file-backed response cache (override via env)."""

CACHE_TTL_S: int = 3600
"""TTL for cached tool responses (1 hour; failed calls are never cached)."""

CACHED_TOOLS: tuple[str, ...] = ("vacancy", "company")
"""Tools whose successful responses are cached (hh.ru page fetches).

``search`` is deliberately absent — its results change between pages.
"""

# The sanitization strategies below inspect the directory (max filename
# length), so it must exist before they are constructed.
CACHE_DIR.mkdir(parents=True, exist_ok=True)

cache_store = FileTreeStore(
    data_directory=CACHE_DIR,
    key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(CACHE_DIR),
    collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(
        CACHE_DIR
    ),
)

mcp.add_middleware(
    ResponseCachingMiddleware(
        cache_storage=cache_store,
        call_tool_settings={
            "ttl": CACHE_TTL_S,
            "included_tools": list(CACHED_TOOLS),
        },
    )
)