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


DETAIL = """🏷 نام اکانت: {name}
🔶 نوع اکانت: سرویس اقتصادی حجمی
🔷 توضیحات: 1 ماهه 10 گیگ بدون محدودیت کاربر

🟣 وضعیت: ✅ فعال
🟡 حجم مصرف شده: {used}
🔴 حجم باقیمانده: {left} گیگ
📆 تاریخ اتمام: 1405/09/02 03:51

زمان باقیمانده: 29 روز 23 ساعت و 48 دقیقه"""


RENEW_OPTIONS = "تمدید اکانت {name}\nحجم اولیه: 10 گیگ\n\n👇 لطفا حجم تمدید مورد نظرت رو انتخاب کن"
RENEW_CONFIRM = "تمدید اکانت {name} با حجم اولیه 10 گیگ\n\n❗ لطفا دقت کن بعد از زدن تایید تمدید، مبلغ {shown} تومان از حسابت کم خواهم کرد و قابل بازگشت نیست 😁"
RENEWED_DETAIL = DETAIL_RENEWED = (
    "🏷 نام اکانت: {name}\n🔶 نوع اکانت: سرویس اقتصادی حجمی\n🔷 توضیحات: ماهانه 10 گیگ بدون محدودیت کاربر\n"
    "🟢 تاریخ تمدید: {renewed}\n\n🟣 وضعیت: ✅ فعال\n🟡 حجم مصرف شده: 0\n🔴 حجم باقیمانده: 10 گیگ\n📆 تاریخ اتمام: {end}\n\n"
    "زمان باقیمانده: 30 روز 0 ساعت و 0 دقیقه"
)


