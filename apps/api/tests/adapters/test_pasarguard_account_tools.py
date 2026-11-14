"""PasarGuard Phase 3 / PG-10: account tools (usage, last seen, devices, link rotation, suspend/resume, compensation).

Rules under test: one core service for three roles; a tool a role does not have never reaches the panel; a panel that cannot do a
tool reports it unavailable; customers never see per-node detail or presence; writes are audited; compensation is admin-only and
absolute."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_order, make_product, make_store, make_user, open_schema_engine
from melorin.core.errors import AppError
from melorin.kernel.models.system import AuditEvent
from melorin.kernel.models.vpn import Panel, VpnAccount
from melorin.modules.vpn_accounts import account_tools as tools
from melorin.modules.panel_integrations.adapters.base import Capabilities, ErrorKind, PanelAccount, PanelError

GIB = 1024**3
NOW = dt.datetime.now(dt.UTC)


class FakeAdapter:
    kind = "pasarguard"

    def __init__(self, *, caps=None, fail=None):
        self.caps = caps or Capabilities(
            suspend=True, extend=True, subscription_url=True, traffic_reset=True,
            subscription_rotate=True, usage_ops=True, device_ops=True,
        )  # fmt: skip
        self.fail, self.calls = fail, []
        self.remote = PanelAccount(
            username="acc1", ref="1", status="active", remote_status="active", expire_at=NOW + dt.timedelta(days=10),
            traffic_limit_bytes=10 * GIB, traffic_used_bytes=GIB, subscription_url="https://sub/old", links=["old"],
        )  # fmt: skip

    def capabilities(self):
        return self.caps

    def _go(self, name, *a, **kw):
        self.calls.append(name)
        if self.fail:
            raise PanelError(self.fail, "panel says no")

    async def get_usage(self, username, *, start=None, end=None, period="day"):
        self._go("usage")
        return [
            {"period_start": "2026-11-01", "node_id": 1, "total": 100},
            {"period_start": "2026-11-01", "node_id": 2, "total": 50},
            {"period_start": "2026-11-02", "node_id": 1, "total": 10},
        ]

    async def list_devices(self, username):
        self._go("list_devices")
        return [{"hwid": "abcdef123456", "device_model": "Pixel 8", "platform": "android"}, {"hwid": ""}]

    async def delete_device(self, username, hwid):
        self._go("delete_device")

    async def reset_devices(self, username):
        self._go("reset_devices")

    async def rotate_subscription(self, username):
        self._go("rotate")
        self.remote.subscription_url, self.remote.links = "https://sub/new", ["new"]
        return self.remote

    async def suspend_account(self, username):
        self._go("suspend")

    async def resume_account(self, username):
        self._go("resume")

    async def get_account(self, username):
        self._go("get_account")
        return self.remote

    async def extend_account(self, username, *, expire_at, traffic_bytes):
        self._go("extend")
        self.remote.expire_at, self.remote.traffic_limit_bytes = expire_at, traffic_bytes
        return self.remote

    async def close(self):
        pass


@pytest.fixture
async def maker():
    async with open_schema_engine() as engine:
        yield async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def adapter(monkeypatch):
    fake = FakeAdapter()
    monkeypatch.setattr(tools, "build_adapter", lambda panel, server=None: fake)
    monkeypatch.setattr(tools, "seed_adapter", lambda a, acc: None)
    tools._last_rotate.clear()
    return fake


async def _account(s, *, status="active", expires=None):
    store, user, product = await make_store(s, kind="main"), await make_user(s), await make_product(s)
    panel = Panel(name="P", kind="pasarguard", base_url="https://p.example.com", config={}, is_enabled=True, health_status="healthy")
    s.add(panel)
    await s.flush()
    order = await make_order(s, user=user, store=store, product=product, status="completed")
    acc = VpnAccount(
        username="acc1", user_id=user.id, store_id=store.id, order_id=order.id, product_id=product.id, panel_id=panel.id, status=status,
        sold_expires_at=expires or NOW + dt.timedelta(days=10), sold_traffic_bytes=10 * GIB,     )  # fmt: skip
    s.add(acc)
    await s.commit()
    return acc, panel, user


async def _audits(s, action):
    return list(await s.scalars(select(AuditEvent).where(AuditEvent.action == action)))


# ---------------------------------------------------------------------------------------------------------------- the matrix
async def test_matrix_lists_only_the_tools_of_the_role_with_reasons(maker):
    async with maker() as s:
        acc, panel, _ = await _account(s)
        cust = {t["tool"]: t for t in tools.available(acc, tools.CUSTOMER, panel)}
        assert set(cust) == {"usage", "devices", "devices_manage", "rotate"}  # no presence, suspend or compensation for a customer
        assert all(t["available"] for t in cust.values())
        assert {t["tool"] for t in tools.available(acc, tools.OWNER, panel)} >= {"presence", "suspend"}
        assert "adjust" not in {t["tool"] for t in tools.available(acc, tools.OWNER, panel)}
        assert "adjust" in {t["tool"] for t in tools.available(acc, tools.ADMIN, panel)}


async def test_archived_or_unprovisioned_accounts_have_no_tools(maker):
    async with maker() as s:
        acc, panel, _ = await _account(s, status="revoked")
        rows = tools.available(acc, tools.ADMIN, panel)
        assert rows and not any(t["available"] for t in rows) and "وضعیتی نیست" in rows[0]["reason"]


async def test_panel_without_a_capability_reports_it_unavailable_and_is_never_called(maker, adapter):
    async with maker() as s:
        acc, panel, _ = await _account(s)
        panel.capabilities = {
            "flags": Capabilities(suspend=True, extend=True).to_dict()
        }  # a credential that probed without device/usage rights
        rows = {t["tool"]: t for t in tools.available(acc, tools.CUSTOMER, panel)}
        assert not rows["devices"]["available"] and "پشتیبانی" in rows["devices"]["reason"]
        with pytest.raises(AppError) as e:
            await tools.devices(s, acc, role=tools.CUSTOMER)
        assert e.value.code == "TOOL_UNAVAILABLE" and e.value.status == 409 and adapter.calls == []


async def test_a_role_without_the_tool_is_refused_before_any_panel_call(maker, adapter):
    async with maker() as s:
        acc, _, user = await _account(s)
        for call in (
            tools.suspend(s, acc, role=tools.CUSTOMER, actor_id=user.id),
            tools.adjust(s, acc, role=tools.OWNER, actor_id=user.id, add_days=1, reason="خرابی"),
        ):
            with pytest.raises(AppError) as e:
                await call
            assert e.value.status == 403
        with pytest.raises(AppError):
            await tools.presence(s, acc, tools.CUSTOMER)
        assert adapter.calls == []


# ---------------------------------------------------------------------------------------------------------------- read tools
async def test_usage_is_summed_per_period_and_customers_get_no_node_detail(maker, adapter):
    async with maker() as s:
        acc, _, _ = await _account(s)
        mine = await tools.usage(s, acc, role=tools.CUSTOMER, days=7)
        assert mine["points"] == [{"at": "2026-11-01", "used_bytes": 150}, {"at": "2026-11-02", "used_bytes": 10}]
        assert mine["total_bytes"] == 160 and mine["by_node"] == [] and mine["days"] == 7
        owner = await tools.usage(s, acc, role=tools.OWNER)
        assert len(owner["by_node"]) == 3
        with pytest.raises(AppError) as e:
            await tools.usage(s, acc, role=tools.CUSTOMER, period="week")
        assert e.value.code == "BAD_PERIOD"


async def test_presence_reads_the_panel_live_and_never_a_stored_copy(maker, adapter):
    async with maker() as s:
        acc, _, _ = await _account(s)  # the row stores no ``online_at`` any more (R7)
        # fresh clock, not the import-time NOW: a slow CI run would otherwise age this past the 5-minute "online" window
        adapter.remote.online_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=2)
        adapter.remote.lifetime_used_bytes = 7 * GIB
        adapter.get_account_calls = 0

        async def get_account(username):
            adapter.get_account_calls += 1
            return adapter.remote

        adapter.get_account = get_account
        p = await tools.presence(s, acc, tools.OWNER)
        assert p["live"] and p["online_now"] and not p["never_connected"] and p["lifetime_used_bytes"] == 7 * GIB
        assert "ip" not in "".join(p)
        adapter.remote.online_at = None
        assert (await tools.presence(s, acc, tools.ADMIN))["never_connected"]
        assert adapter.get_account_calls == 2  # every call asks the panel


async def test_presence_with_the_panel_down_shows_nothing_instead_of_an_old_number(maker, adapter):
    async with maker() as s:
        acc, _, _ = await _account(s)

        async def get_account(username):
            raise PanelError(ErrorKind.TRANSIENT, "down")

        adapter.get_account = get_account
        p = await tools.presence(s, acc, tools.OWNER)
        assert p["live"] is False and p["note"]
        assert p["online_at"] is None and p["lifetime_used_bytes"] is None and not p["online_now"]


async def test_presence_stays_closed_to_customers(maker, adapter):
    async with maker() as s:
        acc, _, _ = await _account(s)
        with pytest.raises(AppError) as e:
            await tools.presence(s, acc, tools.CUSTOMER)
        assert e.value.status == 403


async def test_devices_listing_drops_rows_without_an_id(maker, adapter):
    async with maker() as s:
        acc, _, _ = await _account(s)
        out = await tools.devices(s, acc, role=tools.CUSTOMER)
        assert out["items"] == [{"hwid": "abcdef123456", "label": "Pixel 8", "platform": "android", "first_seen": None, "last_seen": None}]


async def test_panel_errors_become_safe_client_errors(maker, adapter):
    async with maker() as s:
        acc, _, _ = await _account(s)
        adapter.fail = ErrorKind.TRANSIENT
        with pytest.raises(AppError) as e:
            await tools.usage(s, acc, role=tools.CUSTOMER)
        assert e.value.code == "PANEL_UNAVAILABLE" and e.value.status == 503 and "panel says no" not in e.value.message
        adapter.fail = ErrorKind.PERMANENT
        with pytest.raises(AppError) as e2:
            await tools.devices(s, acc, role=tools.CUSTOMER)
        assert e2.value.code == "PANEL_REJECTED"


# ---------------------------------------------------------------------------------------------------------------- write tools
async def test_device_delete_and_reset_are_audited_with_the_acting_role(maker, adapter):
    async with maker() as s:
        acc, _, user = await _account(s)
        await tools.delete_device(s, acc, role=tools.CUSTOMER, actor_id=user.id, hwid="abcdef123456")
        await tools.reset_devices(s, acc, role=tools.OWNER, actor_id=user.id)
        (deleted,), (reset,) = await _audits(s, "vpn_account.device_deleted"), await _audits(s, "vpn_account.devices_reset")
        assert deleted.data["hwid_prefix"] == "abcdef" and "abcdef123456" not in str(deleted.data)  # never the full device id
        assert reset.actor_type == "reseller" and reset.store_id == acc.store_id
        with pytest.raises(AppError):
            await tools.delete_device(s, acc, role=tools.CUSTOMER, actor_id=user.id, hwid="  ")


async def test_rotate_updates_the_link_audits_and_is_rate_limited(maker, adapter):
    async with maker() as s:
        acc, _, user = await _account(s)
        await tools.rotate_subscription(s, acc, role=tools.CUSTOMER, actor_id=user.id)
        assert not hasattr(acc, "subscription_url")  # the current link lives on the panel; nothing is copied onto the account
        assert len(await _audits(s, "vpn_account.subscription_rotated")) == 1
        with pytest.raises(AppError) as e:
            await tools.rotate_subscription(s, acc, role=tools.CUSTOMER, actor_id=user.id)
        assert e.value.status == 429 and adapter.calls.count("rotate") == 1


async def test_suspend_then_resume_roundtrip_with_guards(maker, adapter):
    async with maker() as s:
        acc, _, user = await _account(s)
        await tools.suspend(s, acc, role=tools.OWNER, actor_id=user.id, reason="عدم پرداخت")
        assert acc.status == "suspended" and "suspend" in adapter.calls  # the panel was switched off; the raw status is not stored
        (event,) = await _audits(s, "vpn_account.suspended")
        assert event.data["reason"] == "عدم پرداخت"
        await tools.resume(s, acc, role=tools.ADMIN, actor_id=user.id)
        assert acc.status == "active"
        with pytest.raises(AppError) as e:  # already active: nothing to resume
            await tools.resume(s, acc, role=tools.ADMIN, actor_id=user.id)
        assert e.value.code == "ACCOUNT_NOT_SUSPENDED"


async def test_expired_or_limited_accounts_cannot_be_suspended_and_expired_ones_not_resumed(maker, adapter):
    async with maker() as s:
        acc, _, user = await _account(s, status="limited")
        with pytest.raises(AppError) as e:
            await tools.suspend(s, acc, role=tools.ADMIN, actor_id=user.id)
        assert e.value.code == "ACCOUNT_NOT_ACTIVE"
        acc.status, acc.sold_expires_at = "suspended", NOW - dt.timedelta(days=1)
        with pytest.raises(AppError) as e2:
            await tools.resume(s, acc, role=tools.ADMIN, actor_id=user.id)
        assert e2.value.code == "ACCOUNT_NOT_SUSPENDED" and "resume" not in adapter.calls


# ---------------------------------------------------------------------------------------------------------------- compensation
async def test_adjust_adds_on_top_of_the_panels_fresh_state_and_audits_before_after(maker, adapter):
    async with maker() as s:
        acc, _, admin = await _account(s)
        before = adapter.remote.expire_at
        await tools.adjust(s, acc, actor_id=admin.id, add_days=3, add_traffic_gb=5, reason="قطعی نود")
        assert adapter.remote.expire_at == before + dt.timedelta(days=3) and adapter.remote.traffic_limit_bytes == 15 * GIB
        assert acc.sold_traffic_bytes == 15 * GIB and acc.sold_expires_at == adapter.remote.expire_at
        (event,) = await _audits(s, "vpn_account.adjusted")
        assert event.data["add_days"] == 3 and event.data["before"]["traffic_limit_bytes"] == 10 * GIB
        assert event.data["after"]["traffic_limit_bytes"] == 15 * GIB and event.actor_type == "admin"


async def test_adjust_validates_reason_amounts_and_unlimited_accounts(maker, adapter):
    async with maker() as s:
        acc, _, admin = await _account(s)
        for kwargs, code in (
            ({"add_days": 1, "reason": " "}, "REASON_REQUIRED"),
            ({"add_days": 0, "add_traffic_gb": 0, "reason": "xyz"}, "BAD_ADJUSTMENT"),
            ({"add_days": 9999, "reason": "xyz"}, "BAD_ADJUSTMENT"),
        ):
            with pytest.raises(AppError) as e:
                await tools.adjust(s, acc, actor_id=admin.id, **kwargs)
            assert e.value.code == code
        adapter.remote.traffic_limit_bytes = 0  # unlimited volume
        with pytest.raises(AppError) as e2:
            await tools.adjust(s, acc, actor_id=admin.id, add_traffic_gb=1, reason="xyz")
        assert e2.value.code == "UNLIMITED_TRAFFIC" and "extend" not in adapter.calls
        adapter.remote.expire_at = None
        with pytest.raises(AppError) as e3:
            await tools.adjust(s, acc, actor_id=admin.id, add_days=1, reason="xyz")
        assert e3.value.code == "UNLIMITED_TIME"


async def test_adjust_on_an_expired_account_counts_from_now_not_from_the_past(maker, adapter):
    async with maker() as s:
        acc, _, admin = await _account(s)
        adapter.remote.expire_at = NOW - dt.timedelta(days=30)
        await tools.adjust(s, acc, actor_id=admin.id, add_days=2, reason="جبران")
        assert adapter.remote.expire_at > NOW + dt.timedelta(days=1, hours=23)


# ---------------------------------------------------------------------------------------------------------------- HTTP surface
def test_routes_exist_per_role_and_privileged_tools_are_not_registered_for_lower_roles():
    from melorin.modules.vpn_accounts.tools_router import router

    paths = {(m, r.path) for r in router.routes for m in r.methods}
    cust, own, adm = (
        "/stores/{store_id}/vpn-accounts/{account_id}/tools",
        "/stores/{store_id}/reseller/accounts/{account_id}/tools",
        "/admin/vpn-accounts/{account_id}/tools",
    )
    for base in (cust, own, adm):
        for method, suffix in (
            ("GET", ""),
            ("GET", "/usage"),
            ("GET", "/devices"),
            ("DELETE", "/devices/{hwid}"),
            ("POST", "/devices/reset"),
            ("POST", "/rotate-subscription"),
        ):
            assert (method, base + suffix) in paths
    for suffix in ("/presence", "/suspend", "/resume", "/adjust"):
        assert ("GET", cust + suffix) not in paths and ("POST", cust + suffix) not in paths
    assert ("POST", own + "/suspend") in paths and ("POST", own + "/adjust") not in paths
    assert ("POST", adm + "/adjust") in paths and ("GET", adm + "/presence") in paths
