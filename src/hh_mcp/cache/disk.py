"""Disk response cache: the caching layer of hh-mcp."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.middleware.caching import ResponseCachingMiddleware, CallToolSettings
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)

from hh_mcp.cache import logger

__all__ = [
    "CACHE_DIR",
    "CACHE_OFF_VALUES",
    "CACHE_TTL_S",
    "CACHED_TOOLS",
    "LoggingFileTreeStore",
    "attach",
    "cache_enabled",
]

# --- Configuration ---------------------------------------------------------

CACHE_DIR: Path = Path(
    os.environ.get("HH_MCP_CACHE_DIR", Path.home() / ".cache" / "hh-mcp")
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


# --- Store -----------------------------------------------------------------


def _approx_chars(value: Any) -> int:
    """Return a cheap size estimate for log lines, without serializing."""
    if isinstance(value, str):
        return len(value)
    if isinstance(value, Mapping):
        return sum(len(str(key)) + _approx_chars(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return sum(_approx_chars(item) for item in value)
    return len(str(value))


class LoggingFileTreeStore(FileTreeStore):
    """File-backed store that logs every read, miss and write."""

    def __init__(self, **kwargs: Any) -> None:
        """Forward keyword arguments to :class:`FileTreeStore`."""
        super().__init__(**kwargs)
        self._logger = logger

    async def get(self, key: str, **kwargs: Any) -> dict[str, Any] | None:
        """Read one entry and log whether it was there."""
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
        """Write one entry and log the write."""
        await super().put(key, value, **kwargs)
        self._logger.info(
            "disk cache write: key=%s chars=%d ttl=%s",
            key,
            _approx_chars(value),
            kwargs.get("ttl"),
        )


# --- Wiring ----------------------------------------------------------------


def cache_enabled() -> bool:
    """Return ``False`` when ``HH_MCP_CACHE`` turns the cache off."""
    raw = os.environ.get("HH_MCP_CACHE")
    if raw is None:
        return True
    return raw.strip().casefold() not in CACHE_OFF_VALUES


def attach(mcp: FastMCP) -> None:
    """Attach the disk response cache to *mcp* when it is enabled."""
    if not cache_enabled():
        logger.info(
            "response cache disabled via HH_MCP_CACHE=%s",
            os.environ.get("HH_MCP_CACHE"),
        )
        return

    # The sanitization strategies inspect the directory, so it must exist first.
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    store = LoggingFileTreeStore(
        data_directory=CACHE_DIR,
        key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(CACHE_DIR),
        collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(
            CACHE_DIR
        ),
    )

    mcp.add_middleware(
        ResponseCachingMiddleware(
            cache_storage=store,
            call_tool_settings=CallToolSettings(
                ttl=CACHE_TTL_S, included_tools=list(CACHED_TOOLS)
            ),
        )
    )
    logger.info(
        "response cache enabled: tier=disk dir=%s ttl=%ss tools=%s",
        CACHE_DIR,
        CACHE_TTL_S,
        ", ".join(CACHED_TOOLS),
    )
