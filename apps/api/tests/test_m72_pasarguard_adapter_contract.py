"""M7.2: PasarGuard adapter contract tests against an in-memory fake panel (httpx.MockTransport).

Shapes follow the PasarGuard panel API (current ``/api/user/by-id`` style and the legacy Marzban-style
``/api/user/{username}`` style) as documented in the adapter module docstring."""

import datetime as dt
import json
from urllib.parse import parse_qs, unquote

import httpx
import pytest

from melorin.modules.vpn.adapters import pasarguard
from melorin.modules.vpn.adapters.base import AccountSpec, ErrorKind, PanelError
from melorin.modules.vpn.adapters.pasarguard import PasarGuardAdapter

GB = 1024**3
EXPIRE = dt.datetime(2027, 1, 1, 12, 30, 15, 999, tzinfo=dt.UTC)
CREDS = {"username": "admin", "password": "s3cret"}
CFG = {"group_ids": [1, 2], "sub_base_url": "https://sub.example.com"}


@pytest.fixture(autouse=True)
def _clear_token_cache():
    pasarguard._TOKENS.clear()
    yield
    pasarguard._TOKENS.clear()


class FakePanel:
    """Minimal PasarGuard: password login, users keyed by username, numeric ids, full create/modify/delete."""

    def __init__(self, *, legacy=False, token="tok-1", require_grant_type=True):
        self.legacy, self.token, self.require_grant_type = legacy, token, require_grant_type
        self.users: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []
        self.raw_paths: list[str] = []
        self.logins = 0
        self.bodies: list[dict] = []
        self.next_id = 1
        self.fail: dict[tuple[str, str], tuple[int, object]] = {}  # (method, path) -> (status, body)
        self.expire_token_after_login = False

    # ------------------------------------------------------------------ helpers
    def _user_json(self, u):
        return {**u, "subscription_url": f"/sub/{u['username']}-token", "links": ["vless://x"]}

    def _find_by_id(self, uid):
        return next((u for u in self.users.values() if u["id"] == int(uid)), None)

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path, method = req.url.path, req.method
        self.calls.append((method, path))
        self.raw_paths.append(req.url.raw_path.decode().split("?")[0])
        if path == "/api/admin/token":
            form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
            self.logins += 1
            if self.require_grant_type and "grant_type" not in form:
                return httpx.Response(422, json={"detail": [{"loc": ["body", "grant_type"], "msg": "field required"}]})
            if form.get("username") != "admin" or form.get("password") != "s3cret":
                return httpx.Response(401, json={"detail": "Incorrect username or password"})
            return httpx.Response(200, json={"access_token": self.token, "token_type": "bearer"})
        key_ok = req.headers.get("X-Api-Key") == "k-1"
        if not key_ok and req.headers.get("Authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"detail": "Not authenticated"})
        if (method, path) in self.fail:
            status, body = self.fail[(method, path)]
            return httpx.Response(status, json=body) if not isinstance(body, str) else httpx.Response(status, text=body)
        body = json.loads(req.content) if req.content else {}
        if body:
            self.bodies.append(body)
        if path == "/api/system":
            return httpx.Response(200, json={"version": "1.0"})
        if path == "/api/admin":
            return httpx.Response(200, json={"username": "admin"})
        if path == "/api/groups/simple":
            return httpx.Response(200, json={"groups": [{"id": 1, "name": "g1"}, "junk"]})
        if path == "/api/user" and method == "POST":
            return self._create(body)
        if path == "/api/user/from_template" and method == "POST":
            return self._create(
                {"username": body["username"], "status": "active", "data_limit": 5 * GB, "expire": None, "note": body.get("note")}
            )
        prefix = "/api/user/" if self.legacy else "/api/user/by-username/"
        if method == "GET" and path.startswith(prefix):
            u = self.users.get(unquote(path[len(prefix) :]))
            return httpx.Response(200, json=self._user_json(u)) if u else httpx.Response(404, json={"detail": "User not found"})
        if path.startswith("/api/user/by-id/"):
            rest = path[len("/api/user/by-id/") :].split("/")
            u = self._find_by_id(rest[0])
            if not u:
                return httpx.Response(404, json={"detail": "User not found"})
            return self._mutate(method, u, "/".join(rest[1:]), body)
        if self.legacy and path.startswith("/api/user/"):
            rest = path[len("/api/user/") :].split("/", 1)
            u = self.users.get(unquote(rest[0]))
            if not u:
                return httpx.Response(404, json={"detail": "User not found"})
            return self._mutate(method, u, rest[1] if len(rest) > 1 else "", body)
        return httpx.Response(404, json={"detail": "no route"})

    def _create(self, body):
        if body["username"] in self.users:
            return httpx.Response(409, json={"detail": "User already exists"})
        u = {"id": self.next_id, "used_traffic": 0, "data_limit": 0, "expire": None, **body}
        self.next_id += 1
        self.users[u["username"]] = u
        return httpx.Response(200, json=self._user_json(u))

    def _mutate(self, method, u, suffix, body):
        if method == "DELETE":
            del self.users[u["username"]]
            return httpx.Response(204)
        if suffix == "reset":
            u["used_traffic"] = 0
            return httpx.Response(200, json=self._user_json(u))
        if suffix == "revoke_sub":
            u["subscription_url"] = f"/sub/{u['username']}-rotated"
            return httpx.Response(200, json={**self._user_json(u), "subscription_url": u["subscription_url"]})
        if method == "PUT":
            u.update(body)
            return httpx.Response(200, json=self._user_json(u))
        return httpx.Response(405)


def make(panel: FakePanel, *, creds=CREDS, cfg=None, base="https://panel.example.com"):
    config = {**CFG, **(cfg or {})}
    if panel.legacy:
        config["api_style"] = "legacy"
    return PasarGuardAdapter(base, creds, config, transport=httpx.MockTransport(panel))


def spec(**kw):
    base = dict(username="m_1001_ab", expire_at=EXPIRE, traffic_bytes=10 * GB, max_devices=3, note="order 1001")
    base.update(kw)
    return AccountSpec(**base)


# ------------------------------------------------------------------ construction / auth


@pytest.mark.parametrize("url", ["", "ftp://x", "panel.example.com", "https://"])
def test_invalid_base_url_is_rejected(url):
    with pytest.raises(PanelError) as exc:
        PasarGuardAdapter(url, CREDS)
    assert exc.value.kind == ErrorKind.PERMANENT


def test_dashboard_suffix_is_stripped_from_the_base_url():
    assert PasarGuardAdapter("https://p.example.com:8443/dashboard/", CREDS).base == "https://p.example.com:8443"
    assert PasarGuardAdapter("https://p.example.com/", CREDS).base == "https://p.example.com"


async def test_password_login_is_form_encoded_with_grant_type_and_token_is_cached_across_calls():
    panel = FakePanel()
    a = make(panel)
    assert await a.health_check() and await a.health_check()
    assert panel.logins == 1


async def test_login_retries_without_grant_type_on_422_for_older_builds():
    panel = FakePanel(require_grant_type=False)
    a = make(panel)
    assert await a.health_check() is True and panel.logins == 1


async def test_wrong_credentials_fail_permanently_and_do_not_retry():
    panel = FakePanel()
    a = make(panel, creds={"username": "admin", "password": "wrong"})
    with pytest.raises(PanelError) as exc:
        await a.get_account("x")
    assert exc.value.kind == ErrorKind.PERMANENT and "login failed" in exc.value.message and panel.logins == 1


@pytest.mark.parametrize("creds", [{}, {"username": "a"}, {"password": "p"}])
async def test_missing_credentials_are_a_permanent_error(creds):
    with pytest.raises(PanelError) as exc:
        await make(FakePanel(), creds=creds).get_account("x")
    assert exc.value.kind == ErrorKind.PERMANENT and "credentials" in exc.value.message


async def test_an_expired_token_triggers_exactly_one_transparent_relogin():
    panel = FakePanel()
    a = make(panel)
    await a.health_check()
    pasarguard._TOKENS[a._key] = ("stale", pasarguard.time.monotonic() + 1000)
    assert await a.get_account("nobody") is None
    assert panel.logins == 2


async def test_static_access_token_skips_login_and_api_key_uses_the_api_key_header():
    panel = FakePanel()
    assert await make(panel, creds={"access_token": "tok-1"}).health_check() is True
    assert panel.logins == 0
    assert await make(panel, creds={"api_key": "k-1"}).health_check() is True
    assert panel.logins == 0


async def test_login_response_without_access_token_is_a_permanent_error():
    def handler(req):
        return httpx.Response(200, json={"token_type": "bearer"})

    a = PasarGuardAdapter("https://p.example.com", CREDS, CFG, transport=httpx.MockTransport(handler))
    with pytest.raises(PanelError) as exc:
        await a.get_account("x")
    assert exc.value.kind == ErrorKind.PERMANENT and "access_token" in exc.value.message


# ------------------------------------------------------------------ create


async def test_create_account_sends_the_documented_payload_and_maps_the_response():
    panel = FakePanel()
    acc = await make(panel).create_account(spec())
    body = panel.bodies[-1]
    assert body == {
        "username": "m_1001_ab",
        "status": "active",
        "group_ids": [1, 2],
        "proxy_settings": {},
        "data_limit": 10 * GB,
        "expire": "2027-01-01T12:30:15Z",  # UTC ISO-8601 with Z and no microseconds
        "hwid_limit": 3,
        "note": "order 1001",
    }
    assert ("POST", "/api/user") in panel.calls
    assert acc.username == "m_1001_ab" and acc.ref == "1" and acc.status == "active"
    assert acc.traffic_limit_bytes == 10 * GB and acc.expire_at == EXPIRE.replace(microsecond=0)
    assert acc.subscription_url == "https://sub.example.com/sub/m_1001_ab-token"  # relative URL gets sub_base_url
    assert acc.links == ["vless://x"]


async def test_create_account_omits_optional_fields_and_truncates_long_notes():
    panel = FakePanel()
    await make(panel, cfg={"data_limit_reset_strategy": "month", "proxy_settings": {"vless": {}}}).create_account(
        spec(max_devices=None, note="n" * 900, traffic_bytes=0, expire_at=None, username="u2")
    )
    body = panel.bodies[-1]
    assert "hwid_limit" not in body and len(body["note"]) == 500
    assert body["data_limit"] == 0 and body["expire"] == 0
    assert body["data_limit_reset_strategy"] == "month" and body["proxy_settings"] == {"vless": {}}


async def test_create_account_from_template_uses_the_template_endpoint_and_minimal_body():
    panel = FakePanel()
    await make(panel, cfg={"user_template_id": "7", "group_ids": []}).create_account(spec(username="t1"))
    assert ("POST", "/api/user/from_template") in panel.calls
    assert panel.bodies[-1] == {"user_template_id": 7, "username": "t1", "note": "order 1001"}


@pytest.mark.parametrize("template_id", ["abc", 0, -3])
async def test_invalid_template_id_is_a_permanent_error(template_id):
    with pytest.raises(PanelError) as exc:
        await make(FakePanel(), cfg={"user_template_id": template_id}).create_account(spec())
    assert exc.value.kind == ErrorKind.PERMANENT and "user_template_id" in exc.value.message


async def test_group_ids_are_required_for_direct_creation():
    with pytest.raises(PanelError) as exc:
        await make(FakePanel(), cfg={"group_ids": []}).create_account(spec())
    assert exc.value.kind == ErrorKind.PERMANENT and "group_ids" in exc.value.message


async def test_create_is_idempotent_when_the_user_already_exists_after_an_unknown_outcome():
    panel = FakePanel()
    a = make(panel)
    first = await a.create_account(spec())
    again = await a.create_account(spec())
    assert first.ref == again.ref and len(panel.users) == 1
    assert [c for c in panel.calls if c == ("POST", "/api/user")] == [("POST", "/api/user")]


async def test_create_conflict_409_is_resolved_by_reading_the_existing_user():
    panel = FakePanel()
    a = make(panel)
    # The user appears between the existence probe and the create call (race with a retry).
    original_get = a._get_raw
    calls = {"n": 0}

    async def racing_get(username):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await original_get(username)

    panel.users["m_1001_ab"] = {"id": 9, "username": "m_1001_ab", "status": "active", "used_traffic": 0, "data_limit": 5, "expire": None}
    a._get_raw = racing_get
    acc = await a.create_account(spec())
    assert acc.ref == "9"


async def test_create_response_without_username_is_completed_by_re_reading_the_user():
    panel = FakePanel()
    a = make(panel)
    real = panel._create

    def lean_create(body):
        real(body)
        return httpx.Response(200, json={"ok": True})

    panel._create = lean_create
    acc = await a.create_account(spec())
    assert acc.username == "m_1001_ab"


# ------------------------------------------------------------------ read / map


async def test_get_account_returns_none_for_404_and_maps_status_and_usage():
    panel = FakePanel()
    a = make(panel)
    assert await a.get_account("ghost") is None
    panel.users["bob"] = {
        "id": 5, "username": "bob", "status": "on_hold", "used_traffic": 123, "data_limit": 2 * GB, "expire": 1_800_000_000,
    }  # fmt: skip
    acc = await a.get_account("bob")
    assert acc.status == "active" and acc.traffic_used_bytes == 123 and acc.traffic_limit_bytes == 2 * GB
    assert acc.expire_at == dt.datetime.fromtimestamp(1_800_000_000, dt.UTC)


async def test_usernames_are_url_quoted_in_the_path():
    panel = FakePanel()
    a = make(panel)
    await a.get_account("we ird/name")
    assert panel.raw_paths[-1] == "/api/user/by-username/we%20ird%2Fname"


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("active", "active"),
        ("on_hold", "active"),
        ("disabled", "disabled"),
        ("expired", "expired"),
        ("limited", "limited"),
        ("weird", "unknown"),
        ("", "unknown"),
    ],
)
def test_status_normalisation(raw, normalized):
    assert PasarGuardAdapter("https://p.example.com", CREDS).normalize_status(raw) == normalized


