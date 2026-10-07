"""hh-mcp server entry-point for the native launcher.

Run from the repository root::

    uv run fastmcp run          # reads fastmcp.json (transport http, /mcp)
    uv run fastmcp dev apps .   # dev preview: MCP server + browser UI

The launcher imports this module and picks up :data:`mcp` (the
``entrypoint`` declared in ``fastmcp.json``).

``hh_mcp.app.app`` is a :class:`fastmcp.FastMCPApp` — a *Provider*, not a
server — so the canonical composition applies: build a ``FastMCP`` server
and attach the provider (gofastmcp.com/apps pattern).

The server enables :class:`ResponseCachingMiddleware` with a **file-backed**
store (``FileTreeStore`` from ``py-key-value-aio``): repeating a backend
tool call with the same argument (e.g. the same vacancy id) is served
from the cache instead of hitting hh.ru again.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.middleware.caching import ResponseCachingMiddleware
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)

from hh_mcp.app import app

__all__ = ["mcp"]

# --- Response cache ---------------------------------------------------------

CACHE_DIR: Path = Path(
    os.environ.get("HH_MCP_CACHE_DIR", "~/.cache/hh-mcp")
).expanduser()
"""Directory for the file-backed response cache (override via env)."""

CACHE_TTL_S: int = 3600
"""TTL for cached tool responses (1 hour; failed calls are never cached)."""

CACHED_TOOLS: tuple[str, ...] = ("get_vacancy", "get_employer")
"""Backend tools whose successful responses are cached (hh.ru calls)."""

# Sanitization strategies need the directory to already exist.
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_cache_store = FileTreeStore(
    data_directory=CACHE_DIR,
    key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(CACHE_DIR),
    collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(
        CACHE_DIR
    ),
)

mcp = FastMCP(app.name)
mcp.add_provider(app)
mcp.add_middleware(
    ResponseCachingMiddleware(
        cache_storage=_cache_store,
        call_tool_settings={
            "ttl": CACHE_TTL_S,
            "included_tools": list(CACHED_TOOLS),
        },
    )
)
