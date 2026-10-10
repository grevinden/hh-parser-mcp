"""The search-query guide an agent reads before calling :func:`hh_mcp.app.search`."""

from __future__ import annotations

__all__ = ["SEARCH_GUIDE_URI", "SEARCH_GUIDE_MD"]

from pathlib import Path

SEARCH_GUIDE_URI: str = "hh-mcp://search-guide"
"""MCP URI of the guide. Named in the ``search`` tool description, otherwise no agent knows the resource exists."""

SEARCH_GUIDE_MD: str = Path(__file__).with_suffix(".md").read_text()
