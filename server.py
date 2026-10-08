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
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastmcp.server.middleware.caching import ResponseCachingMiddleware
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)

from hh_mcp.app import mcp

__all__ = ["LoggingFileTreeStore", "mcp"]

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


def _configure_logging() -> None:
    """Send ``hh_mcp`` log records to stderr, the way fastmcp does its own.

    ``fastmcp.utilities.logging.configure_logging`` configures the ``fastmcp``
    logger only and stops propagation, so records from ``hh_mcp.*`` would reach
    a root logger with no handler and disappear — a cache decision nobody can
    see. The entry point configures logging for its own namespace and takes the
    level from the launcher's settings, so ``log_level`` in ``fastmcp.json``
    governs our lines too.
    """
    import fastmcp

    namespace = logging.getLogger("hh_mcp")
    level = getattr(fastmcp.settings, "log_level", logging.INFO)
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    namespace.setLevel(level)
    if not namespace.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        namespace.addHandler(handler)
    namespace.propagate = False


def _approx_chars(value: Any) -> int:
    """Return a cheap size estimate for log lines, without serializing.

    Parameters
    ----------
    value:
        Arbitrary nested structure — the cached response is a mapping of
        content blocks, whose payload can be tens of kilobytes.

    Returns
    -------
    int
        Sum of the string lengths of every leaf, plus mapping keys, in
        characters — the unit a log line comparing sizes must use, because the
        index write counts bytes and the two differ for Russian text.
    """
    if isinstance(value, str):
        return len(value)
    if isinstance(value, Mapping):
        return sum(len(str(key)) + _approx_chars(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return sum(_approx_chars(item) for item in value)
    return len(str(value))


class LoggingFileTreeStore(FileTreeStore):
    """File-backed store that logs every read, miss and write.

    ``ResponseCachingMiddleware`` decides *when* the store is consulted; this
    subclass only makes those decisions visible, so a log shows which tier
    answered: the disk cache here, the search database in
    :mod:`hh_mcp.search_index`, or hh.ru itself. Values are reported by size
    only — never their content, which is a whole vacancy page.
    """

    def __init__(self, *, logger: logging.Logger, **kwargs: Any) -> None:
        """Build the store and remember where to log.

        Parameters
        ----------
        logger:
            Logger to write the cache decisions to.
        **kwargs:
            Forwarded verbatim to :class:`FileTreeStore`.
        """
        super().__init__(**kwargs)
        self._logger = logger

    async def get(self, key: str, **kwargs: Any) -> dict[str, Any] | None:
        """Read one entry and log whether it was there.

        Parameters
        ----------
        key:
            Store key, as produced by the middleware.
        **kwargs:
            Forwarded verbatim to the base store.

        Returns
        -------
        dict[str, Any] | None
            The stored value, or ``None`` when the key is absent or expired.
        """
        value = await super().get(key, **kwargs)
        if value is None:
            self._logger.info("disk cache miss: key=%s", key)
        else:
            self._logger.info(
                "disk cache hit: key=%s chars=%d", key, _approx_chars(value)
            )
        return value

    async def put(
        self, key: str, value: Mapping[str, Any], **kwargs: Any
    ) -> None:
        """Write one entry and log the write.

        Parameters
        ----------
        key:
            Store key, as produced by the middleware.
        value:
            Response to store.
        **kwargs:
            Forwarded verbatim to the base store.
        """
        await super().put(key, value, **kwargs)
        self._logger.info(
            "disk cache write: key=%s chars=%d ttl=%s",
            key,
            _approx_chars(value),
            kwargs.get("ttl"),
        )


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


_configure_logging()

if cache_enabled():
    # The sanitization strategies below inspect the directory (max filename
    # length), so it must exist before they are constructed.
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    cache_store = LoggingFileTreeStore(
        logger=logger,
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
        "response cache enabled: tier=disk dir=%s ttl=%ss tools=%s",
        CACHE_DIR,
        CACHE_TTL_S,
        ", ".join(CACHED_TOOLS),
    )
else:
    logger.info(
        "response cache disabled via HH_MCP_CACHE=%s",
        os.environ.get("HH_MCP_CACHE"),
    )