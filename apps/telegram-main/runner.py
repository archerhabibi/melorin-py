"""Production Telegram long-poll runner (main store bot).

Telegram is transport only: identity, authorization, pricing, wallet, orders and
tickets stay in Core. Every update is exchanged for a Core session through
``/api/v1/auth/telegram/bot`` (X-Bot-Secret). The offset is persisted so a restart
replays no acknowledged update; order/top-up calls carry an Idempotency-Key derived
from the Telegram update/callback id so a replay can never double-charge.

UX model (v2): inline navigation edits the tapped message in place (one "window" instead of
a growing chat), every screen has a back button, purchase screens show the wallet balance
before and after the payment, and accounts open as cards with usage bar, QR and renewal."""

import asyncio
import logging
import mimetypes
import os
import sys
from pathlib import Path
import httpx

# ``tgmain`` lives next to this file (the reseller supervisor loads this module by path, so make the sibling package importable).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tgmain.client import Ctx, TransportMixin  # noqa: E402,F401
from tgmain.errors import CoreError  # noqa: E402,F401
from tgmain.handlers.identity import IdentityMixin
from tgmain.handlers.plans import PlansMixin
from tgmain.handlers.wallet import WalletMixin
from tgmain.handlers.accounts import AccountsMixin
from tgmain.handlers.reseller import ResellerMixin
from tgmain.handlers.tickets import TicketsMixin
from tgmain.ui import *  # noqa: E402,F401,F403  (re-exported: the reseller runner uses money/keyboard/esc/BOT_COMMANDS)

log = logging.getLogger("melorin.telegram.main")


