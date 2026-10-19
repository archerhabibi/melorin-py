"""Bundle-based purchase flow of the Telegram bot (bundle -> location -> packages -> username -> quote -> order). Telegram + Core mocked."""

import asyncio
import importlib.util
import json
import uuid
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).parents[2]
PID = str(uuid.uuid4())
ACC = str(uuid.uuid4())
P1, P2, P3 = (str(uuid.uuid4()) for _ in range(3))
PAN1, PAN2 = str(uuid.uuid4()), str(uuid.uuid4())


def bundle(pid, name, kind="direct", sel="automatic", naming="automatic", panels=()):
    return {"id": pid, "name": name, "kind_label": kind, "selection_mode": sel, "naming_mode": naming, "panels": list(panels)}


class Fake:
    def __init__(self):
        self.sent, self.edits, self.calls = [], [], []
        self.bundles = [bundle(P1, "Alpha")]
        self.pkgs = [{"product_id": PID, "name": "Pkg", "price": 1000, "currency": "IRT"}]
        self.renewal = {"renewable": True, "package": self.pkgs[0], "after": {"duration_days": 30, "traffic_gb": 10}}

    def handler(self, request: httpx.Request) -> httpx.Response:
        url, body = str(request.url), request.content or b""
        if "api.telegram.org" in url:
            method = url.rsplit("/", 1)[1]
            if method == "sendMessage":
                self.sent.append(json.loads(body))
            elif method == "editMessageText":
                self.edits.append(json.loads(body))
            return httpx.Response(200, json={"ok": True, "result": {}})
        path = request.url.path
        js = json.loads(body) if body and request.headers.get("content-type", "").startswith("application/json") else None
        self.calls.append((request.method, path, js))
        if path == "/api/v1/stores/main":
            return httpx.Response(200, json={"id": "s1", "name": "Main"})
        if path == "/api/v1/auth/telegram/bot":
            return httpx.Response(200, json={"access_token": "A", "refresh_token": "R"})
        if path == "/api/v1/stores/s1/bundles":
            return httpx.Response(200, json=self.bundles)
        if path.startswith("/api/v1/stores/s1/bundles/") and path.endswith("/packages"):
            return httpx.Response(200, json=self.pkgs)
        if path == f"/api/v1/stores/s1/accounts/{ACC}/renewal":
            return httpx.Response(200, json=self.renewal)
        if path == "/api/v1/stores/s1/checkout/quote":
            return httpx.Response(
                200,
                json={
                    "unit_price": 1000,
                    "discount": 0,
                    "total": 1000,
                    "currency": "IRT",
                    "wallet_balance": 5000,
                    "sufficient_funds": True,
                },
            )
        if path == "/api/v1/stores/s1/orders":
            return httpx.Response(201, json={"number": "ORD-1", "status": "paid", "total": 1000, "currency": "IRT"})
        return httpx.Response(404, json={})

    def last(self, suffix):
        return [c for c in self.calls if c[1].endswith(suffix)][-1][2]


