"""PG-00: the adapter capability model - flags, optional operation groups, permission probe, stored snapshot, admin API."""

import datetime as dt
import json

import httpx
import pytest

from _http import PASSWORD, add_user, api_client, totp_now
from melorin.kernel.models.vpn import Panel
from melorin.modules.panel_integrations import capabilities as service
from melorin.modules.panel_integrations.adapters import pasarguard, registry
from melorin.modules.panel_integrations.adapters.base import (
    ALL_CAPABILITIES,
    CAPABILITY_PROTOCOLS,
    Capabilities,
    CapabilityReport,
    ErrorKind,
    PanelError,
    discover,
    require,
    static_report,
    supports,
)
from melorin.modules.panel_integrations.adapters.mock import MockPanelAdapter
from melorin.modules.panel_integrations.adapters.pasarguard import PasarGuardAdapter
from melorin.modules.panel_integrations.adapters.pasarguard.capabilities import (
    build_report,
    merge_permissions,
    missing_permissions,
    permission_granted,
)

CREDS = {"username": "admin", "password": "pw"}


@pytest.fixture(autouse=True)
def _clear_tokens():
    pasarguard._TOKENS.clear()
    yield
    pasarguard._TOKENS.clear()


OPERATOR = {  # what a store Operator may do on PasarGuard 5.6 (users: own scope, no nodes, settings read_general only)
    "users": {"read": 1, "create": 1, "update": 1, "delete": 1, "reset_usage": 1, "revoke_sub": 1, "set_owner": 0},
    "nodes": {},
    "settings": {"read_general": True},
    "hwids": {"read": True, "delete": True},
    "admins": {},
}
SERVICE = {  # a dedicated service role (PG-05 target): everything Melorin needs, nothing destructive on infrastructure
    "users": {"read": 2, "update": 2, "reset_usage": 2, "revoke_sub": 2, "set_owner": 2, "activate_next_plan": 2},
    "nodes": {"read": True, "reconnect": True, "stats": True},
    "system": {"read": True},
    "hwids": {"read": True, "delete": True},
    "settings": {"read": True},
    "admins": {"read": True, "create": True, "update": True},
    "admin_roles": {"read_simple": True},
    "groups": {"read": True},
    "hosts": {"read": True},
    "templates": {"read": True, "create": True, "update": True},
}


class Panel5:
    """PasarGuard stub whose ``GET /api/admin`` answers with a configurable role; also serves nodes/users for the operation tests."""

    def __init__(self, admin=None, roles=None, nodes=0, fail=None):
        self.admin = admin if admin is not None else {"username": "admin", "role": {"name": "owner", "is_owner": True}}
        self.roles, self.nodes, self.fail = roles, nodes, fail or {}
        self.calls: list[tuple[str, str]] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        m, p = req.method, req.url.path
        self.calls.append((m, p))
        if p == "/api/admin/token":
            return httpx.Response(200, json={"access_token": "t"})
        if (m, p) in self.fail:
            return httpx.Response(self.fail[(m, p)], json={"detail": "nope"})
        if p == "/api/admin":
            return httpx.Response(200, json=self.admin)
        if p == "/api/admin-roles":
            return httpx.Response(200, json={"roles": self.roles or []})
        if p == "/api/nodes":
            off, lim = int(req.url.params["offset"]), int(req.url.params["limit"])
            rows = [{"id": i, "name": f"n{i}", "status": "connected"} for i in range(self.nodes)]
            return httpx.Response(200, json={"nodes": rows[off : off + lim], "total": self.nodes})
        if p.startswith("/api/node/") and p.endswith("/reconnect"):
            return httpx.Response(200, json={})
        if p == "/api/node/404":
            return httpx.Response(404, json={"detail": "x"})
        if p == "/api/user/by-username/alice":
            return httpx.Response(200, json={"id": 5, "username": "alice", "status": "active"})
        if p == "/api/user/5/hwids/dev-1":
            return httpx.Response(404, json={"detail": "gone"})
        return httpx.Response(200, json={})


