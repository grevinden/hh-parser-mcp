"""hh-mcp entry point — ``python -m hh_mcp`` / ``hh-mcp`` console script.

Commands
--------
``hh-mcp`` (without ``--dev``)
    Start the MCP server. ``--transport`` picks the protocol
    (default ``stdio``); ``--host`` / ``--port`` are forwarded to the
    server only for HTTP-ish transports — the stdio runner does not
    accept them.

``hh-mcp --dev``
    Local development mode: MCP server (transport ``http``, path
    ``/mcp``) and the web frontend (:mod:`hh_mcp.devapp`) in ONE process,
    via ``asyncio.gather``. SIGINT / SIGTERM (Ctrl+C, ``kill``)
    cancel both tasks together, then the process exits.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys
from collections.abc import Sequence
from typing import Any

__all__ = [
    "DEFAULT_DEV_PORT",
    "DEFAULT_MCP_PORT",
    "MCP_PATH",
    "HTTP_TRANSPORTS",
    "build_parser",
    "dev_mode",
    "main",
    "run_mode",
]

DEFAULT_MCP_PORT = 8000
DEFAULT_DEV_PORT = 8080
MCP_PATH = "/mcp"
HTTP_TRANSPORTS = ("http", "sse", "streamable-http")

logger = logging.getLogger("hh_mcp")


# --- CLI parsing -----------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the flat CLI parser (separated for testability).

    Returns
    -------
    argparse.ArgumentParser
        Flat parser with ``--transport``, ``--host``, ``--port``,
        ``--dev``, ``--mcp-port`` and ``--dev-port`` flags.
    """
    parser = argparse.ArgumentParser(
        prog="hh-mcp",
        description="hh-mcp — hh.ru pages as MCP tools and in-browser apps.",
    )
    parser.add_argument(
        "--transport",
        choices=(*HTTP_TRANSPORTS, "stdio"),
        default=None,
        help=(
            "Transport protocol (default: stdio, auto-fallback to"
            " fastmcp settings)."
        ),
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="HTTP bind host (HTTP transports only; default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_MCP_PORT,
        help=(
            "HTTP bind port (HTTP transports only, MCP port in dev mode;"
            " default: %d)." % DEFAULT_MCP_PORT
        ),
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Start in dev mode (MCP server + web frontend in one process).",
    )
    parser.add_argument(
        "--mcp-port",
        type=int,
        default=None,
        help="Port for the MCP server in dev mode (default: %d)." % DEFAULT_MCP_PORT,
    )
    parser.add_argument(
        "--dev-port",
        type=int,
        default=None,
        help="Port for the web frontend in dev mode (default: %d)." % DEFAULT_DEV_PORT,
    )
    return parser


# --- run mode ------------------------------------------------------------


def run_mode(*, transport: str | None, host: str, port: int) -> None:
    """Start the MCP server (blocking).

    ``host`` / ``port`` are forwarded only for HTTP-ish transports: the
    stdio runner does not accept them.

    Parameters
    ----------
    transport:
        ``stdio``, one of :data:`HTTP_TRANSPORTS`, or ``None`` (fallback to
        fastmcp settings → ``stdio``).
    host:
        HTTP bind host.
    port:
        HTTP bind port.
    """
    from hh_mcp.app import app

    kwargs: dict[str, Any] = {}
    if transport is not None and transport in HTTP_TRANSPORTS:
        kwargs["host"] = host
        kwargs["port"] = port
    app.run(transport=transport, **kwargs)


# --- dev mode ------------------------------------------------------------


