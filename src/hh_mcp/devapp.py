"""Dev web frontend for the hh-mcp server (Starlette, single module).

One-process dev mode (see :mod:`hh_mcp.__main__` ``dev`` command) runs
this ASGI app next to the MCP server. The app talks to the MCP server
over HTTP with :class:`fastmcp.client.Client` and exposes a tiny JSON
API plus a single offline HTML page (no CDN, no external assets).

API
---
``GET  /api/status``   connection state + server / protocol info
``GET  /api/mcp``      tools / resources / prompts of the MCP server
``POST /api/mcp/call`` ``{"tool": ..., "arguments": {...}}`` → tool result
``GET  /``             the HTML page (JS polls ``/api/status``)

Error contract: no MCP connection → ``503 {"error": ...}``; an error
coming from a reachable server → ``502 {"error": ...}``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
import mcp_types
import pydantic
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from fastmcp.client import Client

__all__ = ["CallToolRequest", "McpBackend", "McpStatus", "create_app"]

logger = logging.getLogger(__name__)

# --- Error classification ------------------------------------------------------

# Connection-level failures: nothing at the MCP URL is reachable.
# The fastmcp/mcp layers wrap socket errors in their own types
# (e.g. ``RuntimeError`` with an httpx2 ``ConnectError`` as ``__cause__``),
# so the classifier walks the ``__cause__`` chain in addition to direct
# ``isinstance`` checks.
_NETWORK_ERRORS: tuple[type[Exception], ...] = (
    httpx2.NetworkError,
    httpx2.TimeoutException,
)


def _connection_error(exc: Exception) -> bool:
    """Return ``True`` if *exc* means the MCP server cannot be reached."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (OSError, *_NETWORK_ERRORS)):
            return True
        current = current.__cause__
    return False


def _json_error(exc: Exception) -> JSONResponse:
    """Map a backend failure to 503 (no connection) or 502 (server error)."""
    code = 503 if _connection_error(exc) else 502
    return JSONResponse(
        {"error": f"{type(exc).__name__}: {exc}"}, status_code=code
    )


# --- API models ----------------------------------------------------------------


class McpStatus(pydantic.BaseModel):
    """Connection state of the dev frontend to its MCP server."""

    connected: bool
    mcp_url: str
    server: str | None = None
    protocol_version: str | None = None
    tool_count: int | None = None


class CallToolRequest(pydantic.BaseModel):
    """Body of ``POST /api/mcp/call``."""

    tool: str
    arguments: dict[str, Any] = {}


# --- Backend -------------------------------------------------------------------


class _ClientProxy:
    """Shim mapping fastmcp ``Client`` methods to the mcp-types mirror.

    Used by :func:`create_app` when *backend_factory* is the default
    (``fastmcp.client.Client``) so the rest of the backend works in
    mcp-types vocabulary (``ServerModel``, ``Tool``, ``TextContent``, …).
    A user-supplied factory that already returns mcp-shaped clients
    (tests' ``FakeClient``) bypasses the proxy.
    """

    def __init__(self, client: Any) -> None:
        self._c = client

    @property
    def server_info(self) -> mcp_types.Implementation | None:
        info = self._c.server_info
        if info is None:
            return None
        return mcp_types.Implementation(
            name=info.name, title=info.title, version=info.version
        )

    @property
    def protocol_version(self) -> str | None:
        return self._c.protocol_version

    def is_connected(self) -> bool:
        return self._c.is_connected()

    async def __aenter__(self) -> "_ClientProxy":
        await self._c.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._c.__aexit__(*args)

    async def list_tools(self) -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name=t.name, title=t.title, description=t.description,
                input_schema=t.input_schema,
            )
            for t in await self._c.list_tools()
        ]

    async def list_resources(self) -> list[mcp_types.Resource]:
        return [
            mcp_types.Resource(
                name=r.name, title=r.title, uri=r.uri,
                description=r.description, mime_type=r.mime_type,
            )
            for r in await self._c.list_resources()
        ]

    async def list_prompts(self) -> list[mcp_types.Prompt]:
        prompts = await self._c.list_prompts()
        return [
            mcp_types.Prompt(
                name=p.name, title=p.title, description=p.description,
                arguments=[
                    mcp_types.PromptArgument(
                        name=a.name, description=a.description,
                        required=bool(a.required),
                    )
                    for a in (p.arguments or [])
                ],
            )
            for p in prompts
        ]

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> mcp_types.CallToolResult:
        result = await self._c.call_tool(name, arguments, raise_on_error=False)
        return mcp_types.CallToolResult(
            content=list(result.content or []),
            structured_content=result.structured_content,
            is_error=bool(result.is_error),
        )