def make(panel, **cfg) -> PasarGuardAdapter:
    return PasarGuardAdapter("https://p.example.com", CREDS, cfg or {"group_ids": [1]}, transport=httpx.MockTransport(panel))


# ------------------------------------------------------------------------------------------------------------- the model
def test_new_flags_default_off_and_core_flags_keep_their_defaults():
    c = Capabilities()
    assert (c.suspend, c.extend, c.subscription_url, c.traffic_reset) == (True, True, True, False)
    assert not any(getattr(c, n) for n in ALL_CAPABILITIES if n not in ("suspend", "extend", "subscription_url"))


def test_dict_roundtrip_ignores_unknown_keys_and_fills_missing_ones():
    c = Capabilities(node_ops=True, traffic_reset=True)
    assert Capabilities.from_dict(c.to_dict()) == c
    assert Capabilities.from_dict({"node_ops": 1, "from_the_future": True}).node_ops is True
    assert Capabilities.from_dict(None) == Capabilities() and Capabilities.from_dict("junk") == Capabilities()
    assert set(c.to_dict()) == set(ALL_CAPABILITIES)


def test_has_enabled_and_restricted_to():
    full = Capabilities(node_ops=True, usage_ops=True, traffic_reset=True)
    narrowed = full.restricted_to({"node_ops": True, "suspend": True})
    assert narrowed.node_ops and not narrowed.usage_ops and not narrowed.traffic_reset
    assert full.has("node_ops") and not full.has("device_ops") and not full.has("nope")
    assert "node_ops" in full.enabled()


def test_every_optional_flag_has_a_protocol_and_the_protocols_are_real():
    for flag, protocol in CAPABILITY_PROTOCOLS.items():
        assert flag in ALL_CAPABILITIES
        assert getattr(protocol, "_is_runtime_protocol", False)


def test_supports_needs_both_the_flag_and_the_methods():
    a = make(Panel5())
    assert supports(a, "node_ops") and supports(a, "usage_ops") and supports(a, "traffic_reset")
    assert supports(a, "event_source")  # shipped in Phase 2 (PG-03): verify + connect/disconnect at the panel
    assert not supports(a, "no_such_capability")

    class FlagOnly:  # advertises node_ops but implements nothing: a bug the helper must not trust
        def capabilities(self):
            return Capabilities(node_ops=True)

    assert not supports(FlagOnly(), "node_ops")

    class Broken:
        def capabilities(self):
            raise RuntimeError("boom")

    assert not supports(Broken(), "node_ops")  # never takes the caller down


def test_require_raises_a_permanent_panel_error():
    with pytest.raises(PanelError) as exc:
        require(MockPanelAdapter(base_url="https://m"), "node_ops")
    assert exc.value.kind is ErrorKind.PERMANENT and "node_ops" in exc.value.message
    require(make(Panel5()), "node_ops")  # no error


@pytest.mark.parametrize("kind", sorted(registry.ADAPTERS))
def test_every_adapter_keeps_its_promises(kind):
    """A flag may only be on when its methods exist - for EVERY registered adapter, so a new adapter cannot lie."""
    try:
        adapter = registry.ADAPTERS[kind](base_url="https://panel.example.com", credentials={}, config={})
    except Exception:
        pytest.skip(f"{kind} needs live collaborators to construct")
    caps = adapter.capabilities()
    assert isinstance(caps, Capabilities)
    for flag in caps.enabled():
        protocol = CAPABILITY_PROTOCOLS.get(flag)
        assert protocol is None or isinstance(adapter, protocol), f"{kind} advertises {flag} without implementing it"


def test_adapters_other_than_pasarguard_do_not_claim_panel_operations():
    for kind in ("sanaei", "mock", "upstream_bot"):
        try:
            caps = registry.ADAPTERS[kind](base_url="https://x.example.com", credentials={}, config={}).capabilities()
        except Exception:
            continue
        assert not any(
            caps.has(n) for n in ("node_ops", "node_control", "device_ops", "bulk_ops", "admin_ops", "settings_ops", "event_source")
        )


