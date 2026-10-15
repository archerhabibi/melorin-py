"""Production Telegram long-poll runner (main store bot).

Telegram is transport only: identity, authorization, pricing, wallet, orders and
tickets stay in Core. Every update is exchanged for a Core session through
``/api/v1/auth/telegram/bot`` (X-Bot-Secret). The offset is persisted so a restart
replays no acknowledged update; order/top-up calls carry an Idempotency-Key derived
from the Telegram update/callback id so a replay can never double-charge.

UX model (v2): inline navigation edits the tapped message in place (one "window" instead of
a growing chat), every screen has a back button, purchase screens show the wallet balance
before and after the payment, and accounts open as cards with usage bar, QR and renewal.
"""
import asyncio
import base64
import datetime as dt
import html
import io
import json
import logging
import mimetypes
import os
import re
import uuid
from pathlib import Path

import httpx

log = logging.getLogger("melorin.telegram.main")

HELP = (
    "فرمان‌ها:\n"
    "/plans خرید اکانت\n/wallet کیف پول و شارژ حساب\n/topup مبلغ — شارژ کیف پول\n"
    "/accounts استعلام و تمدید اکانت\n/orders سفارش‌ها\n/test دریافت اکانت تست\n"
    "/tickets پشتیبانی و تیکت‌ها\n/me حساب کاربری\n/referral دعوت از دوستان"
)

# Registered with Telegram (setMyCommands) so the "Menu" button lists them.
BOT_COMMANDS = [
    ("start", "شروع و منوی اصلی"), ("plans", "🛒 خرید اکانت"), ("accounts", "🔑 اکانت‌های من"),
    ("wallet", "💰 کیف پول و شارژ"), ("orders", "📦 سفارش‌ها"), ("test", "🧪 اکانت تست"),
    ("tickets", "🎧 پشتیبانی"), ("referral", "🎁 دعوت از دوستان"), ("help", "راهنما"),
]

# Must stay in sync with the public bot's Persian reply keyboard.
MAIN_MENU = [
    ["🛒 خرید اکانت", "🔍 استعلام و تمدید اکانت"],
    ["💰 کیف پول و شارژ حساب", "👤 حساب کاربری"],
    ["🎁 دعوت از دوستان", "🧪 دریافت اکانت تست"],
    ["📜 قوانین خرید و آموزش", "🎧 پشتیبانی"],
    ["🤖 درخواست ربات نماینده و همکاری"],
]

# Inline actions used inside the flows behind the reply keyboard.
MENU = [[("🛒 خرید اکانت", "menu:plans"), ("💰 کیف پول", "menu:wallet")],
        [("📦 سفارش‌ها", "menu:orders"), ("🔑 اکانت‌ها", "menu:accounts")],
        [("🎫 تیکت‌ها", "menu:tickets"), ("🔔 اعلان‌ها", "menu:notifications")]]

CURRENCY_LABEL = {"IRT": "تومان", "IRR": "ریال"}
ACCOUNT_STATUS = {"active": "🟢 فعال", "pending": "⏳ در انتظار", "provisioning": "⏳ در حال ساخت", "suspended": "🟠 مسدود",
                  "expired": "🔴 منقضی", "revoked": "⛔ لغوشده", "archived": "📁 بایگانی"}
ORDER_STATUS = {"pending": "⏳ در انتظار پرداخت", "paid": "💳 پرداخت‌شده", "processing": "⚙️ در حال پردازش",
                "provisioning": "⚙️ در حال ساخت اکانت", "completed": "✅ تکمیل‌شده", "provisioning_failed": "❌ ناموفق",
                "refund_pending": "↩️ در حال بازگشت وجه", "refunded": "↩️ بازگشت داده شد", "cancelled": "🚫 لغوشده",
                "manual_review": "🔎 در حال بررسی"}
TX_KIND = {"purchase": "🛒 خرید", "topup": "💳 شارژ", "refund": "↩️ بازگشت وجه", "topup_refund": "↩️ برگشت شارژ",
           "referral_first": "🎁 پاداش دعوت", "referral_recurring": "🎁 پاداش دعوت", "manual_adjustment": "✏️ اصلاح دستی"}
PAGE_SIZE = 8
KIND_BADGE = {"direct": "مستقیم", "tunnel": "تانل", "softether": "Softether"}


TICKET_ICON = {"open": "🟡", "answered": "🟢", "closed": "⚫"}
TICKET_LABEL = {"open": "🟡 باز", "answered": "🟢 پاسخ داده شد", "closed": "⚫ بسته"}
PRIORITY_LABEL = {"low": "کم", "normal": "عادی", "high": "🟠 مهم", "urgent": "🔴 فوری"}


def esc(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=False)


def money(n) -> str:
    return f"{int(n or 0):,}"


def cur(code) -> str:
    return CURRENCY_LABEL.get(str(code or "").upper(), str(code or ""))


def fmt(n, code) -> str:
    return f"{money(n)} {cur(code)}"


def gb(b) -> str:
    return f"{(b or 0) / 1073741824:.1f}"


def keyboard(rows):
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}


def reply_keyboard(rows):
    return {"keyboard": [[{"text": text} for text in row] for row in rows], "resize_keyboard": True}


def b64(value) -> str:
    """UUID -> 22 chars so two ids still fit in Telegram's 64-byte callback_data limit."""
    return base64.urlsafe_b64encode(uuid.UUID(str(value)).bytes).decode().rstrip("=")


def unb64(token: str) -> str:
    try:
        return str(uuid.UUID(bytes=base64.urlsafe_b64decode(token + "==")))
    except (ValueError, TypeError) as exc:
        raise CoreError(400, "گزینه نامعتبر است. دوباره از منو انتخاب کنید.") from exc


def usage_bar(used, limit, width: int = 10) -> str:
    if not limit:
        return f"♾ نامحدود · مصرف {gb(used)} GB"
    pct = min(1.0, (used or 0) / limit)
    filled = round(pct * width)
    return f"{'▰' * filled}{'▱' * (width - filled)} {int(pct * 100)}٪\n{gb(used)} / {gb(limit)} GB"


def parse_dt(value) -> dt.datetime | None:
    if not value:
        return None
    try:
        d = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.UTC)


def expiry_line(value) -> str:
    d = parse_dt(value)
    if d is None:
        return "⏳ انقضا: نامحدود"
    left = (d - dt.datetime.now(dt.UTC)).days
    tail = f"{left} روز مانده" if left >= 0 else "منقضی شده"
    return f"⏳ انقضا: {d:%Y-%m-%d} ({tail})"


def qr_png(data: str) -> bytes | None:
    try:
        import segno
    except ImportError:  # optional dependency: the bot still works, just without the QR image
        return None
    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="png", scale=8, border=4)
    return buf.getvalue()


