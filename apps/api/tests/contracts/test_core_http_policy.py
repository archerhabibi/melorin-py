"""Outbound HTTP policy (T-R04): one factory, bounded timeouts, no redirects by default, per-purpose metrics."""

import re
from pathlib import Path

import httpx
import pytest

from melorin.core import metrics
from melorin.core.http import DEFAULT_TIMEOUT, USER_AGENT, outbound_client

SRC = Path(__file__).resolve().parents[2] / "melorin"
DIRECT = re.compile(r"\bhttpx\.(AsyncClient|Client)\(")


def test_no_module_builds_an_httpx_client_directly():
    offenders = [str(p.relative_to(SRC)) for p in SRC.rglob("*.py") if p.name != "http.py" and DIRECT.search(p.read_text(encoding="utf-8"))]
    assert offenders == [], f"use melorin.core.http.outbound_client instead: {offenders}"


def test_purpose_label_is_validated():
    for bad in ("", "has space", "http://x", "a-b"):
        with pytest.raises(ValueError):
            outbound_client(bad)


async def test_defaults_do_not_follow_redirects_and_send_a_user_agent():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

    async with outbound_client("unit_test", transport=httpx.MockTransport(handler)) as c:
        r = await c.get("https://example.test/")
        assert c.timeout == DEFAULT_TIMEOUT
    assert r.status_code == 302 and seen["ua"] == USER_AGENT


async def test_callers_can_override_timeout_and_redirects():
    async with outbound_client(
        "unit_test", timeout=3, follow_redirects=True, transport=httpx.MockTransport(lambda r: httpx.Response(200))
    ) as c:
        assert c.timeout == httpx.Timeout(3) and c.follow_redirects is True


async def test_every_response_is_counted_and_timed_per_purpose():
    metrics.reset()
    async with outbound_client("unit_metrics", transport=httpx.MockTransport(lambda r: httpx.Response(204))) as c:
        await c.get("https://example.test/")
    rendered = metrics.render()
    assert 'melorin_outbound_http_total{purpose="unit_metrics",status="2xx"} 1' in rendered
    assert 'melorin_outbound_http_seconds_count{purpose="unit_metrics"} 1' in rendered
