"""Contract tests for the Sanaei 3x-ui adapter against an in-memory fake panel (v3 clients API + legacy inbound API).

Shapes follow https://docs.sanaei.dev/docs/reference/api/ and web/controller/client.go in MHSanaei/3x-ui.
"""
import datetime as dt
import json
from urllib.parse import parse_qs, unquote

import httpx
import pytest

from melorin.modules.vpn.adapters.base import AccountSpec, ErrorKind, PanelError
from melorin.modules.vpn.adapters.sanaei import SanaeiAdapter, clean_client

GB = 1024**3
SUB = "https://sub.example.com:2096/sub"


class FakeV3:
    """Minimal 3x-ui 3.x: /panel/api/clients/* with Bearer auth and full-row update semantics."""

    def __init__(self, token="tok"):
        self.token, self.clients, self.traffic, self.calls, self.next_id = token, {}, {}, [], 1

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path.removeprefix("/kharej")  # web base path
        self.calls.append((req.method, path))
        if req.headers.get("Authorization") != f"Bearer {self.token}":
            return httpx.Response(401 if req.headers.get("X-Requested-With") else 404)
        body = json.loads(req.content) if req.content else {}
        if path == "/panel/api/clients/list/paged":
            return httpx.Response(200, json={"success": True, "obj": {"items": [], "total": len(self.clients)}})
        if path == "/panel/api/server/status":
            return httpx.Response(200, json={"success": True, "obj": {"cpu": 3.5, "xray": {"state": "running"}}})
        if path.startswith("/panel/api/clients/get/"):
            email = unquote(path.rsplit("/", 1)[1])
            rec = self.clients.get(email)
            if not rec:
                return httpx.Response(200, json={"success": False, "msg": "get: record not found", "obj": None})
            return httpx.Response(200, json={"success": True, "obj": {"client": rec, "inboundIds": rec["_inbounds"]}})
        if path.startswith("/panel/api/clients/traffic/"):
            email = unquote(path.rsplit("/", 1)[1])
            t = self.traffic.get(email)
            return httpx.Response(200, json={"success": True, "obj": t} if t else {"success": False, "msg": "record not found"})
        if path.startswith("/panel/api/clients/links/"):
            return httpx.Response(200, json={"success": True, "obj": ["vless://uuid@host:443#x"]})
        if path == "/panel/api/clients/add":
            c = body["client"]
            assert isinstance(c.get("tgId", 0), int), "tgId must be int64"
            if c["email"] in self.clients:
                return httpx.Response(200, json={"success": False, "msg": "email already in use"})
            rec = {**c, "id": self.next_id, "uuid": f"uuid-{self.next_id}", "_inbounds": body["inboundIds"]}
            self.next_id += 1
            self.clients[c["email"]] = rec
            self.traffic[c["email"]] = {"email": c["email"], "up": 0, "down": 0, "total": c["totalGB"], "enable": True}
            return httpx.Response(200, json={"success": True, "msg": "Client added"})
        if path.startswith("/panel/api/clients/update/"):
            email = unquote(path.rsplit("/", 1)[1])
            if email not in self.clients:
                return httpx.Response(200, json={"success": False, "msg": "record not found"})
            # model.Client.id is a string; a numeric record id would fail Go unmarshal.
            if not isinstance(body.get("id", ""), str) or not isinstance(body.get("tgId", 0), int):
                return httpx.Response(200, json={"success": False, "msg": "json: cannot unmarshal"})
            old = self.clients[email]
            # full replace, not patch
            self.clients[email] = {**body, "id": old["id"], "uuid": body.get("id", old["uuid"]), "_inbounds": old["_inbounds"]}
            return httpx.Response(200, json={"success": True, "msg": "Client updated"})
        if path.startswith("/panel/api/clients/del/"):
            email = unquote(path.rsplit("/", 1)[1])
            if self.clients.pop(email, None) is None:
                return httpx.Response(200, json={"success": False, "msg": "record not found"})
            return httpx.Response(200, json={"success": True})
        if path.startswith("/panel/api/clients/resetTraffic/"):
            email = unquote(path.rsplit("/", 1)[1])
            self.traffic[email].update(up=0, down=0)
            return httpx.Response(200, json={"success": True})
        return httpx.Response(404)


