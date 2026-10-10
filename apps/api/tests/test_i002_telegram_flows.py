"""Executable Telegram flow tests with Telegram and Core both mocked (no network)."""
import asyncio
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Fake:
    def __init__(self):
        self.sent, self.core_calls = [], []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url, body = str(request.url), (request.content or b"")
        if "api.telegram.org" in url:
            if url.endswith("/sendMessage"):
                self.sent.append(json.loads(body))
            return httpx.Response(200, json={"ok": True, "result": {}})
        path = request.url.path
        self.core_calls.append((request.method, path, dict(request.headers)))
        if path == "/api/v1/stores/main":
            return httpx.Response(200, json={"id": "s1", "name": "Main"})
        if path == "/api/v1/auth/telegram/bot":
            assert request.headers["x-bot-secret"] == "sek"
            return httpx.Response(200, json={"access_token": "A", "refresh_token": "R"})
        assert request.headers.get("authorization") == "Bearer A"
        if path == "/api/v1/stores/s1/checkout/quote":
            return httpx.Response(200, json={"unit_price": 100, "discount": 0, "total": 100, "currency": "IRR", "wallet_balance": 500, "sufficient_funds": True})
        if path == "/api/v1/stores/s1/orders" and request.method == "POST":
            return httpx.Response(201, json={"number": "ORD-1", "status": "paid"})
        if path == "/api/v1/stores/s1/wallet/topups":
            return httpx.Response(200, json={"id": "p1", "amount": 5000, "currency": "IRR", "instructions": {"card_number": "6037", "holder": "X", "bank": "B"}})
        if path == "/api/v1/stores/s1/tickets":
            return httpx.Response(403, json={"error": {"message": "ممنوع"}})
        return httpx.Response(404, json={})


@pytest.fixture
def runner(tmp_path, monkeypatch):
    for k, v in {"MELORIN_TELEGRAM_TOKEN": "tok", "MELORIN_CORE_URL": "http://core", "MELORIN_BOT_SERVICE_SECRET": "sek", "MELORIN_TELEGRAM_OFFSET_FILE": str(tmp_path / "o.json")}.items():
        monkeypatch.setenv(k, v)
    mod = load("tg_main", "telegram-main/runner.py")
    r, fake = mod.TelegramRunner(), Fake()
    r.client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    return r, fake


def msg(text, uid=1):
    return {"update_id": uid, "message": {"chat": {"id": 9}, "from": {"id": 7, "first_name": "A"}, "text": text}}


def test_buy_callback_uses_replay_safe_idempotency_key(runner):
    r, fake = runner
    cb = {"update_id": 5, "callback_query": {"id": "cb42", "from": {"id": 7}, "data": "buy:prod1", "message": {"chat": {"id": 9}}}}
    asyncio.run(r.handle(cb))
    order = [c for c in fake.core_calls if c[1].endswith("/orders")][0]
    assert order[2]["idempotency-key"] == "tg-cb42"
    assert "ORD-1" in fake.sent[-1]["text"]


def test_topup_sets_receipt_state_and_shows_card(runner):
    r, fake = runner
    asyncio.run(r.handle(msg("/topup ۵۰۰۰")))
    assert "6037" in fake.sent[-1]["text"]
    assert r.state["9"]["receipt_payment"] == "p1"
    assert json.loads(r.state_file.read_text())["9"]["receipt_payment"] == "p1"


def test_core_error_is_reported_not_raised(runner):
    r, fake = runner
    asyncio.run(r.handle(msg("/ticket موضوع | متن")))
    assert "ممنوع" in fake.sent[-1]["text"]


def test_unknown_command_and_plain_text(runner):
    r, fake = runner
    asyncio.run(r.handle(msg("/nope")))
    assert "/help" in fake.sent[-1]["text"]


def test_reseller_runner_binds_store_by_slug(tmp_path, monkeypatch):
    for k, v in {"MELORIN_TELEGRAM_RESELLER_TOKEN": "rt", "MELORIN_CORE_URL": "http://core", "MELORIN_BOT_SERVICE_SECRET": "sek", "MELORIN_STORE_SLUG": "shop1", "MELORIN_TELEGRAM_OFFSET_FILE": str(tmp_path / "o.json")}.items():
        monkeypatch.setenv(k, v)
    mod = load("tg_res", "telegram-reseller/runner.py")
    r = mod.ResellerTelegramRunner()
    seen = []

    def h(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={"id": "rs1", "name": "Shop"})

    r.client = httpx.AsyncClient(transport=httpx.MockTransport(h))
    assert asyncio.run(r.store_info())["id"] == "rs1"
    assert seen == ["/api/v1/stores/by-slug/shop1"] and "/report" in r.commands and "rv" in r.callbacks