class FakeParentBot:
    """State machine of the parent bot: reply-keyboard menu, buy flow, account search, refund (as in the screenshots/video)."""

    def __init__(
        self,
        price_on_confirm=60000,
        deliver=True,
        refund_offered=True,
        refund_ack=True,
        used_gb=0,
        balance=445000,
        renew_ack=True,
        renew_applies=True,
        renew_price=60000,
        renew_shown=0,
        stale_renew=False,
    ):
        self.balance, self.renew_ack, self.renew_applies, self.renew_price, self.renew_shown = (
            balance,
            renew_ack,
            renew_applies,
            renew_price,
            renew_shown,
        )
        self.stale_renew = stale_renew
        self.renewals = self.renew_confirms = 0
        self.renewed: dict[str, tuple[str, str]] = {}  # name -> (renewed_at, end) as the parent bot prints them
        self.msgs: list[Msg] = []
        self.n = 0
        self.price_on_confirm, self.deliver, self.refund_offered, self.refund_ack = price_on_confirm, deliver, refund_offered, refund_ack
        self.used_gb = used_gb
        self.accounts: dict[str, str] = {}  # name -> active | refunded
        self.purchases = self.refunds = self.starts = 0
        self.awaiting_name = False

    def _add(self, text, buttons=(), inline=True):
        self.n += 1
        self.msgs.append(
            Msg(self.n, text, [Button(t, t.encode() if inline else None, i, 0) for i, t in enumerate(buttons)], date_ts=time.time())
        )
        return self.msgs[-1]

    async def send_text(self, text):
        mid = self._add(text).id
        if text == "/start":
            self.starts += 1
            self.awaiting_name = False
            self._add("Welcome!\nلطفا یکی از گزینه های زیر رو انتخاب کن", ["🛍 خرید اکانت", "💗 خریدهای من", "قوانین خرید"], inline=False)
        elif "خرید اکانت" in text:
            self._add("وضعیت سرویسها", ["سرویس اقتصادی", "سرویس وایرگارد"])
        elif "خریدهای من" in text:
            self._add("حداکثر تا 20 خرید آخر در این لیست قابل نمایشه", list(self.accounts))
            self._add(
                "اگه میخای قبل از اینکه حجم تموم بشه ربات بهت پیام بفرسته...",
                ["اعلانهای فعال من", "🔍 جستجوی اکانت", "بازگشت به منو"],
                inline=False,
            )
        elif "جستجوی اکانت" in text:
            self.awaiting_name = True
            self._add("لطفا اسم اکانت رو دقیق و با حروف کوچیک بنویس و به ربات ارسال کن", ["❌ انصراف"])
        elif self.awaiting_name:
            self.awaiting_name = False
            if self.accounts.get(text) == "active":
                left = 10 - self.used_gb
                if text in self.renewed:
                    shown = RENEWED_DETAIL.format(name=text, renewed=self.renewed[text][0], end=self.renewed[text][1])
                else:
                    shown = DETAIL.format(name=text, used=self.used_gb, left=left)
                self._add(
                    shown,
                    ["🔁 تمدید اکانت", "⬆️ افزایش حجم", "🔗 دریافت لینک و QR", "⭕ مرجوعی اکانت"],
                )
            else:
                self._add("اکانت پیدا نشد")
        return mid

    async def click(self, msg, button):
        if button.data is None:
            await self.send_text(button.text)
        elif button.text == "سرویس اقتصادی":
            self._add("لیست سرویس اقتصادی", ["♨️ 10 گیگ یک ماهه 60,000 تومان", "♨️ 20 گیگ یک ماهه 90,000 تومان", "برگشت"])
        elif "10 گیگ" in button.text or "20 گیگ" in button.text:
            self._add(CONFIRM.replace("60,000", f"{self.price_on_confirm:,}"), ["📥 تایید خرید", "❌ انصراف"])
        elif "تایید خرید" in button.text and self.deliver:
            self.purchases += 1
            name = f"eg1_{1067 + self.purchases}"
            self.accounts[name] = "active"
            self._add(DELIVERY.replace("eg1_1068", name))
        elif "تمدید اکانت" in button.text and "تایید" not in button.text:
            name = next(n for n, st in self.accounts.items() if st == "active")
            if self.stale_renew:
                self._add("❗ زمان عملیات منقضی شده از اول باید بری", ["عملیات منقضی شده"])
                return
            self._add(f"💵 موجودی حساب شما: {self.balance:,} تومان")
            self._add(
                RENEW_OPTIONS.format(name=name),
                [
                    f"تمدید با حجم اولیه {self.renew_price} تومان",  # no thousands separator, as in the real bot
                    "تمدید و افزایش 10 گیگ 110,000 تومان",
                    "تمدید و افزایش 20 گیگ 210,000 تومان",
                    "❌ انصراف",
                ],
            )
        elif button.text.startswith("تمدید با حجم اولیه") or button.text.startswith("تمدید و افزایش"):
            name = next(n for n, st in self.accounts.items() if st == "active")
            self._add(RENEW_CONFIRM.format(name=name, shown=self.renew_shown), ["تایید تمدید اکانت", "🔙 برگشت"])
        elif "تایید تمدید" in button.text:
            name = next(n for n, st in self.accounts.items() if st == "active")
            self.renew_confirms += 1
            if self.renew_applies:
                self.renewals += 1
                self.balance -= self.renew_price
                self.renewed[name] = (f"1405/08/{10 + self.renewals:02d} 04:34", f"1405/09/{10 + self.renewals:02d} 04:34")
            if self.renew_ack and self.renew_applies:
                self._add(f"اکانت {name} رو با موفقیت تمدید کردم 😁✅", ["✅ عملیات موفق"])
                self._add(f"مبلغ {self.renew_price:,} تومان از حسابت کم کردم")
                self._add(f"موجودی حساب شما: {self.balance:,} تومان")
        elif "مرجوعی اکانت" in button.text:
            if self.refund_offered:
                self._add("شرایط مرجوعی، در اکانتهای حجمی مصرف حداکثر 3 روز و 5 درصد حجم...\nاکانتهای نامحدود فعلا غیر قابل مرجوع میباشد")
                self._add("اکانت x قابل مرجوع میباشد. آیا تایید میکنی؟", ["✅ تایید میکنم", "❌ انصراف"])
            else:
                self._add("مصرف اکانت بیش از 5 درصد است و قابل مرجوع نیست")
        elif "تایید میکنم" in button.text:
            name = next(n for n, st in self.accounts.items() if st == "active")
            self.accounts[name] = "refunded"
            self.refunds += 1
            if self.refund_ack:
                self._add(f"اکانت {name} رو با موفقیت مرجوع کردم ✅")
                self._add("مبلغ 60,000 تومان به حسابت بابت مرجوعی این کانت اضافه کردم")

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
    bot.accounts["eg1_1068"] = "active"
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


