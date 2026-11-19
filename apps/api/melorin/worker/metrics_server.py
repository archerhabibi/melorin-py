"""Small authenticated Prometheus endpoint for metrics held in the worker process.

The API and ARQ worker are separate processes/containers; scraping the API's
in-process registry cannot observe worker job counters or item failures.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
from typing import Any

from melorin.core.config import get_settings
from melorin.core.metrics import render

log = logging.getLogger("melorin.worker.metrics")

HOST = "0.0.0.0"
PORT = 8001
_READ_TIMEOUT = 2.0


async def _write_response(writer: asyncio.StreamWriter, status: int, reason: str, body: str) -> None:
    payload = body.encode("utf-8")
    headers = (
        f"HTTP/1.1 {status} {reason}\r\n"
        "Content-Type: text/plain; version=0.0.4; charset=utf-8\r\n"
        f"Content-Length: {len(payload)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    writer.write(headers + payload)
    await writer.drain()


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=_READ_TIMEOUT)
        lines = raw.decode("latin-1").split("\r\n")
        request = lines[0].split()
        if len(request) != 3 or request[2] != "HTTP/1.1":
            await _write_response(writer, 400, "Bad Request", "bad request\n")
            return
        method, path, _ = request
        if method != "GET":
            await _write_response(writer, 405, "Method Not Allowed", "method not allowed\n")
            return
        if path != "/metrics":
            await _write_response(writer, 404, "Not Found", "not found\n")
            return

        headers: dict[str, str] = {}
        for line in lines[1:]:
            if not line:
                continue
            name, separator, value = line.partition(":")
            if separator:
                headers[name.strip().lower()] = value.strip()

        settings = get_settings()
        token = settings.metrics_token
        if not settings.is_dev and not token:
            await _write_response(writer, 503, "Service Unavailable", "metrics authentication is not configured\n")
            return
        if token and not hmac.compare_digest(headers.get("authorization", ""), f"Bearer {token}"):
            writer.write(
                b"HTTP/1.1 401 Unauthorized\r\nWWW-Authenticate: Bearer\r\nContent-Length: 13\r\nConnection: close\r\n\r\nunauthorized\n"
            )
            await writer.drain()
            return

        await _write_response(writer, 200, "OK", render())
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError, UnicodeError):
        try:
            await _write_response(writer, 400, "Bad Request", "bad request\n")
        except (ConnectionError, OSError):
            pass
    except (ConnectionError, OSError):
        log.debug("worker metrics client disconnected", exc_info=True)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass


async def start_metrics_server(ctx: dict[str, Any], *, host: str = HOST, port: int = PORT) -> asyncio.AbstractServer:
    """Start the worker-local scrape endpoint and retain its server in ARQ context."""
    server = await asyncio.start_server(_handle, host, port, limit=64 * 1024)
    ctx["metrics_server"] = server
    bound = server.sockets[0].getsockname() if server.sockets else (host, port)
    log.info("worker metrics endpoint listening on %s:%s", bound[0], bound[1])
    return server


async def stop_metrics_server(ctx: dict[str, Any]) -> None:
    """Close the worker-local scrape endpoint during ARQ shutdown."""
    server = ctx.get("metrics_server")
    if isinstance(server, asyncio.AbstractServer):
        server.close()
        await server.wait_closed()
        ctx.pop("metrics_server", None)
