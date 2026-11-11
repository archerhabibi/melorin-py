"""T-G06: W3C trace context is honoured, echoed, logged and forwarded."""

import httpx

from melorin.core import http as core_http
from melorin.core.context import trace_id
from melorin.core.tracing import format_traceparent, new_trace_id, parse_traceparent

GOOD = "0af7651916cd43dd8448eb211c80319c"


def test_parse_accepts_valid_and_rejects_garbage():
    assert parse_traceparent(f"00-{GOOD}-b7ad6b7169203331-01") == GOOD
    for bad in (None, "", "junk", f"00-{'0' * 32}-b7ad6b7169203331-01", f"00-{GOOD}-{'0' * 16}-01", f"ff-{GOOD}-b7ad6b7169203331-01"):
        assert parse_traceparent(bad) is None


def test_format_roundtrips():
    tid = new_trace_id()
    assert parse_traceparent(format_traceparent(tid)) == tid


async def test_outbound_client_forwards_current_trace():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["tp"] = request.headers.get("traceparent")
        return httpx.Response(200)

    token = trace_id.set(GOOD)
    try:
        async with core_http.outbound_client("trace_test", transport=httpx.MockTransport(handler)) as client:
            await client.get("https://peer.example/ping")
    finally:
        trace_id.reset(token)
    assert parse_traceparent(seen["tp"]) == GOOD


async def test_middleware_echoes_inbound_trace():
    from melorin.app import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/health/live", headers={"traceparent": f"00-{GOOD}-b7ad6b7169203331-01"})
        assert parse_traceparent(r.headers["traceparent"]) == GOOD
        r2 = await client.get("/health/live")
        assert parse_traceparent(r2.headers["traceparent"]) not in (None, GOOD)
