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

Cache control (environment):

``HH_MCP_CACHE=0``
    Disable the response cache entirely (the middleware is not attached).
    Every call hits hh.ru, which is what you want while iterating on the
    fetch pipeline — otherwise the same id keeps serving the stale
    Markdown (and ``tools/list`` keeps a stale tool list) for the whole TTL.
    Accepted off values: ``0``, ``off``, ``false``, ``no`` (case-insensitive).
``HH_MCP_CACHE_DIR``
    Directory for the file-backed store (default ``~/.cache/hh-mcp``).
    Remove the directory **while the server is stopped** — a live
    ``FileTreeStore`` cannot recreate it and fails writes with
    ``FileNotFoundError``.

Examples::

    uv run fastmcp run                              # cache on (default)
    HH_MCP_CACHE=0 uv run fastmcp run               # cache off
    HH_MCP_CACHE=0 uv run fastmcp dev apps fastmcp.json
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger("hh_mcp.server")

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

CACHE_OFF_VALUES: frozenset[str] = frozenset({"0", "off", "false", "no"})
"""Values of ``HH_MCP_CACHE`` that turn the response cache off."""


def cache_enabled() -> bool:
    """Return ``True`` unless ``HH_MCP_CACHE`` says otherwise.

    Returns:
        bool
            ``False`` when ``HH_MCP_CACHE`` is set to one of
            :data:`CACHE_OFF_VALUES` (case-insensitive), ``True``
            otherwise (including when the variable is unset).
    """
    raw = os.environ.get("HH_MCP_CACHE")
    if raw is None:
        return True
    return raw.strip().casefold() not in CACHE_OFF_VALUES


if cache_enabled():
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
    logger.info(
        "response cache enabled: dir=%s ttl=%ss tools=%s",
        CACHE_DIR,
        CACHE_TTL_S,
        ", ".join(CACHED_TOOLS),
    )
else:
    logger.info(
        "response cache disabled via HH_MCP_CACHE=%s",
        os.environ.get("HH_MCP_CACHE"),
    )