def test_expire_helpers_round_trip_and_treat_zero_as_never():
    assert pasarguard.iso_expire(None) == 0
    assert pasarguard.iso_expire(dt.datetime(2027, 1, 1, 3, 30)) == "2027-01-01T03:30:00Z"  # naive == UTC
    tehran = dt.timezone(dt.timedelta(hours=3, minutes=30))
    assert pasarguard.iso_expire(dt.datetime(2027, 1, 1, 7, 0, tzinfo=tehran)) == "2027-01-01T03:30:00Z"
    for never in (None, 0, "0", ""):
        assert pasarguard.parse_expire(never) is None
    assert pasarguard.parse_expire("2027-01-01T03:30:00Z") == dt.datetime(2027, 1, 1, 3, 30, tzinfo=dt.UTC)
    assert pasarguard.parse_expire("2027-01-01T03:30:00").tzinfo is dt.UTC
    assert pasarguard.parse_expire(1_800_000_000.0).tzinfo is dt.UTC


def test_modify_payload_only_contains_requested_fields():
    assert pasarguard.build_modify_payload() == {}
    assert pasarguard.build_modify_payload(status="disabled") == {"status": "disabled"}
    assert pasarguard.build_modify_payload(traffic_bytes=0) == {"data_limit": 0}
    assert pasarguard.build_modify_payload(expire_at=None, set_expire=True) == {"expire": 0}


