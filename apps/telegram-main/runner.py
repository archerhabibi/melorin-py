"""Production Telegram long-poll runner (main store bot).

Telegram is transport only: identity, authorization, pricing, wallet, orders and
tickets stay in Core. Every update is exchanged for a Core session through
``/api/v1/auth/telegram/bot`` (X-Bot-Secret). The offset is persisted so a restart
replays no acknowledged update; order/top-up calls carry an Idempotency-Key derived
from the Telegram update/callback id so a replay can never double-charge.
"""
import asyncio
import json
import logging
import mimetypes
import os
import os
from pathlib import Path

import httpx

log = logging.getLogger("melorin.telegram.main")

HELP = (
    "فرمان‌ها:\n"
    "/plans سرویس‌ها و خرید\n/wallet کیف پول و تراکنش‌ها\n/topup مبلغ — شارژ کیف پول\n"
    "/orders سفارش‌ها\n/accounts اکانت‌های VPN\n/test دریافت اکانت تست\n"
    "/tickets تیکت‌ها\n/ticket موضوع | متن — تیکت جدید\n/notifications اعلان‌ها\n"
    "/link کد — اتصال به حساب وب\n/me حساب من"
)
MENU = [
    [("🛒 سرویس‌ها", "menu:plans"), ("👛 کیف پول", "menu:wallet")],
    [("📦 سفارش‌ها", "menu:orders"), ("🔑 اکانت‌ها", "menu:accounts")],
    [("🎫 تیکت‌ها", "menu:tickets"), ("🔔 اعلان‌ها", "menu:notifications")],
]


def money(n) -> str:
    return f"{int(n or 0):,}"


def gb(b) -> str:
    return f"{(b or 0) / 1073741824:.1f}"


def keyboard(rows):
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}


class CoreError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