@pytest.fixture
def bot(tmp_path, monkeypatch):
    for k, v in {
        "MELORIN_TELEGRAM_TOKEN": "tok",
        "MELORIN_CORE_URL": "http://core",
        "MELORIN_BOT_SERVICE_SECRET": "sek",
        "MELORIN_TELEGRAM_OFFSET_FILE": str(tmp_path / "o.json"),
    }.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location("tg_bundles", ROOT / "telegram-main/runner.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    r, fake = mod.TelegramRunner(), Fake()
    r.client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    r.n = 0
    return mod, r, fake


def send(r, data=None, text=None):
    r.n += 1
    chat = {"id": 9}
    if data:
        u = {
            "update_id": r.n,
            "callback_query": {
                "id": f"c{r.n}",
                "from": {"id": 7, "first_name": "A"},
                "data": data,
                "message": {"chat": chat, "message_id": 5},
            },
        }
    else:
        u = {"update_id": r.n, "message": {"chat": chat, "from": {"id": 7, "first_name": "A"}, "text": text}}
    asyncio.run(r.handle(u))


def screen(fake):
    return fake.edits[-1] if fake.edits and (not fake.sent or True) else fake.sent[-1]


def btns(p):
    return [b for row in p["reply_markup"]["inline_keyboard"] for b in row]


def texts(p):
    return [b["text"] for b in btns(p)]


def datas(p):
    return [b["callback_data"] for b in btns(p)]


def test_single_bundle_skips_bundle_screen(bot):
    _, r, fake = bot
    send(r, "menu:plans")
    assert f"plan:{PID}" in datas(fake.edits[-1])
    assert not any(d.startswith("bundle:") for d in datas(fake.edits[-1]))
    assert any(c[1].endswith(f"/bundles/{P1}/packages") for c in fake.calls)


def test_no_bundles_message(bot):
    _, r, fake = bot
    fake.bundles = []
    send(r, "menu:plans")
    assert "فعلاً سرویسی برای فروش موجود نیست." in fake.edits[-1]["text"]


def test_multiple_bundles_show_kind_badges_and_pick_loads_packages(bot):
    _, r, fake = bot
    fake.bundles = [bundle(P1, "Alpha", "برچسب یک"), bundle(P2, "Beta", "برچسب دو"), bundle(P3, "Gamma", "")]
    send(r, "menu:plans")
    t = texts(fake.edits[-1])
    assert "برچسب یک · Alpha" in t and "برچسب دو · Beta" in t and "Gamma" in t and "· Gamma" not in t
    assert "manual" not in json.dumps(fake.edits[-1]) and "automatic" not in json.dumps(fake.edits[-1])
    send(r, f"bundle:{P2}")
    assert f"plan:{PID}" in datas(fake.edits[-1])
    assert any(c[1].endswith(f"/bundles/{P2}/packages") for c in fake.calls)


def test_manual_bundle_shows_labels_never_panel_names(bot):
    _, r, fake = bot
    fake.bundles = [bundle(P1, "Alpha", sel="manual", panels=[{"id": PAN1, "label": "آلمان"}, {"id": PAN2, "label": "هلند"}])]
    fake.bundles[0]["panels"][0]["name"] = "SECRET-PANEL-NAME"
    send(r, "menu:plans")
    e = fake.edits[-1]
    assert "📍 یکی از گزینه‌ها را انتخاب کنید:" in e["text"]
    assert "آلمان" in texts(e) and "هلند" in texts(e)
    assert "SECRET" not in json.dumps(e, ensure_ascii=False) and "پنل" not in json.dumps(e, ensure_ascii=False)
    send(r, f"pnl:{PAN2}")
    send(r, f"plan:{PID}")
    send(r, f"buy:{PID}")
    body = fake.last("/orders")
    assert body["bundle_id"] == P1 and body["selected_panel_id"] == PAN2 and "account_name" not in body
    assert fake.last("/quote")["selected_panel_id"] == PAN2


def test_custom_bundle_asks_and_validates_name_then_sends_account_name(bot):
    _, r, fake = bot
    fake.bundles = [bundle(P1, "Alpha", naming="custom")]
    send(r, "menu:plans")
    send(r, f"plan:{PID}")
    assert "نام کاربری دلخواه" in fake.edits[-1]["text"]
    quotes = len([c for c in fake.calls if c[1].endswith("/quote")])
    send(r, text="a!")  # too short after cleaning
    assert "نامعتبر" in fake.sent[-1]["text"]
    assert len([c for c in fake.calls if c[1].endswith("/quote")]) == quotes
    send(r, text="my user!name")
    assert fake.last("/quote")["bundle_id"] == P1
    assert "myusername" in fake.sent[-1]["text"] and "Alpha" in fake.sent[-1]["text"]
    send(r, f"buy:{PID}")
    body = fake.last("/orders")
    assert body["account_name"] == "myusername" and body["bundle_id"] == P1 and body["kind"] == "purchase"
    assert "selected_panel_id" not in body


def test_automatic_bundle_sends_no_account_name_and_coupon_keeps_flow(bot):
    _, r, fake = bot
    send(r, "menu:plans")
    send(r, f"plan:{PID}")
    send(r, f"cpn:{PID}")
    send(r, text="off10")
    assert fake.last("/quote")["coupon_code"] == "OFF10" and fake.last("/quote")["bundle_id"] == P1
    send(r, f"buy:{PID}")
    body = fake.last("/orders")
    assert "account_name" not in body and body["coupon_code"] == "OFF10" and body["bundle_id"] == P1


def test_new_purchase_resets_flow(bot):
    _, r, fake = bot
    fake.bundles = [bundle(P1, "Alpha", naming="custom"), bundle(P2, "Beta")]
    send(r, f"bundle:{P1}")
    send(r, f"plan:{PID}")
    send(r, text="alice")
    send(r, "menu:plans")
    send(r, f"bundle:{P2}")
    send(r, f"plan:{PID}")
    send(r, f"buy:{PID}")
    assert "account_name" not in fake.last("/orders") and fake.last("/orders")["bundle_id"] == P2


def test_callback_data_fits_telegram_limit(bot):
    _, r, fake = bot
    fake.bundles = [bundle(P1, "Alpha", sel="manual", naming="custom", panels=[{"id": PAN1, "label": "x"}]), bundle(P2, "Beta")]
    for step in ("menu:plans", f"bundle:{P1}", f"pnl:{PAN1}", f"plan:{PID}"):
        send(r, step)
    send(r, text="alice")
    send(r, f"cpn:{PID}")
    for e in fake.edits + fake.sent:
        if "reply_markup" in e and "inline_keyboard" in e["reply_markup"]:
            assert all(len(d.encode()) <= 64 for d in datas(e))
    assert len(fake.edits) >= 5


def test_renewal_goes_straight_to_the_quote_of_the_accounts_own_package(bot):
    mod, r, fake = bot
    send(r, f"rnw:{mod.b64(ACC)}")
    assert any(c[1].endswith(f"/accounts/{ACC}/renewal") for c in fake.calls)  # Core decides what is renewable and with what
    assert not any(c[1].endswith("/bundles") for c in fake.calls)
    assert fake.last("/quote") == {"product_id": PID, "vpn_account_id": ACC}  # no package picking step
    assert f"rnb:{mod.b64(ACC)}:{mod.b64(PID)}" in datas(fake.edits[-1])
    assert all(len(x.encode()) <= 64 for x in datas(fake.edits[-1]))


def test_renewal_refused_by_core_shows_its_reason_and_offers_a_new_purchase(bot):
    mod, r, fake = bot
    fake.renewal = {"renewable": False, "code": "RENEWAL_WINDOW_PASSED", "message": "مهلت تمدید تمام شده است"}
    send(r, f"rnw:{mod.b64(ACC)}")
    assert "مهلت تمدید تمام شده است" in fake.edits[-1]["text"]
    assert "menu:plans" in datas(fake.edits[-1]) and not any(c[1].endswith("/quote") for c in fake.calls)
