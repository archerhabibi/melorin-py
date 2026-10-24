"""Upstream-bot adapter: parser tests on the real screenshots' texts + a fake parent bot driving the full buy flow."""

import datetime as dt
import time

import pytest

from melorin.modules.vpn.adapters.base import GB, AccountSpec, ErrorKind, PanelError
from melorin.modules.vpn.adapters.upstream_bot import UpstreamBotAdapter, adapter as mod, parsing
from melorin.modules.vpn.adapters.upstream_bot.chat import Button, Msg

DELIVERY = (
    "🏷 نام اکانت: eg1_1068\n🔶 نوع اکانت: سرویس اقتصادی حجمی\n🔷 توضیحات: ماهانه 10 گیگ بدون محدودیت کاربر\n"
    "🟢 تاریخ خرید: 1405/08/02 03:18\n\n🔗 لینک اکانت:\nhttps://eg1.god-ping.monster:8443/sub/ZWcxXzEwNjgsMTc5Mjc5OTMzNgDdGXCyF56m?name=eg1_1068\n\n"
    "❗ برای کپی لینک روی کلیک کنید و فقط در برنامه Happ وارد کنید ❗"
)
CONFIRM = "سرویس انتخابی شما: همه نت ها اقتصادی\nحجم: 10 گیگ\nمدت: 1 ماهه\n\n❗ لطفا دقت کن بعد از زدن تایید خرید، مبلغ 60,000 تومان از حسابت کم خواهم کرد و قابل بازگشت نیست"


def test_parse_plan_labels():
    p = parsing.parse_plan_label("♨️ 10 گیگ یک ماهه 60,000 تومان")
    assert (p.traffic_gb, p.months, p.price) == (10, 1, 60000)
    p = parsing.parse_plan_label("♨️ ۱۰۰ گیگ سه ماهه ۳۴۵,۰۰۰ تومان")
    assert (p.traffic_gb, p.months, p.price) == (100, 3, 345000)
    assert parsing.parse_plan_label("🔙 برگشت به لیست سرویسها") is None


def test_parse_delivery_and_balance():
    r = parsing.parse_purchase_result(DELIVERY)
    assert r.name == "eg1_1068" and r.subscription_url.endswith("?name=eg1_1068") and r.subscription_url.startswith("https://eg1.god-ping")
    assert parsing.parse_purchase_result("خرید تایید شد ✅\nاسم اکانت eg1_1068") is None  # not the delivery message
    assert parsing.parse_balance("💵 موجودی حساب شما: 505,000 تومان") == 505000
    assert parsing.confirm_amount(CONFIRM) == 60000 and parsing.is_confirm_prompt(CONFIRM)


class FakeParentBot:
    """Minimal state machine of the parent bot (menu -> service -> plans -> confirm -> delivery)."""

    def __init__(self, price_on_confirm=60000, deliver=True, balance=505000):
        self.msgs: list[Msg] = []
        self.n = 0
        self.price_on_confirm, self.deliver, self.balance = price_on_confirm, deliver, balance
        self.purchases = 0

    def _add(self, text, buttons=()):
        self.n += 1
        self.msgs.append(Msg(self.n, text, [Button(t, t.encode(), i, 0) for i, t in enumerate(buttons)], date_ts=time.time()))
        return self.msgs[-1]

    async def send_text(self, text):
        self._add(text)
        if text == "خرید اکانت":
            self._add("وضعیت سرویسها", ["سرویس اقتصادی", "سرویس وایرگارد"])
        return self.n

    async def click(self, msg, button):
        if button.text == "سرویس اقتصادی":
            self._add("لیست سرویس اقتصادی", ["♨️ 10 گیگ یک ماهه 60,000 تومان", "♨️ 20 گیگ یک ماهه 90,000 تومان", "برگشت"])
        elif "10 گیگ" in button.text or "20 گیگ" in button.text:
            self._add(CONFIRM.replace("60,000", f"{self.price_on_confirm:,}"), ["تایید خرید", "انصراف"])
        elif button.text == "تایید خرید" and self.deliver:
            self.purchases += 1
            self._add(DELIVERY)

    async def recent(self, limit=15):
        return list(reversed(self.msgs))[:limit]

    async def get(self, msg_id):
        return next((m for m in self.msgs if m.id == msg_id), None)

    async def close(self):
        pass