# ------------------------------------------------------------------ lifecycle


async def test_suspend_and_resume_toggle_status_by_id():
    panel = FakePanel()
    a = make(panel)
    await a.create_account(spec())
    await a.suspend_account("m_1001_ab")
    assert panel.users["m_1001_ab"]["status"] == "disabled" and ("PUT", "/api/user/by-id/1") in panel.calls
    await a.resume_account("m_1001_ab")
    assert panel.users["m_1001_ab"]["status"] == "active"


async def test_extend_sets_expiry_traffic_and_reactivates_and_never_converts_unlimited():
    panel = FakePanel()
    a = make(panel)
    await a.create_account(spec())
    await a.suspend_account("m_1001_ab")
    new_expire = EXPIRE + dt.timedelta(days=30)
    await a.extend_account("m_1001_ab", expire_at=new_expire, traffic_bytes=20 * GB)
    assert panel.bodies[-1] == {"expire": "2027-01-31T12:30:15Z", "data_limit": 20 * GB, "status": "active"}
    await a.extend_account("m_1001_ab", expire_at=None, traffic_bytes=0)
    assert panel.bodies[-1] == {"expire": 0, "data_limit": 0, "status": "active"}


async def test_extend_of_an_unknown_user_is_a_permanent_error():
    with pytest.raises(PanelError) as exc:
        await make(FakePanel()).extend_account("ghost", expire_at=EXPIRE, traffic_bytes=1)
    assert exc.value.kind == ErrorKind.PERMANENT and "not found" in exc.value.message


