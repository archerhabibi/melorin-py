"""Optional OpenTelemetry export without the OpenTelemetry SDK (audit T-G06 / T-R13).

With ``MELORIN_OTLP_ENDPOINT`` unset (the default) nothing happens: :func:`record_span` returns immediately. When it is set to an
OTLP/HTTP collector base URL (``http://otel-collector:4318``), every finished HTTP request becomes one server span that is sent
as OTLP JSON to ``<endpoint>/v1/traces`` in small batches. The span carries the same trace id the logs and the ``traceparent``
headers use, so a trace in the collector lines up with log lines and outbound calls.

Design choices: no new dependency (the JSON encoding is a stable public part of OTLP), a bounded in-memory queue (a dead collector
can never grow memory: the oldest spans are dropped and counted) and best-effort delivery (an export failure is a metric, never an
error in a request).
"""

from __future__ import annotations

import asyncio
import collections
import logging
import time
from typing import Any

import httpx

from melorin.core import metrics
from melorin.core.config import get_settings
from melorin.core.http import outbound_client

log = logging.getLogger("melorin.otlp")

QUEUE_MAX = 2048
BATCH_MAX = 200
FLUSH_SECONDS = 5.0
_SERVER_SPAN = 2  # SPAN_KIND_SERVER

_queue: collections.deque[dict[str, Any]] = collections.deque(maxlen=QUEUE_MAX)
_task: asyncio.Task[None] | None = None


def enabled() -> bool:
    return bool(get_settings().otlp_endpoint.strip())


def _attr(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": str(value)}}


def build_span(
    *, trace_id: str, span_id: str, name: str, start_ns: int, end_ns: int, attributes: dict[str, Any], status_code: int
) -> dict[str, Any]:
    failed = status_code >= 500
    return {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "kind": _SERVER_SPAN,
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(end_ns),
        "attributes": [_attr(k, v) for k, v in attributes.items()],
        "status": {"code": 2 if failed else 1},
    }


def build_payload(spans: list[dict[str, Any]], service_name: str) -> dict[str, Any]:
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [_attr("service.name", service_name)]},
                "scopeSpans": [{"scope": {"name": "melorin"}, "spans": spans}],
            }
        ]
    }


def record_span(*, trace_id: str, span_id: str, method: str, route: str, status_code: int, start_ns: int, end_ns: int) -> None:
    """Queue one finished request. Cheap and non-blocking; a no-op unless an endpoint is configured."""
    if not enabled():
        return
    if len(_queue) == QUEUE_MAX:
        metrics.inc("melorin_otlp_spans_dropped_total")
    _queue.append(
        build_span(
            trace_id=trace_id,
            span_id=span_id,
            name=f"{method} {route}",
            start_ns=start_ns,
            end_ns=end_ns,
            attributes={"http.request.method": method, "http.route": route, "http.response.status_code": status_code},
            status_code=status_code,
        )
    )
    _ensure_flusher()


def _ensure_flusher() -> None:
    global _task
    if _task is not None and not _task.done():
        return
    try:
        _task = asyncio.get_running_loop().create_task(_flush_loop())
    except RuntimeError:  # no running loop (sync caller): spans stay queued until a loop exists
        _task = None


async def flush() -> int:
    """Send everything queued, in batches. Returns the number of spans delivered."""
    settings = get_settings()
    url = settings.otlp_endpoint.rstrip("/") + "/v1/traces"
    sent = 0
    while _queue:
        batch = [_queue.popleft() for _ in range(min(BATCH_MAX, len(_queue)))]
        try:
            async with outbound_client("otlp_export", timeout=5.0) as client:
                resp = await client.post(url, json=build_payload(batch, settings.otlp_service_name))
                resp.raise_for_status()
            sent += len(batch)
            for _ in batch:
                metrics.inc("melorin_otlp_spans_exported_total")
        except (httpx.HTTPError, OSError):
            metrics.inc("melorin_otlp_export_failures_total")
            log.warning("OTLP export to %s failed; %d spans dropped", url, len(batch))
            break
    return sent


async def _flush_loop() -> None:
    while True:
        await asyncio.sleep(FLUSH_SECONDS)
        await flush()
        if not _queue:
            return  # restarted by the next span; an idle process keeps no timer alive


def now_ns() -> int:
    return time.time_ns()
