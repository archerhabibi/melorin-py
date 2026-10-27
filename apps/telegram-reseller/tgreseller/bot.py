"""One reseller store bot: the main-bot runner specialised for a store (owner menu, store texts, token redaction)."""

import logging
import os
import re
import time
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import httpx

_here = Path(__file__).resolve().parent.parent  # /app in the image, apps/telegram-reseller in the repo
_path = next(p for p in (_here / "telegram-main" / "runner.py", _here.parent / "telegram-main" / "runner.py") if p.exists())
_spec = spec_from_file_location("melorin_telegram_main_runner", _path)
_module = module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_module)
money, keyboard, esc = _module.money, _module.keyboard, _module.esc

log = logging.getLogger("melorin.telegram.reseller")

OWNER_BUTTON = "🏪 مدیریت فروشگاه"
OWNER_HELP = "\n\nبخش نماینده:\n/manage مدیریت فروشگاه\n/report گزارش فروش\n/customers مشتریان\n/payments پرداخت‌های در انتظار تأیید\n/prices قیمت فروش محصولات\n/myreferral برنامه‌ی رفرال و کمیسیون فروشگاه"
CUSTOMER_COMMANDS = [(c, d) for c, d in _module.BOT_COMMANDS if c != "reseller"]
OWNER_COMMANDS = [("manage", OWNER_BUTTON), ("report", "📊 گزارش فروش"), ("customers", "👥 مشتریان"), ("payments", "💳 پرداخت‌های در انتظار"), ("prices", "💲 قیمت فروش"), ("allaccounts", "🗂 اکانت‌های من و مشتریان"), ("myreferral", "🎁 رفرال و کمیسیون فروشگاه")]
DEBT_LABEL = {"ok": "🟢 عادی", "near": "🟠 نزدیک به سقف بدهی", "reached": "🔴 به سقف بدهی رسیده"}
OWNER_CACHE_SECONDS = 600
STORE_CACHE_SECONDS = 60  # welcome / support texts edited by the admin or the owner apply within a minute, no restart
TOKEN_RE = re.compile(r"bot\d{6,15}:[A-Za-z0-9_-]{20,}")


def owner_referral_text(rules: list, summary: dict, currency: str | None) -> str:
    """The owner's view of HIS store's referral programme, built only from Core (rules + summary of this store)."""
    cur = currency or ""
    def reward(r: dict) -> str:
        v = r.get("value") or 0
        if r.get("model") == "percent":
            out = f"{v / 100:g}٪"
            if r.get("max_amount"):
                out += f" (حداکثر {money(r['max_amount'])} {cur})"
            return out
        return f"{money(v)} {cur}"
    labels = {"signup_reward": "پاداش ثبت‌نام دوست", "commission": "کمیسیون هر خرید دوست"}
    default = [r for r in rules if r.get("is_active") and not r.get("product_id")]
    per_product = [r for r in rules if r.get("is_active") and r.get("product_id")]
    lines = ["🎁 <b>برنامه‌ی رفرال فروشگاه شما</b>", "پاداش‌ها فقط برای مشتریان همین فروشگاه و از حساب هزینه‌ی همین فروشگاه پرداخت می‌شود.", ""]
    shown = [f"• {labels.get(r.get('kind'), esc(str(r.get('kind'))))}: <b>{esc(reward(r))}</b>" for r in default if (r.get("value") or 0) > 0]
    lines += shown or ["فعلاً طرح پیش‌فرضی فعال نیست (برنامه را از بخش رفرال سایت فروشگاه تنظیم کنید)."]
    if per_product:
        lines.append(f"طرح‌های اختصاصی محصول: <b>{len(per_product)}</b>")
    lines += ["", f"دعوت‌شده‌ها: <b>{int(summary.get('invited') or 0)}</b> · معرف‌های فعال: <b>{int(summary.get('referrers') or 0)}</b>",
              f"پرداخت‌شده تا امروز: <b>{esc(money(summary.get('paid_out') or 0))} {esc(cur)}</b>"]
    if summary.get("reversed"):
        lines.append(f"برگشت‌خورده: {esc(money(summary['reversed']))} {esc(cur)}")
    if summary.get("outstanding_clawback"):
        lines.append(f"بدهی استرداد از معرف‌ها: {esc(money(summary['outstanding_clawback']))} {esc(cur)}")
    return "\n".join(lines)