class CoreError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


class Ctx:
    def __init__(self, chat_id, user, pair, update_id, callback_id=None, message_id=None):
        self.chat_id, self.user, self.pair = chat_id, user, pair
        self.update_id, self.callback_id = update_id, callback_id
        self.message_id = message_id  # the tapped message (callbacks only) -> edited in place

    @property
    def idem(self) -> str:
        return f"tg-{self.callback_id or self.update_id}"


class TelegramRunner:
    channel = "main"

    def __init__(self):
        self.token = os.environ["MELORIN_TELEGRAM_TOKEN"]
        self.core = os.environ["MELORIN_CORE_URL"].rstrip("/")
        self.secret = os.environ["MELORIN_BOT_SERVICE_SECRET"]
        self.offset_file = Path(os.getenv("MELORIN_TELEGRAM_OFFSET_FILE", "/var/lib/melorin/offset.json"))
        self.offset_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file = self.offset_file.with_name(self.offset_file.stem + "-state.json")
        self.offset = self._load_offset()
        self.state = self._load_state()
        self.store: dict | None = None
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(35.0, connect=10.0))
        self.commands = {
            "/start": self.cmd_start, "/help": self.cmd_help, "/me": self.cmd_me, "/plans": self.cmd_plans,
            "/wallet": self.cmd_wallet, "/topup": self.cmd_topup, "/orders": self.cmd_orders,
            "/accounts": self.cmd_accounts, "/test": self.cmd_test, "/tickets": self.cmd_tickets,
            "/ticket": self.cmd_ticket, "/notifications": self.cmd_notifications, "/link": self.cmd_link, "/referral": self.cmd_referral,
        }
        self.callbacks = {
            "menu": self.cb_menu, "plan": self.cb_plan, "buy": self.cb_buy, "ticket": self.cb_ticket,
            "reply": self.cb_reply, "readall": self.cb_readall, "wallet": self.cb_wallet_amount,
            "account": self.cb_account, "plans": self.cb_plans, "cpn": self.cb_coupon, "qr": self.cb_qr,
            "pool": self.cb_pool, "pnl": self.cb_panel, "qt": self.cb_quote, "rnw": self.cb_renew, "rnq": self.cb_renew_quote, "rnb": self.cb_renew_buy, "noop": self.cb_noop,
            "tnew": self.cb_ticket_new, "tedit": self.cb_ticket_edit_msg, "tsubj": self.cb_ticket_edit_subject,
            "tclose": self.cb_ticket_close, "treopen": self.cb_ticket_reopen,
        }

    # ---------- persistence ----------
    def _load_offset(self) -> int | None:
        try:
            return int(json.loads(self.offset_file.read_text())["offset"])
        except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError):
            return None

    def _save_offset(self, offset: int) -> None:
        tmp = self.offset_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"offset": offset}))
        tmp.replace(self.offset_file)
        self.offset = offset

    def _load_state(self) -> dict:
        try:
            return json.loads(self.state_file.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _set_state(self, chat_id, value: dict | None) -> None:
        if value is None:
            self.state.pop(str(chat_id), None)
        else:
            self.state[str(chat_id)] = value
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state))
        tmp.replace(self.state_file)

    # ---------- transport ----------
    async def tg(self, method: str, payload: dict) -> dict:
        r = await self.client.post(f"https://api.telegram.org/bot{self.token}/{method}", json=payload)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description", method))
        return data["result"]

    async def send(self, chat_id, text: str, rows=None, *, reply=False, html: bool = False) -> None:
        payload = {"chat_id": chat_id, "text": text[:4000]}
        if html:
            payload["parse_mode"] = "HTML"
            payload["link_preview_options"] = {"is_disabled": True}
        if rows:
            payload["reply_markup"] = reply_keyboard(rows) if reply else keyboard(rows)
        await self.tg("sendMessage", payload)

    async def screen(self, ctx: Ctx, text: str, rows=None) -> None:
        """Show an HTML screen. From an inline button the tapped message is edited in place
        (single-window navigation); otherwise, or when Telegram refuses the edit, a new message is sent."""
        if ctx.message_id and ctx.callback_id:
            payload = {"chat_id": ctx.chat_id, "message_id": ctx.message_id, "text": text[:4000], "parse_mode": "HTML",
                       "link_preview_options": {"is_disabled": True}}
            if rows:
                payload["reply_markup"] = keyboard(rows)
            try:
                await self.tg("editMessageText", payload)
                return
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 400:
                    raise  # transient: let the runner retry the update
                try:
                    reason = str(exc.response.json().get("description", ""))
                except ValueError:
                    reason = ""
                if "not modified" in reason:
                    return  # same content: nothing to do
                # message is a photo / too old to edit -> fall through to a fresh message
        await self.send(ctx.chat_id, text, rows, html=True)

    async def send_photo(self, chat_id, png: bytes, caption: str, rows=None) -> None:
        data = {"chat_id": str(chat_id), "caption": caption[:1024], "parse_mode": "HTML"}
        if rows:
            data["reply_markup"] = json.dumps(keyboard(rows))
        r = await self.client.post(f"https://api.telegram.org/bot{self.token}/sendPhoto", data=data, files={"photo": ("qr.png", png, "image/png")})
        r.raise_for_status()

    async def send_main_menu(self, chat_id, text: str) -> None:
        await self.send(chat_id, text, MAIN_MENU, reply=True)

    async def api(self, ctx: Ctx, method: str, path: str, **kw) -> dict | list:
        headers = {"Authorization": f"Bearer {ctx.pair['access_token']}", "Accept": "application/json", **kw.pop("headers", {})}
        r = await self.client.request(method, f"{self.core}{path}", headers=headers, **kw)
        if r.status_code >= 500:
            r.raise_for_status()  # transient: let the runner retry the update
        if r.status_code >= 400:
            raise CoreError(r.status_code, self._err(r))
        return r.json()

    @staticmethod
    def _err(r: httpx.Response) -> str:
        try:
            d = r.json()
            e = d.get("error", d) if isinstance(d, dict) else {}
            m = e.get("message") or d.get("detail")
            if isinstance(m, str):
                return m
        except Exception:  # noqa: BLE001
            pass
        return "درخواست انجام نشد." if r.status_code != 403 else "شما به این بخش دسترسی ندارید."

    # ---------- identity ----------
    async def store_info(self) -> dict:
        if self.store is None:
            r = await self.client.get(f"{self.core}/api/v1/stores/main")
            r.raise_for_status()
            self.store = r.json()
        return self.store

    async def core_login(self, message: dict, referral: str | None = None) -> dict:
        user = message.get("_telegram_from") or message.get("from") or {}
        store = await self.store_info()
        body = {
            "telegram_id": user["id"], "first_name": user.get("first_name"), "last_name": user.get("last_name"),
            "username": user.get("username"), "language_code": user.get("language_code"), "store_id": store["id"],
        }
        if referral:
            body["referral_code"] = referral
        r = await self.client.post(f"{self.core}/api/v1/auth/telegram/bot", headers={"X-Bot-Secret": self.secret, "Accept": "application/json"}, json=body)
        r.raise_for_status()
        return r.json()

    # ---------- dispatch ----------
    async def handle(self, update: dict) -> None:
        message = update.get("message")
        callback = update.get("callback_query")
        if callback:
            await self.tg("answerCallbackQuery", {"callback_query_id": callback["id"]})
            message = callback.get("message")
            if message is not None:
                message = {**message, "_telegram_from": callback.get("from") or {}}
        if not message or not message.get("chat"):
            return
        text = (message.get("text") or "").strip()
        arg = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
        referral = arg[4:] if text.lower().startswith("/start") and arg.startswith("ref_") else None
        pair = await self.core_login(message, referral)
        user = message.get("_telegram_from") or message.get("from") or {}
        ctx = Ctx(message["chat"]["id"], user, pair, update["update_id"], callback["id"] if callback else None,
                  message.get("message_id") if callback else None)
        try:
            if callback:
                prefix, _, rest = (callback.get("data") or "").partition(":")
                fn = self.callbacks.get(prefix)
                await (fn(ctx, rest) if fn else self.send(ctx.chat_id, "گزینه نامعتبر است."))
            elif message.get("photo") or message.get("document"):
                await self.on_file(ctx, message)
            elif text.startswith("/"):
                cmd = text.split(maxsplit=1)[0].split("@")[0].lower()
                fn = self.commands.get(cmd)
                await (fn(ctx, arg) if fn else self.send(ctx.chat_id, "فرمان شناخته نشد. /help را بفرستید."))
            elif text:
                await self.on_text(ctx, text)
        except CoreError as exc:
            await self.send(ctx.chat_id, f"⚠️ {exc.message}")

    async def on_text(self, ctx: Ctx, text: str) -> None:
        st = self.state.get(str(ctx.chat_id)) or {}
        main = {
            "🛒 خرید اکانت": self.cmd_plans,
            "🔍 استعلام و تمدید اکانت": self.cmd_accounts,
            "💰 کیف پول و شارژ حساب": self.cmd_wallet,
            "👤 حساب کاربری": self.cmd_me,
            "🎁 دعوت از دوستان": self.cmd_referral,
            "🧪 دریافت اکانت تست": self.cmd_test,
            "📜 قوانین خرید و آموزش": self.cmd_rules,
            "🎧 پشتیبانی": self.cmd_support,
            "🤖 درخواست ربات نماینده و همکاری": self.cmd_reseller,
        }
        if text in main:
            self._set_state(ctx.chat_id, None)
            await main[text](ctx, "")
        elif st.get("topup_amount"):
            digits = "".join(ch for ch in text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")) if ch.isdigit())
            if not digits or int(digits) <= 0:
                return await self.send(ctx.chat_id, "مبلغ نامعتبر است. فقط عدد (به تومان) وارد کنید:")
            self._set_state(ctx.chat_id, None)
            await self.create_topup(ctx, int(digits))
        elif st.get("coupon_for"):
            pid = st["coupon_for"]
            # One-shot: clear first so a rejected code or an insufficient balance
            # never leaves the next free-text message to be read as a coupon again.
            self._merge_state(ctx.chat_id, coupon_for=None)
            await self.show_quote(ctx, pid, coupon=text.strip().upper())
        elif self._flow(ctx).get("ask"):
            await self.set_account_name(ctx, self._flow(ctx)["ask"], text.strip())
        elif st.get("reply_ticket"):
            await self.api(ctx, "POST", f"/api/v1/tickets/{st['reply_ticket']}/messages", json={"body": text})
            self._set_state(ctx.chat_id, None)
            await self.send(ctx.chat_id, "✅ پیام شما ثبت شد؛ پاسخ پشتیبانی همین‌جا به شما اطلاع داده می‌شود.", [[("📂 مشاهدهٔ تیکت", f"ticket:{st['reply_ticket']}")], [("🎫 همهٔ تیکت‌ها", "menu:tickets")]])
        elif st.get("edit_msg"):
            tid, mid = st["edit_ticket"], st["edit_msg"]
            await self.api(ctx, "PATCH", f"/api/v1/tickets/{tid}/messages/{mid}", json={"body": text})
            self._set_state(ctx.chat_id, None)
            await self.send(ctx.chat_id, "✏️ پیام ویرایش شد.", [[("📂 مشاهدهٔ تیکت", f"ticket:{tid}")]])
        elif st.get("edit_subject"):
            tid = st["edit_subject"]
            await self.api(ctx, "PATCH", f"/api/v1/tickets/{tid}", json={"subject": text.strip()[:200]})
            self._set_state(ctx.chat_id, None)
            await self.send(ctx.chat_id, "📝 موضوع تیکت ویرایش شد.", [[("📂 مشاهدهٔ تیکت", f"ticket:{tid}")]])
        elif st.get("new_ticket_ask_subject"):
            subject = text.strip()
            if len(subject) < 2:
                return await self.send(ctx.chat_id, "موضوع خیلی کوتاه است. یک عنوان کوتاه و روشن بفرستید:")
            self._set_state(ctx.chat_id, {"new_ticket_subject": subject[:200]})
            await self.send(ctx.chat_id, "حالا توضیحات کامل مشکل یا درخواست خود را بفرستید:")
        elif st.get("new_ticket_subject"):
            store = await self.store_info()
            t = await self.api(ctx, "POST", f"/api/v1/stores/{store['id']}/tickets", json={"subject": st["new_ticket_subject"], "body": text})
            self._set_state(ctx.chat_id, None)
            await self.send(ctx.chat_id, f"✅ تیکت شما با شماره <b>#{esc(t.get('number') or '-')}</b> ثبت شد.\nپاسخ پشتیبانی همین‌جا به شما اطلاع داده می‌شود.", [[("📂 مشاهدهٔ تیکت", f"ticket:{t['id']}")], [("🎫 همهٔ تیکت‌ها", "menu:tickets")]], html=True)
        else:
            await self.send_main_menu(ctx.chat_id, "از منوی زیر انتخاب کنید:")

    async def on_file(self, ctx: Ctx, message: dict) -> None:
        st = self.state.get(str(ctx.chat_id)) or {}
        pid = st.get("receipt_payment")
        if not pid:
            return await self.send(ctx.chat_id, "ابتدا با /topup مبلغ یک درخواست شارژ بسازید، سپس رسید را بفرستید.")
        if message.get("photo"):
            file_id, ctype = message["photo"][-1]["file_id"], "image/jpeg"
        else:
            doc = message["document"]
            file_id, ctype = doc["file_id"], doc.get("mime_type") or mimetypes.guess_type(doc.get("file_name", ""))[0] or "application/octet-stream"
        info = await self.tg("getFile", {"file_id": file_id})
        max_bytes = int(os.getenv("MELORIN_MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))
        if int(info.get("file_size") or 0) > max_bytes:
            return await self.send(ctx.chat_id, "حجم فایل بیشتر از حد مجاز است.")
        dl = await self.client.get(f"https://api.telegram.org/file/bot{self.token}/{info['file_path']}")
        dl.raise_for_status()
        if len(dl.content) > max_bytes:
            return await self.send(ctx.chat_id, "حجم فایل بیشتر از حد مجاز است.")
        await self.api(ctx, "POST", f"/api/v1/payments/{pid}/receipt", files={"file": ("receipt", dl.content, ctype)})
        self._set_state(ctx.chat_id, None)
        await self.send(ctx.chat_id, "رسید دریافت شد ✅ پس از تأیید، کیف پول شما شارژ می‌شود.")

    # ---------- commands ----------
    async def cmd_start(self, ctx, arg):
        if arg.startswith("link_"):
            return await self.cmd_link(ctx, arg[5:])
        store = await self.store_info()
        await self.send_main_menu(ctx.chat_id, f"به {store.get('name', 'ملورین')} خوش آمدید 👋\nاز منوی زیر شروع کنید.")
        await self.cmd_home(ctx, "")

    async def cmd_home(self, ctx, arg):
        """Dashboard card: wallet balance + account count + quick actions (skipped silently on any Core error)."""
        try:
            store = await self.store_info()
            w = await self.api(ctx, "GET", f"/api/v1/stores/{store['id']}/wallet")
            accounts = await self.api(ctx, "GET", "/api/v1/vpn-accounts")
        except CoreError:
            return
        active = sum(1 for a in accounts if a.get("status") == "active")
        name = ctx.user.get("first_name") or "دوست عزیز"
        text = (f"سلام {esc(name)} 👋\n\n💰 موجودی کیف پول: <b>{esc(fmt(w['balance'], w['currency']))}</b>\n"
                f"🔑 اکانت‌های فعال: <b>{active}</b> از {len(accounts)}")
        await self.screen(ctx, text, [[("🛒 خرید اکانت", "menu:plans"), ("🔑 اکانت‌های من", "menu:accounts")],
                                      [("💰 کیف پول", "menu:wallet"), ("📦 سفارش‌ها", "menu:orders")]])

    async def cmd_help(self, ctx, arg):
        await self.send(ctx.chat_id, HELP, MENU)

    async def cmd_me(self, ctx, arg):
        me = await self.api(ctx, "GET", "/api/v1/me")
        who = me.get("display_name") or me.get("email") or me["id"]
        await self.screen(ctx, f"👤 <b>حساب کاربری</b>\n\nنام: {esc(who)}\nکد دعوت: <code>{esc(me.get('referral_code', '-'))}</code>",
                          [[("💰 کیف پول", "menu:wallet"), ("🔑 اکانت‌ها", "menu:accounts")]])

    async def cmd_link(self, ctx, arg):
        code = arg.strip()
        if not code:
            return await self.send(ctx.chat_id, "کد اتصال را از بخش «پروفایل» وبسایت بگیرید و به‌صورت /link کد بفرستید.")
        r = await self.client.post(f"{self.core}/api/v1/auth/telegram/link", headers={"X-Bot-Secret": self.secret, "Accept": "application/json"},
                                   json={"code": code, "telegram_id": ctx.user["id"], "first_name": ctx.user.get("first_name"), "last_name": ctx.user.get("last_name"), "username": ctx.user.get("username")})
        if r.status_code >= 500:
            r.raise_for_status()
        await self.send(ctx.chat_id, "حساب تلگرام به حساب وب شما متصل شد ✅" if r.status_code < 400 else f"⚠️ {self._err(r)}")

    async def cb_noop(self, ctx, _):
        return None

    # ----- shop: pool -> (location) -> packages -> (username) -> quote -> pay -----
    def _merge_state(self, chat_id, **kw) -> None:
        """Update keys of the per-chat state without wiping the rest (None removes a key)."""
        st = dict(self.state.get(str(chat_id)) or {})
        for k, v in kw.items():
            if v is None:
                st.pop(k, None)
            else:
                st[k] = v
        self._set_state(chat_id, st or None)

    def _flow(self, ctx) -> dict:
        return (self.state.get(str(ctx.chat_id)) or {}).get("flow") or {}

    async def pools(self) -> list:
        store = await self.store_info()
        r = await self.client.get(f"{self.core}/api/v1/stores/{store['id']}/pools")
        r.raise_for_status()
        return r.json()

    async def cmd_plans(self, ctx, arg):
        self._merge_state(ctx.chat_id, flow=None, coupon=None, coupon_for=None)
        pools = await self.pools()
        if not pools:
            return await self.screen(ctx, "فعلاً سرویسی برای فروش موجود نیست.", [[("↩︎ بازگشت", "menu:home")]])
        if len(pools) == 1:
            return await self.choose_pool(ctx, pools[0], multi=False)
        rows = [[(f"{KIND_BADGE.get(p.get('connection_kind'), '')} · {p['name']}".strip(" ·"), f"pool:{p['id']}")] for p in pools]
        rows.append([("↩︎ بازگشت", "menu:home")])
        await self.screen(ctx, "🛒 <b>خرید اکانت</b>\nنوع سرویس را انتخاب کنید:", rows)

    async def choose_pool(self, ctx, pool, *, multi: bool):
        flow = {"pool": pool["id"], "pname": pool["name"], "naming": pool.get("naming_mode") or "automatic", "multi": multi}
        self._merge_state(ctx.chat_id, flow=flow, coupon=None, coupon_for=None)
        panels = pool.get("panels") or []
        if not panels:
            return await self.show_plans(ctx, 0)
        rows = [[(str(x["label"]), f"pnl:{x['id']}")] for x in panels]
        rows.append([("↩︎ بازگشت", "menu:plans" if multi else "menu:home")])
        await self.screen(ctx, "📍 یکی از گزینه‌ها را انتخاب کنید:", rows)

    async def cb_pool(self, ctx, pool_id):
        pool = next((p for p in await self.pools() if p["id"] == pool_id), None)
        if pool is None:
            return await self.cmd_plans(ctx, "")
        await self.choose_pool(ctx, pool, multi=True)

    async def cb_panel(self, ctx, panel_id):
        flow = self._flow(ctx)
        pool = next((p for p in await self.pools() if p["id"] == flow.get("pool")), None)
        panel = next((x for x in (pool or {}).get("panels") or [] if x["id"] == panel_id), None)
        if panel is None:
            return await self.cmd_plans(ctx, "")
        self._merge_state(ctx.chat_id, flow={**flow, "panel": panel["id"], "plabel": panel["label"]})
        await self.show_plans(ctx, 0)

    async def cb_plans(self, ctx, page):
        await self.show_plans(ctx, int(page) if page.isdigit() else 0)

    async def show_plans(self, ctx, page: int, *, renew: str | None = None):
        flow = self._flow(ctx)
        if renew:
            items = await self.api(ctx, "GET", f"/api/v1/stores/{(await self.store_info())['id']}/accounts/{unb64(renew)}/renewal-packages")
        elif not flow.get("pool"):
            return await self.cmd_plans(ctx, "")
        else:
            store = await self.store_info()
            r = await self.client.get(f"{self.core}/api/v1/stores/{store['id']}/pools/{flow['pool']}/packages")
            r.raise_for_status()
            items = r.json()
        if not items:
            return await self.screen(ctx, "فعلاً سرویسی برای فروش موجود نیست.", [[("↩︎ بازگشت", f"account:{unb64(renew)}" if renew else "menu:home")]])
        pages = max(1, -(-len(items) // PAGE_SIZE))
        page = min(max(page, 0), pages - 1)
        chunk = items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
        pick = (lambda pid: f"rnq:{renew}:{b64(pid)}") if renew else (lambda pid: f"plan:{pid}")
        rows = [[(f"{p['name']} · {fmt(p['price'], p['currency'])}", pick(p["product_id"]))] for p in chunk]
        if pages > 1 and not renew:
            rows.append([("‹ قبلی", f"plans:{page - 1}") if page else ("·", "noop"), (f"{page + 1}/{pages}", "noop"),
                         ("بعدی ›", f"plans:{page + 1}") if page < pages - 1 else ("·", "noop")])
        if renew:
            rows.append([("↩︎ بازگشت به اکانت", f"account:{unb64(renew)}")])
        else:
            rows.append([("↩︎ بازگشت", f"pool:{flow['pool']}" if flow.get("panel") else "menu:plans" if flow.get("multi") else "menu:home")])
        head = f"\n📦 {esc(flow.get('pname'))}" if flow.get("pname") and not renew else ""
        title = "🔄 <b>تمدید اکانت</b>\nسرویس موردنظر برای تمدید را انتخاب کنید:" if renew else f"🛒 <b>خرید اکانت</b>{head}\nیک سرویس انتخاب کنید:"
        await self.screen(ctx, title, rows)

    async def cb_plan(self, ctx, pid):
        flow = self._flow(ctx)
        self._merge_state(ctx.chat_id, coupon=None, coupon_for=None)
        if flow.get("naming") == "custom":
            self._merge_state(ctx.chat_id, flow={**flow, "name": None, "ask": pid})
            return await self.screen(ctx, "✍️ نام کاربری دلخواه اکانت را بفرستید (حداقل ۳ حرف انگلیسی/عدد/_/-):", [[("↩︎ بازگشت", "plans:0")]])
        await self.show_quote(ctx, pid)

    async def set_account_name(self, ctx, pid, text: str):
        name = re.sub(r"[^A-Za-z0-9_-]", "", text)[:40]
        if len(name) < 3:
            return await self.send(ctx.chat_id, "نام نامعتبر است. حداقل ۳ حرف انگلیسی/عدد/_/- بفرستید:")
        self._merge_state(ctx.chat_id, flow={**self._flow(ctx), "name": name, "ask": None})
        await self.show_quote(ctx, pid)

    async def cb_quote(self, ctx, pid):
        await self.show_quote(ctx, pid)

    def _alloc(self, ctx) -> dict:
        f = self._flow(ctx)
        body = {"panel_group_id": f["pool"]} if f.get("pool") else {}
        if f.get("panel"):
            body["selected_panel_id"] = f["panel"]
        return body

    async def show_quote(self, ctx, pid, *, coupon: str | None = None, renew: str | None = None):
        """One card: what you buy, price, discount, wallet balance BEFORE and AFTER, and the right next button."""
        store = await self.store_info()
        flow = {} if renew else self._flow(ctx)
        body = {"product_id": pid, "vpn_account_id": unb64(renew)} if renew else {"product_id": pid, **self._alloc(ctx)}
        if coupon:
            body["coupon_code"] = coupon
        q = await self.api(ctx, "POST", f"/api/v1/stores/{store['id']}/checkout/quote", json=body)
        c = q["currency"]
        lines = ["🔄 <b>تمدید اکانت</b>" if renew else "🧾 <b>پیش‌فاکتور</b>", ""]
        if flow.get("pname"):
            lines.append(f"📦 سرویس: {esc(flow['pname'])}")
        if flow.get("plabel"):
            lines.append(f"📍 {esc(flow['plabel'])}")
        if flow.get("name"):
            lines.append(f"👤 نام کاربری: <code>{esc(flow['name'])}</code>")
        lines.append(f"💵 قیمت: {esc(fmt(q['unit_price'], c))}")
        if q.get("discount"):
            tag = f" ({esc(q.get('coupon_code'))})" if q.get("coupon_code") else ""
            lines.append(f"🏷 تخفیف{tag}: {esc(fmt(q['discount'], c))}")
        lines.append(f"💰 مبلغ نهایی: <b>{esc(fmt(q['total'], c))}</b>")
        balance = int(q.get("wallet_balance") or 0)
        lines += ["", f"👛 موجودی کیف پول: {esc(fmt(balance, c))}"]
        if q.get("sufficient_funds"):
            lines.append(f"📉 موجودی پس از پرداخت: <b>{esc(fmt(balance - int(q['total']), c))}</b>")
            if coupon:
                self._merge_state(ctx.chat_id, coupon={"pid": str(pid), "code": coupon})
            go = f"rnb:{renew}:{b64(pid)}" if renew else f"buy:{pid}"
            rows = [[("✅ تأیید و پرداخت از کیف پول", go)]]
        else:
            short = int(q["total"]) - balance
            lines.append(f"⚠️ موجودی کافی نیست؛ <b>{esc(fmt(short, c))}</b> کم دارید.")
            rows = [[(f"💳 شارژ {fmt(short, c)}", f"wallet:amount:{short}")]]
        if not renew:
            rows.append([("🎟 کد تخفیف", f"cpn:{pid}")])
        rows.append([("↩︎ بازگشت", f"rnw:{renew}" if renew else "plans:0")])
        await self.screen(ctx, "\n".join(lines), rows)

    async def cb_coupon(self, ctx, pid):
        self._merge_state(ctx.chat_id, coupon_for=pid)
        await self.screen(ctx, "🎟 کد تخفیف را بفرستید:", [[("↩︎ بازگشت", f"qt:{pid}")]])

    def _coupon_for(self, ctx, pid) -> str | None:
        c = (self.state.get(str(ctx.chat_id)) or {}).get("coupon") or {}
        return c.get("code") if c.get("pid") == str(pid) else None

    async def cb_buy(self, ctx, pid):
        store = await self.store_info()
        flow = self._flow(ctx)
        body = {"product_id": pid, "payment_method": "wallet", "kind": "purchase", **self._alloc(ctx)}
        if flow.get("naming") == "custom" and flow.get("name"):
            body["account_name"] = flow["name"]
        if self._coupon_for(ctx, pid):
            body["coupon_code"] = self._coupon_for(ctx, pid)
        o = await self.api(ctx, "POST", f"/api/v1/stores/{store['id']}/orders", headers={"Idempotency-Key": ctx.idem}, json=body)
        self._set_state(ctx.chat_id, None)
        await self.order_done(ctx, o, "✅ <b>پرداخت از کیف پول انجام شد</b>")

    async def order_done(self, ctx, o, title: str):
        paid = f"\n💰 مبلغ پرداختی: {esc(fmt(o['total'], o.get('currency')))}" if o.get("total") is not None else ""
        await self.screen(ctx, f"{title}\n\n📦 سفارش: <code>{esc(o['number'])}</code>{paid}\n"
                               "⚙️ اکانت شما در چند لحظه ساخته و همین‌جا ارسال می‌شود "
                               "(لینک اشتراک، QR کد و موجودی کیف پول).", [[("🔑 اکانت‌های من", "menu:accounts")]])

    # ----- wallet -----
    async def cmd_wallet(self, ctx, arg):
        store = await self.store_info()
        w = await self.api(ctx, "GET", f"/api/v1/stores/{store['id']}/wallet")
        tx = await self.api(ctx, "GET", f"/api/v1/stores/{store['id']}/wallet/transactions")
        items = tx if isinstance(tx, list) else tx.get("items", [])
        lines = [f"💰 <b>کیف پول</b>\n\nموجودی: <b>{esc(fmt(w['balance'], w['currency']))}</b>"]
        if items:
            lines.append("\n🕘 آخرین تراکنش‌ها:")
            for t in items[:5]:
                amt = int(t["amount"])
                lines.append(f"{TX_KIND.get(t['kind'], esc(t['kind']))}  {'➕' if amt > 0 else '➖'} {money(abs(amt))}")
        lines.append("\nبرای شارژ، مبلغ را انتخاب کنید:")
        amounts = [[("۲۰۰,۰۰۰ تومان", "wallet:amount:200000"), ("۵۰۰,۰۰۰ تومان", "wallet:amount:500000")],
                   [("۱,۰۰۰,۰۰۰ تومان", "wallet:amount:1000000"), ("✏️ مبلغ دلخواه", "wallet:amount:custom")]]
        await self.screen(ctx, "\n".join(lines), amounts)

    async def cb_wallet_amount(self, ctx, value):
        # Callback data is split once in handle(), so this receives
        # "amount:200000" or "amount:custom", not just the suffix.
        prefix, _, raw = value.partition(":")
        if prefix != "amount":
            raise CoreError(400, "گزینه شارژ نامعتبر است. دوباره از منوی کیف پول انتخاب کنید.")
        if raw == "custom":
            self._set_state(ctx.chat_id, {"topup_amount": True})
            return await self.send(ctx.chat_id, "مبلغ دلخواه را به تومان وارد کنید (فقط عدد):")
        if not re.fullmatch(r"\d+", raw) or int(raw) <= 0:
            raise CoreError(400, "مبلغ شارژ نامعتبر است.")
        await self.create_topup(ctx, int(raw))

    async def create_topup(self, ctx, amount):
        store = await self.store_info()
        p = await self.api(ctx, "POST", f"/api/v1/stores/{store['id']}/wallet/topups", headers={"Idempotency-Key": f"{ctx.idem}-topup"}, json={"amount": amount, "provider": "manual_card"})
        ins = p.get("instructions") or {}
        lines = [f"💳 <b>درخواست شارژ {esc(fmt(p['amount'], p['currency']))} ثبت شد</b>", ""]
        if ins.get("card_number"):
            lines += ["شماره کارت (برای کپی لمس کنید):", f"<code>{esc(ins['card_number'])}</code>",
                      f"به نام: {esc(ins.get('holder', '-'))}", f"بانک: {esc(ins.get('bank', '-'))}"]
        if ins.get("redirect_url"):
            lines.append(f"🌐 پرداخت آنلاین: {esc(ins['redirect_url'])}")
        else:
            lines += ["", "📸 پس از واریز، عکس رسید را همین‌جا بفرستید."]
            self._set_state(ctx.chat_id, {"receipt_payment": p["id"]})
        await self.send(ctx.chat_id, "\n".join(lines), html=True)

    async def cmd_topup(self, ctx, arg):
        digits = "".join(ch for ch in arg.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")) if ch.isdigit())
        if not digits or int(digits) <= 0:
            return await self.send(ctx.chat_id, "مبلغ را وارد کنید. مثال: /topup 100000")
        await self.create_topup(ctx, int(digits))

    # ----- accounts: list -> card (usage bar, link) -> QR / renew -----
    async def cmd_accounts(self, ctx, arg):
        rows = await self.api(ctx, "GET", "/api/v1/vpn-accounts")
        if not rows:
            return await self.screen(ctx, "🔑 هنوز اکانتی ندارید.", [[("🛒 خرید اکانت", "menu:plans")], [("🧪 دریافت اکانت تست", "menu:test")]])
        buttons = []
        for a in rows[:20]:
            d = parse_dt(a.get("expires_at"))
            left = f" · {(d - dt.datetime.now(dt.UTC)).days}ر" if d else ""
            buttons.append([(f"{ACCOUNT_STATUS.get(a['status'], '•').split()[0]} {a['username']}{left}", f"account:{a['id']}")])
        await self.screen(ctx, "🔑 <b>اکانت‌های من</b>\nبرای مشاهده، تمدید یا QR کد یکی را انتخاب کنید:", buttons)

    async def _find_account(self, ctx, account_id):
        rows = await self.api(ctx, "GET", "/api/v1/vpn-accounts")
        return next((a for a in rows if str(a.get("id")) == str(account_id)), None)

    async def cb_account(self, ctx, value):
        account = await self._find_account(ctx, value)
        if not account:
            return await self.screen(ctx, "این اکانت دیگر در دسترس نیست.", [[("↩︎ بازگشت", "menu:accounts")]])
        link = account.get("subscription_url")
        lines = [f"👤 <b>{esc(account.get('username', '-'))}</b>", f"وضعیت: {ACCOUNT_STATUS.get(account['status'], esc(account['status']))}",
                 expiry_line(account.get("expires_at")), "", f"📊 {usage_bar(account.get('traffic_used_bytes'), account.get('traffic_limit_bytes'))}"]
        lines += ["", "🔗 لینک اشتراک (برای کپی لمس کنید):", f"<code>{esc(link)}</code>"] if link else ["", "🔗 لینک در حال آماده‌سازی است."]
        action = []
        if link:
            action.append(("📷 QR کد", f"qr:{b64(account['id'])}"))
        if not account.get("is_test") and account["status"] in ("active", "expired", "suspended"):
            action.append(("🔄 تمدید", f"rnw:{b64(account['id'])}"))
        rows = ([action] if action else []) + [[("↩︎ بازگشت", "menu:accounts")]]
        await self.screen(ctx, "\n".join(lines), rows)

    async def cb_qr(self, ctx, token):
        account = await self._find_account(ctx, unb64(token))
        link = (account or {}).get("subscription_url")
        if not link:
            raise CoreError(404, "لینک اشتراک این اکانت هنوز آماده نیست.")
        png = qr_png(link)
        caption = f"📷 QR کد اشتراک <b>{esc(account['username'])}</b>\n\n<code>{esc(link)}</code>"
        if png:
            await self.send_photo(ctx.chat_id, png, caption)
        else:
            await self.send(ctx.chat_id, f"🔗 <code>{esc(link)}</code>", html=True)

    async def cb_renew(self, ctx, token):
        unb64(token)  # validate early
        await self.show_plans(ctx, 0, renew=token)

    async def cb_renew_quote(self, ctx, rest):
        acc, _, pid = rest.partition(":")
        unb64(acc)
        await self.show_quote(ctx, unb64(pid), renew=acc)

    async def cb_renew_buy(self, ctx, rest):
        acc, _, pid = rest.partition(":")
        store = await self.store_info()
        o = await self.api(ctx, "POST", f"/api/v1/stores/{store['id']}/orders", headers={"Idempotency-Key": ctx.idem},
                           json={"product_id": unb64(pid), "payment_method": "wallet", "kind": "renewal", "vpn_account_id": unb64(acc)})
        await self.order_done(ctx, o, "✅ <b>تمدید با کیف پول پرداخت شد</b>")

    async def cmd_test(self, ctx, arg):
        store = await self.store_info()
        o = await self.api(ctx, "POST", f"/api/v1/stores/{store['id']}/test-account")
        await self.send(ctx.chat_id, f"🧪 اکانت تست ساخته شد ({o['number']}). لینک و QR کد همین‌جا ارسال می‌شود.")

    async def cmd_orders(self, ctx, arg):
        store = await self.store_info()
        os_ = await self.api(ctx, "GET", f"/api/v1/stores/{store['id']}/orders")
        lines = [f"🧾 <code>{esc(o['number'])}</code> · {esc(fmt(o['total'], o['currency']))} · {ORDER_STATUS.get(o['status'], esc(o['status']))}" for o in os_[:10]]
        await self.screen(ctx, "📦 <b>سفارش‌ها</b>\n\n" + ("\n".join(lines) or "هنوز سفارشی ندارید."), [[("🛒 خرید اکانت", "menu:plans")]])

    # ----- engagement / support -----
    async def cmd_referral(self, ctx, arg):
        data = await self.api(ctx, "GET", "/api/v1/me/referrals")
        bot = await self.tg("getMe", {})
        username = bot.get("username", "MelorinBot")
        count = data.get("referred_count", data.get("count", data.get("total", 0)))
        code = data.get("referral_code") or ctx.user["id"]
        await self.send(ctx.chat_id, f"🎁 <b>دعوت از دوستان</b>\n\nلینک اختصاصی شما:\nhttps://t.me/{esc(username)}?start=ref_{esc(code)}\n\nتعداد زیرمجموعه‌ها: <b>{count}</b>", html=True)

    async def cmd_rules(self, ctx, arg):
        await self.send(ctx.chat_id, "📜 قوانین خرید:\n\n۱. پس از خرید امکان بازگشت وجه وجود ندارد مگر در صورت خرابی سرویس.\n۲. اکانت‌ها فقط برای استفاده‌ی شخصی هستند.\n۳. برای هرگونه مشکل با پشتیبانی در تماس باشید.")

    async def cmd_support(self, ctx, arg):
        self._set_state(ctx.chat_id, {"new_ticket_subject": "پشتیبانی تلگرام"})
        await self.send(ctx.chat_id, "🎧 پیام خود را برای پشتیبانی بنویسید:")

    async def cmd_reseller(self, ctx, arg):
        self._set_state(ctx.chat_id, {"new_ticket_subject": "🤖 درخواست ربات نماینده و همکاری"})
        await self.send(ctx.chat_id, "📌 توضیحات خود را برای ثبت درخواست نمایندگی ارسال نمایید.")

    async def cmd_tickets(self, ctx, arg):
        store = await self.store_info()
        ts = await self.api(ctx, "GET", f"/api/v1/stores/{store['id']}/tickets")
        rows = [[(f"{TICKET_ICON.get(t['status'], '⚪')} #{t.get('number') or '-'} · {t['subject'][:28]}", f"ticket:{t['id']}")] for t in ts[:10]]
        rows.append([("➕ تیکت جدید", "tnew:1")])
        head = "🎫 <b>تیکت‌های شما</b>\n🟡 باز   🟢 پاسخ داده شد   ⚫ بسته" if ts else "🎫 هنوز تیکتی ثبت نکرده‌اید."
        await self.screen(ctx, head, rows)

    async def cmd_ticket(self, ctx, arg):
        subject, _, body = arg.partition("|")
        if len(subject.strip()) < 2 or not body.strip():
            return await self.send(ctx.chat_id, "قالب: /ticket موضوع | متن پیام\nیا از /tickets دکمهٔ «تیکت جدید» را بزنید.")
        store = await self.store_info()
        t = await self.api(ctx, "POST", f"/api/v1/stores/{store['id']}/tickets", json={"subject": subject.strip(), "body": body.strip()})
        await self.send(ctx.chat_id, f"تیکت «{t['subject']}» با شمارهٔ #{t.get('number') or '-'} ثبت شد ✅")

    async def cb_ticket_new(self, ctx, _):
        self._set_state(ctx.chat_id, {"new_ticket_ask_subject": True})
        await self.send(ctx.chat_id, "➕ <b>تیکت جدید</b>\nموضوع تیکت را بفرستید (مثلاً: اتصال برقرار نمی‌شود):", html=True)

    async def cb_ticket(self, ctx, tid):
        t = await self.api(ctx, "GET", f"/api/v1/tickets/{tid}")
        ms = await self.api(ctx, "GET", f"/api/v1/tickets/{tid}/messages")
        lines = []
        for m in ms[-5:]:
            who = "🎧 پشتیبانی" if m["is_staff"] else "👤 شما"
            edited = "  <i>(ویرایش‌شده)</i>" if m.get("edited_at") else ""
            lines.append(f"<b>{who}</b>{edited}\n{esc(m['body'][:600])}")
        hidden = f"<i>… {len(ms) - 5} پیام قبلی</i>\n\n" if len(ms) > 5 else ""
        head = f"🎫 <b>#{esc(t.get('number') or '-')}</b> · {esc(t['subject'])}\nوضعیت: {TICKET_LABEL.get(t['status'], t['status'])}"
        if t.get("priority") in ("high", "urgent"):
            head += f"  ·  اولویت: {PRIORITY_LABEL[t['priority']]}"
        closed = t["status"] == "closed"
        rows = [[("🔓 بازگشایی تیکت", f"treopen:{tid}")]] if closed else [[("✍️ پاسخ", f"reply:{tid}"), ("✏️ ویرایش پیام من", f"tedit:{tid}")], [("📝 تغییر موضوع", f"tsubj:{tid}"), ("🔒 بستن تیکت", f"tclose:{tid}")]]
        rows.append([("◀️ همهٔ تیکت‌ها", "menu:tickets")])
        await self.screen(ctx, f"{head}\n━━━━━━━━━━\n{hidden}" + "\n\n".join(lines or ["پیامی نیست."]), rows)

    async def cb_reply(self, ctx, tid):
        self._set_state(ctx.chat_id, {"reply_ticket": tid})
        await self.send(ctx.chat_id, "✍️ متن پاسخ را بفرستید:")

    async def cb_ticket_edit_msg(self, ctx, tid):
        ms = await self.api(ctx, "GET", f"/api/v1/tickets/{tid}/messages")
        mine = [m for m in ms if not m["is_staff"]]
        if not mine:
            return await self.send(ctx.chat_id, "پیامی برای ویرایش وجود ندارد.")
        last = mine[-1]
        self._set_state(ctx.chat_id, {"edit_ticket": tid, "edit_msg": last["id"]})
        await self.send(ctx.chat_id, f"✏️ <b>ویرایش آخرین پیام شما</b>\n\nمتن فعلی:\n<blockquote>{esc(last['body'][:500])}</blockquote>\nمتن جدید را بفرستید:", html=True)

    async def cb_ticket_edit_subject(self, ctx, tid):
        self._set_state(ctx.chat_id, {"edit_subject": tid})
        await self.send(ctx.chat_id, "📝 موضوع جدید تیکت را بفرستید:")

    async def cb_ticket_close(self, ctx, tid):
        await self.api(ctx, "PATCH", f"/api/v1/tickets/{tid}", json={"status": "closed"})
        await self.send(ctx.chat_id, "🔒 تیکت بسته شد. هر زمان خواستید می‌توانید آن را دوباره باز کنید.", [[("📂 مشاهدهٔ تیکت", f"ticket:{tid}")], [("🎫 همهٔ تیکت‌ها", "menu:tickets")]])

    async def cb_ticket_reopen(self, ctx, tid):
        await self.api(ctx, "PATCH", f"/api/v1/tickets/{tid}", json={"status": "open"})
        await self.send(ctx.chat_id, "🔓 تیکت دوباره باز شد.", [[("📂 مشاهدهٔ تیکت", f"ticket:{tid}")]])

    async def cmd_notifications(self, ctx, arg):
        d = await self.api(ctx, "GET", "/api/v1/me/notifications?unread_only=true&limit=10")
        items = d.get("items", [])
        if not items:
            return await self.send(ctx.chat_id, "اعلان جدیدی ندارید.")
        await self.send(ctx.chat_id, "\n\n".join(f"🔔 {n['title']}\n{n['body']}" for n in items), [[("علامت‌گذاری همه", "readall:1")]])

    async def cb_readall(self, ctx, _):
        await self.api(ctx, "POST", "/api/v1/me/notifications/read-all")
        await self.send(ctx.chat_id, "همه اعلان‌ها خوانده شد ✅")

    async def cb_menu(self, ctx, name):
        fn = {"plans": self.cmd_plans, "wallet": self.cmd_wallet, "orders": self.cmd_orders, "accounts": self.cmd_accounts,
              "tickets": self.cmd_tickets, "notifications": self.cmd_notifications, "test": self.cmd_test, "home": self.cmd_home}.get(name)
        await (fn(ctx, "") if fn else self.cmd_help(ctx, ""))

    # ---------- loop ----------
    async def setup_menu(self) -> None:
        try:
            await self.tg("setMyCommands", {"commands": [{"command": c, "description": d} for c, d in BOT_COMMANDS]})
        except (httpx.HTTPError, RuntimeError):  # cosmetic: never block startup on it
            log.warning("setMyCommands failed", exc_info=True)

    async def run(self) -> None:
        await self.setup_menu()
        try:
            while True:
                payload = {"timeout": 25, "allowed_updates": ["message", "callback_query"]}
                if self.offset is not None:
                    payload["offset"] = self.offset
                try:
                    updates = await self.tg("getUpdates", payload)
                    for update in updates:
                        try:
                            await self.handle(update)
                        except (KeyError, ValueError, CoreError):
                            # Malformed/user-level errors are terminal for this update.
                            # Transport/5xx errors escape to the outer retry path, so the
                            # offset is deliberately NOT advanced and the update is replayed.
                            log.exception("dropping malformed update %s", update.get("update_id"))
                        self._save_offset(update["update_id"] + 1)
                except (httpx.HTTPError, RuntimeError) as exc:
                    log.exception("telegram cycle failed: %s", exc)
                    await asyncio.sleep(min(30, 2 ** min(getattr(self, "_failures", 0), 4)))
                    self._failures = getattr(self, "_failures", 0) + 1
                else:
                    self._failures = 0
        finally:
            await self.client.aclose()


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    asyncio.run(TelegramRunner().run())