def test_static_report_and_discover_for_an_adapter_without_a_probe():
    adapter = MockPanelAdapter(base_url="https://m")
    report = static_report(adapter)
    assert report.source == "static" and report.capabilities == adapter.capabilities() and report.error is None
    import asyncio

    assert asyncio.run(discover(adapter)).source == "static"


def test_report_to_dict_is_json_serialisable():
    r = build_report(Capabilities(node_ops=True), role="operator", is_owner=False, permissions=OPERATOR)
    assert json.loads(json.dumps(r.to_dict()))["denied"] == {"node_ops": ["nodes.read"]}


# --------------------------------------------------------------------------------------------- permission interpretation
def test_permission_granted_understands_booleans_and_scopes():
    perms = {"users": {"read": 2, "update": 1, "set_owner": 0, "x": False, "y": None, "z": True}}
    assert permission_granted(perms, "users.read") and permission_granted(perms, "users.update") and permission_granted(perms, "users.z")
    assert not permission_granted(perms, "users.set_owner")  # scope 0 = none
    assert not permission_granted(perms, "users.x") and not permission_granted(perms, "users.y")
    assert (
        not permission_granted(perms, "nodes.read") and not permission_granted(None, "users.read") and not permission_granted(perms, "bad")
    )


def test_merge_permissions_applies_overrides_per_action():
    merged = merge_permissions(
        {"nodes": {"read": False, "reconnect": False}, "users": {"read": 1}}, {"nodes": {"read": True}, "settings": {"read": True}}
    )
    assert merged["nodes"] == {"read": True, "reconnect": False}
    assert merged["settings"] == {"read": True} and merged["users"] == {"read": 1}
    assert merge_permissions(None, None) == {}


def test_missing_permissions_names_exactly_what_is_lacking():
    assert missing_permissions(OPERATOR, "node_control") == ["nodes.read", "nodes.reconnect"]
    assert missing_permissions(OPERATOR, "bulk_ops") == ["users.set_owner"]  # set_owner scope 0
    assert missing_permissions(SERVICE, "bulk_ops") == []


def test_owner_gets_every_declared_capability_without_a_permission_table():
    declared = make(Panel5()).declared_capabilities()
    r = build_report(declared, role="owner", is_owner=True, permissions=None)
    assert r.capabilities == declared and not r.denied and r.is_owner and r.source == "probe"


def test_operator_loses_what_its_role_cannot_do_and_the_report_says_why():
    declared = make(Panel5()).declared_capabilities()
    r = build_report(declared, role="operator", is_owner=False, permissions=OPERATOR)
    caps = r.capabilities
    assert caps.suspend and caps.extend and caps.traffic_reset and caps.subscription_rotate and caps.device_ops
    assert not caps.node_ops and not caps.node_control and not caps.bulk_ops and not caps.admin_ops and not caps.settings_ops
    assert r.denied["node_ops"] == ["nodes.read"] and r.denied["bulk_ops"] == ["users.set_owner"]
    assert r.users_scope == 1  # own users only
    assert not r.capabilities.restricted_to(declared).event_source


def test_service_role_is_enough_for_everyday_work_but_not_for_webhook_setup():
    declared = make(Panel5()).declared_capabilities()
    r = build_report(declared, role="melorin-service", is_owner=False, permissions=SERVICE)
    assert r.capabilities.node_control and r.capabilities.bulk_ops and r.capabilities.admin_ops and r.users_scope == 2
    # events need ``settings.update``: a role without it keeps everything else and only loses the one-click webhook setup
    # Phase 4: reading stats is allowed, but restarting cores / toggling nodes, hosts and groups is infrastructure control and stays denied
    assert r.denied == {
        "event_source": ["settings.update"],
        "infra_control": ["nodes.update", "hosts.update", "groups.update", "cores.read", "cores.update"],
    }
    assert not r.capabilities.event_source and not r.capabilities.infra_control and r.capabilities.node_insight


