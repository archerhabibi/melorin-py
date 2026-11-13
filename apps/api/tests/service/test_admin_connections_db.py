"""Decision 5: connection IPs and subscription-fetch history are an ADMIN-ONLY view, read live from the panel, never stored.

Owners and customers never reach the panel for it; the audit row of an admin view carries counts, never the IPs; one half can fail
without hiding the other; both failing is a panel error."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_order, make_product, make_store, make_user, open_schema_engine
from melorin.core.errors import AppError
from melorin.kernel.models.system import AuditEvent
from melorin.kernel.models.vpn import Panel, VpnAccount
from melorin.modules.vpn import account_tools as tools
from melorin.modules.panel_integrations.adapters.base import Capabilities, ErrorKind, PanelError
from melorin.modules.panel_integrations.adapters.pasarguard import PasarGuardAdapter

NOW = dt.datetime.now(dt.UTC)
IP_A, IP_B = "203.0.113.7", "198.51.100.9"


class Fake:
    kind = "pasarguard"

    def __init__(self, *, ips_fail=False, history_fail=False):
        self.ips_fail, self.history_fail, self.calls = ips_fail, history_fail, []
        self.caps = Capabilities(suspend=True, extend=True, subscription_url=True, ip_ops=True)

    def capabilities(self):
        return self.caps

    async def online_ips(self, username):
        self.calls.append("ips")
        if self.ips_fail:
            raise PanelError(ErrorKind.TRANSIENT, "node down")
        return [{"node_id": 1, "ip": IP_A, "connections": 2}]

    async def subscription_updates(self, username, *, limit=20, offset=0):
        self.calls.append(("history", limit, offset))
        if self.history_fail:
            raise PanelError(ErrorKind.TRANSIENT, "slow")
        return {"count": 41, "items": [{"created_at": "2026-11-08T10:00:00Z", "user_agent": "v2rayN", "ip": IP_B, "hwid": None}]}

    async def close(self):
        pass


@pytest.fixture
async def maker():
    async with open_schema_engine() as engine:
        yield async_sessionmaker(engine, expire_on_commit=False)


def _patch(monkeypatch, fake):
    monkeypatch.setattr(tools, "build_adapter", lambda panel, server=None: fake)
    monkeypatch.setattr(tools, "seed_adapter", lambda a, acc: None)


async def _account(s):
    store, user, product = await make_store(s, kind="main"), await make_user(s), await make_product(s)
    panel = Panel(name="P", kind="pasarguard", base_url="https://p.example.com", config={}, is_enabled=True, health_status="healthy")
    s.add(panel)
    await s.flush()
    order = await make_order(s, user=user, store=store, product=product, status="completed")
    acc = VpnAccount(
        username="acc1", user_id=user.id, store_id=store.id, order_id=order.id, product_id=product.id, panel_id=panel.id,
        status="active", sold_expires_at=NOW + dt.timedelta(days=10), sold_traffic_bytes=1,     )  # fmt: skip
    s.add(acc)
    await s.commit()
    return acc, panel, user


async def test_only_the_admin_has_the_tool(maker):
    async with maker() as s:
        acc, panel, _ = await _account(s)
        for role in (tools.CUSTOMER, tools.OWNER):
            assert "connections" not in {t["tool"] for t in tools.available(acc, role, panel)}
        assert "connections" in {t["tool"] for t in tools.available(acc, tools.ADMIN, panel)}


async def test_owner_and_customer_are_refused_before_any_panel_call(maker, monkeypatch):
    fake = Fake()
    _patch(monkeypatch, fake)
    async with maker() as s:
        acc, _, user = await _account(s)
        for role in (tools.CUSTOMER, tools.OWNER):
            with pytest.raises(AppError) as e:
                await tools.connections(s, acc, role=role, actor_id=user.id)
            assert e.value.status == 403
        assert fake.calls == []


async def test_admin_sees_both_halves_and_the_audit_row_holds_no_ip(maker, monkeypatch):
    fake = Fake()
    _patch(monkeypatch, fake)
    async with maker() as s:
        acc, _, user = await _account(s)
        out = await tools.connections(s, acc, role=tools.ADMIN, actor_id=user.id, limit=500, offset=-3)
        assert out["online_available"] and out["online_ips"][0]["ip"] == IP_A
        assert out["history_available"] and out["history_count"] == 41 and out["history"][0]["ip"] == IP_B
        assert (out["limit"], out["offset"]) == (tools.MAX_FETCH_HISTORY, 0)  # clamped
        rows = list(await s.scalars(select(AuditEvent).where(AuditEvent.action == "vpn_account.connections_viewed")))
        assert len(rows) == 1 and rows[0].data["online_ips"] == 1 and rows[0].data["fetches"] == 1
        assert IP_A not in str(rows[0].data) and IP_B not in str(rows[0].data)


async def test_one_half_failing_keeps_the_other(maker, monkeypatch):
    _patch(monkeypatch, Fake(ips_fail=True))
    async with maker() as s:
        acc, _, user = await _account(s)
        out = await tools.connections(s, acc, role=tools.ADMIN, actor_id=user.id)
        assert not out["online_available"] and out["online_ips"] == [] and out["history_available"] and out["history"]


async def test_both_failing_is_a_panel_error_and_nothing_is_audited(maker, monkeypatch):
    _patch(monkeypatch, Fake(ips_fail=True, history_fail=True))
    async with maker() as s:
        acc, _, user = await _account(s)
        with pytest.raises(AppError) as e:
            await tools.connections(s, acc, role=tools.ADMIN, actor_id=user.id)
        assert e.value.code == "PANEL_UNAVAILABLE"
        assert not list(await s.scalars(select(AuditEvent).where(AuditEvent.action == "vpn_account.connections_viewed")))


async def test_panel_without_ip_ops_is_unavailable_and_never_called(maker, monkeypatch):
    fake = Fake()
    _patch(monkeypatch, fake)
    async with maker() as s:
        acc, panel, user = await _account(s)
        panel.capabilities = {"flags": Capabilities(suspend=True, extend=True).to_dict()}
        with pytest.raises(AppError) as e:
            await tools.connections(s, acc, role=tools.ADMIN, actor_id=user.id)
        assert e.value.code == "TOOL_UNAVAILABLE" and fake.calls == []


# ------------------------------------------------------------------------------------------------ the real adapter parser
def _adapter(handler):
    return PasarGuardAdapter("https://p.example.com", {"api_key": "k"}, {"group_ids": [1]}, transport=httpx.MockTransport(handler))


def _panel(ip_body, sub_body):
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.path, dict(req.url.params)))
        path = req.url.path
        if path.endswith("/online_stats/7/ip"):
            return httpx.Response(200, json=ip_body)
        if path.endswith("/by-id/7/sub_update"):
            return httpx.Response(200, json=sub_body)
        if path.startswith("/api/user/by-username/"):
            return httpx.Response(200, json={"id": 7, "username": "acc1", "status": "active", "used_traffic": 0, "data_limit": 0})
        return httpx.Response(404, json={"detail": "no"})

    return handler, seen


async def test_adapter_parses_nodes_skips_down_nodes_and_paginates():
    handler, seen = _panel(
        {"nodes": {"2": {"ips": {IP_B: 1}}, "1": {"ips": {IP_A: 3}}, "3": None}},
        {"count": 2, "updates": [{"created_at": "2026-11-08T10:00:00Z", "user_agent": "ua", "ip": IP_A, "hwid": "h"}, "junk"]},
    )
    a = _adapter(handler)
    try:
        rows = await a.online_ips("acc1")
        assert [(r["node_id"], r["ip"], r["connections"]) for r in rows] == [(1, IP_A, 3), (2, IP_B, 1)]
        hist = await a.subscription_updates("acc1", limit=9999, offset=-5)
        assert hist["count"] == 2 and len(hist["items"]) == 1 and hist["items"][0]["user_agent"] == "ua"
        assert seen[-1][2] == {"limit": "100", "offset": "0"}  # clamped before it reaches the panel
    finally:
        await a.close()


async def test_adapter_tolerates_odd_payloads():
    handler, _ = _panel({"nodes": None}, {"updates": None})
    a = _adapter(handler)
    try:
        assert await a.online_ips("acc1") == []
        assert await a.subscription_updates("acc1") == {"count": 0, "items": []}
    finally:
        await a.close()
