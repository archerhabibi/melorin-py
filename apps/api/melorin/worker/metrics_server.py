"""Small authenticated Prometheus endpoint for metrics held in a background process.

The API and ARQ worker are separate processes/containers; scraping the API's
in-process registry cannot observe worker job counters or item failures. The
listener is only reachable on the internal ``backend`` network (no published port)
and is always protected by the same bearer token as the API's ``/metrics``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from melorin.core.config import get_settings
from melorin.core.metrics import render
from melorin.core.security import safe_equal

log = logging.getLogger("melorin.process.metrics")

HOST = "0.0.0.0"  # noqa: S104 - internal docker network only; the compose file publishes no port for this listener
PORT = 8001
CTX_KEY = "metrics_server"
_READ_TIMEOUT = 2.0  # seconds to receive the request head
_HANDLER_TIMEOUT = 10.0  # hard ceiling for one connection, so a stalled reader cannot pin a task
_MAX_HEAD_BYTES = 16 * 1024
_TEXT = "text/plain; version=0.0.4; charset=utf-8"


async def _write_response(
    writer: asyncio.StreamWriter,
    status: int,
    reason: str,
    body: str,
    *,
    extra_headers: tuple[str, ...] = (),
    head_only: bool = False,
) -> None:
    payload = body.encode("utf-8")
    head = [
        f"HTTP/1.1 {status} {reason}",
        f"Content-Type: {_TEXT}",
        f"Content-Length: {len(payload)}",
        "Cache-Control: no-store",
        "Connection: close",
        *extra_headers,
    ]
    writer.write(("\r\n".join(head) + "\r\n\r\n").encode("ascii") + (b"" if head_only else payload))
    await writer.drain()


def _parse_headers(lines: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in lines:
        name, separator, value = line.partition(":")
        if separator:
            headers[name.strip().lower()] = value.strip()
    return headers


async def _respond(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=_READ_TIMEOUT)
    lines = raw.decode("latin-1").split("\r\n")
    request = lines[0].split()
    if len(request) != 3 or request[2] not in ("HTTP/1.0", "HTTP/1.1"):
        await _write_response(writer, 400, "Bad Request", "bad request\n")
        return
    method, target, _ = request
    if method not in ("GET", "HEAD"):
        await _write_response(writer, 405, "Method Not Allowed", "method not allowed\n", extra_headers=("Allow: GET, HEAD",))
        return
    if target.partition("?")[0] != "/metrics":
        await _write_response(writer, 404, "Not Found", "not found\n")
        return
    head_only = method == "HEAD"

    settings = get_settings()
    token = settings.metrics_token
    if not settings.is_dev and not token:
        await _write_response(writer, 503, "Service Unavailable", "metrics authentication is not configured\n", head_only=head_only)
        return
    if token and not safe_equal(_parse_headers(lines[1:]).get("authorization", ""), f"Bearer {token}"):
        await _write_response(
            writer, 401, "Unauthorized", "unauthorized\n", extra_headers=("WWW-Authenticate: Bearer",), head_only=head_only
        )
        return
    await _write_response(writer, 200, "OK", render(), head_only=head_only)


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        await asyncio.wait_for(_respond(reader, writer), timeout=_HANDLER_TIMEOUT)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError, UnicodeError):
        try:
            await _write_response(writer, 400, "Bad Request", "bad request\n")
        except (ConnectionError, OSError):
            pass
    except (ConnectionError, OSError):
        log.debug("process metrics client disconnected", exc_info=True)
    except Exception:  # never let one scrape take the worker down or leak a traceback to the peer
        log.exception("process metrics request failed")
        try:
            await _write_response(writer, 500, "Internal Server Error", "internal error\n")
        except (ConnectionError, OSError):
            pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass


async def start_metrics_server(ctx: dict[str, Any], *, host: str = HOST, port: int | None = None) -> asyncio.AbstractServer | None:
    """Start the process-local scrape endpoint and retain it in ``ctx``.

    Failing to bind (port taken, ...) must not stop the jobs themselves: the error is logged and the
    ``MelorinWorkerMetricsUnavailable`` / ``MelorinBackupMetricsUnavailable`` alerts surface the missing target.
    """
    try:
        server = await asyncio.start_server(_handle, host, PORT if port is None else port, limit=_MAX_HEAD_BYTES)
    except OSError:
        log.exception("process metrics endpoint could not start on %s:%s; continuing without it", host, PORT if port is None else port)
        return None
    ctx[CTX_KEY] = server
    bound = server.sockets[0].getsockname() if server.sockets else (host, port)
    log.info("process metrics endpoint listening on %s:%s", bound[0], bound[1])
    return server


async def stop_metrics_server(ctx: dict[str, Any]) -> None:
    """Close the process-local scrape endpoint during shutdown (idempotent)."""
    server = ctx.pop(CTX_KEY, None)
    if isinstance(server, asyncio.AbstractServer):
        server.close()
        await server.wait_closed()