def _default_client_factory(url: str) -> Any:
    """Default client: fastmcp ``Client`` wrapped in :class:`_ClientProxy`."""
    return _ClientProxy(Client(url))


def _text_content(block: Any) -> str | None:
    """Extract text from one tool result content block (mcp-types shape)."""
    if isinstance(block, mcp_types.TextContent):
        return block.text
    if isinstance(block, dict):
        if block.get("type") == "text":
            return str(block.get("text", ""))
        return str(block)
    if getattr(block, "type", None) == "text":
        return str(getattr(block, "text", ""))
    return str(block)


class McpBackend:
    """Thin async wrapper over an MCP client (one-shot connections).

    Every backend method opens a fresh client via
    ``client_factory(mcp_url)``, uses it, and closes it, so the frontend
    never keeps live sessions. *client_factory* is a seam: production
    passes :func:`_default_client_factory` (fastmcp ``Client``), tests
    pass a factory that returns a mcp-shaped :class:`FakeClient`.
    """

    def __init__(
        self,
        mcp_url: str,
        client_factory: Any | None = None,
    ) -> None:
        self.mcp_url = mcp_url
        self._client_factory = client_factory or _default_client_factory

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[Any]:
        """Async context manager that yields a connected client, closed on exit.

        The client's own context manager performs the connect and the
        initialisation handshake, so there is nothing else to do here.
        ``close()`` in ``finally`` is belt-and-braces: it also releases the
        transport, which a plain ``__aexit__`` does not.
        """
        client = self._client_factory(self.mcp_url)
        try:
            async with client:
                yield client
        finally:
            close = getattr(client, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception:  # noqa: BLE001 - best-effort cleanup
                    pass

    async def status(self) -> McpStatus:
        """Probe the server and return its :class:`McpStatus`."""
        state = McpStatus(connected=False, mcp_url=self.mcp_url)
        try:
            async with self._client() as client:
                if not client.is_connected():
                    # The client did not establish a usable session — a
                    # connection-level failure (→ 503), not a server error.
                    raise ConnectionError("MCP session not connected")
                state.connected = True
                state.server = (
                    client.server_info.name if client.server_info else None
                )
                state.protocol_version = client.protocol_version
                state.tool_count = len(await client.list_tools())
        except Exception as exc:  # noqa: BLE001 - reported via ``connected``
            logger.debug("status probe failed for %s: %s", self.mcp_url, exc)
        return state

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return the server's tools as plain dicts."""
        async with self._client() as client:
            tools = await client.list_tools()
        return [
            {
                "name": t.name,
                "title": t.title,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]

    async def list_resources(self) -> list[dict[str, Any]]:
        """Return the server's resources as plain dicts."""
        async with self._client() as client:
            resources = await client.list_resources()
        return [
            {
                "name": r.name,
                "uri": r.uri,
                "description": r.description,
                "mimeType": r.mime_type,
            }
            for r in resources
        ]

    async def list_prompts(self) -> list[dict[str, Any]]:
        """Return the server's prompts as plain dicts."""
        async with self._client() as client:
            prompts = await client.list_prompts()
        return [
            {
                "name": p.name,
                "description": p.description,
                "arguments": [a.name for a in (p.arguments or [])],
            }
            for p in prompts
        ]

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Call *name* with *arguments*; tool errors are reported, not raised."""
        async with self._client() as client:
            result = await client.call_tool(name, arguments)
        payload: dict[str, Any] = {
            "isError": bool(result.is_error),
            "content": [
                text
                for text in (_text_content(b) for b in (result.content or []))
                if text is not None
            ],
        }
        if result.structured_content is not None:
            payload["structuredContent"] = result.structured_content
        return payload


# --- HTML page (self-contained, offline, XSS-safe) -----------------------------

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>hh-mcp — dev</title>
<style>
:root { color-scheme: light; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; background: #f8f9fa; color: #212529; }
header { display: flex; align-items: center; gap: .75rem; padding: .9rem 1.25rem;
         background: #fff; border-bottom: 1px solid #dee2e6; }
header h1 { font-size: 1.05rem; margin: 0; font-weight: 650; }
.badge { padding: .2rem .65rem; border-radius: 999px; font-size: .8rem; font-weight: 600; }
.badge.ok { background: #d1e7dd; color: #0f5132; }
.badge.bad { background: #f8d7da; color: #842029; }
main { max-width: 980px; margin: 1.25rem auto; padding: 0 1.25rem 3rem; }
section { background: #fff; border: 1px solid #dee2e6; border-radius: .5rem;
          margin-bottom: 1.1rem; padding: 1rem 1.25rem; }
h2 { font-size: .95rem; margin: 0 0 .75rem; color: #495057; }
.item { padding: .45rem 0; border-bottom: 1px dashed #e9ecef; font-size: .92rem; }
.item:last-child { border-bottom: none; }
.item .name { font-weight: 600; }
.item .desc { color: #6c757d; font-size: .85rem; margin-top: .1rem; }
.note { color: #6c757d; font-size: .85rem; }
form { display: grid; gap: .6rem; }
input, textarea { width: 100%; padding: .5rem .6rem; border: 1px solid #ced4da;
                  border-radius: .35rem; font: inherit; font-size: .92rem; }
textarea { min-height: 64px; font-family: ui-monospace, monospace; }
button { justify-self: start; padding: .5rem 1.1rem; border: 0; border-radius: .35rem;
         background: #0d6efd; color: #fff; font-weight: 600; cursor: pointer; }
button:disabled { opacity: .55; cursor: not-allowed; }
pre#result { white-space: pre-wrap; word-break: break-word; background: #f1f3f5;
             border-radius: .35rem; padding: .75rem; min-height: 3.5rem;
             font-family: ui-monospace, monospace; font-size: .85rem; }
.err { color: #842029; }
</style>
</head>
<body>
<header>
  <h1>hh-mcp — dev</h1>
  <span id="status" class="badge bad">…</span>
  <span id="meta" class="note"></span>
</header>
<main>
  <section>
    <h2>Tools</h2>
    <div id="tools"><div class="note">loading…</div></div>
  </section>
  <section>
    <h2>Resources</h2>
    <div id="resources"><div class="note">—</div></div>
  </section>
  <section>
    <h2>Prompts</h2>
    <div id="prompts"><div class="note">—</div></div>
  </section>
  <section>
    <h2>Call tool</h2>
    <form id="call-form">
      <input id="tool" name="tool" placeholder="tool name (e.g. get_vacancy)" required>
      <textarea id="args" name="arguments" placeholder='{"id": 123}'></textarea>
      <button id="call-btn" type="submit">Call</button>
    </form>
    <pre id="result">(no result yet)</pre>
  </section>
</main>
<script>
"use strict";
const $ = (id) => document.getElementById(id);

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;  // XSS-safe
  return e;
}

function renderList(container, items, fmt) {
  container.textContent = "";
  if (!items.length) { container.appendChild(el("div", "note", "—")); return; }
  for (const it of items) container.appendChild(fmt(it));
}

function itemRow(name, description, extra) {
  const row = el("div", "item");
  row.appendChild(el("div", "name", name));
  row.appendChild(el("div", "desc", description));
  row.appendChild(el("div", "note", extra));
  return row;
}

async function refresh() {
  try {
    const s = await (await fetch("/api/status")).json();
    const b = $("status");
    b.className = "badge " + (s.connected ? "ok" : "bad");
    b.textContent = s.connected ? "connected" : "disconnected";
    $("meta").textContent = [s.server, s.protocol_version,
      s.tool_count !== null && s.tool_count !== undefined
        ? s.tool_count + " tools" : null, s.mcp_url]
      .filter(Boolean).join("  ·  ");
    const m = await (await fetch("/api/mcp")).json();
    renderList($("tools"), m.tools || [],
      (t) => itemRow(t.name, t.description || "", t.title || ""));
    renderList($("resources"), m.resources || [],
      (r) => itemRow(r.name || r.uri, r.description || "", r.uri || ""));
    renderList($("prompts"), m.prompts || [],
      (p) => itemRow(p.name, p.description || "",
        (p.arguments || []).join(",")));
  } catch {
    const b = $("status");
    b.className = "badge bad";
    b.textContent = "error";
  }
}

$("call-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  let args = {};
  const rawArgs = $("args").value.trim();
  if (rawArgs) {
    try { args = JSON.parse(rawArgs); }
    catch { $("result").textContent = "arguments is not valid JSON"; return; }
  }
  const btn = $("call-btn");
  btn.disabled = true;
  $("result").textContent = "calling…";
  try {
    const resp = await fetch("/api/mcp/call", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({tool: $("tool").value.trim(), arguments: args}),
    });
    const data = await resp.json();
    if (resp.ok) {
      $("result").textContent =
        (data.isError ? "ERROR: " : "") + (data.content || []).join("\\n");
    } else {
      $("result").textContent = String(data.error || resp.status);
    }
  } finally {
    btn.disabled = false;
  }
});

refresh();
setInterval(refresh, 5000);  // auto-poll
</script>
</body>
</html>
"""

# --- App factory -----------------------------------------------------------------


def create_app(
    mcp_url: str,
    *,
    backend_factory: Any | None = None,
) -> Starlette:
    """Build the dev ASGI app.

    Parameters
    ----------
    mcp_url:
        Full URL of the MCP endpoint, e.g. ``http://127.0.0.1:8000/mcp``.
    backend_factory:
        Optional ``mcp_url -> client-or-async-cm[client]`` for tests;
        the returned client is used as-is (expected to speak the
        mcp-types vocabulary: ``server_info`` / ``list_tools()`` /
        ``list_prompts()`` / ``call_tool(name, arguments)``.

    Returns
    -------
    Starlette
        ASGI app with routes ``/`` (HTML page), ``/api/status``,
        ``/api/mcp`` and ``POST /api/mcp/call``.
    """
    backend = McpBackend(mcp_url, client_factory=backend_factory)

    async def index(_request: Request) -> HTMLResponse:
        return HTMLResponse(_PAGE)

    async def status(_request: Request) -> JSONResponse:
        state = await backend.status()
        return JSONResponse(state.model_dump(mode="json"))

    async def mcp_listing(_request: Request) -> JSONResponse:
        try:
            tools = await backend.list_tools()
            resources = await backend.list_resources()
            prompts = await backend.list_prompts()
        except Exception as exc:
            return _json_error(exc)
        return JSONResponse(
            {"tools": tools, "resources": resources, "prompts": prompts}
        )

    async def mcp_call(request: Request) -> JSONResponse:
        try:
            payload = CallToolRequest.model_validate_json(
                await request.body()
            )
        except pydantic.ValidationError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        try:
            result = await backend.call_tool(payload.tool, payload.arguments)
        except Exception as exc:
            return _json_error(exc)
        return JSONResponse(result)

    return Starlette(
        routes=[
            Route("/", index, methods=["GET"]),
            Route("/api/status", status, methods=["GET"]),
            Route("/api/mcp", mcp_listing, methods=["GET"]),
            Route("/api/mcp/call", mcp_call, methods=["POST"]),
        ]
    )