# ------------------------------------------------------------------------------------------------------------ the probe
def test_declared_capabilities_of_current_and_legacy_api_styles():
    current = PasarGuardAdapter("https://p.example.com", CREDS, {"group_ids": [1]}).capabilities()
    legacy = PasarGuardAdapter("https://p.example.com", CREDS, {"group_ids": [1], "api_style": "legacy"}).capabilities()
    assert current.node_ops and current.device_ops and current.traffic_reset and current.event_source
    assert not legacy.event_source  # the legacy API style has no settings route
    assert legacy.traffic_reset and legacy.subscription_rotate and not legacy.node_ops and not legacy.device_ops and not legacy.admin_ops


async def test_probe_owner_role():
    r = await make(Panel5()).discover_capabilities()
    assert r.source == "probe" and r.is_owner and r.role == "owner" and r.capabilities.node_ops and not r.denied


async def test_probe_operator_with_inline_permissions_and_overrides():
    admin = {"username": "ml", "role": {"name": "operator", "permissions": OPERATOR}, "permission_overrides": {"nodes": {"read": True}}}
    r = await make(Panel5(admin=admin)).discover_capabilities()
    assert r.source == "probe" and r.role == "operator" and not r.is_owner
    assert r.capabilities.node_ops and not r.capabilities.node_control  # override granted read, not reconnect
    assert "bulk_ops" in r.denied


async def test_probe_looks_the_role_up_by_name_when_the_panel_returns_only_a_name():
    panel = Panel5(
        admin={"username": "ml", "role": "operator"},
        roles=[{"name": "Operator", "permissions": OPERATOR}, {"name": "other", "permissions": {}}],
    )
    r = await make(panel).discover_capabilities()
    assert r.source == "probe" and r.role == "operator" and not r.capabilities.node_ops and ("GET", "/api/admin-roles") in panel.calls


async def test_probe_falls_back_to_static_when_permissions_cannot_be_read():
    panel = Panel5(admin={"username": "ml", "role": "operator"}, fail={("GET", "/api/admin-roles"): 403})
    r = await make(panel).discover_capabilities()
    assert r.source == "static" and "not exposed" in r.error and r.capabilities == make(panel).declared_capabilities()


async def test_probe_survives_an_unreachable_or_forbidden_panel():
    r = await make(Panel5(fail={("GET", "/api/admin"): 403})).discover_capabilities()
    assert r.source == "static" and "403" in r.error and r.capabilities.suspend
    r = await make(Panel5(admin=[1, 2])).discover_capabilities()
    assert r.source == "static" and "unexpected" in r.error


async def test_discover_helper_never_raises():
    class Exploding:
        kind = "x"

        def capabilities(self):
            return Capabilities()

        async def discover_capabilities(self):
            raise RuntimeError("probe bug")

    r = await discover(Exploding())
    assert r.source == "static" and "probe bug" in r.error


# --------------------------------------------------------------------------------------------- the new operation groups
async def test_list_nodes_pages_through_everything():
    panel = Panel5(nodes=230)
    rows = await make(panel).list_nodes()
    assert len(rows) == 230 and [c for c in panel.calls if c[1] == "/api/nodes"].__len__() == 3


async def test_get_node_missing_is_none_and_reconnect_posts():
    panel = Panel5()
    a = make(panel)
    assert await a.get_node(404) is None
    await a.reconnect_node(7)
    assert ("POST", "/api/node/7/reconnect") in panel.calls


async def test_usage_validates_the_period_before_calling_the_panel():
    panel = Panel5()
    a = make(panel)
    with pytest.raises(PanelError) as exc:
        await a.get_usage("alice", period="decade")
    assert exc.value.kind is ErrorKind.PERMANENT and not panel.calls
    assert await a.get_usage("alice", start=dt.datetime(2026, 1, 1, tzinfo=dt.UTC), period="month") == []


