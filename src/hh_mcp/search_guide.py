"""The search-query guide an agent reads before calling :func:`hh_mcp.app.search`.

Content lives here, not in ``app.py``: it is reference text, not wiring, and
this way the MCP server layer stays a plain assembly of decorators (DIP) and
the guide can be asserted on without a client.

Source of truth: the hh.ru blog article on the search query language
(https://hh.ru/blog/lajfhaki-hh-bystryj-poisk-vakansij), plus the filters
this server applies on every call — an agent that knows both can tell an
empty result apart from a badly written query.
"""

from __future__ import annotations

__all__ = ["SEARCH_GUIDE_URI", "SEARCH_GUIDE_MD"]

from pathlib import Path

SEARCH_GUIDE_URI: str = "hh-mcp://search-guide"
"""MCP URI of the guide. Named in the ``search`` tool description, otherwise no agent knows the resource exists."""

SEARCH_GUIDE_MD: str = Path(__file__).with_suffix(".md").read_text()
