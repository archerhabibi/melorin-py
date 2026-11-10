"""Phase 5.6 (audit W18): the API sends its own security headers, so EXTERNAL_PROXY installs are protected too."""

import httpx
import pytest

from melorin.app import app
from melorin.core.config import get_settings


async def _get(path="/health/live", headers=None, client=("203.0.113.9", 5000), base="http://testserver"):
    transport = httpx.ASGITransport(app=app, client=client)
    async with httpx.AsyncClient(transport=transport, base_url=base) as c:
        return await c.get(path, headers=headers)


@pytest.mark.asyncio
async def test_baseline_headers_on_every_response():
    r = await _get()
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "camera=()" in r.headers["permissions-policy"]
    assert r.headers["content-security-policy"].startswith("default-src 'none'")


@pytest.mark.asyncio
async def test_error_and_404_responses_also_carry_headers():
    r = await _get("/api/v1/definitely-not-a-route")
    assert r.status_code == 404
    assert r.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_no_hsts_over_plain_http():
    r = await _get()
    assert "strict-transport-security" not in r.headers


@pytest.mark.asyncio
async def test_hsts_when_scheme_is_https():
    r = await _get(base="https://testserver")
    assert r.headers["strict-transport-security"].startswith("max-age=31536000")


@pytest.mark.asyncio
async def test_hsts_trusts_forwarded_proto_only_from_a_trusted_proxy():
    trusted = await _get(headers={"X-Forwarded-Proto": "https"}, client=("127.0.0.1", 5000))
    assert "strict-transport-security" in trusted.headers
    spoofed = await _get(headers={"X-Forwarded-Proto": "https"}, client=("198.51.100.7", 5000))
    assert "strict-transport-security" not in spoofed.headers


@pytest.mark.asyncio
async def test_headers_a_proxy_or_handler_already_set_are_not_overwritten():
    from melorin.core.middleware import SecurityHeadersMiddleware

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"x-frame-options", b"SAMEORIGIN")]})
        await send({"type": "http.response.body", "body": b""})

    seen = {}

    async def send(msg):
        if msg["type"] == "http.response.start":
            seen["h"] = msg["headers"]

    await SecurityHeadersMiddleware(inner)({"type": "http", "path": "/x", "headers": [], "client": ("1.2.3.4", 1)}, None, send)
    frames = [v for k, v in seen["h"] if k == b"x-frame-options"]
    assert frames == [b"SAMEORIGIN"]


@pytest.mark.asyncio
async def test_can_be_disabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "security_headers_enabled", False)
    r = await _get()
    assert "x-content-type-options" not in r.headers