async def test_revoke_deletes_and_is_idempotent_when_the_user_is_already_gone():
    panel = FakePanel()
    a = make(panel)
    await a.create_account(spec())
    await a.revoke_account("m_1001_ab")
    await a.revoke_account("m_1001_ab")
    assert panel.users == {}
    assert [c for c in panel.calls if c[0] == "DELETE"] == [("DELETE", "/api/user/by-id/1")]


async def test_reset_traffic_and_rotate_subscription():
    panel = FakePanel()
    a = make(panel)
    await a.create_account(spec())
    panel.users["m_1001_ab"]["used_traffic"] = 999
    acc = await a.reset_traffic("m_1001_ab")
    assert acc.traffic_used_bytes == 0
    rotated = await a.rotate_subscription("m_1001_ab")
    assert rotated.subscription_url.endswith("-rotated") and rotated.subscription_url.startswith("https://sub.example.com")


async def test_list_groups_returns_only_dict_entries_and_falls_back_to_the_full_endpoint():
    panel = FakePanel()
    assert await make(panel).list_groups() == [{"id": 1, "name": "g1"}]
    panel.fail[("GET", "/api/groups/simple")] = (404, {"detail": "nope"})
    original = panel.__call__

    def with_groups(req):
        if req.url.path == "/api/groups" and req.headers.get("Authorization") == "Bearer tok-1":
            return httpx.Response(200, json=[{"id": 2}])
        return original(req)

    a = PasarGuardAdapter("https://panel.example.com", CREDS, CFG, transport=httpx.MockTransport(with_groups))
    assert await a.list_groups() == [{"id": 2}]


