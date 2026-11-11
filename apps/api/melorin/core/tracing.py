"""Dependency-free W3C Trace Context (audit T-G06 / T-R13).

No collector or SDK is required: an inbound ``traceparent`` is honoured (so a front proxy or caller can correlate), otherwise a
fresh trace id is made. The id is echoed on the response, written to every log line and forwarded on outbound HTTP, so one
request can be followed across Core, the worker's calls and the panels. An OpenTelemetry exporter can later read
``context.trace_id`` without touching call sites.
"""

from __future__ import annotations

import re
import secrets

_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")


def new_trace_id() -> str:
    return secrets.token_hex(16)


def new_span_id() -> str:
    return secrets.token_hex(8)


def parse_traceparent(value: str | None) -> str | None:
    """Return the trace id of a valid ``traceparent`` header, else ``None`` (all-zero ids are invalid per the spec)."""
    m = _TRACEPARENT.match((value or "").strip().lower())
    if not m or m.group(1) == "0" * 32 or m.group(2) == "0" * 16:
        return None
    return m.group(1)


def format_traceparent(trace_id: str, span_id: str | None = None) -> str:
    return f"00-{trace_id}-{span_id or new_span_id()}-01"
