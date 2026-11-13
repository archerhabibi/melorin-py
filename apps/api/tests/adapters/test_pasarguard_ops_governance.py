"""PasarGuard Phase 4: ops console (PG-07), store governance (PG-12), subscription test (PG-13) and the admin API on top of them.

Rules under test: every action needs a reason and is audited; a core restart needs its name typed; the last connected node cannot be
disabled by accident; a credential without the capability never reaches the panel; the subscription probe only ever fetches hosts
Melorin was configured with; a store that did not opt in is untouched by a suspension."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_store, make_user, open_schema_engine
from _http import PASSWORD, add_user, api_client, totp_now
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.kernel.models.system import AuditEvent
from melorin.kernel.models.vpn import BulkOperation, Panel, PanelAdmin, PanelNode
from melorin.modules.panelops import governance, subscription_check
from melorin.modules.panelops import ops_console
from melorin.modules.vpn.adapters.base import Capabilities, ErrorKind, PanelError
from melorin.modules.vpn.adapters.pasarguard import PasarGuardAdapter

BASE = "/api/v1/admin"
GIB = 1024**3


class FakeOps:
    kind = "pasarguard"

    def __init__(self, *, caps=None):
        self.caps = caps or Capabilities(
            node_insight=True, node_control=True, infra_control=True, admin_governance=True, subscription_probe=True, capacity_ops=True
        )
        self.calls: list[tuple] = []
        self.fail: PanelError | None = None
        self.admin = {
            "id": 9,
            "username": "ml_shop",
            "total_users": 4,
            "used_traffic": 30 * GIB,
            "data_limit": 100 * GIB,
            "status": "active",
        }
        self.settings = {"url_prefix": "https://sub.example.com:1010"}
        self.probe = {"ok": True, "status": 200, "error": None}

    def capabilities(self):
        return self.caps

    def _go(self, *call):
        self.calls.append(call)
        if self.fail:
            raise self.fail

    async def get_system_stats(self):
        self._go("system")
        return {"version": "5.6.0", "online_users": 3, "cpu_usage": 12.5, "secret": {"nested": 1}}

    async def get_system_resources(self):
        self._go("resources")
        return {"cpu": 1.5, "mem": {"x": 1}}

    async def get_nodes_realtime(self):
        self._go("realtime")
        return {1: {"cpu_usage": 3.0, "uptime": 99, "junk": [1]}, 2: None}

    async def get_node_stats(self, node_id):
        self._go("node_stats", node_id)
        return {}

    async def list_nodes(self):
        return []

    async def get_node(self, node_id):
        return None

    async def reconnect_node(self, node_id):
        self._go("reconnect", node_id)

    async def bulk_users_action(self, refs, action):
        return len(refs)

    async def set_admin_users_state(self, remote_id, *, active):
        return None

    async def sync_node(self, node_id):
        self._go("sync", node_id)

    async def list_cores(self):
        self._go("cores")
        return [{"id": 1, "name": "xray-main"}]

    async def restart_core(self, core_id):
        self._go("restart", core_id)

    async def set_nodes_disabled(self, ids, disabled):
        self._go("nodes", tuple(ids), disabled)

    async def set_hosts_disabled(self, ids, disabled):
        self._go("hosts", tuple(ids), disabled)

    async def set_groups_disabled(self, ids, disabled):
        self._go("groups", tuple(ids), disabled)

    async def list_groups_full(self):
        return [{"id": 1, "name": "VIP1", "is_disabled": False, "total_users": 4}]

    async def list_inbound_details(self):
        return []

    async def list_hosts(self):
        return [{"id": 5, "remark": "h", "inbound_tag": "vless", "is_disabled": True}]

    async def get_admin_detail(self, remote_id):
        self._go("admin_detail", remote_id)
        return self.admin if remote_id == 9 else None

    async def update_admin_limits(self, remote_id, *, data_limit=None, status=None, notifications_off=None):
        self._go("admin_update", remote_id, data_limit, status, notifications_off)
        return {"status": status or self.admin["status"]}

    async def get_subscription_settings(self):
        self._go("sub_settings")
        return self.settings

    async def probe_subscription(self, url, *, allowed_hosts):
        self._go("probe", url, frozenset(allowed_hosts))
        return self.probe

    async def check_health(self):
        return None

    async def close(self):
        pass


@pytest.fixture
def fake(monkeypatch):
    f = FakeOps()
    for module in (ops_console, governance, subscription_check):
        monkeypatch.setattr(module, "build_adapter", lambda panel, server=None, _f=f: _f)

    # the console refreshes node health after an action; the health layer is covered by its own tests
    async def _noop(session, panel, adapter, **kw):
        class R:
            status = "healthy"
            detail = {}

        return R()

    monkeypatch.setattr(ops_console.health, "check_panel", _noop)
    monkeypatch.setattr(ops_console.health, "apply", lambda panel, result, now=None: "healthy")
    return f


async def _panel(s, *, kind="pasarguard", config=None):
    panel = Panel(
        name="pg", kind=kind, base_url="https://panel.example.com", config=config or {}, health_status="healthy", last_health_at=utcnow()
    )
    s.add(panel)
    await s.flush()
    s.add_all(
        [
            PanelNode(panel_id=panel.id, remote_id=1, name="ok-node", status="connected", status_changed_at=utcnow()),
            PanelNode(
                panel_id=panel.id,
                remote_id=2,
                name="bad-node",
                status="error",
                message="CERTIFICATE_VERIFY_FAILED (self-signed)",
                status_changed_at=utcnow(),
            ),
        ]
    )
    await s.commit()
    return panel


def _actions(rows):
    return [a.action for a in rows]


async def _audit(s):
    return (await s.scalars(select(AuditEvent))).all()


# --------------------------------------------------------------------------------------------------------------- PG-07 read
async def test_overview_merges_live_stats_with_node_rows_and_hints(fake):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        panel = await _panel(s)
        out = await ops_console.overview(s, panel.id)
        assert out["system"] == {"version": "5.6.0", "online_users": 3, "cpu_usage": 12.5}  # nested junk never leaks to the UI
        assert out["resources"] == {"cpu": 1.5}
        by = {n["name"]: n for n in out["nodes"]}
        assert by["ok-node"]["realtime"] == {"cpu_usage": 3.0, "uptime": 99} and by["ok-node"]["hint"] is None
        assert "server_ca" in by["bad-node"]["hint"] and by["bad-node"]["realtime"] is None
        assert out["errors"] == {}


async def test_one_failing_section_does_not_hide_the_others(fake):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        panel = await _panel(s)

        async def boom():
            raise PanelError(ErrorKind.PERMANENT, "403 system.read")

        fake.get_system_stats = boom
        out = await ops_console.overview(s, panel.id)
        assert "system" in out["errors"] and out["system"] is None and out["resources"] == {"cpu": 1.5} and len(out["nodes"]) == 2


async def test_overview_without_insight_capability_says_so_and_calls_nothing(monkeypatch):
    limited = FakeOps(caps=Capabilities())
    monkeypatch.setattr(ops_console, "build_adapter", lambda panel, server=None: limited)
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        panel = await _panel(s)
        out = await ops_console.overview(s, panel.id)
        assert "insight" in out["errors"] and limited.calls == [] and out["nodes"]


async def test_non_pasarguard_panels_are_refused(fake):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        panel = await _panel(s, kind="sanaei")
        with pytest.raises(AppError) as e:
            await ops_console.overview(s, panel.id)
        assert e.value.code == "OPS_NOT_SUPPORTED"


# -------------------------------------------------------------------------------------------------------------- PG-07 writes
async def test_node_actions_need_a_reason_hit_the_panel_and_are_audited(fake):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        panel = await _panel(s)
        admin = await make_user(s, super_admin=True)
        with pytest.raises(AppError) as e:
            await ops_console.node_action(s, panel.id, 2, "reconnect", admin_id=admin.id, reason=" ")
        assert e.value.code == "REASON_REQUIRED" and fake.calls == []
        assert (await ops_console.node_action(s, panel.id, 2, "reconnect", admin_id=admin.id, reason="گواهی اصلاح شد"))[
            "node"
        ] == "bad-node"
        await ops_console.node_action(s, panel.id, 2, "sync", admin_id=admin.id, reason="ارسال دوباره تنظیمات")
        assert [c for c in fake.calls if c[0] in ("reconnect", "sync")] == [("reconnect", 2), ("sync", 2)]
        assert {"panel.ops.node_reconnect", "panel.ops.node_sync"} <= set(_actions(await _audit(s)))
        with pytest.raises(AppError) as e:
            await ops_console.node_action(s, panel.id, 99, "reconnect", admin_id=admin.id, reason="نود ناشناس")
        assert e.value.status == 404


async def test_panel_refusal_becomes_a_clean_502_and_nothing_is_audited(fake):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        panel = await _panel(s)
        admin = await make_user(s, super_admin=True)
        fake.fail = PanelError(ErrorKind.PERMANENT, "403 nodes.reconnect")
        with pytest.raises(AppError) as e:
            await ops_console.node_action(s, panel.id, 2, "reconnect", admin_id=admin.id, reason="تلاش دوباره")
        assert e.value.status == 502 and not [a for a in await _audit(s) if a.action.startswith("panel.ops.")]


async def test_core_restart_needs_the_typed_name(fake):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        panel = await _panel(s)
        admin = await make_user(s, super_admin=True)
        for wrong in ("", "xray", "XRAY-MAIN"):
            with pytest.raises(AppError) as e:
                await ops_console.core_restart(s, panel.id, 1, admin_id=admin.id, reason="به‌روزرسانی", confirm_name=wrong)
            assert e.value.code == "CONFIRM_NAME_MISMATCH"
        assert not [c for c in fake.calls if c[0] == "restart"]
        await ops_console.core_restart(s, panel.id, 1, admin_id=admin.id, reason="به‌روزرسانی", confirm_name="xray-main")
        assert [c for c in fake.calls if c[0] == "restart"] == [("restart", 1)]
        with pytest.raises(AppError) as e:
            await ops_console.core_restart(s, panel.id, 77, admin_id=admin.id, reason="هسته ناموجود", confirm_name="x")
        assert e.value.status == 404


async def test_disabling_the_last_connected_node_needs_force(fake):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        panel = await _panel(s)
        admin = await make_user(s, super_admin=True)
        with pytest.raises(AppError) as e:
            await ops_console.toggle(s, panel.id, "nodes", [1], True, admin_id=admin.id, reason="نگهداری")
        assert e.value.code == "LAST_NODE" and not [c for c in fake.calls if c[0] == "nodes"]
        await ops_console.toggle(
            s, panel.id, "nodes", [2], True, admin_id=admin.id, reason="نود خراب"
        )  # a failing node may always be turned off
        await ops_console.toggle(s, panel.id, "nodes", [1], True, admin_id=admin.id, reason="نگهداری برنامه‌ریزی‌شده", force=True)
        assert [c for c in fake.calls if c[0] == "nodes"] == [("nodes", (2,), True), ("nodes", (1,), True)]


async def test_toggle_validates_family_ids_and_capability(fake, monkeypatch):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        panel = await _panel(s)
        admin = await make_user(s, super_admin=True)
        for bad_family, ids in (("users", [1]), ("hosts", []), ("hosts", [0, -3])):
            with pytest.raises(AppError):
                await ops_console.toggle(s, panel.id, bad_family, ids, True, admin_id=admin.id, reason="آزمایش")
        await ops_console.toggle(s, panel.id, "hosts", [5, 5, 6], False, admin_id=admin.id, reason="فعال‌سازی")
        assert [c for c in fake.calls if c[0] == "hosts"] == [("hosts", (5, 6), False)]  # deduplicated, sorted
        monkeypatch.setattr(ops_console, "build_adapter", lambda panel, server=None: FakeOps(caps=Capabilities(node_insight=True)))
        with pytest.raises(AppError) as e:
            await ops_console.toggle(s, panel.id, "groups", [1], True, admin_id=admin.id, reason="بدون دسترسی")
        assert e.value.code == "CAPABILITY_MISSING"


# ---------------------------------------------------------------------------------------------------------------- PG-12
async def _store_admin(s, panel, *, policy="none", cap=100 * GIB, used=30 * GIB):
    user = await make_user(s)
    store = await make_store(s, kind="reseller", owner=user)
    store.suspend_policy = policy
    row = PanelAdmin(
        panel_id=panel.id,
        store_id=store.id,
        username="ml_shop",
        remote_id=9,
        status="active",
        data_limit_bytes=cap,
        usage_snapshot={"used_traffic_bytes": used, "status": "active"},
    )
    s.add(row)
    await s.commit()
    return store, row


def test_usage_ratio_warning_level_and_sell_blocked_rules():
    def row(**kw):
        return PanelAdmin(
            data_limit_bytes=kw.get("cap"), usage_snapshot={"used_traffic_bytes": kw.get("used"), "status": kw.get("status", "active")}
        )

    assert governance.usage_ratio(row()) is None and governance.warning_level(row(cap=0, used=5)) == 0
    assert governance.warning_level(row(cap=100, used=79)) == 0
    assert governance.warning_level(row(cap=100, used=80)) == 80 and governance.warning_level(row(cap=100, used=96)) == 95
    assert governance.sell_blocked(row(cap=100, used=99)) is None
    assert (
        governance.sell_blocked(row(cap=100, used=100))
        and governance.sell_blocked(row(status="disabled"))
        and governance.sell_blocked(row(status="limited"))
    )


async def test_sync_usage_reads_every_admin_and_adopts_a_panel_side_cap_only_once(fake):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        panel = await _panel(s)
        store, row = await _store_admin(s, panel, cap=None, used=None)
        stats = await governance.sync_usage(s, panel)
        await s.commit()  # the caller (worker job / admin route) owns the commit
        assert (stats.checked, stats.updated, stats.errors) == (1, 1, 0)
        await s.refresh(row)
        assert row.usage_snapshot["used_traffic_bytes"] == 30 * GIB and row.usage_snapshot["total_users"] == 4
        assert row.data_limit_bytes == 100 * GIB  # adopted
        fake.admin["data_limit"] = 5 * GIB  # someone changed it on the panel: Melorin's own value is not silently replaced
        await governance.sync_usage(s, panel)
        await s.commit()
        await s.refresh(row)
        assert row.data_limit_bytes == 100 * GIB


async def test_sync_usage_isolates_failures_per_admin(fake):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        panel = await _panel(s)
        _, good = await _store_admin(s, panel)
        user = await make_user(s)
        other = await make_store(s, kind="reseller", owner=user)
        gone = PanelAdmin(panel_id=panel.id, store_id=other.id, username="ml_gone", remote_id=404, status="active")
        s.add(gone)
        await s.commit()
        stats = await governance.sync_usage(s, panel)
        await s.commit()
        await s.refresh(gone)
        assert (stats.checked, stats.updated, stats.errors) == (2, 1, 1) and gone.governance_error


async def test_set_limits_is_absolute_validated_and_audited(fake):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        panel = await _panel(s)
        store, row = await _store_admin(s, panel)
        admin = await make_user(s, super_admin=True)
        for kwargs in ({}, {"data_limit_gb": -1}, {"data_limit_gb": 0}, {"status": "limited"}):
            with pytest.raises(AppError):
                await governance.set_limits(s, row, actor_id=admin.id, **kwargs)
        assert not [c for c in fake.calls if c[0] == "admin_update"]
        await governance.set_limits(s, row, actor_id=admin.id, data_limit_gb=250, notifications_off=True, reason="سقف جدید")
        assert fake.calls[-1] == ("admin_update", 9, 250 * GIB, None, True) and row.data_limit_bytes == 250 * GIB
        await governance.set_limits(s, row, actor_id=admin.id, clear_limit=True)
        assert fake.calls[-1] == ("admin_update", 9, 0, None, None) and row.data_limit_bytes is None  # 0 = unlimited on the panel
        entry = next(a for a in await _audit(s) if a.action == "panel_admin.governance")
        assert entry.store_id == store.id and entry.data["before"]["data_limit_bytes"] == 100 * GIB


async def test_store_status_only_follows_the_panel_for_stores_that_opted_in(fake):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        panel = await _panel(s)
        store, row = await _store_admin(s, panel, policy="none")
        assert await governance.apply_store_status(s, store, suspended=True, actor_id=None) == [] and not fake.calls
        store.suspend_policy = "disable_accounts"
        await s.commit()
        report = await governance.apply_store_status(s, store, suspended=True, actor_id=None)
        assert (
            report == [{"panel": "pg", "ok": True}]
            and fake.calls[-1] == ("admin_update", 9, None, "disabled", None)
            and row.usage_snapshot["status"] == "disabled"
        )
        await governance.apply_store_status(s, store, suspended=False, actor_id=None)
        assert fake.calls[-1] == ("admin_update", 9, None, "active", None) and row.usage_snapshot["status"] == "active"


async def test_a_failing_panel_is_reported_not_raised_on_store_suspension(fake):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        panel = await _panel(s)
        store, row = await _store_admin(s, panel, policy="disable_accounts")
        fake.fail = PanelError(ErrorKind.TRANSIENT, "502")
        report = await governance.apply_store_status(s, store, suspended=True, actor_id=None)
        assert report[0]["ok"] is False and row.governance_error


# ---------------------------------------------------------------------------------------------------------------- PG-13
def _states(checks):
    return {c["name"]: c["state"] for c in checks}


def test_evaluate_flags_a_prefix_mismatch_and_a_stale_account_link():
    checks = subscription_check.evaluate(
        panel_prefix="https://sub.example.com:1010", sub_base_url="https://other.example.com", link="https://old.example.com/sub/abc",
        probe={"ok": False, "status": 404, "error": "http 404"}, store_domains=["shop.example.com"],
    )  # fmt: skip
    st = _states(checks)
    assert st["prefix"] == "fail" and st["link_prefix"] == "fail" and st["reachable"] == "fail" and st["store_domains"] == "warn"
    assert subscription_check.verdict(checks) == "fail"


def test_evaluate_is_clean_when_everything_matches_and_skips_without_a_link():
    ok = subscription_check.evaluate(
        panel_prefix="https://sub.example.com:1010/", sub_base_url="https://sub.example.com:1010", link="https://sub.example.com:1010/sub/t",
        probe={"ok": True, "status": 200, "error": None}, store_domains=["sub.example.com"],
    )  # fmt: skip
    assert subscription_check.verdict(ok) == "ok"
    none = subscription_check.evaluate(panel_prefix="https://s.example.com", sub_base_url=None, link=None, probe=None, store_domains=[])
    assert _states(none)["link_prefix"] == "skip" and _states(none)["reachable"] == "skip" and subscription_check.verdict(none) == "ok"
    assert (
        _states(subscription_check.evaluate(panel_prefix=None, sub_base_url=None, link=None, probe=None, store_domains=[]))["prefix"]
        == "warn"
    )


async def test_run_stores_the_verdict_and_probes_only_configured_hosts(fake):
    from melorin.domain.order_state import VpnStatus
    from melorin.kernel.models.vpn import VpnAccount
    from _db import make_order, make_product

    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        panel = await _panel(s, config={"sub_base_url": "https://sub.example.com:1010"})
        user, store, product = await make_user(s), await make_store(s), await make_product(s)
        order = await make_order(s, user=user, store=store, product=product)
        s.add(VpnAccount(delivery_snapshot={"subscription_url": "https://sub.example.com:1010/sub/tok"}, username="a1", user_id=user.id, store_id=store.id, order_id=order.id, product_id=product.id, panel_id=panel.id, panel_ref="1",
                         status=VpnStatus.ACTIVE, ))  # fmt: skip
        await s.commit()
        out = await subscription_check.run(s, panel.id, actor_id=None)
        assert out["verdict"] == "ok" and out["tested_account"] == "a1"
        probe = next(c for c in fake.calls if c[0] == "probe")
        assert probe[2] == frozenset({"sub.example.com", "panel.example.com"})
        await s.refresh(panel)
        assert panel.subscription_check["verdict"] == "ok" and panel.subscription_checked_at is not None
        assert "panel.subscription_checked" in _actions(await _audit(s))


async def test_run_without_the_capability_is_refused(monkeypatch):
    monkeypatch.setattr(subscription_check, "build_adapter", lambda panel, server=None: FakeOps(caps=Capabilities()))
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        panel = await _panel(s)
        with pytest.raises(AppError) as e:
            await subscription_check.run(s, panel.id, actor_id=None)
        assert e.value.code == "CAPABILITY_MISSING"


async def test_probe_never_fetches_an_unconfigured_host_or_follows_redirects():
    hits: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        hits.append(str(req.url))
        return (
            httpx.Response(302, headers={"location": "http://169.254.169.254/"})
            if "redir" in req.url.path
            else httpx.Response(200, json={})
        )

    real = httpx.AsyncClient

    class Client(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    adapter = PasarGuardAdapter("https://panel.example.com", {"api_key": "k"}, {})

    httpx.AsyncClient = Client
    try:
        allowed = {"sub.example.com"}
        assert (await adapter.probe_subscription("https://evil.example.org/sub/x", allowed_hosts=allowed))["ok"] is False
        assert (await adapter.probe_subscription("http://169.254.169.254/latest", allowed_hosts=allowed))["ok"] is False
        assert (await adapter.probe_subscription("file:///etc/passwd", allowed_hosts=allowed))["ok"] is False
        assert hits == []  # nothing left the process for those three
        ok = await adapter.probe_subscription("https://sub.example.com/sub/tok?x=1", allowed_hosts=allowed)
        assert ok["ok"] is True and hits == ["https://sub.example.com/sub/tok/info"]  # query dropped, /info appended
        redirected = await adapter.probe_subscription("https://sub.example.com/redir", allowed_hosts=allowed)
        assert redirected["ok"] is False and redirected["status"] == 302 and len(hits) == 2  # the redirect target was not requested
    finally:
        httpx.AsyncClient = real


# ----------------------------------------------------------------------------------------------------------------- admin API
async def _login(c, maker):
    await add_user(maker, email="root@example.com", admin=True, totp=True)
    r = await c.post("/api/v1/auth/password/login", json={"email": "root@example.com", "password": PASSWORD, "totp_code": totp_now()})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_every_phase4_endpoint_needs_an_admin():
    pid = "00000000-0000-0000-0000-000000000001"
    async with api_client() as (c, _, __):
        for method, path in (
            ("get", f"/panels/{pid}/ops"), ("get", f"/panels/{pid}/ops/infra"), ("post", f"/panels/{pid}/ops/nodes/1/reconnect"),
            ("post", f"/panels/{pid}/ops/cores/1/restart"), ("post", f"/panels/{pid}/ops/nodes/toggle"),
            ("get", f"/panels/{pid}/subscription-check"), ("post", f"/panels/{pid}/subscription-check"),
            ("post", "/bulk-operations/preview"), ("get", "/bulk-operations"), ("get", f"/bulk-operations/{pid}"),
            ("post", f"/bulk-operations/{pid}/confirm"), ("post", f"/bulk-operations/{pid}/cancel"), ("post", f"/bulk-operations/{pid}/resume"),
            ("get", "/store-admins"), ("post", "/store-admins/refresh"), ("patch", f"/store-admins/{pid}"), ("put", f"/resellers/{pid}/suspend-policy"),
        ):  # fmt: skip
            r = await getattr(c, method)(BASE + path)
            assert r.status_code in (401, 403), (method, path, r.status_code)


async def test_bulk_flow_through_the_http_api(fake, monkeypatch):
    from melorin.domain.order_state import VpnStatus
    from melorin.kernel.models.vpn import VpnAccount
    from melorin.modules.panelops import bulk
    from _db import make_order, make_product

    async with api_client() as (c, maker, main):
        h = await _login(c, maker)
        async with maker() as s:
            panel = await _panel(s)
            user, product = await make_user(s), await make_product(s)
            for i in range(2):
                order = await make_order(s, user=user, store=main, product=product)
                s.add(VpnAccount(username=f"u{i}", user_id=user.id, store_id=main.id, order_id=order.id, product_id=product.id, panel_id=panel.id,
                                 panel_ref=str(i + 1), status=VpnStatus.ACTIVE, sold_traffic_bytes=GIB))  # fmt: skip
            await s.commit()
            pid = str(panel.id)
        bad = await c.post(
            f"{BASE}/bulk-operations/preview", headers=h, json={"kind": "disable", "selection": {"panel_id": pid}, "reason": "x"}
        )
        assert bad.status_code == 422  # reason too short is rejected by validation before any work
        pv = await c.post(
            f"{BASE}/bulk-operations/preview", headers=h, json={"kind": "disable", "selection": {"panel_id": pid}, "reason": "قطعی نود"}
        )
        assert pv.status_code == 200, pv.text
        op = pv.json()
        assert op["status"] == "previewed" and op["total"] == 2 and op["panel_name"] == "pg" and op["kind_label"]
        wrong = await c.post(f"{BASE}/bulk-operations/{op['id']}/confirm", headers=h, json={"count": 1})
        assert (
            wrong.status_code == 409 and wrong.json()["error"]["code"] == "BULK_COUNT_MISMATCH"
            if "error" in wrong.json()
            else wrong.status_code == 409
        )
        ok = await c.post(f"{BASE}/bulk-operations/{op['id']}/confirm", headers=h, json={"count": 2})
        assert ok.status_code == 200 and ok.json()["status"] == "confirmed"
        detail = (await c.get(f"{BASE}/bulk-operations/{op['id']}", headers=h)).json()
        assert [i["username"] for i in detail["items"]] == ["u0", "u1"] and all(i["status"] == "pending" for i in detail["items"])
        listed = (await c.get(f"{BASE}/bulk-operations", headers=h, params={"status": "confirmed"})).json()
        assert listed["total"] == 1
        cancelled = await c.post(f"{BASE}/bulk-operations/{op['id']}/cancel", headers=h)
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        assert (await c.post(f"{BASE}/bulk-operations/{op['id']}/resume", headers=h)).status_code == 409
        _ = (bulk, monkeypatch, BulkOperation)


async def test_console_endpoints_and_suspend_policy_through_the_http_api(fake):
    async with api_client() as (c, maker, main):
        h = await _login(c, maker)
        async with maker() as s:
            panel = await _panel(s)
            reseller = await make_store(s, kind="reseller")
            await s.commit()
            pid, sid = str(panel.id), str(reseller.id)
        body = (await c.get(f"{BASE}/panels/{pid}/ops", headers=h)).json()
        assert body["can"] == {"reconnect": True, "infra": True, "insight": True} and len(body["nodes"]) == 2
        infra = (await c.get(f"{BASE}/panels/{pid}/ops/infra", headers=h)).json()
        assert infra["cores"] == [{"id": 1, "name": "xray-main"}] and infra["hosts"][0]["disabled"] is True
        no_reason = await c.post(f"{BASE}/panels/{pid}/ops/nodes/2/reconnect", headers=h, json={"reason": ""})
        assert no_reason.status_code == 422
        done = await c.post(f"{BASE}/panels/{pid}/ops/nodes/2/reconnect", headers=h, json={"reason": "گواهی اصلاح شد"})
        assert done.status_code == 200 and done.json()["ok"] is True
        last = await c.post(f"{BASE}/panels/{pid}/ops/nodes/toggle", headers=h, json={"ids": [1], "disabled": True, "reason": "نگهداری"})
        assert last.status_code == 409
        bad_policy = await c.put(f"{BASE}/resellers/{sid}/suspend-policy", headers=h, json={"suspend_policy": "delete_all"})
        assert bad_policy.status_code == 422
        policy = await c.put(f"{BASE}/resellers/{sid}/suspend-policy", headers=h, json={"suspend_policy": "disable_accounts"})
        assert policy.status_code == 200 and policy.json()["suspend_policy"] == "disable_accounts"
        main_policy = await c.put(f"{BASE}/resellers/{main.id}/suspend-policy", headers=h, json={"suspend_policy": "none"})
        assert main_policy.status_code == 404  # only reseller stores have the policy


async def test_suspending_a_reseller_through_the_api_follows_the_panel_only_when_opted_in(fake):
    async with api_client() as (c, maker, main):
        h = await _login(c, maker)
        async with maker() as s:
            panel = await _panel(s)
            opted, plain = await _store_admin(s, panel, policy="disable_accounts"), None
            store = opted[0]
            await s.commit()
            sid = str(store.id)
        r = await c.patch(f"{BASE}/resellers/{sid}", headers=h, json={"status": "suspended"})
        assert r.status_code == 200, r.text
        assert ("admin_update", 9, None, "disabled", None) in fake.calls
        r = await c.patch(f"{BASE}/resellers/{sid}", headers=h, json={"status": "active"})
        assert r.status_code == 200 and ("admin_update", 9, None, "active", None) in fake.calls
        _ = plain
