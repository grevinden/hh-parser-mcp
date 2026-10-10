"""Cache layer of hh-mcp.

Today this is a single tier — a file-backed response cache. See
:mod:`hh_mcp.cache.disk` for the implementation and :func:`attach` for wiring
it onto the server.
"""

import hh_mcp

# The logger must exist before ``disk`` is imported: that module reads it back
# from this package (``from hh_mcp.cache import logger``), and defining it after
# the import would leave the package partially initialized — a circular import.
logger = hh_mcp.logger.getChild("cache")

from hh_mcp.cache.disk import (
    CACHE_DIR,
    CACHE_OFF_VALUES,
    CACHE_TTL_S,
    CACHED_TOOLS,
    LoggingFileTreeStore,
    attach,
    cache_enabled,
)

__all__ = [
    "logger",
    "CACHE_DIR",
    "CACHE_OFF_VALUES",
    "CACHE_TTL_S",
    "CACHED_TOOLS",
    "LoggingFileTreeStore",
    "attach",
    "cache_enabled",
]