async def test_device_operations_are_idempotent_and_validated():
    panel = Panel5()
    a = make(panel)
    await a.delete_device("alice", "dev-1")  # the panel answers 404: already gone, not an error
    await a.reset_devices("alice")
    assert ("POST", "/api/user/5/hwids/reset") in panel.calls
    with pytest.raises(PanelError):
        await a.delete_device("alice", " ")


async def test_get_settings_returns_a_dict():
    assert await make(Panel5()).get_settings() == {}


# --------------------------------------------------------------------------------------------- stored snapshot (service)
class Row:  # minimal Panel stand-in (no DB)
    kind, base_url, config = "pasarguard", "https://p.example.com", {"group_ids": [1]}
    capabilities = None
    capabilities_checked_at = None


def test_capabilities_out_falls_back_to_the_static_declaration():
    out = service.capabilities_out(Row())
    assert (
        out["source"] == "static"
        and out["flags"]["node_ops"] is True
        and out["checked_at"] is None
        and set(out["flags"]) == set(ALL_CAPABILITIES)
    )


def test_unknown_panel_kind_is_not_an_error():
    r = Row()
    r.kind = "marzban-someday"
    assert service.capabilities_out(r)["flags"]["node_ops"] is False


def test_store_keeps_a_good_probe_when_the_next_one_fails():
    row = Row()
    good = build_report(make(Panel5()).declared_capabilities(), role="operator", is_owner=False, permissions=OPERATOR)
    service.store(row, good)
    assert row.capabilities["flags"]["node_ops"] is False and row.capabilities_checked_at is not None
    failed = CapabilityReport(capabilities=Capabilities(), declared=Capabilities(), source="static", error="panel down")
    service.store(row, failed)
    assert row.capabilities["flags"]["node_ops"] is False and row.capabilities["error"] == "panel down"  # restrictions survive an outage
    assert service.capabilities_of(row).traffic_reset is True and service.capabilities_of(row).node_ops is False


def test_first_probe_failure_is_stored_as_the_static_declaration_with_the_error():
    row = Row()
    service.store(row, CapabilityReport(capabilities=Capabilities(node_ops=True), declared=Capabilities(node_ops=True), error="down"))
    assert row.capabilities["source"] == "static" and row.capabilities["error"] == "down"


def test_is_stale_after_an_hour():
    row, now = Row(), dt.datetime(2026, 11, 6, 12, tzinfo=dt.UTC)
    assert service.is_stale(row, now)
    row.capabilities_checked_at = now - dt.timedelta(minutes=59)
    assert not service.is_stale(row, now)
    row.capabilities_checked_at = now - dt.timedelta(hours=1)
    assert service.is_stale(row, now)
    row.capabilities_checked_at = (now - dt.timedelta(minutes=5)).replace(tzinfo=None)  # naive timestamps (SQLite) are treated as UTC
    assert not service.is_stale(row, now)


async def test_probe_reports_a_build_failure_instead_of_raising(monkeypatch):
    def boom(panel, server=None):
        raise PanelError(ErrorKind.PERMANENT, "tls required")

    monkeypatch.setattr(service.registry, "build_adapter", boom)
    r = await service.probe(Row())
    assert r.source == "static" and "tls required" in r.error


# ------------------------------------------------------------------------------------------------------ admin API (HTTP)
@pytest.fixture
def probed_panel(monkeypatch):
    """Route every PasarGuard adapter through an in-memory panel; ``state['admin']`` picks the role the credential has."""
    state = {"admin": {"username": "admin", "role": {"name": "operator", "permissions": OPERATOR}}, "calls": 0}

    class Wired(PasarGuardAdapter):
        def __init__(self, base_url, credentials, config=None, **kw):
            panel = Panel5(admin=state["admin"])

            def counted(req):
                state["calls"] += 1
                return panel(req)

            super().__init__(base_url, credentials, config, transport=httpx.MockTransport(counted))

    monkeypatch.setitem(registry.ADAPTERS, "pasarguard", Wired)
    return state


