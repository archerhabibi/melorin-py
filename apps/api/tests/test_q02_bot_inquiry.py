"""Bot account inquiry (customer + reseller-store owner): chips, search, paging, live card. Telegram + Core mocked."""

import asyncio
import importlib.util
import json
import uuid
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def acc(i, **kw):
    return {
        "id": str(uuid.uuid4()),
        "username": f"u{i}",
        "status": "active",
        "health": "active",
        "days_left": 20,
        "can_renew": True,
        "subscription_url": f"https://s/x{i}",
        "expires_at": "2099-01-01T00:00:00Z",
        "traffic_limit_bytes": 0,
        "traffic_used_bytes": 0,
        **kw,
    }


class Core:
    def __init__(self):
        self.sent, self.edits, self.calls = [], [], []
        self.rows = [acc(i) for i in range(10)]
        self.owner = True

    def handler(self, request: httpx.Request) -> httpx.Response:
        url, body = str(request.url), request.content or b""
        if "api.telegram.org" in url:
            method = url.rsplit("/", 1)[1]
            if method == "sendMessage":
                self.sent.append(json.loads(body))
            elif method == "editMessageText":
                self.edits.append(json.loads(body))
            return httpx.Response(200, json={"ok": True, "result": {}})
        path, params = request.url.path, dict(request.url.params)
        self.calls.append((request.method, path, params))
        if path == "/api/v1/stores/main":
            return httpx.Response(200, json={"id": "s1", "name": "Main"})
        if path.startswith("/api/v1/stores/by-slug/"):
            return httpx.Response(200, json={"id": "s1", "name": "Shop"})
        if path == "/api/v1/stores/s1/reseller/profile":
            return httpx.Response(200 if self.owner else 403, json={})
        if path == "/api/v1/auth/telegram/bot":
            return httpx.Response(200, json={"access_token": "A", "refresh_token": "R"})
        if "/reseller/" in path and not self.owner:
            return httpx.Response(403, json={})
        if path.endswith("/summary"):
            return httpx.Response(200, json={"total": len(self.rows), "active": len(self.rows), "expiring": 0, "expired": 0})
        if path.endswith("/refresh"):
            row = next(a for a in self.rows if a["id"] in path)
            return httpx.Response(200, json={**row, "customer_name": "Sara"})
        if path in ("/api/v1/vpn-accounts", "/api/v1/stores/s1/reseller/accounts"):
            rows = self.rows
            if params.get("q"):
                rows = [a for a in rows if params["q"] in a["username"]]
            off, lim = int(params.get("offset", 0)), int(params.get("limit", 100))
            return httpx.Response(200, json=[{**a, "customer_name": "Sara"} for a in rows[off : off + lim]])
        return httpx.Response(404, json={})


@pytest.fixture
def bots(tmp_path, monkeypatch):
    for k, v in {
        "MELORIN_TELEGRAM_TOKEN": "tok",
        "MELORIN_CORE_URL": "http://core",
        "MELORIN_BOT_SERVICE_SECRET": "sek",
        "MELORIN_TELEGRAM_OFFSET_FILE": str(tmp_path / "o.json"),
    }.items():
        monkeypatch.setenv(k, v)
    core = Core()
    main = load("q02_main", "telegram-main/runner.py").TelegramRunner()
    main.client = httpx.AsyncClient(transport=httpx.MockTransport(core.handler))
    res_mod = load("q02_res", "telegram-reseller/runner.py")
    res = res_mod.ResellerTelegramRunner(token="rtok", slug="shop", state_suffix="s1")
    res.client = httpx.AsyncClient(transport=httpx.MockTransport(core.handler))
    return main, res, core


def cb(data, uid=1):
    return {
        "update_id": uid,
        "callback_query": {
            "id": f"c{uid}",
            "from": {"id": 7, "first_name": "Ali"},
            "data": data,
            "message": {"chat": {"id": 9}, "message_id": 5},
        },
    }


def msg(text, uid=1):
    return {"update_id": uid, "message": {"chat": {"id": 9}, "from": {"id": 7, "first_name": "Ali"}, "text": text}}


def data_of(payload):
    return [b["callback_data"] for row in payload["reply_markup"]["inline_keyboard"] for b in row]


def run(r, u):
    asyncio.run(r.handle(u))


def test_list_has_chips_pages_and_search(bots):
    main, _, core = bots
    run(main, msg("/accounts"))
    first = core.sent[-1]
    d = data_of(first)
    assert sum(x.startswith("account:") for x in d) == 8 and "acl:-:1" in d and "acs:1" in d
    assert {"acl:a:0", "acl:x:0", "acl:e:0"} <= set(d)
    run(main, cb("acl:-:1", 2))
    assert sum(x.startswith("account:") for x in data_of(core.edits[-1])) == 2


def test_search_is_one_shot_and_sent_to_core(bots):
    main, _, core = bots
    run(main, msg("/accounts"))
    run(main, cb("acs:1", 2))
    run(main, msg("u7", 3))
    assert core.calls[-1][2]["q"] == "u7" and "u7" in core.sent[-1]["text"]
    run(main, msg("random text", 4))  # no longer read as a search
    assert not any(c[2].get("q") == "random text" for c in core.calls)
    run(main, cb("acq:1", 5))
    assert "q" not in core.calls[-1][2]


def test_state_filter_is_passed_to_core(bots):
    main, _, core = bots
    run(main, msg("/accounts"))
    run(main, cb("acl:x:0", 2))
    assert core.calls[-1][2]["state"] == "expiring"


def test_card_reads_live_from_panel_via_refresh(bots):
    main, _, core = bots
    run(main, msg("/accounts"))
    target = core.rows[0]["id"]
    run(main, cb(f"account:{target}", 2))
    assert core.calls[-1][1] == f"/api/v1/vpn-accounts/{target}/refresh" and core.calls[-1][0] == "POST"
    assert any(x.startswith("rnw:") for x in data_of(core.edits[-1]))


def test_owner_sees_store_accounts_with_customer_names(bots):
    _, res, core = bots
    run(res, msg("/allaccounts"))
    assert core.calls[-1][1] == "/api/v1/stores/s1/reseller/accounts"
    assert "Sara" in json.dumps(core.sent[-1], ensure_ascii=False)
    target = core.rows[0]["id"]
    run(res, cb(f"oaccount:{target}", 2))
    e = core.edits[-1]
    assert "Sara" in e["text"] and not any(x.startswith("rnw:") for x in data_of(e)) and any(x.startswith("oqr:") for x in data_of(e))


def test_non_owner_is_refused_by_core(bots):
    _, res, core = bots
    core.owner = False
    run(res, msg("/allaccounts"))
    assert "دسترسی" in core.sent[-1]["text"]
