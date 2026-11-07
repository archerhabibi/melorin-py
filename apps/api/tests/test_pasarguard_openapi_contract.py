"""PG-17: the PasarGuard adapter checked against the committed OpenAPI contract of the panel version it was built for.

The fixture (``tests/fixtures/pasarguard-openapi-5.6.0.contract.json``) is a slimmed export of the panel's own OpenAPI. These
tests drive EVERY adapter operation against a permissive in-memory panel, record the real HTTP requests, and compare them with
the fixture: route exists, query parameters are declared, JSON body fields are declared, required fields are present. They also
check the capability tables (routes and permissions) and the status/period enums.

When PasarGuard is upgraded: ``python scripts/pasarguard_contract.py diff <new-openapi.json> --fixture <fixture>`` shows what moved,
then these tests show which adapter call it breaks. Update the fixture (``slim``) only after the adapter is compatible."""

import datetime as dt
import importlib.util
import json
import re
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from melorin.modules.vpn.adapters import pasarguard
from melorin.modules.vpn.adapters.base import ALL_CAPABILITIES, AccountSpec
from melorin.modules.vpn.adapters.pasarguard import PasarGuardAdapter
from melorin.modules.vpn.adapters.pasarguard.capabilities import CAPABILITY_ENDPOINTS, CAPABILITY_REQUIREMENTS, LEGACY_CAPABILITIES
from melorin.modules.vpn.adapters.pasarguard.events import USER_EVENTS
from melorin.modules.vpn.adapters.pasarguard.users import USAGE_PERIODS

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests/fixtures/pasarguard-openapi-5.6.0.contract.json").read_text(encoding="utf-8"))
OPS: dict[str, dict] = FIXTURE["operations"]
SCHEMAS: dict[str, dict] = FIXTURE["schemas"]
ENUMS: dict[str, list] = FIXTURE["enums"]

GB = 1024**3
EXPIRE = dt.datetime(2027, 1, 1, tzinfo=dt.UTC)
CREDS = {"username": "admin", "password": "pw"}


@pytest.fixture(autouse=True)
def _clear_tokens():
    pasarguard._TOKENS.clear()
    yield
    pasarguard._TOKENS.clear()