class TelegramRunner(TransportMixin, IdentityMixin, PlansMixin, WalletMixin, AccountsMixin, ResellerMixin, TicketsMixin):
    """Composition root: wiring (commands/callbacks), update dispatch and the long-poll loop. Feature handlers live in ``tgmain.handlers``."""

    channel = "main"
    # Least-privilege secret for this kind of runner (Core accepts it only for stores of that kind); falls back to the shared one.
    secret_env = "MELORIN_MAIN_BOT_SECRET"

    def __init__(self, *, token: str | None = None, offset_file: str | Path | None = None):
        # ``token`` / ``offset_file`` let one process host several bots (the reseller supervisor) without touching os.environ.
        self.token = token or os.environ["MELORIN_TELEGRAM_TOKEN"]
        self.core = os.environ["MELORIN_CORE_URL"].rstrip("/")
        self.secret = os.environ.get(self.secret_env) or os.environ["MELORIN_BOT_SERVICE_SECRET"]
        self.offset_file = Path(offset_file or os.getenv("MELORIN_TELEGRAM_OFFSET_FILE", "/var/lib/melorin/offset.json"))
        self.offset_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file = self.offset_file.with_name(self.offset_file.stem + "-state.json")
        self.offset = self._load_offset()
        self.state = self._load_state()
        self.store: dict | None = None
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(35.0, connect=10.0))
        self.commands = {
            "/start": self.cmd_start,
            "/help": self.cmd_help,
            "/me": self.cmd_me,
            "/plans": self.cmd_plans,
            "/wallet": self.cmd_wallet,
            "/topup": self.cmd_topup,
            "/orders": self.cmd_orders,
            "/accounts": self.cmd_accounts,
            "/test": self.cmd_test,
            "/tickets": self.cmd_tickets,
            "/ticket": self.cmd_ticket,
            "/notifications": self.cmd_notifications,
            "/link": self.cmd_link,
            "/referral": self.cmd_referral,
            "/reseller": self.cmd_reseller,
            "/cancel": self.cmd_cancel,
        }
        self.callbacks = {
            "menu": self.cb_menu,
            "plan": self.cb_plan,
            "buy": self.cb_buy,
            "ticket": self.cb_ticket,
            "reply": self.cb_reply,
            "readall": self.cb_readall,
            "wallet": self.cb_wallet_amount,
            "account": self.cb_account,
            "acl": self.cb_acc_list,
            "acs": self.cb_acc_search,
            "acq": self.cb_acc_clear,
            "plans": self.cb_plans,
            "cpn": self.cb_coupon,
            "qr": self.cb_qr,
            "bundle": self.cb_bundle,
            "pnl": self.cb_panel,
            "qt": self.cb_quote,
            "an": self.cb_autoname,
            "rnw": self.cb_renew,
            "rnq": self.cb_renew_quote,
            "rnb": self.cb_renew_buy,
            "noop": self.cb_noop,
            "tnew": self.cb_ticket_new,
            "tedit": self.cb_ticket_edit_msg,
            "tsubj": self.cb_ticket_edit_subject,
            "tclose": self.cb_ticket_close,
            "treopen": self.cb_ticket_reopen,
            "rsc": self.cb_reseller_cancel,
            "wla": self.cb_web_login,
            "wld": self.cb_web_login_deny,
        }

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
        try:
            pair = await self.core_login(message, referral)
        except CoreError as exc:
            if exc.code != "ADMIN_USE_PANEL":
                raise
            return await self.send(message["chat"]["id"], ADMIN_NOTICE)  # the admin's alert address: say so instead of staying silent
        user = message.get("_telegram_from") or message.get("from") or {}
        ctx = Ctx(
            message["chat"]["id"],
            user,
            pair,
            update["update_id"],
            callback["id"] if callback else None,
            message.get("message_id") if callback else None,
            None if callback else message.get("message_id"),
        )
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
            ACCOUNT_BUTTON: self.cmd_me,
            LEGACY_ACCOUNT_BUTTON: self.cmd_me,
            "🎁 دعوت از دوستان": self.cmd_referral,
            "🧪 دریافت اکانت تست": self.cmd_test,
            "📜 قوانین خرید و آموزش": self.cmd_rules,
            "🎧 پشتیبانی": self.cmd_support,
            "🤖 درخواست ربات نماینده و همکاری": self.cmd_reseller,
        }
        if text in main:
            self._set_state(ctx.chat_id, None)
            await main[text](ctx, "")
        elif st.get("acc_search"):
            await self.acc_apply_search(ctx, st["acc_search"], text)
        elif st.get("rs"):
            await self.reseller_step(ctx, st, text)
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
            await self.send(
                ctx.chat_id,
                "✅ پیام شما ثبت شد؛ پاسخ پشتیبانی همین‌جا به شما اطلاع داده می‌شود.",
                [[("📂 مشاهدهٔ تیکت", f"ticket:{st['reply_ticket']}")], [("🎫 همهٔ تیکت‌ها", "menu:tickets")]],
            )
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
            t = await self.api(
                ctx, "POST", f"/api/v1/stores/{store['id']}/tickets", json={"subject": st["new_ticket_subject"], "body": text}
            )
            self._set_state(ctx.chat_id, None)
            await self.send(
                ctx.chat_id,
                f"✅ تیکت شما با شماره <b>#{esc(t.get('number') or '-')}</b> ثبت شد.\nپاسخ پشتیبانی همین‌جا به شما اطلاع داده می‌شود.",
                [[("📂 مشاهدهٔ تیکت", f"ticket:{t['id']}")], [("🎫 همهٔ تیکت‌ها", "menu:tickets")]],
                html=True,
            )
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
            file_id, ctype = (
                doc["file_id"],
                doc.get("mime_type") or mimetypes.guess_type(doc.get("file_name", ""))[0] or "application/octet-stream",
            )
        info = await self.tg("getFile", {"file_id": file_id})
        max_bytes = int(os.getenv("MELORIN_MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))
        if int(info.get("file_size") or 0) > max_bytes:
            return await self.send(ctx.chat_id, "حجم فایل بیشتر از حد مجاز است.")
        dl = await self.client.get(f"https://api.telegram.org/file/bot{self.token}/{info['file_path']}")
        dl.raise_for_status()
        if len(dl.content) > max_bytes:
            return await self.send(ctx.chat_id, "حجم فایل بیشتر از حد مجاز است.")
        await self.api(
            ctx,
            "POST",
            f"/api/v1/stores/{(await self.store_info())['id']}/payments/{pid}/receipt",
            files={"file": ("receipt", dl.content, ctype)},
        )
        self._set_state(ctx.chat_id, None)
        await self.send(ctx.chat_id, "رسید دریافت شد ✅ پس از تأیید، کیف پول شما شارژ می‌شود.")

    # ---------- commands ----------
    async def cmd_start(self, ctx, arg):
        if arg.startswith("link_"):
            return await self.cmd_link(ctx, arg[5:])
        if arg.startswith("wl_"):
            return await self.cmd_web_login(ctx, arg[3:])
        store = await self.store_info()
        await self.send_main_menu(ctx.chat_id, f"به {store.get('name', 'ملورین')} خوش آمدید 👋\nاز منوی زیر شروع کنید.")
        await self.cmd_home(ctx, "")

    async def cmd_home(self, ctx, arg):
        """Dashboard card: wallet balance + account count + quick actions (skipped silently on any Core error)."""
        try:
            store = await self.store_info()
            w = await self.api(ctx, "GET", f"/api/v1/stores/{store['id']}/wallet")
            accounts = await self.api(ctx, "GET", f"/api/v1/stores/{store['id']}/vpn-accounts")
        except CoreError:
            return
        active = sum(1 for a in accounts if a.get("status") == "active")
        name = ctx.user.get("first_name") or "دوست عزیز"
        text = (
            f"سلام {esc(name)} 👋\n\n💰 موجودی کیف پول: <b>{esc(fmt(w['balance'], w['currency']))}</b>\n"
            f"🔑 اکانت‌های فعال: <b>{active}</b> از {len(accounts)}"
        )
        await self.screen(
            ctx,
            text,
            [
                [("🛒 خرید اکانت", "menu:plans"), ("🔑 اکانت‌های من", "menu:accounts")],
                [("💰 کیف پول", "menu:wallet"), ("📦 سفارش‌ها", "menu:orders")],
            ],
        )

    async def cmd_help(self, ctx, arg):
        await self.send(ctx.chat_id, HELP, MENU)

    async def cb_noop(self, ctx, _):
        return None

    async def cmd_rules(self, ctx, arg):
        await self.send(
            ctx.chat_id,
            "📜 قوانین خرید:\n\n۱. پس از خرید امکان بازگشت وجه وجود ندارد مگر در صورت خرابی سرویس.\n۲. اکانت‌ها فقط برای استفاده‌ی شخصی هستند.\n۳. برای هرگونه مشکل با پشتیبانی در تماس باشید.",
        )

    async def cmd_support(self, ctx, arg):
        self._set_state(ctx.chat_id, {"new_ticket_subject": "پشتیبانی تلگرام"})
        await self.send(ctx.chat_id, "🎧 پیام خود را برای پشتیبانی بنویسید:")

    async def cmd_cancel(self, ctx, arg):
        self._set_state(ctx.chat_id, None)
        await self.send(ctx.chat_id, "انصراف داده شد.")

    async def cb_menu(self, ctx, name):
        fn = {
            "plans": self.cmd_plans,
            "wallet": self.cmd_wallet,
            "orders": self.cmd_orders,
            "accounts": self.cmd_accounts,
            "tickets": self.cmd_tickets,
            "notifications": self.cmd_notifications,
            "test": self.cmd_test,
            "home": self.cmd_home,
        }.get(name)
        await (fn(ctx, "") if fn else self.cmd_help(ctx, ""))

    # ---------- loop ----------
    async def setup_menu(self) -> None:
        try:
            await self.tg("setMyCommands", {"commands": [{"command": c, "description": d} for c, d in BOT_COMMANDS]})
        except (httpx.HTTPError, RuntimeError):  # cosmetic: never block startup on it
            log.warning("setMyCommands failed", exc_info=True)

    # A transient failure (network, Core 5xx, 429) replays the update; after this many attempts it is dropped so one
    # poisoned update can never freeze the whole bot for every user (head-of-line blocking).
    MAX_UPDATE_ATTEMPTS = 5

    async def _process_update(self, update: dict) -> None:
        """Handle one update and acknowledge it. Transient errors propagate (offset not advanced) until the attempt cap."""
        uid = update["update_id"]
        attempts = getattr(self, "_attempts", None)
        if attempts is None:
            attempts = self._attempts = {}
        try:
            await self.handle(update)
        except (KeyError, ValueError, CoreError):
            # Malformed/user-level errors are terminal for this update.
            log.exception("dropping malformed update %s", uid)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status < 500 and status != 429:
                # A definitive 4xx (blocked user, bad payload, expired callback) can never succeed on replay.
                log.exception("dropping update %s after HTTP %s", uid, status)
            else:
                self._count_or_drop(attempts, uid)
        except (httpx.HTTPError, RuntimeError):
            # Transport trouble, or Telegram answered ok=false (e.g. "query is too old"): retry a bounded number of times.
            self._count_or_drop(attempts, uid)
        except Exception:  # noqa: BLE001 - a handler bug must neither crash the runner nor be replayed forever
            log.exception("handler bug, dropping update %s", uid)
        attempts.pop(uid, None)
        self._save_offset(uid + 1)

    def _count_or_drop(self, attempts: dict, uid: int) -> None:
        attempts[uid] = attempts.get(uid, 0) + 1
        if attempts[uid] < self.MAX_UPDATE_ATTEMPTS:
            raise  # re-raised inside the caller's ``except``: the outer loop backs off and the update is replayed
        log.error("update %s failed %s times, dropping it", uid, attempts[uid])

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
                        await self._process_update(update)
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