async def test_renew_can_be_switched_off():
    bot = FakeParentBot()
    a = make(bot, renew={"enabled": False})
    assert a.capabilities().extend is False and a.capabilities().suspend is False
    await a.create_account(spec())
    with pytest.raises(PanelError) as e:
        await a.extend_account("Mel_10G1", expire_at=None, traffic_bytes=10 * GB)
    assert e.value.kind == ErrorKind.PERMANENT and "not enabled" in e.value.message and bot.renew_confirms == 0
    assert make(bot).capabilities().extend is True  # verified flow: on by default


async def test_remember_reseeds_mapping_from_panel_ref():
    bot = FakeParentBot()
    bot.accounts["eg1_77"] = "active"
    a = make(bot)
    a.remember("Mel_X", "eg1_77")
    assert (await a.get_account("Mel_X")).ref == "eg1_77"


def test_bad_base_url():
    with pytest.raises(PanelError):
        UpstreamBotAdapter("not a url!!", {}, {})


def test_parse_account_detail_and_jalali():
    d = parsing.parse_account_detail(DETAIL.format(name="eg1_1069", used=0, left=10))
    assert d.name == "eg1_1069" and d.status == "active" and d.used_bytes == 0 and d.remaining_bytes == 10 * GB
    assert d.expire_at == dt.datetime(2026, 11, 23, 0, 21, tzinfo=dt.UTC)  # 1405/09/02 03:51 Tehran (UTC+3:30)
    assert parsing.parse_jalali("1405/08/02 03:18") == dt.datetime(2026, 10, 23, 23, 48, tzinfo=dt.UTC)
    assert parsing.parse_jalali("1403/01/01") == dt.datetime(2024, 3, 19, 20, 30, tzinfo=dt.UTC)  # Nowruz 1403 = 2024-03-20
    assert parsing.parse_purchase_result(DETAIL.format(name="eg1_1069", used=0, left=10)) is None  # detail is not a delivery


def test_parse_refund_messages():
    assert parsing.is_refund_confirm_prompt("اکانت eg1_1069 قابل مرجوع میباشد. آیا تایید میکنی؟")
    assert not parsing.is_refund_confirm_prompt("اکانتهای نامحدود فعلا غیر قابل مرجوع میباشد")  # rules text, no confirm
    assert parsing.parse_refund_success("اکانت eg1_1069 رو با موفقیت مرجوع کردم")
    assert parsing.parse_refund_amount("مبلغ 60,000 تومان به حسابت بابت مرجوعی این کانت اضافه کردم") == 60000


async def test_live_read_uses_account_screen_and_is_cached():
    bot = FakeParentBot(used_gb=2)
    a = make(bot, status_ttl=300)
    await a.create_account(spec())
    got = await a.get_account("Mel_10G1")
    assert got.traffic_used_bytes == 2 * GB and got.traffic_limit_bytes == 10 * GB
    assert got.expire_at == dt.datetime(2026, 11, 23, 0, 21, tzinfo=dt.UTC) and got.status == "active"
    starts = bot.starts
    await a.get_account("Mel_10G1")
    assert bot.starts == starts  # served from cache inside status_ttl
    assert (await make(bot, status_ttl=0).get_account("Mel_10G1")).traffic_used_bytes == 2 * GB


async def test_unknown_account_is_missing_not_error():
    bot = FakeParentBot()
    a = make(bot, status_ttl=0)
    await a.create_account(spec())
    bot.accounts["eg1_1068"] = "refunded"
    assert await a.get_account("Mel_10G1") is None


async def test_refund_goes_through_the_parent_bot_and_is_idempotent():
    bot = FakeParentBot()
    a = make(bot)
    await a.create_account(spec())
    await a.revoke_account("Mel_10G1")
    assert bot.refunds == 1 and bot.accounts["eg1_1068"] == "refunded"
    d = await a.store.get("Mel_10G1")
    assert d["status"] == "revoked" and d["upstream_refunded"] and d["refund_amount"] == 60000
    await a.revoke_account("Mel_10G1")  # outbox retry
    assert bot.refunds == 1


