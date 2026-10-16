"""The reseller sets its own retail prices from its Telegram bot; the core enforces the cost floor. Telegram + Core mocked."""
import asyncio
import importlib.util
import json
import uuid
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).parents[2]
PID = str(uuid.uuid4())


class Fake:
    def __init__(self):
        self.sent, self.calls = [], []
        self.reject = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        url, body = str(request.url), request.content or b""
        if "api.telegram.org" in url:
            if url.endswith("sendMessage"):
                self.sent.append(json.loads(body))
            return httpx.Response(200, json={"ok": True, "result": {}})
        path = request.url.path
        js = json.loads(body) if body else None
        self.calls.append((request.method, path, js))
        if path == "/api/v1/stores/by-slug/shop":
            return httpx.Response(200, json={"id": "s1", "name": "Shop"})
        if path == "/api/v1/auth/telegram/bot":
            return httpx.Response(200, json={"access_token": "A", "refresh_token": "R"})
        if path == "/api/v1/stores/s1/reseller/prices" and request.method == "GET":
            return httpx.Response(200, json=[{"product_id": PID, "name": "Pkg", "customer_price": None, "cost_floor": 20000, "state": "unset"}])
        if path == f"/api/v1/stores/s1/reseller/prices/{PID}":
            if self.reject:
                return httpx.Response(422, json={"error": {"code": "CUSTOMER_PRICE_BELOW_COST", "message": "کمتر از قیمت همکاری است"}})
            return httpx.Response(200, json={"ok": True, "customer_price": js["customer_price"]})
        return httpx.Response(404, json={})


@pytest.fixture
def bot(tmp_path, monkeypatch):
    for k, v in {"MELORIN_TELEGRAM_TOKEN": "tok", "MELORIN_TELEGRAM_RESELLER_TOKEN": "tok", "MELORIN_CORE_URL": "http://core", "MELORIN_BOT_SERVICE_SECRET": "sek", "MELORIN_STORE_SLUG": "shop",
                 "MELORIN_TELEGRAM_OFFSET_FILE": str(tmp_path / "off.json")}.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location("tg_reseller", ROOT / "telegram-reseller/runner.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    r, fake = mod.ResellerTelegramRunner(), Fake()
    r.client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    r.n = 0
    return r, fake


def send(r, data=None, text=None):
    r.n += 1
    chat = {"id": 9}
    if data:
        u = {"update_id": r.n, "callback_query": {"id": f"c{r.n}", "from": {"id": 7, "first_name": "A"}, "data": data, "message": {"chat": chat, "message_id": 5}}}
    else:
        u = {"update_id": r.n, "message": {"chat": chat, "from": {"id": 7, "first_name": "A"}, "text": text}}
    asyncio.run(r.handle(u))


def test_reseller_sets_a_price_and_core_receives_it(bot):
    r, fake = bot
    send(r, text="/prices")
    markup = fake.sent[-1]["reply_markup"]["inline_keyboard"]
    assert markup[0][0]["callback_data"] == f"prc:{PID}" and "حداقل" in markup[0][0]["text"]
    send(r, data=f"prc:{PID}")
    send(r, text="۲۶۰۰۰")
    put = [c for c in fake.calls if c[0] == "PUT"][-1]
    assert put[1].endswith(f"/reseller/prices/{PID}") and put[2] == {"customer_price": 26000}
    assert "ثبت شد" in fake.sent[-1]["text"]


def test_price_below_the_floor_is_refused_by_core_and_the_reseller_can_retry(bot):
    r, fake = bot
    fake.reject = True
    send(r, data=f"prc:{PID}")
    send(r, text="100")
    assert "کمتر از قیمت همکاری" in fake.sent[-1]["text"]
    fake.reject = False
    send(r, text="30000")
    assert "ثبت شد" in fake.sent[-1]["text"]