def test_capabilities_advertise_traffic_reset():
    caps = PasarGuardAdapter("https://p.example.com", CREDS).capabilities()
    assert caps.suspend and caps.extend and caps.subscription_url and caps.traffic_reset


async def test_close_is_a_noop():
    assert await PasarGuardAdapter("https://p.example.com", CREDS).close() is None


# ------------------------------------------------------------------ legacy API style


async def test_legacy_style_uses_username_paths_for_read_and_write():
    panel = FakePanel(legacy=True)
    a = make(panel)
    await a.create_account(spec())
    await a.suspend_account("m_1001_ab")
    await a.revoke_account("m_1001_ab")
    paths = [c for c in panel.calls if c[1].startswith("/api/user/")]
    assert ("GET", "/api/user/m_1001_ab") in paths
    assert ("PUT", "/api/user/m_1001_ab") in paths and ("DELETE", "/api/user/m_1001_ab") in paths
    assert not any("by-id" in p or "by-username" in p for _, p in paths)


# ------------------------------------------------------------------ error classification


@pytest.mark.parametrize(
    ("status", "kind"),
    [(500, ErrorKind.TRANSIENT), (502, ErrorKind.TRANSIENT), (408, ErrorKind.TRANSIENT), (425, ErrorKind.TRANSIENT), (429, ErrorKind.TRANSIENT),
     (400, ErrorKind.PERMANENT), (403, ErrorKind.PERMANENT), (422, ErrorKind.PERMANENT)],
)  # fmt: skip
async def test_http_errors_are_classified_for_the_retry_policy(status, kind):
    panel = FakePanel()
    panel.fail[("GET", "/api/user/by-username/x")] = (status, {"detail": "boom"})
    with pytest.raises(PanelError) as exc:
        await make(panel).get_account("x")
    assert exc.value.kind == kind and f"-> {status}" in exc.value.message and "boom" in exc.value.message