class FakeLegacy:
    """3x-ui 2.x: cookie login, clients inside inbound.settings (JSON string)."""

    def __init__(self):
        self.inbound = {"id": 7, "protocol": "vless", "settings": json.dumps({"clients": [], "decryption": "none"}), "clientStats": []}
        self.logged_in, self.logins, self.calls = False, 0, []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        self.calls.append((req.method, path))
        if path == "/xui/login":
            form = parse_qs(req.content.decode())
            ok = form.get("username") == ["admin"] and form.get("password") == ["pw"]
            self.logged_in, self.logins = ok, self.logins + 1
            return httpx.Response(200, json={"success": ok})
        if not self.logged_in:
            return httpx.Response(401)
        if path.startswith("/xui/panel/api/clients/"):
            return httpx.Response(404)
        s = json.loads(self.inbound["settings"])
        if path == "/xui/panel/api/inbounds/get/7":
            return httpx.Response(200, json={"success": True, "obj": self.inbound})
        body = json.loads(req.content) if req.content else {}
        if path == "/xui/panel/api/inbounds/addClient":
            new = json.loads(body["settings"])["clients"]
            s["clients"] += new
            self.inbound["clientStats"] += [{"email": c["email"], "up": 1, "down": 2, "enable": True} for c in new]
        elif path.startswith("/xui/panel/api/inbounds/updateClient/"):
            cid = path.rsplit("/", 1)[1]
            upd = json.loads(body["settings"])["clients"][0]
            s["clients"] = [upd if c["id"] == cid else c for c in s["clients"]]
        elif path.startswith("/xui/panel/api/inbounds/7/delClient/"):
            cid = path.rsplit("/", 1)[1]
            s["clients"] = [c for c in s["clients"] if c["id"] != cid]
        elif path in ("/xui/server/status", "/xui/panel/api/server/status"):
            return httpx.Response(200, json={"success": True, "obj": {}})
        else:
            return httpx.Response(404)
        self.inbound["settings"] = json.dumps(s)
        return httpx.Response(200, json={"success": True})


def v3_adapter(fake, **cfg):
    config = {"inbound_ids": [3, 5], "sub_base_url": SUB, **cfg}
    return SanaeiAdapter("https://panel.example.com:2053/kharej", {"api_token": "tok"}, config, transport=httpx.MockTransport(fake))


def spec(name="m_ord1_ab12", days=30, gb=50):
    return AccountSpec(name, dt.datetime.now(dt.UTC) + dt.timedelta(days=days), gb * GB, 2, "ORD1")


async def test_v3_full_lifecycle():
    fake = FakeV3()
    a = v3_adapter(fake)
    acc = await a.create_account(spec())
    assert acc.status == "active" and acc.traffic_limit_bytes == 50 * GB
    assert acc.subscription_url.startswith(SUB + "/") and acc.links
    assert fake.clients["m_ord1_ab12"]["_inbounds"] == [3, 5]
    assert fake.clients["m_ord1_ab12"]["limitIp"] == 2
    # idempotent create
    again = await a.create_account(spec())
    assert again.subscription_url == acc.subscription_url and len(fake.clients) == 1

    await a.suspend_account("m_ord1_ab12")
    assert (await a.get_account("m_ord1_ab12")).status == "disabled"
    # update must keep fields the API would otherwise wipe (full replace)
    assert fake.clients["m_ord1_ab12"]["subId"] and fake.clients["m_ord1_ab12"]["uuid"] == "uuid-1"

    new_exp = dt.datetime.now(dt.UTC) + dt.timedelta(days=60)
    ext = await a.extend_account("m_ord1_ab12", expire_at=new_exp, traffic_bytes=100 * GB)
    assert ext.status == "active" and ext.traffic_limit_bytes == 100 * GB
    assert ext.subscription_url == acc.subscription_url  # renew keeps the same link

    fake.traffic["m_ord1_ab12"].update(up=60 * GB, down=50 * GB)
    assert (await a.get_account("m_ord1_ab12")).status == "limited"
    assert (await a.reset_traffic("m_ord1_ab12")).traffic_used_bytes == 0

    await a.revoke_account("m_ord1_ab12")
    await a.revoke_account("m_ord1_ab12")  # already gone = ok
    assert await a.get_account("m_ord1_ab12") is None
    assert await a.health_check() is True
    await a.close()


async def test_v3_requires_sub_base_url_before_writing():
    fake = FakeV3()
    a = SanaeiAdapter("https://p.example.com", {"api_token": "tok"}, {"inbound_ids": [1]}, transport=httpx.MockTransport(fake))
    with pytest.raises(PanelError) as e:
        await a.create_account(spec())
    assert e.value.kind == ErrorKind.PERMANENT and not fake.clients
    assert not any(p.endswith("/add") for _, p in fake.calls)


async def test_v3_template_client_supplies_inbounds_and_flow():
    fake = FakeV3()
    fake.clients["template"] = {"email": "template", "id": 9, "uuid": "u9", "flow": "xtls-rprx-vision", "limitIp": 1, "_inbounds": [11]}
    a = SanaeiAdapter("https://p.example.com", {"api_token": "tok"}, {"template_username": "template", "sub_base_url": SUB},
                      transport=httpx.MockTransport(fake))
    await a.create_account(AccountSpec("u1", None, 0))
    c = fake.clients["u1"]
    assert c["_inbounds"] == [11] and c["flow"] == "xtls-rprx-vision" and c["limitIp"] == 1 and c["expiryTime"] == 0