class Ctx:
    def __init__(self, chat_id, user, pair, update_id, callback_id=None):
        self.chat_id, self.user, self.pair = chat_id, user, pair
        self.update_id, self.callback_id = update_id, callback_id

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
            "/ticket": self.cmd_ticket, "/notifications": self.cmd_notifications, "/link": self.cmd_link,
        }
        self.callbacks = {
            "menu": self.cb_menu, "plan": self.cb_plan, "buy": self.cb_buy, "ticket": self.cb_ticket,
            "reply": self.cb_reply, "readall": self.cb_readall,
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

    async def send(self, chat_id, text: str, rows=None) -> None:
        payload = {"chat_id": chat_id, "text": text[:4000]}
        if rows:
            payload["reply_markup"] = keyboard(rows)
        await self.tg("sendMessage", payload)

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
        ctx = Ctx(message["chat"]["id"], user, pair, update["update_id"], callback["id"] if callback else None)
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
        if st.get("reply_ticket"):
            await self.api(ctx, "POST", f"/api/v1/tickets/{st['reply_ticket']}/messages", json={"body": text})
            self._set_state(ctx.chat_id, None)
            await self.send(ctx.chat_id, "پیام شما ثبت شد ✅")
        else:
            await self.send(ctx.chat_id, "برای دیدن فرمان‌ها /help را بفرستید.", MENU)

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
        await self.send(ctx.chat_id, f"به {store.get('name', 'ملورین')} خوش آمدید 👋\nاز منوی زیر شروع کنید.", MENU)

    async def cmd_help(self, ctx, arg):
        await self.send(ctx.chat_id, HELP, MENU)

    async def cmd_me(self, ctx, arg):
        me = await self.api(ctx, "GET", "/api/v1/me")
        await self.send(ctx.chat_id, f"حساب: {me.get('display_name') or me.get('email') or me['id']}\nکد دعوت: {me.get('referral_code', '-')}")

    async def cmd_link(self, ctx, arg):
        code = arg.strip()
        if not code:
            return await self.send(ctx.chat_id, "کد اتصال را از بخش «پروفایل» وبسایت بگیرید و به‌صورت /link کد بفرستید.")
        r = await self.client.post(f"{self.core}/api/v1/auth/telegram/link", headers={"X-Bot-Secret": self.secret, "Accept": "application/json"},
                                   json={"code": code, "telegram_id": ctx.user["id"], "first_name": ctx.user.get("first_name"), "last_name": ctx.user.get("last_name"), "username": ctx.user.get("username")})
        if r.status_code >= 500:
            r.raise_for_status()
        await self.send(ctx.chat_id, "حساب تلگرام به حساب وب شما متصل شد ✅" if r.status_code < 400 else f"⚠️ {self._err(r)}")

    async def cmd_plans(self, ctx, arg):
        store = await self.store_info()
        r = await self.client.get(f"{self.core}/api/v1/stores/{store['id']}/catalog")
        r.raise_for_status()
        items = r.json()
        if not items:
            return await self.send(ctx.chat_id, "فعلاً سرویسی برای فروش موجود نیست.")
        rows = [[(f"{p['name']} · {money(p['price'])} {p['currency']}", f"plan:{p['product_id']}")] for p in items[:20]]
        await self.send(ctx.chat_id, "یک سرویس انتخاب کنید:", rows)

    async def cb_plan(self, ctx, pid):
        store = await self.store_info()
        q = await self.api(ctx, "POST", f"/api/v1/stores/{store['id']}/checkout/quote", json={"product_id": pid})
        txt = f"پیش‌فاکتور\nقیمت: {money(q['unit_price'])}\nتخفیف: {money(q['discount'])}\nمبلغ نهایی: {money(q['total'])} {q['currency']}\nموجودی کیف پول: {money(q.get('wallet_balance'))}"
        if q.get("sufficient_funds"):
            await self.send(ctx.chat_id, txt, [[("✅ پرداخت از کیف پول", f"buy:{pid}")], [("↩︎ بازگشت", "menu:plans")]])
        else:
            await self.send(ctx.chat_id, txt + "\n\nموجودی کافی نیست. با /topup مبلغ کیف پول را شارژ کنید.", [[("↩︎ بازگشت", "menu:plans")]])

    async def cb_buy(self, ctx, pid):
        store = await self.store_info()
        o = await self.api(ctx, "POST", f"/api/v1/stores/{store['id']}/orders", headers={"Idempotency-Key": ctx.idem},
                           json={"product_id": pid, "payment_method": "wallet", "kind": "purchase"})
        await self.send(ctx.chat_id, f"سفارش {o['number']} ثبت شد ✅\nوضعیت: {o['status']}\nپس از آماده شدن، اکانت را در /accounts ببینید.", [[("🔑 اکانت‌ها", "menu:accounts")]])

    async def cmd_wallet(self, ctx, arg):
        store = await self.store_info()
        w = await self.api(ctx, "GET", f"/api/v1/stores/{store['id']}/wallet")
        tx = await self.api(ctx, "GET", f"/api/v1/stores/{store['id']}/wallet/transactions")
        items = tx if isinstance(tx, list) else tx.get("items", [])
        lines = [f"{t['kind']}: {money(t['amount'])}" for t in items[:5]]
        await self.send(ctx.chat_id, f"موجودی: {money(w['balance'])} {w['currency']}\n\nآخرین تراکنش‌ها:\n" + ("\n".join(lines) or "—") + "\n\nشارژ: /topup مبلغ")

    async def cmd_topup(self, ctx, arg):
        digits = "".join(ch for ch in arg.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")) if ch.isdigit())
        if not digits or int(digits) <= 0:
            return await self.send(ctx.chat_id, "مبلغ را وارد کنید. مثال: /topup 100000")
        store = await self.store_info()
        p = await self.api(ctx, "POST", f"/api/v1/stores/{store['id']}/wallet/topups", headers={"Idempotency-Key": f"{ctx.idem}-topup"}, json={"amount": int(digits), "provider": "manual_card"})
        ins = p.get("instructions") or {}
        lines = [f"درخواست شارژ {money(p['amount'])} {p['currency']} ثبت شد."]
        if ins.get("card_number"):
            lines += [f"کارت: {ins['card_number']}", f"به نام: {ins.get('holder', '-')}", f"بانک: {ins.get('bank', '-')}"]
        if ins.get("redirect_url"):
            lines.append(f"پرداخت آنلاین: {ins['redirect_url']}")
        else:
            lines.append("پس از واریز، عکس رسید را همین‌جا بفرستید.")
            self._set_state(ctx.chat_id, {"receipt_payment": p["id"]})
        await self.send(ctx.chat_id, "\n".join(lines))

    async def cmd_orders(self, ctx, arg):
        store = await self.store_info()
        os_ = await self.api(ctx, "GET", f"/api/v1/stores/{store['id']}/orders")
        lines = [f"{o['number']} · {money(o['total'])} {o['currency']} · {o['status']}" for o in os_[:10]]
        await self.send(ctx.chat_id, "سفارش‌ها:\n" + ("\n".join(lines) or "هنوز سفارشی ندارید."))

    async def cmd_accounts(self, ctx, arg):
        rows = await self.api(ctx, "GET", "/api/v1/vpn-accounts")
        if not rows:
            return await self.send(ctx.chat_id, "اکانتی ندارید. از /plans خرید کنید یا /test بگیرید.")
        for a in rows[:8]:
            lim = gb(a["traffic_limit_bytes"]) if a.get("traffic_limit_bytes") else "∞"
            exp = (a.get("expires_at") or "نامحدود")[:10]
            await self.send(ctx.chat_id, f"👤 {a['username']}\nوضعیت: {a['status']}\nانقضا: {exp}\nمصرف: {gb(a['traffic_used_bytes'])} / {lim} GB\n🔗 {a.get('subscription_url') or 'در حال آماده‌سازی'}")

    async def cmd_test(self, ctx, arg):
        store = await self.store_info()
        o = await self.api(ctx, "POST", f"/api/v1/stores/{store['id']}/test-account")
        await self.send(ctx.chat_id, f"اکانت تست ساخته شد ({o['number']}). لینک را از /accounts بگیرید.")

    async def cmd_tickets(self, ctx, arg):
        store = await self.store_info()
        ts = await self.api(ctx, "GET", f"/api/v1/stores/{store['id']}/tickets")
        rows = [[(f"{t['subject'][:40]} · {t['status']}", f"ticket:{t['id']}")] for t in ts[:10]]
        await self.send(ctx.chat_id, "تیکت‌های شما (برای تیکت جدید: /ticket موضوع | متن):" if rows else "تیکتی ندارید. برای ساخت: /ticket موضوع | متن", rows or None)

    async def cmd_ticket(self, ctx, arg):
        subject, _, body = arg.partition("|")
        if len(subject.strip()) < 2 or not body.strip():
            return await self.send(ctx.chat_id, "قالب: /ticket موضوع | متن پیام")
        store = await self.store_info()
        t = await self.api(ctx, "POST", f"/api/v1/stores/{store['id']}/tickets", json={"subject": subject.strip(), "body": body.strip()})
        await self.send(ctx.chat_id, f"تیکت «{t['subject']}» ثبت شد ✅")

    async def cb_ticket(self, ctx, tid):
        ms = await self.api(ctx, "GET", f"/api/v1/tickets/{tid}/messages")
        txt = "\n\n".join(f"{'پشتیبانی' if m['is_staff'] else 'شما'}: {m['body']}" for m in ms[-6:])
        await self.send(ctx.chat_id, txt or "پیامی نیست.", [[("✍️ پاسخ", f"reply:{tid}")]])

    async def cb_reply(self, ctx, tid):
        self._set_state(ctx.chat_id, {"reply_ticket": tid})
        await self.send(ctx.chat_id, "متن پاسخ را بفرستید:")

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
              "tickets": self.cmd_tickets, "notifications": self.cmd_notifications}.get(name)
        await (fn(ctx, "") if fn else self.cmd_help(ctx, ""))

    # ---------- loop ----------
    async def run(self) -> None:
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