async def test_refund_without_ack_is_unknown_then_settled_on_retry():
    bot = FakeParentBot(refund_ack=False)
    a = make(bot)
    await a.create_account(spec())
    with pytest.raises(PanelError) as e:
        await a.revoke_account("Mel_10G1")
    assert e.value.kind == ErrorKind.UNKNOWN and bot.refunds == 1
    await a.revoke_account("Mel_10G1")  # account is gone upstream and we had pressed confirm: it went through
    assert bot.refunds == 1 and (await a.store.get("Mel_10G1"))["status"] == "revoked"


async def test_refund_refused_by_parent_bot_is_permanent_with_reason():
    bot = FakeParentBot(refund_offered=False)
    a = make(bot)
    await a.create_account(spec())
    with pytest.raises(PanelError) as e:
        await a.revoke_account("Mel_10G1")
    assert e.value.kind == ErrorKind.PERMANENT and "5 درصد" in e.value.message and bot.refunds == 0


async def test_refund_of_unknown_or_unbought_account_is_a_noop():
    a = make(FakeParentBot())
    await a.revoke_account("never-bought")


# ----------------------------------------------------------------------------- renewal (تمدید), real screens of 24 Oct 2026
def test_parse_renew_screens_from_screenshots():
    o = parsing.parse_renew_option("تمدید با حجم اولیه 60000 تومان")
    assert (o.kind, o.price) == ("initial", 60000)
    o = parsing.parse_renew_option("تمدید و افزایش 10 گیگ 110,000 تومان")
    assert (o.kind, o.extra_gb, o.price) == ("increase", 10, 110000)
    assert parsing.parse_renew_option("❌ انصراف") is None and parsing.parse_renew_option("🔙 برگشت") is None
    scr = parsing.parse_renew_screen(RENEW_OPTIONS.format(name="eg2_1052"))
    assert (scr.name, scr.initial_gb) == ("eg2_1052", 10)
    conf = RENEW_CONFIRM.format(name="eg2_1052", shown=0)
    assert parsing.is_renew_confirm_prompt(conf, "eg2_1052") and not parsing.is_renew_confirm_prompt(conf, "eg2_9999")
    assert not parsing.is_renew_confirm_prompt(RENEW_OPTIONS.format(name="eg2_1052"), "eg2_1052")
    assert parsing.renew_confirm_amount(conf) == 0  # the real bot prints 0 here
    assert parsing.parse_renew_success("اکانت eg2_1052 رو با موفقیت تمدید کردم 😁✅", "eg2_1052")
    assert not parsing.parse_renew_success("اکانت eg2_1052 رو با موفقیت مرجوع کردم ✅", "eg2_1052")
    assert parsing.parse_charged_amount("مبلغ 60,000 تومان از حسابت کم کردم") == 60000
    assert parsing.parse_charged_amount(conf) is None  # future tense = not charged yet
    assert parsing.is_operation_expired("❗ زمان عملیات منقضی شده از اول باید بری")


def test_account_detail_reads_renewal_date():
    d = parsing.parse_account_detail(RENEWED_DETAIL.format(name="eg2_1052", renewed="1405/08/02 04:34", end="1405/09/02 04:34"))
    assert d.renewed_at == parsing.parse_jalali("1405/08/02 04:34") and d.expire_at == parsing.parse_jalali("1405/09/02 04:34")
    assert parsing.parse_account_detail(DETAIL.format(name="eg1_1", used=0, left=10)).renewed_at is None


async def test_renew_flow_pays_once_and_reads_the_new_expiry():
    bot = FakeParentBot()
    a = make(bot)
    await a.create_account(spec())
    pa = await a.extend_account("Mel_10G1", expire_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=30), traffic_bytes=10 * GB)
    assert bot.renewals == 1 and bot.balance == 385000
    assert pa.expire_at == parsing.parse_jalali("1405/09/11 04:34") and pa.traffic_limit_bytes == 10 * GB and pa.traffic_used_bytes == 0
    d = await a.store.get("Mel_10G1")
    assert d["renew_charged"] == 60000 and "renew_started" not in d and "renew_pending" not in d


async def test_renew_accepts_the_zero_amount_the_real_bot_prints():
    bot = FakeParentBot(renew_shown=0)
    a = make(bot)
    await a.create_account(spec())
    await a.extend_account("Mel_10G1", expire_at=None, traffic_bytes=10 * GB)
    assert bot.renewals == 1