async def _login(c, maker):
    await add_user(maker, email="root@example.com", admin=True, totp=True)
    r = await c.post("/api/v1/auth/password/login", json={"email": "root@example.com", "password": PASSWORD, "totp_code": totp_now()})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_create_panel_stores_and_returns_the_probed_capabilities(probed_panel):
    async with api_client() as (c, maker, _):
        h = await _login(c, maker)
        body = {"name": "pg", "kind": "pasarguard", "base_url": "https://p.example.com", "credentials": CREDS, "config": {"group_ids": [1]}}
        r = await c.post("/api/v1/admin/panels", json=body, headers=h)
        assert r.status_code == 201, r.text
        caps = r.json()["capabilities"]
        assert caps["source"] == "probe" and caps["role"] == "operator" and caps["checked_at"]
        assert caps["flags"]["suspend"] is True and caps["flags"]["node_ops"] is False
        assert caps["denied"]["node_ops"] == ["nodes.read"]
        listed = (await c.get("/api/v1/admin/panels", headers=h)).json()
        assert listed[0]["capabilities"]["flags"] == caps["flags"]


async def test_panel_without_a_working_probe_still_lists_the_static_declaration(monkeypatch):
    monkeypatch.setattr(
        registry, "build_adapter", lambda panel, server=None: (_ for _ in ()).throw(PanelError(ErrorKind.PERMANENT, "unreachable"))
    )
    async with api_client() as (c, maker, _):
        h = await _login(c, maker)
        body = {"name": "mk", "kind": "mock", "base_url": "https://m.example.com", "credentials": {}, "config": {}}
        r = await c.post("/api/v1/admin/panels", json=body, headers=h)
        assert r.status_code == 201, r.text
        caps = r.json()["capabilities"]
        assert caps["source"] == "static" and caps["flags"]["suspend"] is True and caps["flags"]["node_ops"] is False


async def test_editing_the_connection_reprobes_and_a_rename_does_not(probed_panel):
    async with api_client() as (c, maker, _):
        h = await _login(c, maker)
        body = {"name": "pg", "kind": "pasarguard", "base_url": "https://p.example.com", "credentials": CREDS, "config": {"group_ids": [1]}}
        pid = (await c.post("/api/v1/admin/panels", json=body, headers=h)).json()["id"]
        before = probed_panel["calls"]
        assert (
            await c.patch(f"/api/v1/admin/panels/{pid}", json={**body, "name": "renamed", "credentials": {}}, headers=h)
        ).status_code == 200
        assert probed_panel["calls"] == before  # name only: no network

        probed_panel["admin"] = {"username": "admin", "role": {"name": "owner", "is_owner": True}}  # the role was widened on the panel
        assert (
            await c.patch(f"/api/v1/admin/panels/{pid}", json={**body, "base_url": "https://p2.example.com"}, headers=h)
        ).status_code == 200
        caps = next(p for p in (await c.get("/api/v1/admin/panels", headers=h)).json() if p["id"] == pid)["capabilities"]
        assert caps["is_owner"] is True and caps["flags"]["node_ops"] is True and not caps["denied"]


async def test_health_check_refreshes_the_snapshot(probed_panel):
    async with api_client() as (c, maker, _):
        h = await _login(c, maker)
        body = {"name": "pg", "kind": "pasarguard", "base_url": "https://p.example.com", "credentials": CREDS, "config": {"group_ids": [1]}}
        pid = (await c.post("/api/v1/admin/panels", json=body, headers=h)).json()["id"]
        probed_panel["admin"] = {"username": "admin", "role": {"name": "owner", "is_owner": True}}
        assert (await c.post(f"/api/v1/admin/panels/{pid}/health", headers=h)).json()["healthy"] is True
        async with maker() as s:
            row = await s.get(Panel, __import__("uuid").UUID(pid))
            assert row.capabilities["flags"]["node_ops"] is True
