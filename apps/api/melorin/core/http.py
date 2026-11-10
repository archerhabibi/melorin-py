"""The one place that builds outbound HTTP clients (audit T-O02 / T-R04).

Before this module 20 files called ``httpx.AsyncClient`` directly, each with its own timeout, redirect and (no) metrics
policy. Everything that leaves the process now goes through :func:`outbound_client`, which fixes the policy once:

* a bounded default timeout (``DEFAULT_TIMEOUT``) so a hung peer can never pin a worker;
* redirects are **off** unless a caller opts in (an open redirect must not turn a vetted URL into an internal one);
* every response is counted and timed per ``purpose`` (``melorin_outbound_http_total`` / ``..._seconds``). ``purpose`` is
  a fixed, low-cardinality label chosen at the call site, never a URL, host or token;
* a stable ``User-Agent`` so operators of the peers can recognise the traffic.

SSRF filtering of *user-supplied* hosts (webhooks, domain verification) stays with the callers that know the allow rules
(``domain.webhook`` / ``reseller.auto_verify.host_is_public``); the guard test ``tests/test_core_http_policy.py`` keeps
new code from bypassing this module. ``httpx`` is looked up at call time so tests may still patch ``httpx.AsyncClient``.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from melorin.core import metrics

DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
USER_AGENT = "melorin-core/1"
_T0 = "melorin_t0"


def _status_class(code: int) -> str:
    return f"{code // 100}xx"


async def _on_request(request: httpx.Request) -> None:
    request.extensions[_T0] = time.monotonic()


def _make_response_hook(purpose: str):
    async def _on_response(response: httpx.Response) -> None:
        started = response.request.extensions.get(_T0)
        metrics.inc("melorin_outbound_http_total", purpose=purpose, status=_status_class(response.status_code))
        if isinstance(started, float):
            metrics.observe("melorin_outbound_http_seconds", time.monotonic() - started, purpose=purpose)

    return _on_response


def outbound_client(purpose: str, **kwargs: Any) -> httpx.AsyncClient:
    """Build an ``httpx.AsyncClient`` under the shared policy. ``kwargs`` go to httpx and may override the defaults."""
    if not purpose or not purpose.replace("_", "").isalnum():
        raise ValueError("purpose must be a short snake_case label")
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    kwargs.setdefault("follow_redirects", False)
    headers = {"user-agent": USER_AGENT, **dict(kwargs.pop("headers", None) or {})}
    hooks = kwargs.pop("event_hooks", None) or {}
    event_hooks = {
        "request": [_on_request, *hooks.get("request", [])],
        "response": [_make_response_hook(purpose), *hooks.get("response", [])],
    }
    return httpx.AsyncClient(headers=headers, event_hooks=event_hooks, **kwargs)
