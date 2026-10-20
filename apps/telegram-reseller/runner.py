"""Reseller Telegram runner.

Same Core-authenticated transport as the main runner, bound to one reseller Store per bot. Customers get the full
storefront under the store's own name and texts; the owner additionally gets a management menu (/manage, /report,
/customers, /payments, /prices). Authorization is enforced by Core (403 for non-owners); this process never holds
infrastructure credentials or other stores' data.

Where the bots come from
------------------------
Normal operation is *Core-driven*: the supervisor asks Core which reseller bots should run
(``GET /api/v1/internal/reseller-bots``), starts one isolated runner per store, restarts a runner when its token
changes, stops it when the store is suspended / the bot is switched off / the token is removed, and reports each
bot's real connection state back to Core, which the admin screen shows. Adding or editing a reseller in the admin
needs no restart and no environment variable.

Legacy static modes still work for development: ``MELORIN_RESELLER_BOTS_JSON`` (several bots) or
``MELORIN_TELEGRAM_RESELLER_TOKEN`` + ``MELORIN_STORE_SLUG`` (one bot).
"""
import asyncio
import json
import logging
import os
import re
import time
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import httpx

_here = Path(__file__).parent
_path = next(p for p in (_here / "telegram-main" / "runner.py", _here.parent / "telegram-main" / "runner.py") if p.exists())
_spec = spec_from_file_location("melorin_telegram_main_runner", _path)
_module = module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_module)
money, keyboard, esc = _module.money, _module.keyboard, _module.esc

log = logging.getLogger("melorin.telegram.reseller")

OWNER_BUTTON = "🏪 مدیریت فروشگاه"
OWNER_HELP = "\n\nبخش نماینده:\n/manage مدیریت فروشگاه\n/report گزارش فروش\n/customers مشتریان\n/payments پرداخت‌های در انتظار تأیید\n/prices قیمت فروش محصولات"
CUSTOMER_COMMANDS = [(c, d) for c, d in _module.BOT_COMMANDS if c != "reseller"]
OWNER_COMMANDS = [("manage", OWNER_BUTTON), ("report", "📊 گزارش فروش"), ("customers", "👥 مشتریان"), ("payments", "💳 پرداخت‌های در انتظار"), ("prices", "💲 قیمت فروش"), ("allaccounts", "🗂 اکانت‌های من و مشتریان")]
DEBT_LABEL = {"ok": "🟢 عادی", "near": "🟠 نزدیک به سقف بدهی", "reached": "🔴 به سقف بدهی رسیده"}
OWNER_CACHE_SECONDS = 600
STORE_CACHE_SECONDS = 60  # welcome / support texts edited by the admin or the owner apply within a minute, no restart
TOKEN_RE = re.compile(r"bot\d{6,15}:[A-Za-z0-9_-]{20,}")


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

    def __init__(self, *, token: str | None = None, slug: str | None = None, state_suffix: str | None = None):
        token = token or os.environ["MELORIN_TELEGRAM_RESELLER_TOKEN"]
        self.slug = slug or os.environ["MELORIN_STORE_SLUG"]
        offset_file = f"/var/lib/melorin/reseller-{state_suffix}-offset.json" if state_suffix else None
        super().__init__(token=token, offset_file=offset_file)
        self.health, self.health_detail = "connecting", None  # what the supervisor reports to Core
        self._store_at = 0.0
        self._owners: dict[str, tuple[bool, float]] = {}
        self.commands.update({"/manage": self.cmd_manage, "/report": self.cmd_report, "/customers": self.cmd_customers, "/payments": self.cmd_payments, "/prices": self.cmd_prices, "/allaccounts": self.cmd_owner_accounts})
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
        rows = [[("📊 گزارش فروش", "mg:report"), ("👥 مشتریان", "mg:customers")], [("🗂 اکانت‌های مشتریان", "mg:accounts")], [(pay_label, "mg:payments"), ("💲 قیمت فروش", "mg:prices")]]
        site = await self.account_url(ctx)
        if site:
            rows.append([("🌐 ورود به فروشگاه در وب", site)])
        await self.screen(ctx, "\n".join(lines), rows)

    async def cb_manage(self, ctx, which):
        fn = {"report": self.cmd_report, "customers": self.cmd_customers, "accounts": self.cmd_owner_accounts, "payments": self.cmd_payments, "prices": self.cmd_prices}.get(which)
        if fn is None:
            return await self.send(ctx.chat_id, "گزینه نامعتبر است.")
        await fn(ctx, "")

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



# ---------------------------------------------------------------- hosting: supervisor + legacy static modes
HEARTBEAT_SECONDS = 15


async def heartbeat_loop(path: str | None) -> None:
    """Touch a file so the container healthcheck can tell the process is alive and not stuck."""
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    while True:
        target.write_text(str(int(time.time())))
        await asyncio.sleep(HEARTBEAT_SECONDS)


class Slot:
    def __init__(self, cfg: dict, runner: ResellerTelegramRunner, task: asyncio.Task):
        self.cfg, self.runner, self.task = cfg, runner, task
        self.revoked = False  # token refused by Telegram: wait for a different token instead of retrying