async def test_renew_refuses_a_different_amount_on_the_confirm_screen():
    bot = FakeParentBot(renew_shown=95000)
    a = make(bot)
    await a.create_account(spec())
    with pytest.raises(PanelError) as e:
        await a.extend_account("Mel_10G1", expire_at=None, traffic_bytes=10 * GB)
    assert e.value.kind == ErrorKind.PERMANENT and "cancelled" in e.value.message and bot.renew_confirms == 0


async def test_renew_price_cap_and_low_wallet_stop_before_confirm():
    bot = FakeParentBot()
    a = make(bot, max_price=100000)
    await a.create_account(spec())
    bot.renew_price = 120000
    with pytest.raises(PanelError) as e:
        await a.extend_account("Mel_10G1", expire_at=None, traffic_bytes=10 * GB)
    assert e.value.kind == ErrorKind.PERMANENT and "max_price" in e.value.message and bot.renew_confirms == 0
    bot.renew_price, bot.balance = 60000, 50000
    with pytest.raises(PanelError) as e:
        await a.extend_account("Mel_10G1", expire_at=None, traffic_bytes=10 * GB)
    assert e.value.kind == ErrorKind.PERMANENT and "top it up" in e.value.message and bot.renew_confirms == 0


async def test_renew_other_volume_is_manual_and_pays_nothing():
    bot = FakeParentBot()
    a = make(bot)
    await a.create_account(spec())
    with pytest.raises(PanelError) as e:
        await a.extend_account("Mel_10G1", expire_at=None, traffic_bytes=20 * GB)
    assert e.value.kind == ErrorKind.PERMANENT and "manual" in e.value.message and bot.renew_confirms == 0


async def test_renew_stale_buttons_is_transient():
    bot = FakeParentBot(stale_renew=True)
    a = make(bot)
    await a.create_account(spec())
    with pytest.raises(PanelError) as e:
        await a.extend_account("Mel_10G1", expire_at=None, traffic_bytes=10 * GB)
    assert e.value.kind == ErrorKind.TRANSIENT and bot.renew_confirms == 0


async def test_renew_without_ack_is_unknown_and_a_retry_never_pays_twice():
    bot = FakeParentBot(renew_ack=False)
    a = make(bot)
    await a.create_account(spec())
    with pytest.raises(PanelError) as e:
        await a.extend_account("Mel_10G1", expire_at=None, traffic_bytes=10 * GB)
    assert e.value.kind == ErrorKind.UNKNOWN and bot.renewals == 1
    pa = await a.extend_account("Mel_10G1", expire_at=None, traffic_bytes=10 * GB)  # outbox retry: the account screen shows it landed
    assert bot.renewals == 1 and bot.renew_confirms == 1 and pa.expire_at == parsing.parse_jalali("1405/09/11 04:34")


async def test_renew_confirmed_but_not_applied_blocks_a_second_payment_inside_the_window():
    bot = FakeParentBot(renew_applies=False)
    a = make(bot)
    await a.create_account(spec())
    for _ in range(2):
        with pytest.raises(PanelError) as e:
            await a.extend_account("Mel_10G1", expire_at=None, traffic_bytes=10 * GB)
        assert e.value.kind == ErrorKind.UNKNOWN
    assert bot.renew_confirms == 1  # second attempt did not confirm again
    d = await a.store.get("Mel_10G1")
    d["renew_started"] = time.time() - 3600  # window over, nothing changed upstream: the earlier confirm never took effect
    await a.store.set("Mel_10G1", d)
    bot.renew_applies = True
    await a.extend_account("Mel_10G1", expire_at=None, traffic_bytes=10 * GB)
    assert bot.renewals == 1 and bot.renew_confirms == 2


async def test_renewed_usage_is_zero_so_core_needs_no_second_extend_call():
    bot = FakeParentBot()
    a = make(bot)
    await a.create_account(spec())
    pa = await a.extend_account("Mel_10G1", expire_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=30), traffic_bytes=10 * GB)
    assert pa.traffic_used_bytes == 0  # usage is back to zero, so Core's "raise the limit by what was used" fallback never fires
