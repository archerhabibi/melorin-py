"""Dependency-free OTLP/HTTP span export (T-G06 / T-R13): off by default, correct JSON, bounded, failure-tolerant."""

import asyncio
import json

import httpx
import pytest

from melorin.core import otlp
from melorin.core.config import get_settings

TRACE = "0af7651916cd43dd8448eb211c80319c"
SPAN = "b7ad6b7169203331"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    otlp._queue.clear()
    yield
    otlp._queue.clear()


def _record(status=200):
    otlp.record_span(trace_id=TRACE, span_id=SPAN, method="GET", route="/api/v1/x", status_code=status, start_ns=1, end_ns=2)


def test_disabled_by_default_records_nothing(monkeypatch):
    monkeypatch.setattr(get_settings(), "otlp_endpoint", "")
    _record()
    assert not otlp._queue


def test_payload_is_valid_otlp_json_with_ids_and_status():
    span = otlp.build_span(
        trace_id=TRACE, span_id=SPAN, name="GET /x", start_ns=1, end_ns=2, attributes={"http.response.status_code": 503}, status_code=503
    )
    body = otlp.build_payload([span], "melorin-api")
    got = body["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert got["traceId"] == TRACE and got["spanId"] == SPAN and got["kind"] == 2 and got["status"]["code"] == 2
    assert got["attributes"][0]["value"] == {"intValue": "503"}
    assert body["resourceSpans"][0]["resource"]["attributes"][0]["value"]["stringValue"] == "melorin-api"


def test_flush_posts_batches_to_v1_traces(monkeypatch):
    monkeypatch.setattr(get_settings(), "otlp_endpoint", "http://collector:4318/")
    monkeypatch.setattr(otlp, "_ensure_flusher", lambda: None)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, json={})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    for _ in range(3):
        _record()
    assert asyncio.run(otlp.flush()) == 3
    assert seen[0][0] == "http://collector:4318/v1/traces"
    assert len(seen[0][1]["resourceSpans"][0]["scopeSpans"][0]["spans"]) == 3
    assert not otlp._queue


def test_collector_down_never_raises_and_queue_stays_bounded(monkeypatch):
    monkeypatch.setattr(get_settings(), "otlp_endpoint", "http://collector:4318")
    monkeypatch.setattr(otlp, "_ensure_flusher", lambda: None)

    def handler(request):
        raise httpx.ConnectError("down")

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    for _ in range(otlp.QUEUE_MAX + 50):
        _record()
    assert len(otlp._queue) == otlp.QUEUE_MAX
    assert asyncio.run(otlp.flush()) == 0