async def dev_mode(host: str, mcp_port: int, dev_port: int) -> None:
    """Run the MCP server and the web frontend in one process.

    Both servers are uvicorn ``Server`` instances run via ``asyncio.gather``
    — but through ``Server._serve()`` directly, NOT ``Server.serve()``.
    ``serve()`` wraps ``_serve()`` in ``capture_signals()``, which installs
    ``signal.signal(SIGINT, ...)``; with two servers in one process the
    last-installed handler would win and the other server would never shut
    down (and our own loop-installed handlers would be overwritten too).
    Instead the event loop owned by :func:`main` installs the single set of
    SIGINT / SIGTERM handlers (Ctrl+C, ``kill``) and cancels whichever
    server is still running, so the process exits cleanly.

    Parameters
    ----------
    host:
        Bind host for both servers.
    mcp_port:
        Port of the MCP server (transport ``http``, path ``/mcp``).
    dev_port:
        Port of the web frontend.
    """
    import uvicorn
    from fastmcp.server.server import FastMCP
    from hh_mcp.app import app as mcp_app
    from hh_mcp.devapp import create_app

    # MCP: build the FastMCP HTTP ASGI app the same way ``run_http_async``
    # does internally, but run it with our own uvicorn server so we can
    # call ``_serve()`` directly (see the docstring for why not ``serve()``).
    fastmcp_app = FastMCP(mcp_app.name)
    fastmcp_app.add_provider(mcp_app)
    mcp_asgi = fastmcp_app.http_app(path=MCP_PATH, transport="http")
    mcp_uvicorn = uvicorn.Server(
        uvicorn.Config(
            mcp_asgi,
            host=host,
            port=mcp_port,
            log_level="warning",
            timeout_graceful_shutdown=2,
            lifespan="on",
            ws="websockets-sansio",
        )
    )

    # Web: the dev frontend ASGI app, served by a second uvicorn server.
    mcp_url = f"http://{host}:{mcp_port}{MCP_PATH}"
    web_asgi = create_app(mcp_url)
    web_uvicorn = uvicorn.Server(
        uvicorn.Config(web_asgi, host=host, port=dev_port, log_level="warning")
    )
    web_url = f"http://{host}:{dev_port}"

    logger.info("MCP: %s", mcp_url)
    logger.info("Web: %s", web_url)
    print(
        f"\nhh-mcp dev — MCP: {mcp_url} | Web: {web_url}"
        " (Ctrl+C to stop)\n",
        flush=True,
    )

    # Per-instance opt-out: uvicorn's ``serve()`` wraps the server in a
    # ``capture_signals()`` context manager that installs
    # ``signal.signal(SIGINT/SIGTERM, ...)`` — with two servers in one
    # process the last one would win and break our loop-owned handlers.
    # Replacing the bound method with ``nullcontext`` keeps the public
    # ``serve()`` API but skips exactly that wrapper.
    mcp_uvicorn.capture_signals = contextlib.nullcontext  # type: ignore[method-assign]
    web_uvicorn.capture_signals = contextlib.nullcontext  # type: ignore[method-assign]

    loop = asyncio.get_running_loop()

    async def _body() -> None:
        await asyncio.gather(mcp_uvicorn.serve(), web_uvicorn.serve())

    task = asyncio.ensure_future(_body())

    def _on_signal() -> None:
        # Silence uvicorn's "Shutting down" noise during the clean exit.
        logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)
        task.cancel()

    if sys.platform != "win32":
        loop.add_signal_handler(signal.SIGINT, _on_signal)
        loop.add_signal_handler(signal.SIGTERM, _on_signal)

    try:
        await task
    except asyncio.CancelledError:
        pass
    finally:
        if sys.platform != "win32":
            loop.remove_signal_handler(signal.SIGINT)
            loop.remove_signal_handler(signal.SIGTERM)


# --- entry point ---------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> None:
    """Parse CLI arguments and dispatch to run / dev mode.

    Parameters
    ----------
    argv:
        Argument list (``None`` → ``sys.argv[1:]``).
    """
    args = build_parser().parse_args(argv)
    if args.dev:
        mcp_port = args.mcp_port or args.port or DEFAULT_MCP_PORT
        dev_port = args.dev_port or DEFAULT_DEV_PORT
        asyncio.run(dev_mode(host=args.host, mcp_port=mcp_port, dev_port=dev_port))
    else:
        run_mode(
            transport=args.transport,
            host=args.host,
            port=args.port or DEFAULT_MCP_PORT,
        )


if __name__ == "__main__":
    main()