def make(bot, **cfg):
    config = {"max_price": 100000, "poll_interval": 0.01, "step_timeout": 1, "delivery_timeout": 0.2, **cfg}
    return UpstreamBotAdapter("https://t.me/AjdarNetPlusbot", {}, config, chat=bot)


def spec(name="Mel_10G1", gb=10, days=30):
    return AccountSpec(name, dt.datetime.now(dt.UTC) + dt.timedelta(days=days), gb * GB)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    mod._MEM.clear()
    monkeypatch.setattr(mod, "_redis", lambda: None)


async def test_buy_flow_maps_upstream_name():
    bot = FakeParentBot()
    a = make(bot)
    pa = await a.create_account(spec())
    assert pa.ref == "eg1_1068" and pa.username == "Mel_10G1" and pa.subscription_url.startswith("https://eg1.god-ping")
    assert pa.traffic_limit_bytes == 10 * GB and bot.purchases == 1
    assert (await a.get_account("Mel_10G1")).ref == "eg1_1068"
    assert await a.get_account("nobody") is None


async def test_retry_never_pays_twice():
    bot = FakeParentBot()
    a = make(bot)
    await a.create_account(spec())
    await a.create_account(spec())  # provisioning retry of the same Melorin username
    assert bot.purchases == 1


async def test_timeout_after_confirm_is_unknown_then_recovered():
    bot = FakeParentBot(deliver=False)
    a = make(bot)
    with pytest.raises(PanelError) as e:
        await a.create_account(spec())
    assert e.value.kind == ErrorKind.UNKNOWN
    assert (await a.store.get("Mel_10G1"))["status"] == "pending"
    bot._add(DELIVERY)  # the parent bot answers late
    got = await a.get_account("Mel_10G1")
    assert got and got.ref == "eg1_1068"


async def test_price_mismatch_cancels_and_never_confirms():
    bot = FakeParentBot(price_on_confirm=90000)
    with pytest.raises(PanelError) as e:
        await make(bot).create_account(spec())
    assert e.value.kind == ErrorKind.PERMANENT and "mismatch" in e.value.message and bot.purchases == 0


async def test_requires_price_cap_and_known_plan():
    with pytest.raises(PanelError) as e:
        await make(FakeParentBot(), max_price=0).create_account(spec())
    assert "max_price" in e.value.message
    with pytest.raises(PanelError) as e:
        await make(FakeParentBot()).create_account(spec(gb=77))
    assert e.value.kind == ErrorKind.PERMANENT and "no plan" in e.value.message
    with pytest.raises(PanelError):
        await make(FakeParentBot(), max_price=50000).create_account(spec())  # 60,000 > cap


async def test_renew_not_configured_and_revoke_releases_mapping():
    bot = FakeParentBot()
    a = make(bot)
    assert a.capabilities().extend is False and a.capabilities().suspend is False
    await a.create_account(spec())
    with pytest.raises(PanelError) as e:
        await a.extend_account("Mel_10G1", expire_at=None, traffic_bytes=10 * GB)
    assert e.value.kind == ErrorKind.PERMANENT
    await a.revoke_account("Mel_10G1")
    assert await a.get_account("Mel_10G1") is None


async def test_remember_reseeds_mapping_from_panel_ref():
    a = make(FakeParentBot())
    a.remember("Mel_X", "eg1_77")
    assert (await a.get_account("Mel_X")).ref == "eg1_77"


def test_bad_base_url():
    with pytest.raises(PanelError):
        UpstreamBotAdapter("not a url!!", {}, {})
