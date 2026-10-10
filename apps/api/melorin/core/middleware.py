import time
import uuid
import logging

from starlette.types import ASGIApp, Receive, Scope, Send

from melorin.core.context import client_ip, correlation_id
from melorin.core.config import get_settings
from melorin.core.metrics import inc
from melorin.core.proxy import resolve_client_ip

log = logging.getLogger("melorin.http")


class CorrelationMiddleware:
    """Pure ASGI: assigns/propagates X-Request-ID and logs latency."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        rid = headers.get(b"x-request-id", b"").decode()[:64] or uuid.uuid4().hex
        direct = (scope.get("client") or ("", 0))[0]
        fwd = headers.get(b"x-forwarded-for", b"").decode()
        ip = resolve_client_ip(direct, fwd, get_settings().trusted_proxy_ips)
        t1 = correlation_id.set(rid)
        t2 = client_ip.set(ip)
        start = time.perf_counter()
        status = {"code": 0}

        async def _send(msg):
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]
                msg.setdefault("headers", []).append((b"x-request-id", rid.encode()))
            await send(msg)

        try:
            await self.app(scope, receive, _send)
        finally:
            route = scope["path"]
            if route.startswith("/api/v1/"):
                route = "/api/v1/*"
            inc("melorin_http_requests_total", method=scope["method"], path=route, status=status["code"])
            ms = (time.perf_counter() - start) * 1000
            log.info("%s %s %s %.1fms", scope["method"], scope["path"], status["code"], ms)
            correlation_id.reset(t1)
            client_ip.reset(t2)