# ---------------------------------------------------------------------------------------------------------- route matching
def _compile(template: str) -> re.Pattern:
    return re.compile("^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(template)) + "$")


_ROUTES = [(method, path, _compile(path)) for key in OPS for method, path in [key.split(" ", 1)]]


def resolve(method: str, concrete: str) -> str | None:
    """The fixture operation key a real request maps to; the most literal template wins (``/by-id/7`` over ``/{username}/x``)."""
    hits = [(path.count("{"), f"{m} {path}") for m, path, rx in _ROUTES if m == method and rx.match(concrete)]
    return min(hits)[1] if hits else None


# ------------------------------------------------------------------------------------------------- permissive recording panel
class RecordingPanel:
    """Answers every route the adapter uses with a plausible shape and records (method, path, query, json body)."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.requests: list[dict] = []
        self.next_id = 1
        self.settings: dict = {"webhook": {"enable": False}, "general": {"default_flow": ""}}

    def _user(self, username, **extra):
        u = self.users.setdefault(
            username,
            {
                "id": self.next_id,
                "username": username,
                "status": "active",
                "expire": None,
                "data_limit": 0,
                "used_traffic": 0,
                "admin": {"username": "owner"},
            },
        )
        if u["id"] == self.next_id:
            self.next_id += 1
        u.update(extra)
        return {**u, "subscription_url": f"/sub/{username}"}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        method, path = req.method, req.url.path
        q = {k: v[0] for k, v in parse_qs(req.url.query.decode()).items()}
        body = json.loads(req.content) if req.content and "json" in req.headers.get("content-type", "") else None
        self.requests.append({"method": method, "path": path, "query": q, "body": body})
        if path == "/api/admin/token":
            return httpx.Response(200, json={"access_token": "t"})
        if path == "/api/admin":
            return httpx.Response(200, json={"username": "admin", "role": {"name": "owner", "is_owner": True}})
        if path == "/api/admin-roles/simple":
            return httpx.Response(200, json={"roles": [{"id": 3, "name": "operator", "is_owner": False}]})
        if path == "/api/admins":
            return httpx.Response(200, json={"admins": []})
        if path == "/api/admin" and method == "POST" or (path.startswith("/api/admin/by-id/") and method == "PUT"):
            return httpx.Response(200, json={"id": 9, "username": (body or {}).get("username", "s")})
        if path == "/api/nodes":
            return httpx.Response(200, json={"nodes": [{"id": 1, "name": "n1", "status": "error", "message": "x"}], "total": 1})
        if re.fullmatch(r"/api/node/\d+", path):
            return httpx.Response(200, json={"id": 1, "name": "n1", "status": "connected"})
        if path.endswith("/reconnect") or path.endswith("/hwids/reset") or "/hwids/" in path or path == "/api/users/bulk/set_owner":
            return httpx.Response(200, json={})
        if path.endswith("/hwids"):
            return httpx.Response(200, json={"hwids": [{"hwid": "abc"}]})
        if path.endswith("/usage"):
            return httpx.Response(200, json={"stats": [{"total": 1}]})
        if path == "/api/settings":
            if method == "PUT":
                self.settings = body or {}
            return httpx.Response(200, json=self.settings)
        if path == "/api/system":
            return httpx.Response(200, json={"version": "5.6.0"})
        if path == "/api/groups/simple":
            return httpx.Response(200, json={"groups": [{"id": 1, "name": "g"}]})
        if path == "/api/user_templates":
            return httpx.Response(200, json=[{"id": 2, "name": "t"}])
        if path == "/api/groups":
            return httpx.Response(200, json={"groups": [{"id": 1, "name": "g", "total_users": 3, "inbound_tags": ["vless"]}], "total": 1})
        if path == "/api/hosts":
            return httpx.Response(200, json=[{"id": 1, "inbound_tag": "vless", "is_disabled": False}])
        if path == "/api/inbounds/details":
            return httpx.Response(200, json=[{"tag": "vless"}])
        if path == "/api/user_template" and method == "POST":
            return httpx.Response(201, json={"id": 7, "name": (body or {}).get("name"), "group_ids": (body or {}).get("group_ids")})
        if re.fullmatch(r"/api/user_template/\d+", path) and method == "PUT":
            return httpx.Response(200, json={"id": 7})
        if path in ("/api/user_templates/bulk/enable", "/api/user_templates/bulk/disable"):
            return httpx.Response(200, json={"count": 1})
        m = re.fullmatch(r"/api/user/by-username/([^/]+)", path)
        if m and method == "GET":
            name = m.group(1)
            return httpx.Response(200, json=self._user(name)) if name in self.users else httpx.Response(404, json={"detail": "not found"})
        if path in ("/api/user", "/api/user/from_template") and method == "POST":
            return httpx.Response(
                201, json=self._user(body["username"], **({"data_limit": body["data_limit"]} if "data_limit" in body else {}))
            )
        m = re.fullmatch(r"/api/user/by-id/(\d+)(/[a-z_]+)?", path)
        if m:
            user = next(u for u in self.users.values() if u["id"] == int(m.group(1)))
            if method == "DELETE":
                return httpx.Response(204)
            return httpx.Response(
                200, json=self._user(user["username"], **{k: v for k, v in (body or {}).items() if k in ("status", "data_limit")})
            )
        return httpx.Response(200, json={})


def _adapter(panel: RecordingPanel, **cfg) -> PasarGuardAdapter:
    return PasarGuardAdapter("https://p.example.com", CREDS, {"group_ids": [1], **cfg}, transport=httpx.MockTransport(panel))


async def _exercise_everything() -> list[dict]:
    """Every public adapter operation, in group mode and template mode, against the recording panel."""
    panel = RecordingPanel()
    spec = AccountSpec(username="alice", expire_at=EXPIRE, traffic_bytes=GB, max_devices=2, note="n", owner="store-1")
    a = _adapter(panel)
    await a.health_check()
    await a.create_account(spec)
    await a.get_account("alice")
    await a.suspend_account("alice")
    await a.resume_account("alice")
    await a.extend_account("alice", expire_at=EXPIRE, traffic_bytes=2 * GB)
    await a.reset_traffic("alice")
    await a.rotate_subscription("alice")
    await a.get_usage("alice", start=EXPIRE, end=EXPIRE, period="day")
    await a.list_devices("alice")
    await a.delete_device("alice", "abc")
    await a.reset_devices("alice")
    await a.bulk_set_owner(["1", "2"], "store-1")
    await a.find_admin("store-1")
    await a.ensure_admin(
        "store-1",
        "pw",
        profile={"profile_title": "t", "support_url": "u", "discord_webhook": "d", "sub_domain": "s", "note": "n", "telegram_id": 5},
    )
    await a.update_admin_profile(9, {"profile_title": "t", "telegram_id": 5}, password="pw2")
    await a.list_targets()
    await a.list_nodes()
    await a.get_node(1)
    await a.reconnect_node(1)
    # Phase 4 (PG-07 / PG-11 / PG-12 / PG-13)
    await a.get_system_stats()
    await a.get_system_resources()
    await a.get_nodes_realtime()
    await a.get_node_stats(1)
    await a.sync_node(1)
    await a.list_cores()
    await a.restart_core(1)
    for toggle in (a.set_nodes_disabled, a.set_hosts_disabled, a.set_groups_disabled):
        await toggle([1, 2], True)
        await toggle([1, 2], False)
    for action in ("disable", "enable", "reset_usage", "rotate_links"):
        await a.bulk_users_action(["1", "2"], action)
    await a.set_admin_users_state(9, active=False)
    await a.set_admin_users_state(9, active=True)
    await a.get_admin_detail(9)
    await a.update_admin_limits(9, data_limit=GB, status="disabled", notifications_off=True)
    await a.get_subscription_settings()
    await a.get_settings()
    await a.get_webhook_config("https://m.example.com/api/v1/webhooks/pasarguard/p")
    await a.connect_webhook("https://m.example.com/api/v1/webhooks/pasarguard/p", "s3cret")
    await a.disconnect_webhook("https://m.example.com/api/v1/webhooks/pasarguard/p")
    await a.list_accounts(offset=0, limit=50)
    await a.list_groups_full()
    await a.list_hosts()
    await a.list_inbound_details()
    await a.create_template({"name": "t7", "group_ids": [1], "data_limit": GB, "expire_duration": 86400})
    await a.update_template(7, {"data_limit": 2 * GB})
    await a.set_template_disabled(7, True)
    await a.set_template_disabled(7, False)
    await a.set_next_plan("alice", template_id=2)
    await a.clear_next_plan("alice")
    await a.activate_next_plan("alice")
    await a.apply_template("alice", 2)
    await a.revoke_account("alice")
    t = _adapter(panel, user_template_id=2)  # template mode: create from template, then re-apply product limits + owner
    await t.create_account(AccountSpec(username="bob", expire_at=EXPIRE, traffic_bytes=GB, note="n", owner="store-1"))
    await a.discover_capabilities()
    return panel.requests


@pytest.fixture(scope="module")
def recorded():
    import asyncio

    return asyncio.run(_exercise_everything())


# ----------------------------------------------------------------------------------------------------------------- the tests
def test_fixture_is_the_5_6_panel():
    assert FIXTURE["panel_version"] == "5.6.0"
    assert len(OPS) >= 180  # the whole API, not a hand-picked slice


def test_every_request_the_adapter_makes_is_a_route_of_the_panel(recorded):
    unknown = [f"{r['method']} {r['path']}" for r in recorded if resolve(r["method"], r["path"]) is None]
    assert not unknown, f"routes missing from the PasarGuard 5.6.0 contract: {sorted(set(unknown))}"


def test_query_parameters_are_declared_by_the_panel(recorded):
    bad = []
    for r in recorded:
        key = resolve(r["method"], r["path"])
        if key and r["query"] and not set(r["query"]) <= set(OPS[key]["query"]):
            bad.append(f"{key}: sent {sorted(r['query'])}, panel declares {OPS[key]['query']}")
    assert not bad, bad


def test_json_bodies_use_only_fields_the_panel_declares(recorded):
    bad = []
    for r in recorded:
        key = resolve(r["method"], r["path"])
        schema = SCHEMAS.get(OPS.get(key or "", {}).get("body") or "")
        if key and schema and isinstance(r["body"], dict) and not set(r["body"]) <= set(schema["props"]):
            bad.append(f"{key}: unknown fields {sorted(set(r['body']) - set(schema['props']))}")
    assert not bad, bad


def test_required_body_fields_are_always_sent(recorded):
    checked = 0
    for r in recorded:
        key = resolve(r["method"], r["path"])
        schema = SCHEMAS.get(OPS.get(key or "", {}).get("body") or "")
        if key and schema and isinstance(r["body"], dict):
            checked += 1
            assert set(schema["required"]) <= set(r["body"]), f"{key} is missing {set(schema['required']) - set(r['body'])}"
    assert checked >= 4  # POST /api/user, PUT user, POST/PUT admin


def test_every_declared_capability_endpoint_is_real_and_actually_called(recorded):
    called = {resolve(r["method"], r["path"]) for r in recorded}
    for capability, endpoints in CAPABILITY_ENDPOINTS.items():
        for endpoint in endpoints:
            assert endpoint in OPS, f"{capability}: {endpoint} is not in the PasarGuard contract"
            assert endpoint in called, f"{capability}: {endpoint} is declared but no adapter call reaches it"


def test_capability_tables_cover_exactly_the_known_capabilities():
    assert set(CAPABILITY_REQUIREMENTS) == set(ALL_CAPABILITIES) == set(CAPABILITY_ENDPOINTS)
    assert LEGACY_CAPABILITIES <= set(ALL_CAPABILITIES)


PERMISSION_SCHEMAS = {
    "users": "UsersPermissions",
    "nodes": "NodesPermissions",
    "settings": "SettingsPermissions",
    "hwids": "HwidsPermissions",
    "admins": "AdminsPermissions",
    "system": "SystemPermissions",
    "hosts": "HostsPermissions",
    "groups": "CRUDPermissions",
    "cores": "CRUDPermissions",
    "templates": "CRUDPermissions",
    "api_keys": "APIKeysPermissions",
}


def test_required_permissions_exist_in_the_panels_role_schema():
    role_sections = set(SCHEMAS["RolePermissions"]["props"])
    for capability, permissions in CAPABILITY_REQUIREMENTS.items():
        for permission in permissions:
            section, action = permission.split(".")
            assert section in role_sections, f"{capability}: unknown permission section {section}"
            assert action in SCHEMAS[PERMISSION_SCHEMAS[section]]["props"], f"{capability}: {permission} does not exist in the panel"


def test_user_status_mapping_only_knows_real_panel_statuses():
    assert set(pasarguard._STATUS) <= set(ENUMS["UserStatus"])
    assert set(ENUMS["UserStatus"]) <= set(pasarguard._STATUS), "a new panel status would be reported as 'unknown'"


def test_usage_periods_match_the_panel_enum():
    assert list(USAGE_PERIODS) == ENUMS["Period"]


def test_event_vocabulary_is_stable():
    assert len(USER_EVENTS) == len(set(USER_EVENTS)) == 12


def test_fields_the_adapter_reads_exist_on_the_user_response():
    read = {"id", "username", "status", "expire", "data_limit", "used_traffic", "subscription_url", "admin"}
    assert read <= set(SCHEMAS["UserResponse"]["props"])
    # ``links`` is read defensively (older builds, vless links inline) but 5.6.0 no longer returns it: the subscription URL is the
    # source of configs. Kept optional on purpose; if a panel starts requiring it, this assertion documents the gap.
    assert "links" not in SCHEMAS["UserResponse"]["props"]


def test_admin_profile_and_create_fields_exist_on_the_admin_schemas():
    profile = {"profile_title", "support_url", "discord_webhook", "sub_domain", "note", "telegram_id", "password"}
    assert profile <= set(SCHEMAS["AdminModify"]["props"])
    assert {"username", "password", "role_id"} <= set(SCHEMAS["AdminCreate"]["props"])


def test_user_write_payloads_fit_the_user_schemas():
    spec = AccountSpec(username="u", expire_at=EXPIRE, traffic_bytes=GB, max_devices=2, note="n")
    create = pasarguard.build_create_payload(spec, {"group_ids": [1], "data_limit_reset_strategy": "month", "proxy_settings": {}})
    assert set(create) <= set(SCHEMAS["UserCreate"]["props"])
    modify = pasarguard.build_modify_payload(expire_at=EXPIRE, traffic_bytes=GB, status="active", set_expire=True)
    assert set(modify) <= set(SCHEMAS["UserModify"]["props"])
    assert {"disabled", "active"} <= set(ENUMS["UserStatus"])


# ------------------------------------------------------------------------------------------------ the diff tool (CI/ops helper)
def _tool():
    spec = importlib.util.spec_from_file_location("pasarguard_contract", ROOT.parent.parent / "scripts/pasarguard_contract.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_diff_tool_flags_a_removed_route_and_ignores_a_new_one():
    tool = _tool()
    same = tool.diff(FIXTURE, FIXTURE)
    assert not any(same.values())
    shrunk = json.loads(json.dumps(FIXTURE))
    del shrunk["operations"]["GET /api/nodes"]
    shrunk["operations"]["GET /api/brand-new"] = {"body": None, "ok": None, "query": []}
    changes = tool.diff(FIXTURE, shrunk)
    assert changes["removed_operations"] == ["GET /api/nodes"]
    assert changes["added_operations"] == ["GET /api/brand-new"]


def test_diff_tool_flags_a_renamed_schema_field():
    tool = _tool()
    renamed = json.loads(json.dumps(FIXTURE))
    renamed["schemas"]["UserModify"]["props"].remove("data_limit")
    out = tool.diff(FIXTURE, renamed)
    assert any("UserModify" in row and "data_limit" in row for row in out["schema_changes"])


async def test_create_template_without_groups_is_a_permanent_error_not_a_name_error():
    """Regression: the guard referenced ``ErrorKind`` without importing it (NameError instead of a clean PanelError)."""
    from melorin.modules.vpn.adapters.base import ErrorKind, PanelError

    adapter = _adapter(RecordingPanel())
    with pytest.raises(PanelError) as e:
        await adapter.create_template({"name": "melorin-x", "group_ids": []})
    assert e.value.kind == ErrorKind.PERMANENT
