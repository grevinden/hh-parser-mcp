"""hh-mcp entry point for the native launcher.

Run from the repository root::

    uv run fastmcp run            # reads fastmcp.json (transport http, /mcp)
    uv run fastmcp dev apps fastmcp.json

The launcher imports this module and picks up :data:`mcp` (the ``entrypoint``
declared in ``fastmcp.json``). This is the composition root: it puts the source
tree on the import path, configures logging for the ``hh_mcp`` namespace and
attaches the cache layer. Layers: ``app`` (MCP surface), ``service`` (hh.ru
use-cases), ``fetch`` (network), ``cache`` (disk response cache).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# The application is run from source and is not installed as a distribution
# (``[tool.uv] package = false``), so ``src`` is not on the import path. Add it
# here, before importing the package, so the native launcher works from a plain
# checkout.
_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from hh_mcp.app import mcp
from hh_mcp.cache import attach

__all__ = ["mcp"]


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


_configure_logging()
attach(mcp)
