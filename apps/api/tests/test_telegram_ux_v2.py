"""Redesigned bot UX (v2): in-place screens, quote card, accounts card/QR/renewal, dashboard. Telegram + Core mocked."""
import asyncio
import importlib.util
import json
import uuid
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).parents[2]
ACC = str(uuid.uuid4())
PID = str(uuid.uuid4())


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Fake:
    def __init__(self):
        self.sent, self.edits, self.photos, self.calls, self.methods = [], [], [], [], []
        self.edit_status, self.edit_desc = 200, ""
        self.quote = {"product_id": PID, "unit_price": 100_000, "discount": 0, "total": 100_000, "currency": "IRT",
                      "coupon_code": None, "wallet_balance": 350_000, "sufficient_funds": True}
        self.accounts = [{"id": ACC, "username": "m_ab12", "status": "active", "is_test": False, "expires_at": "2099-01-01T00:00:00Z",
                          "traffic_limit_bytes": 10 * 1024**3, "traffic_used_bytes": 3 * 1024**3, "subscription_url": "https://s.example/sub/xyz"}]
        self.catalog = [{"product_id": str(uuid.uuid4()), "name": f"P{i}", "price": 1000 * (i + 1), "currency": "IRT"} for i in range(10)]

    def handler(self, request: httpx.Request) -> httpx.Response:
        url, body = str(request.url), request.content or b""
        if "api.telegram.org" in url:
            method = url.rsplit("/", 1)[1]
            self.methods.append(method)
            if method == "sendMessage":
                self.sent.append(json.loads(body))
            elif method == "editMessageText":
                self.edits.append(json.loads(body))
                if self.edit_status != 200:
                    return httpx.Response(self.edit_status, json={"ok": False, "description": self.edit_desc})
            elif method == "sendPhoto":
                self.photos.append(body)
            elif method == "getMe":
                return httpx.Response(200, json={"ok": True, "result": {"username": "MyBot"}})
            return httpx.Response(200, json={"ok": True, "result": {}})
        path = request.url.path
        js = json.loads(body) if body and request.headers.get("content-type", "").startswith("application/json") else None
        self.calls.append((request.method, path, js, dict(request.headers)))
        if path == "/api/v1/stores/main":
            return httpx.Response(200, json={"id": "s1", "name": "Main"})
        if path == "/api/v1/auth/telegram/bot":
            return httpx.Response(200, json={"access_token": "A", "refresh_token": "R"})
        if path == "/api/v1/stores/s1/catalog":
            return httpx.Response(200, json=self.catalog)
        if path == "/api/v1/stores/s1/checkout/quote":
            return httpx.Response(200, json=self.quote)
        if path == "/api/v1/stores/s1/orders" and request.method == "POST":
            return httpx.Response(201, json={"number": "ORD-9", "status": "paid", "total": 100_000, "currency": "IRT"})
        if path == "/api/v1/stores/s1/wallet":
            return httpx.Response(200, json={"balance": 250_000, "currency": "IRT"})
        if path == "/api/v1/vpn-accounts":
            return httpx.Response(200, json=self.accounts)
        if path == "/api/v1/me/referrals":
            return httpx.Response(200, json={"referral_code": "ABC123", "referred_count": 4})
        return httpx.Response(404, json={})


@pytest.fixture
def bot(tmp_path, monkeypatch):
    for k, v in {"MELORIN_TELEGRAM_TOKEN": "tok", "MELORIN_CORE_URL": "http://core", "MELORIN_BOT_SERVICE_SECRET": "sek", "MELORIN_TELEGRAM_OFFSET_FILE": str(tmp_path / "o.json")}.items():
        monkeypatch.setenv(k, v)
    mod = load("tg_v2", "telegram-main/runner.py")
    r, fake = mod.TelegramRunner(), Fake()
    r.client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    return mod, r, fake


def cb(data, uid=1, mid=77, cid=None):
    return {"update_id": uid, "callback_query": {"id": cid or f"c{uid}", "from": {"id": 7, "first_name": "Ali"}, "data": data, "message": {"chat": {"id": 9}, "message_id": mid}}}


def msg(text, uid=1):
    return {"update_id": uid, "message": {"chat": {"id": 9}, "from": {"id": 7, "first_name": "Ali"}, "text": text}}


def buttons(payload):
    return [b for row in payload["reply_markup"]["inline_keyboard"] for b in row]


def run(r, update):
    asyncio.run(r.handle(update))


def test_navigation_edits_the_tapped_message_in_place(bot):
    _, r, fake = bot
    run(r, cb("buy:" + PID, cid="cb7"))
    assert fake.sent == [] and len(fake.edits) == 1
    e = fake.edits[0]
    assert e["message_id"] == 77 and e["parse_mode"] == "HTML" and "ORD-9" in e["text"]
    order = [c for c in fake.calls if c[1].endswith("/orders")][0]
    assert order[3]["idempotency-key"] == "tg-cb7"


def test_quote_card_shows_balance_before_and_after_and_confirm_button(bot):
    _, r, fake = bot
    run(r, cb("plan:" + PID))
    t = fake.edits[0]["text"]
    assert "350,000" in t and "250,000" in t and "تومان" in t     # before and after (350k - 100k)
    assert f"buy:{PID}" in [b["callback_data"] for b in buttons(fake.edits[0])]