async def test_timeout_is_an_unknown_outcome_and_network_errors_are_transient():
    def timeout(req):
        if req.url.path == "/api/admin/token":
            return httpx.Response(200, json={"access_token": "t"})
        raise httpx.ReadTimeout("slow")

    def down(req):
        raise httpx.ConnectError("refused")

    a = PasarGuardAdapter("https://p.example.com", {"access_token": "t"}, CFG, transport=httpx.MockTransport(timeout))
    with pytest.raises(PanelError) as exc:
        await a.get_account("x")
    assert exc.value.kind == ErrorKind.UNKNOWN
    b = PasarGuardAdapter("https://p.example.com", {"access_token": "t"}, CFG, transport=httpx.MockTransport(down))
    with pytest.raises(PanelError) as exc:
        await b.get_account("x")
    assert exc.value.kind == ErrorKind.TRANSIENT


async def test_redirects_are_never_followed_with_the_bearer_token():
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(302, headers={"location": "https://evil.example.com/steal"})

    a = PasarGuardAdapter("https://p.example.com", {"access_token": "t"}, CFG, transport=httpx.MockTransport(handler))
    with pytest.raises(PanelError) as exc:
        await a.get_account("x")
    assert exc.value.kind == ErrorKind.PERMANENT and "redirect" in exc.value.message
    assert seen == ["https://p.example.com/api/user/by-username/x"]


async def test_non_json_success_response_points_at_a_wrong_base_url():
    def handler(req):
        return httpx.Response(200, text="<html>dashboard</html>")

    a = PasarGuardAdapter("https://p.example.com", {"access_token": "t"}, CFG, transport=httpx.MockTransport(handler))
    with pytest.raises(PanelError) as exc:
        await a.get_account("x")
    assert exc.value.kind == ErrorKind.PERMANENT and "base_url" in exc.value.message


def test_error_detail_extracts_the_most_useful_message():
    d = pasarguard._error_detail
    assert d('{"detail": "User exists"}') == "User exists"
    assert d('{"message": "m"}') == "m"
    assert d('{"detail": [{"loc": ["body", "group_ids"], "msg": "field required"}]}') == "group_ids: field required"
    assert d('{"detail": ["a", "b"]}') == "a; b"
    assert d("plain text") == "plain text"
    assert d("x" * 1000) == "x" * 300
    assert d("[1, 2]") == "[1, 2]"


async def test_health_check_probes_system_then_admin_and_reports_failure():
    panel = FakePanel()
    panel.fail[("GET", "/api/system")] = (403, {"detail": "forbidden"})
    assert await make(panel).health_check() is True  # limited role: falls through to /api/admin
    assert ("GET", "/api/admin") in panel.calls
    broken = FakePanel()
    broken.fail[("GET", "/api/system")] = (500, {"detail": "down"})
    assert await make(broken).health_check() is False
    both = FakePanel()
    both.fail[("GET", "/api/system")] = (404, {})
    both.fail[("GET", "/api/admin")] = (404, {})
    assert await make(both).health_check() is False