class Supervisor:
    """Keeps exactly the bots Core wants running, one isolated runner per reseller store."""

    def __init__(self, *, core: str | None = None, secret: str | None = None, client: httpx.AsyncClient | None = None, make_runner=None):
        self.core = (core or os.environ["MELORIN_CORE_URL"]).rstrip("/")
        self.secret = secret or os.environ["MELORIN_BOT_SERVICE_SECRET"]
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
        self.make_runner = make_runner or (lambda cfg: ResellerTelegramRunner(token=cfg["token"], slug=cfg["slug"], state_suffix=str(cfg["store_id"])))
        self.slots: dict[str, Slot] = {}
        self.poll_seconds = 30

    def _headers(self) -> dict:
        return {"X-Bot-Secret": self.secret, "Accept": "application/json"}

    async def fetch(self) -> list[dict] | None:
        try:
            r = await self.client.get(f"{self.core}/api/v1/internal/reseller-bots", headers=self._headers())
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError):
            log.warning("could not read the reseller bot list from Core; keeping the running bots", exc_info=True)
            return None
        self.poll_seconds = max(10, min(120, int(data.get("poll_seconds") or 30)))
        return data.get("bots") or []

    async def report(self, store_id: str, state: str, detail: str | None, fingerprint: str) -> None:
        try:
            await self.client.post(f"{self.core}/api/v1/internal/reseller-bots/{store_id}/status", headers=self._headers(),
                                   json={"state": state, "detail": detail, "fingerprint": fingerprint})
        except httpx.HTTPError:
            log.warning("could not report bot status for %s", store_id)

    async def _stop(self, key: str) -> None:
        slot = self.slots.pop(key, None)
        if slot is None:
            return
        slot.task.cancel()
        await asyncio.gather(slot.task, return_exceptions=True)
        log.info("stopped reseller bot of store %s", slot.cfg.get("slug"))

    async def sync(self) -> None:
        wanted = await self.fetch()
        if wanted is None:
            return
        by_id = {str(b["store_id"]): b for b in wanted}
        for key in [k for k in self.slots if k not in by_id]:
            await self._stop(key)  # suspended, switched off, or token removed
        for key, cfg in by_id.items():
            slot = self.slots.get(key)
            if slot and slot.cfg["fingerprint"] != cfg["fingerprint"]:
                await self._stop(key)  # token (or slug) changed: restart on the new one
                slot = None
            if slot and slot.task.done() and not slot.revoked:
                exc = None if slot.task.cancelled() else slot.task.exception()
                if isinstance(exc, BotRevoked):
                    slot.revoked = True
                else:
                    log.warning("reseller bot %s stopped unexpectedly; restarting", cfg["slug"])
                    await self._stop(key)
                    slot = None
            if slot is None:
                try:
                    runner = self.make_runner(cfg)
                except Exception:  # noqa: BLE001 - one broken store must never take the others down
                    log.exception("could not start reseller bot of %s", cfg.get("slug"))
                    continue
                self.slots[key] = Slot(cfg, runner, asyncio.create_task(runner.run(), name=f"reseller-{cfg['slug']}"))
                log.info("started reseller bot of store %s (@%s)", cfg["slug"], cfg.get("bot_username"))
        for key, slot in list(self.slots.items()):
            if slot.task.done() and not slot.revoked and isinstance(None if slot.task.cancelled() else slot.task.exception(), BotRevoked):
                slot.revoked = True
            state, detail = ("error", slot.runner.health_detail) if slot.revoked else (slot.runner.health, slot.runner.health_detail)
            await self.report(key, state, detail, slot.cfg["fingerprint"])

    async def run(self) -> None:
        try:
            while True:
                await self.sync()
                await asyncio.sleep(self.poll_seconds)
        finally:
            for key in list(self.slots):
                await self._stop(key)
            await self.client.aclose()


def _static_bots() -> list[ResellerTelegramRunner] | None:
    raw = os.getenv("MELORIN_RESELLER_BOTS_JSON", "").strip()
    if raw:
        try:
            configs = json.loads(raw)
            if not isinstance(configs, list) or not configs:
                raise ValueError
            bots = []
            for i, cfg in enumerate(configs):
                if not isinstance(cfg, dict) or not cfg.get("token") or not cfg.get("store_slug"):
                    raise ValueError("each bot needs token and store_slug")
                slug = str(cfg["store_slug"])
                safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in slug)[:60]
                bots.append(ResellerTelegramRunner(token=str(cfg["token"]), slug=slug, state_suffix=f"{i}-{safe}"))
            return bots
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise SystemExit(f"MELORIN_RESELLER_BOTS_JSON is invalid: {exc}") from exc
    if os.getenv("MELORIN_TELEGRAM_RESELLER_TOKEN") and os.getenv("MELORIN_STORE_SLUG"):
        return [ResellerTelegramRunner()]
    return None


async def main() -> None:
    heartbeat = heartbeat_loop(os.getenv("MELORIN_HEARTBEAT_FILE"))
    bots = _static_bots()
    if bots is None:
        log.info("reseller bots are managed by Core (admin → نمایندگان)")
        await asyncio.gather(heartbeat, Supervisor().run())
    else:
        await asyncio.gather(heartbeat, *(bot.run() for bot in bots))


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    for handler in logging.getLogger().handlers:
        handler.addFilter(RedactTokens())
    asyncio.run(main())
