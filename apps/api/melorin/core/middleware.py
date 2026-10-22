import time
import uuid
import logging

from starlette.types import ASGIApp, Receive, Scope, Send

from melorin.core.context import client_ip, correlation_id
from melorin.core.config import get_settings
from melorin.core.metrics import inc, observe
from melorin.core.proxy import is_trusted_proxy, resolve_client_ip

log = logging.getLogger("melorin.http")

# M7.6: label values stay bounded (a scanner hitting random URLs must not create unbounded series).
_KNOWN_ROUTES = frozenset({"/health", "/health/live", "/health/ready", "/metrics", "/openapi-version"})


def route_label(path: str) -> str:
    route = path
    if route.startswith("/api/v1/"):
        route = "/api/v1/*"
    elif route not in _KNOWN_ROUTES:
        route = "other"
    return route


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
            route = route_label(scope["path"])
            inc("melorin_http_requests_total", method=scope["method"], path=route, status=status["code"])
            seconds = time.perf_counter() - start
            observe("melorin_http_request_duration_seconds", seconds, path=route)
            ms = seconds * 1000
            log.info("%s %s %s %.1fms", scope["method"], scope["path"], status["code"], ms)
            correlation_id.reset(t1)
            client_ip.reset(t2)


# Baseline headers for an API that only returns JSON, text, images and CSV (Phase 5.6, audit W18). The interactive docs
# (development only) need scripts and styles, so the strict CSP is skipped for them.
_BASE_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
    (b"cross-origin-resource-policy", b"same-site"),
)
_API_CSP = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


class SecurityHeadersMiddleware:
    """Pure ASGI: add security headers to every response unless a proxy/handler already set them.

    HSTS is sent only when the request really arrived over HTTPS: either the ASGI scheme is https, or a TRUSTED proxy
    (trusted_proxy_ips) said so with X-Forwarded-Proto. A browser ignores HSTS over plain HTTP anyway, and sending it on
    an http-only dev/test setup would only mislead.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    @staticmethod
    def _is_https(scope: Scope, headers: dict[bytes, bytes]) -> bool:
        if scope.get("scheme") in {"https", "wss"}:
            return True
        direct = (scope.get("client") or ("", 0))[0]
        if not is_trusted_proxy(direct, get_settings().trusted_proxy_ips):
            return False
        return headers.get(b"x-forwarded-proto", b"").split(b",")[0].strip().lower() == b"https"

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        settings = get_settings()
        if scope["type"] != "http" or not settings.security_headers_enabled:
            return await self.app(scope, receive, send)
        request_headers = dict(scope.get("headers") or [])
        https = self._is_https(scope, request_headers)
        docs = scope.get("path", "") in _DOC_PATHS

        async def _send(msg):
            if msg["type"] == "http.response.start":
                headers = msg.setdefault("headers", [])
                present = {k.lower() for k, _ in headers}
                extra = list(_BASE_HEADERS)
                if not docs:
                    extra.append(_API_CSP)
                if https and settings.hsts_max_age > 0:
                    extra.append((b"strict-transport-security", f"max-age={settings.hsts_max_age}; includeSubDomains".encode()))
                headers.extend((k, v) for k, v in extra if k not in present)
            await send(msg)

        await self.app(scope, receive, _send)
