"""hh-mcp server entry-point for the native launcher.

Run from the repository root::

    uv run fastmcp run          # reads fastmcp.json (transport http, /mcp)
    uv run fastmcp dev apps .   # dev preview: MCP server + browser UI

The launcher imports this module and picks up :data:`mcp` (the
``entrypoint`` declared in ``fastmcp.json``).

``hh_mcp.app.app`` is a :class:`fastmcp.FastMCPApp` — a *Provider*, not a
server — so the canonical composition applies: build a ``FastMCP`` server
and attach the provider (gofastmcp.com/apps pattern).
"""

from __future__ import annotations

from fastmcp import FastMCP

from hh_mcp.app import app

__all__ = ["mcp"]

mcp = FastMCP(app.name)
mcp.add_provider(app)