async def test_v3_missing_template_is_permanent_and_not_cached():
    fake = FakeV3()
    a = SanaeiAdapter("https://p.example.com", {"api_token": "tok"}, {"template_username": "nope", "sub_base_url": SUB},
                      transport=httpx.MockTransport(fake))
    with pytest.raises(PanelError):
        await a.create_account(spec())
    assert a._template is None


async def test_bad_token_is_permanent_and_health_false():
    a = SanaeiAdapter("https://p.example.com", {"api_token": "wrong"}, {"inbound_ids": [1], "sub_base_url": SUB},
                      transport=httpx.MockTransport(FakeV3()))
    assert await a.health_check() is False
    with pytest.raises(PanelError) as e:
        await a.get_account("x")
    assert e.value.kind == ErrorKind.PERMANENT


async def test_timeout_is_unknown_and_5xx_transient():
    def timeout(req):
        raise httpx.ReadTimeout("slow", request=req)

    a = SanaeiAdapter("https://p.example.com", {"api_token": "t"}, {"api_style": "v3", "inbound_ids": [1], "sub_base_url": SUB},
                      transport=httpx.MockTransport(timeout))
    with pytest.raises(PanelError) as e:
        await a.get_account("x")
    assert e.value.kind == ErrorKind.UNKNOWN

    b = SanaeiAdapter("https://p.example.com", {"api_token": "t"}, {"api_style": "v3", "inbound_ids": [1], "sub_base_url": SUB},
                      transport=httpx.MockTransport(lambda r: httpx.Response(502)))
    with pytest.raises(PanelError) as e:
        await b.get_account("x")
    assert e.value.kind == ErrorKind.TRANSIENT


async def test_redirect_is_not_followed():
    a = SanaeiAdapter("https://p.example.com", {"api_token": "t"}, {"api_style": "v3", "inbound_ids": [1], "sub_base_url": SUB},
                      transport=httpx.MockTransport(lambda r: httpx.Response(302, headers={"Location": "http://169.254.169.254/"})))
    with pytest.raises(PanelError) as e:
        await a.get_account("x")
    assert e.value.kind == ErrorKind.PERMANENT


async def test_legacy_cookie_flow_with_string_settings_and_relogin():
    fake = FakeLegacy()
    a = SanaeiAdapter("https://p.example.com/xui/panel", {"username": "admin", "password": "pw"},
                      {"inbound_id": 7, "sub_base_url": SUB}, transport=httpx.MockTransport(fake))
    acc = await a.create_account(spec("legacy1"))
    assert acc.ref.startswith("7:") and acc.traffic_used_bytes == 3 and acc.subscription_url.startswith(SUB)
    stored = json.loads(fake.inbound["settings"])["clients"][0]
    assert isinstance(stored["tgId"], int)
    fake.logged_in = False  # session expired -> 401 -> transparent re-login
    await a.suspend_account("legacy1")
    assert fake.logins == 2
    assert (await a.get_account("legacy1")).status == "disabled"
    await a.revoke_account("legacy1")
    assert await a.get_account("legacy1") is None
    assert await a.health_check() is True


async def test_legacy_nested_settings_object_is_accepted():
    fake = FakeLegacy()
    fake.logged_in = True
    a = SanaeiAdapter("https://p.example.com/xui", {"username": "admin", "password": "pw"},
                      {"api_style": "legacy", "inbound_ids": [7], "sub_base_url": SUB}, transport=httpx.MockTransport(fake))
    fake.inbound["settings"] = json.dumps({"clients": [{"id": "c1", "email": "n1", "enable": True, "totalGB": 0, "expiryTime": 0, "subId": "s1"}]})
    orig = fake.__call__

    def nested(req):
        r = orig(req)
        if req.url.path.endswith("/inbounds/get/7"):
            obj = dict(fake.inbound, settings=json.loads(fake.inbound["settings"]))
            return httpx.Response(200, json={"success": True, "obj": obj})
        return r

    a.transport = httpx.MockTransport(nested)
    acc = await a.get_account("n1")
    assert acc and acc.subscription_url == f"{SUB}/s1" and acc.status == "active"


def test_clean_client_maps_record_to_model_client():
    out = clean_client({"id": 14, "uuid": "u-1", "email": "a", "tgId": "", "inboundIds": [1], "traffic": {}, "createdAt": 1})
    assert out == {"id": "u-1", "email": "a", "tgId": 0}


def test_invalid_config_rejected():
    with pytest.raises(PanelError):
        SanaeiAdapter("ftp://x", {}, {})
    with pytest.raises(PanelError):
        SanaeiAdapter("https://x", {}, {"api_style": "v9"})