class RedactTokens(logging.Filter):
    """httpx error text contains the request URL, i.e. the bot token. Never let it reach the logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = TOKEN_RE.sub("bot<redacted>", str(record.msg))
        if record.args:
            record.args = tuple(TOKEN_RE.sub("bot<redacted>", a) if isinstance(a, str) else a for a in (record.args if isinstance(record.args, tuple) else (record.args,)))
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = TOKEN_RE.sub("bot<redacted>", logging.Formatter().formatException(record.exc_info))
        return True


class BotRevoked(Exception):
    """Telegram answered 401: the token was revoked or regenerated. Not retried; the admin must supply a new one."""


class ResellerTelegramRunner(_module.TelegramRunner):
    channel = "reseller"
    secret_env = "MELORIN_RESELLER_BOT_SECRET"

    def __init__(self, *, token: str | None = None, slug: str | None = None, state_suffix: str | None = None):
        token = token or os.environ["MELORIN_TELEGRAM_RESELLER_TOKEN"]
        self.slug = slug or os.environ["MELORIN_STORE_SLUG"]
        offset_file = f"/var/lib/melorin/reseller-{state_suffix}-offset.json" if state_suffix else None
        super().__init__(token=token, offset_file=offset_file)
        self.health, self.health_detail = "connecting", None  # what the supervisor reports to Core
        self._store_at = 0.0
        self._owners: dict[str, tuple[bool, float]] = {}
        self.commands.update({"/manage": self.cmd_manage, "/report": self.cmd_report, "/customers": self.cmd_customers, "/payments": self.cmd_payments, "/prices": self.cmd_prices, "/allaccounts": self.cmd_owner_accounts, "/myreferral": self.cmd_owner_referral})
        # the store owner's account inquiry (every account sold in THIS store); Core answers 403 for anyone else
        self.callbacks.update({"oacl": self.cb_owner_acc_list, "oacs": self.cb_owner_acc_search, "oacq": self.cb_owner_acc_clear,
                               "oaccount": self.cb_owner_account, "oqr": self.cb_owner_qr,
                               "orn": self.cb_owner_renew, "orb": self.cb_owner_renew_buy})
        self.commands.pop("/reseller", None)  # reseller bots have no sub-resellers
        self.callbacks.update({"rv": self.cb_review, "prc": self.cb_price_pick, "prs": self.cb_price_scope, "mg": self.cb_manage})

    # ---------- connection health ----------
    def _fail(self, status: int | None, exc: Exception) -> None:
        if status == 409:
            self.health_detail = "ربات هم‌زمان جای دیگری (وب‌هوک یا نمونهٔ دیگر) پیام دریافت می‌کند."
        elif status == 429:
            self.health_detail = "تلگرام موقتاً درخواست‌ها را محدود کرده است."
        else:
            self.health_detail = "اتصال به تلگرام برقرار نیست."
        self.health = "error"

    async def tg(self, method: str, payload: dict) -> dict:
        try:
            out = await super().tg(method, payload)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 401:
                self.health, self.health_detail = "error", "تلگرام توکن را نمی‌پذیرد؛ توکن جدید در مدیریت ثبت کنید."
                raise BotRevoked(self.slug) from None
            if method == "getUpdates":
                self._fail(status, exc)
            raise
        except (httpx.HTTPError, RuntimeError) as exc:
            if method == "getUpdates":
                self._fail(None, exc)
            raise
        if method == "getUpdates":
            self.health, self.health_detail = "running", None
        return out

    # ---------- store ----------
    async def store_info(self) -> dict:
        if self.store is None or time.monotonic() - self._store_at > STORE_CACHE_SECONDS:
            r = await self.client.get(f"{self.core}/api/v1/stores/by-slug/{self.slug}")
            r.raise_for_status()
            self.store, self._store_at = r.json(), time.monotonic()
        return self.store

    async def text_of(self, key: str) -> str | None:
        msgs = (await self.store_info()).get("bot_messages") or {}
        value = msgs.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    # ---------- owner awareness ----------
    async def is_owner(self, ctx) -> bool:
        """Core decides: the owner-only profile endpoint answers 403 for everybody else. Cached briefly per chat."""
        key = str(ctx.chat_id)
        hit = self._owners.get(key)
        if hit and time.monotonic() - hit[1] < OWNER_CACHE_SECONDS:
            return hit[0]
        s = await self.store_info()
        try:
            await self.api(ctx, "GET", f"/api/v1/stores/{s['id']}/reseller/profile")
            owner = True
        except _module.CoreError as exc:
            if exc.status not in (401, 403, 404):
                raise
            owner = False
        self._owners[key] = (owner, time.monotonic())
        if owner:  # the owner's Menu button also lists the management commands
            try:
                await self.tg("setMyCommands", {"commands": [{"command": c, "description": d} for c, d in CUSTOMER_COMMANDS + OWNER_COMMANDS],
                                                "scope": {"type": "chat", "chat_id": ctx.chat_id}})
            except (httpx.HTTPError, RuntimeError, BotRevoked):
                log.warning("owner command menu could not be set", exc_info=True)
        return owner

    def main_menu_rows(self, chat_id) -> list:
        rows = [list(r) for r in _module.MAIN_MENU[:-1]]  # the last row asks for a reseller bot: not offered here
        hit = self._owners.get(str(chat_id))
        if hit and hit[0]:
            rows.append([OWNER_BUTTON])
        return rows

    async def setup_menu(self) -> None:
        try:
            await self.tg("deleteWebhook", {"drop_pending_updates": False})  # a leftover webhook would block getUpdates (409)
            await self.tg("setMyCommands", {"commands": [{"command": c, "description": d} for c, d in CUSTOMER_COMMANDS]})
        except (httpx.HTTPError, RuntimeError):
            log.warning("bot menu setup failed", exc_info=True)

    # ---------- customer-facing texts ----------
    async def cmd_start(self, ctx, arg):
        if arg.startswith(("link_", "wl_")):
            return await super().cmd_start(ctx, arg)
        store = await self.store_info()
        await self.is_owner(ctx)
        welcome = await self.text_of("welcome") or f"به {store.get('name', 'فروشگاه')} خوش آمدید 👋\nاز منوی زیر شروع کنید."
        await self.send_main_menu(ctx.chat_id, welcome)
        await self.cmd_home(ctx, "")

    async def cmd_help(self, ctx, arg):
        await self.send(ctx.chat_id, _module.HELP.replace("\n/reseller درخواست نمایندگی", "") + (OWNER_HELP if await self.is_owner(ctx) else ""), _module.MENU)

    async def cmd_rules(self, ctx, arg):
        await self.send(ctx.chat_id, "📜 " + (await self.text_of("rules") or "قوانین خرید:\n\n۱. پس از خرید امکان بازگشت وجه وجود ندارد مگر در صورت خرابی سرویس.\n۲. اکانت‌ها فقط برای استفاده‌ی شخصی هستند.\n۳. برای هرگونه مشکل با پشتیبانی در تماس باشید."))

    async def cmd_support(self, ctx, arg):
        self._set_state(ctx.chat_id, {"new_ticket_subject": "پشتیبانی تلگرام"})
        extra = await self.text_of("support")
        await self.send(ctx.chat_id, (f"{extra}\n\n" if extra else "") + "🎧 پیام خود را برای پشتیبانی بنویسید:")

    # ---------- owner management ----------
    async def cmd_manage(self, ctx, arg):
        s = await self.store_info()
        if not await self.is_owner(ctx):
            return await self.send(ctx.chat_id, "این بخش فقط برای مالک فروشگاه است.")
        p = await self.api(ctx, "GET", f"/api/v1/stores/{s['id']}/reseller/profile")
        w = p.get("main_wallet") or {}
        lines = [f"🏪 <b>{esc(p.get('store_name') or s.get('name'))}</b>",
                 f"💰 اعتبار کیف پول نمایندگی: <b>{esc(money(w.get('balance')))} {esc(w.get('currency') or '')}</b>",
                 f"📉 سقف بدهی: {esc(money(p.get('debt_limit')))} · وضعیت: {DEBT_LABEL.get(str(w.get('debt_state')), '—')}"]
        if not p.get("sales_enabled"):
            lines.append("⛔ فروش فروشگاه شما توسط مدیریت متوقف شده است.")
        try:
            pending = [x for x in await self.api(ctx, "GET", f"/api/v1/stores/{s['id']}/reseller/payments") if x["status"] not in ("succeeded", "failed") and x.get("has_receipt")]
        except _module.CoreError:
            pending = []
        pay_label = f"💳 پرداخت‌های در انتظار ({len(pending)})" if pending else "💳 پرداخت‌ها"
        rows = [[("📊 گزارش فروش", "mg:report"), ("👥 مشتریان", "mg:customers")], [("🗂 اکانت‌های مشتریان", "mg:accounts")], [(pay_label, "mg:payments"), ("💲 قیمت فروش", "mg:prices")], [("🎁 رفرال و کمیسیون", "mg:referral")]]
        site = await self.account_url(ctx)
        if site:
            rows.append([("🌐 ورود به فروشگاه در وب", site)])
        await self.screen(ctx, "\n".join(lines), rows)

    async def cb_manage(self, ctx, which):
        fn = {"report": self.cmd_report, "customers": self.cmd_customers, "accounts": self.cmd_owner_accounts, "payments": self.cmd_payments, "prices": self.cmd_prices, "referral": self.cmd_owner_referral}.get(which)
        if fn is None:
            return await self.send(ctx.chat_id, "گزینه نامعتبر است.")
        await fn(ctx, "")

    async def cmd_owner_referral(self, ctx, arg):
        s = await self.store_info()
        if not await self.is_owner(ctx):
            return await self.send(ctx.chat_id, "این بخش فقط برای مالک فروشگاه است.")
        rules = await self.api(ctx, "GET", f"/api/v1/stores/{s['id']}/referral-rules")
        summary = await self.api(ctx, "GET", f"/api/v1/stores/{s['id']}/referrals/summary")
        text = owner_referral_text(rules, summary, s.get("currency"))
        site = await self.account_url(ctx)
        await self.screen(ctx, text, [[("🌐 تنظیم طرح‌ها در وب", site)]] if site else None)

    async def cmd_report(self, ctx, arg):
        s = await self.store_info()
        rep = await self.api(ctx, "GET", f"/api/v1/stores/{s['id']}/reseller/reports")
        lines = [f"{o['status']}: {o['count']} سفارش · فروش {money(o['total'])} · بها {money(o['reseller_cost'])}" for o in rep["orders"]]
        await self.send(ctx.chat_id, f"گزارش ({rep['currency']}):\n" + ("\n".join(lines) or "—"))

    async def cmd_customers(self, ctx, arg):
        s = await self.store_info()
        cs = await self.api(ctx, "GET", f"/api/v1/stores/{s['id']}/reseller/customers")
        lines = [f"{c.get('display_name') or c.get('email') or c['user_id'][:8]} · {c['status']}" for c in cs[:30]]
        await self.send(ctx.chat_id, f"مشتریان ({len(cs)}):\n" + ("\n".join(lines) or "—"))

    async def cmd_payments(self, ctx, arg):
        s = await self.store_info()
        ps = await self.api(ctx, "GET", f"/api/v1/stores/{s['id']}/reseller/payments")
        todo = [p for p in ps if p["status"] not in ("succeeded", "failed") and p.get("has_receipt")][:10]
        if not todo:
            return await self.send(ctx.chat_id, "پرداخت در انتظار تأییدی نیست.")
        for p in todo:
            await self.send(ctx.chat_id, f"پرداخت {money(p['amount'])} {p['currency']} · {p['provider']}",
                            [[("✅ تأیید", f"rv:{p['id']}:1"), ("❌ رد", f"rv:{p['id']}:0")]])

    # ---- retail prices: the reseller sets them for THIS store only; the core enforces the cost floor ----
    async def cmd_prices(self, ctx, arg):
        s = await self.store_info()
        rows = await self.api(ctx, "GET", f"/api/v1/stores/{s['id']}/reseller/prices")
        if not rows:
            return await self.send(ctx.chat_id, "محصولی برای قیمت‌گذاری در دسترس نیست.")
        mark = {"unset": "⚪️ تعیین نشده", "ok": "✅", "below_cost": "⚠️ زیر قیمت همکاری"}
        buttons = []
        for r in rows[:30]:
            price = money(r["customer_price"]) if r["customer_price"] else mark["unset"]
            buttons.append([(f"{r['name']} · {price} · حداقل {money(r['cost_floor'])}", f"prc:{r['product_id']}")])
        await self.send(ctx.chat_id, "💲 قیمت فروش به مشتریان شما. محصولی را انتخاب کنید تا قیمتش را عوض کنید.\nمحصول بدون قیمت یا با قیمت زیر حداقل به مشتری نمایش داده نمی‌شود.", buttons)

    async def _price_row(self, ctx, pid):
        """One row of the core's price table (the same table the website shows)."""
        s = await self.store_info()
        rows = await self.api(ctx, "GET", f"/api/v1/stores/{s['id']}/reseller/prices")
        return next((r for r in rows if str(r["product_id"]) == str(pid)), None)

    async def cb_price_pick(self, ctx, pid):
        """A package with sales bundles is priced per bundle (or store-wide), like on the website; the core resolves
        and validates everything. A package the core lists without bundles keeps the single store-wide price."""
        row = await self._price_row(ctx, pid)
        bundles = (row or {}).get("bundles") or []
        self._merge_state(ctx.chat_id, price_for=pid, price_bundle=None)
        if not bundles:
            return await self.send(ctx.chat_id, "قیمت فروش جدید را به عدد (تومان) بفرستید. برای برداشتن قیمت، 0 بفرستید.")
        base = money(row["customer_price"]) if row.get("customer_price") else "تعیین نشده"
        buttons = [[(f"🏷 قیمت کلی فروشگاه · {base}", "prs:s")]]
        for i, pl in enumerate(bundles[:20]):
            eff = money(pl["effective_price"]) if pl.get("effective_price") else "تعیین نشده"
            tag = "" if pl.get("source") != "store" else " (قیمت کلی)"
            buttons.append([(f"{pl.get('kind_label') or ''} {pl['bundle_name']} · {eff}{tag} · هزینه {money(pl['cost'])}".strip(), f"prs:{i}")])
        await self.send(ctx.chat_id, f"{row['name']}\nقیمت را برای کدام بسته تعیین می‌کنید؟ قیمت هر بسته بر قیمت کلی فروشگاه مقدم است.", buttons)

    async def cb_price_scope(self, ctx, which):
        pid = (self.state.get(str(ctx.chat_id)) or {}).get("price_for")
        if not pid:
            return await self.send(ctx.chat_id, "ابتدا /prices را بفرستید.")
        if which == "s":
            self._merge_state(ctx.chat_id, price_bundle=None)
            return await self.send(ctx.chat_id, "قیمت کلی فروشگاه را به عدد (تومان) بفرستید؛ برای بسته‌هایی که قیمت اختصاصی ندارند اعمال می‌شود. برای برداشتن، 0 بفرستید.")
        row = await self._price_row(ctx, pid)
        bundles = (row or {}).get("bundles") or []
        try:
            bundle = bundles[int(which)]
        except (ValueError, IndexError):
            return await self.send(ctx.chat_id, "بسته پیدا نشد؛ دوباره /prices را بفرستید.")
        self._merge_state(ctx.chat_id, price_bundle=str(bundle["bundle_id"]))
        await self.send(ctx.chat_id, f"قیمت فروش در «{bundle['bundle_name']}» را به عدد (تومان) بفرستید (حداقل {money(bundle['cost'])}). برای برداشتن و استفاده از قیمت کلی، 0 بفرستید.")

    # ---------- owner: account inquiry ----------
    async def _owner_only(self, ctx) -> bool:
        if await self.is_owner(ctx):
            return True
        await self.send(ctx.chat_id, "شما به این بخش دسترسی ندارید.")
        return False

    async def cmd_owner_accounts(self, ctx, arg):
        if not await self._owner_only(ctx):
            return
        self._merge_state(ctx.chat_id, acc_search=None)
        self._acc_set_view(ctx, "ow", f=None, q=None, p=None)
        await self.show_accounts(ctx, "ow")

    async def cb_owner_acc_list(self, ctx, v):
        await self.cb_acc_list(ctx, v, "ow")

    async def cb_owner_acc_search(self, ctx, v):
        await self.cb_acc_search(ctx, v, "ow")

    async def cb_owner_acc_clear(self, ctx, v):
        await self.cb_acc_clear(ctx, v, "ow")

    async def cb_owner_account(self, ctx, v):
        await self.show_account_card(ctx, v, "ow")

    async def cb_owner_qr(self, ctx, v):
        await self.cb_qr(ctx, v, "ow")

    async def on_text(self, ctx, text):
        if text == OWNER_BUTTON:
            self._set_state(ctx.chat_id, None)
            return await self.cmd_manage(ctx, "")
        st = self.state.get(str(ctx.chat_id)) or {}
        pid, bundle = st.get("price_for"), st.get("price_bundle")
        if not pid or text.startswith("/"):
            return await super().on_text(ctx, text)
        digits = "".join(ch for ch in text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")) if ch.isdigit())
        if not digits:  # not a number: the reseller moved on (menu button, other text)
            self._merge_state(ctx.chat_id, price_for=None, price_bundle=None)
            return await super().on_text(ctx, text)
        s = await self.store_info()
        path = f"/api/v1/stores/{s['id']}/reseller/" + (f"bundles/{bundle}/prices/{pid}" if bundle else f"prices/{pid}")
        try:
            out = await self.api(ctx, "PUT", path, json={"customer_price": int(digits)})
        except _module.CoreError as e:  # the state stays, so the reseller can send another number
            return await self.send(ctx.chat_id, f"{e.message if hasattr(e, 'message') else e}\nعدد دیگری بفرستید:")
        self._merge_state(ctx.chat_id, price_for=None, price_bundle=None)
        if not out.get("customer_price"):
            msg = "قیمت اختصاصی این بسته برداشته شد؛ از قیمت کلی فروشگاه استفاده می‌شود." if bundle else "قیمت برداشته شد؛ محصول به مشتری نمایش داده نمی‌شود."
        else:
            msg = f"✅ قیمت فروش {money(out['customer_price'])} ثبت شد."
        await self.send(ctx.chat_id, msg)

    async def cb_review(self, ctx, rest):
        pid, _, flag = rest.partition(":")
        s = await self.store_info()
        await self.api(ctx, "POST", f"/api/v1/stores/{s['id']}/reseller/payments/{pid}/review", json={"approve": flag == "1", "note": None if flag == "1" else "رد از طریق ربات"})
        await self.send(ctx.chat_id, "پرداخت تأیید شد ✅" if flag == "1" else "پرداخت رد شد ❌")