def test_insufficient_funds_offers_exact_shortfall_topup(bot):
    _, r, fake = bot
    fake.quote.update(wallet_balance=30_000, sufficient_funds=False)
    run(r, cb("plan:" + PID))
    data = [b["callback_data"] for b in buttons(fake.edits[0])]
    assert "wallet:amount:70000" in data and f"buy:{PID}" not in data


def test_plans_are_paginated(bot):
    _, r, fake = bot
    run(r, cb("menu:plans"))
    first = buttons(fake.edits[0])
    assert sum(b["callback_data"].startswith("plan:") for b in first) == 8
    assert "plans:1" in [b["callback_data"] for b in first]
    run(r, cb("plans:1", uid=2))
    assert sum(b["callback_data"].startswith("plan:") for b in buttons(fake.edits[1])) == 2


def test_account_card_has_usage_bar_link_qr_and_renew(bot):
    _, r, fake = bot
    run(r, cb(f"account:{ACC}"))
    e = fake.edits[0]
    assert "▰" in e["text"] and "30٪" in e["text"] and "<code>https://s.example/sub/xyz</code>" in e["text"]
    data = [b["callback_data"] for b in buttons(e)]
    assert any(d.startswith("qr:") for d in data) and any(d.startswith("rnw:") for d in data)


def test_test_account_cannot_be_renewed(bot):
    _, r, fake = bot
    fake.accounts[0]["is_test"] = True
    run(r, cb(f"account:{ACC}"))
    assert not any(b["callback_data"].startswith("rnw:") for b in buttons(fake.edits[0]))


def test_callback_data_always_fits_telegram_limit(bot):
    mod, r, fake = bot
    run(r, cb(f"rnw:{mod.b64(ACC)}"))
    run(r, cb(f"rnq:{mod.b64(ACC)}:{mod.b64(PID)}", uid=2))
    for e in fake.edits:
        for b in buttons(e):
            assert len(b["callback_data"].encode()) <= 64, b
    assert mod.unb64(mod.b64(ACC)) == ACC


def test_renewal_flow_creates_renewal_order_for_the_right_account(bot):
    mod, r, fake = bot
    run(r, cb(f"rnb:{mod.b64(ACC)}:{mod.b64(PID)}", cid="rn1"))
    body = [c for c in fake.calls if c[1].endswith("/orders")][0][2]
    assert body == {"product_id": PID, "payment_method": "wallet", "kind": "renewal", "vpn_account_id": ACC}
    assert "ORD-9" in fake.edits[0]["text"]


def test_bad_callback_token_is_a_friendly_error_not_a_crash(bot):
    _, r, fake = bot
    run(r, cb("rnw:%%%"))
    assert "⚠️" in fake.sent[-1]["text"]


def test_qr_callback_sends_one_photo(bot):
    mod, r, fake = bot
    run(r, cb(f"qr:{mod.b64(ACC)}"))
    assert fake.photos and b"\x89PNG" in fake.photos[0] and b"https://s.example/sub/xyz" in fake.photos[0]


def test_referral_link_uses_ref_prefix_the_start_handler_understands(bot):
    _, r, fake = bot
    run(r, msg("/referral"))
    assert "https://t.me/MyBot?start=ref_ABC123" in fake.sent[-1]["text"]


def test_edit_not_modified_is_silent_and_other_400_falls_back_to_new_message(bot):
    _, r, fake = bot
    fake.edit_status, fake.edit_desc = 400, "Bad Request: message is not modified"
    run(r, cb(f"account:{ACC}"))
    assert fake.sent == []
    fake.edit_desc = "Bad Request: there is no text in the message to edit"
    run(r, cb(f"account:{ACC}", uid=2))
    assert len(fake.sent) == 1 and fake.sent[0]["parse_mode"] == "HTML"


def test_start_shows_main_menu_then_dashboard(bot):
    _, r, fake = bot
    run(r, msg("/start"))
    assert "keyboard" in fake.sent[0]["reply_markup"]
    assert "250,000" in fake.sent[1]["text"] and "Ali" in fake.sent[1]["text"]


def test_coupon_flow_quotes_with_code_and_buy_carries_it(bot):
    _, r, fake = bot
    run(r, cb(f"cpn:{PID}"))
    fake.quote.update(discount=10_000, total=90_000, coupon_code="OFF10")
    run(r, msg("off10", uid=2))
    assert [c for c in fake.calls if c[1].endswith("/quote")][-1][2]["coupon_code"] == "OFF10"
    run(r, cb(f"buy:{PID}", uid=3))
    assert [c for c in fake.calls if c[1].endswith("/orders")][0][2]["coupon_code"] == "OFF10"


def test_command_menu_is_registered_at_startup(bot):
    _, r, fake = bot
    asyncio.run(r.setup_menu())
    assert "setMyCommands" in fake.methods


def test_source_never_carries_allocation_data():
    src = (ROOT / "telegram-main/runner.py").read_text()
    for forbidden in ("panel_group_id", "selected_panel_id", "default_panel_group", "server_id"):
        assert forbidden not in src


def test_coupon_prompt_is_one_shot_even_when_funds_are_insufficient(bot):
    _, r, fake = bot
    run(r, cb(f"cpn:{PID}"))
    fake.quote.update(wallet_balance=1_000, sufficient_funds=False, total=90_000, discount=10_000, coupon_code="OFF10")
    run(r, msg("off10", uid=2))
    quotes_before = len([c for c in fake.calls if c[1].endswith("/quote")])
    run(r, msg("سلام", uid=3))  # ordinary text afterwards must NOT be treated as another coupon
    assert len([c for c in fake.calls if c[1].endswith("/quote")]) == quotes_before
