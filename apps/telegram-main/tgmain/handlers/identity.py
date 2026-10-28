"""Account linking, website login approval, referral link and profile commands."""

import logging

from tgmain.ui import (
    esc,
    referral_text,
)
from tgmain.errors import CoreError
from tgmain.client import Ctx

log = logging.getLogger("melorin.telegram.main")


class IdentityMixin:
    """Account linking, website login approval, referral link and profile commands."""

    LINE = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

    WEB_LOGIN_DENIED = {
        "user_denied": "⛔ درخواست ورود رد شد.\nاگر شما آن را نداده بودید، کار درستی کردید ✅",
        "too_many_wrong_choices": "⛔ عدد اشتباه انتخاب شد و برای امنیت شما درخواست بسته شد.\nاگر خودتان وارد می‌شدید، از وب‌سایت دوباره شروع کنید.",
        "admin_use_panel": "⛔ ورود مدیران فقط از پنل مدیریت انجام می‌شود.",
        "account_disabled": "⛔ حساب شما غیرفعال است. با پشتیبانی تماس بگیرید.",
        "registration_closed": "⛔ ثبت‌نام جدید موقتاً بسته است.",
        "rate_limited": "⛔ تلاش‌های ورود زیاد بود. کمی بعد دوباره امتحان کنید.",
        "login_disabled": "⛔ ورود با تلگرام موقتاً غیرفعال شده است.",
        "device_account_mismatch": "⛔ این مرورگر برای حساب دیگری تأیید شده بود؛ درخواست بسته شد.",
    }

    async def account_url(self, ctx: Ctx) -> str | None:
        """Core builds the one-time sign-in URL of THIS store's website (reseller domain or main store URL)."""
        store = await self.store_info()
        try:
            out = await self.api(
                ctx, "POST", "/api/v1/me/web-handoff", json={"store_id": store["id"]}
            )
        except CoreError:
            return None
        url = str(out.get("url") or "")
        host = url.split("/")[2] if url.count("/") >= 2 else ""
        if not url.startswith(("https://", "http://")) or host.split(":")[0] in (
            "localhost",
            "127.0.0.1",
        ):
            return None  # Telegram rejects such URL buttons; fall back to the in-bot summary only
        return url

    async def cmd_me(self, ctx, arg):
        """Account button: opens the user's account on the store website. The site offers Telegram and Google sign-in,
        and the profile page lets a Telegram-created account attach its Google account (one account, both logins)."""
        me = await self.api(ctx, "GET", "/api/v1/me")
        who = me.get("display_name") or me.get("email") or me["id"]
        text = (
            f"🌐 <b>حساب من در سایت</b>\n\nنام: {esc(who)}\nکد دعوت: <code>{esc(me.get('referral_code', '-'))}</code>\n\n"
            "با دکمهٔ زیر حساب‌تان در سایت فروش باز می‌شود و خودکار وارد می‌شوید؛ لینک فقط ۲ دقیقه و یک‌بار معتبر است. اتصال گوگل هم همان‌جا با یک تأیید انجام می‌شود."
        )
        rows = [[("💰 کیف پول", "menu:wallet"), ("🔑 اکانت‌ها", "menu:accounts")]]
        url = await self.account_url(ctx)
        if url:
            rows.insert(0, [("🌐 باز کردن حساب در سایت", url)])
        await self.screen(ctx, text, rows)

    async def cmd_link(self, ctx, arg):
        code = arg.strip()
        if not code:
            return await self.send(
                ctx.chat_id,
                "کد اتصال را از بخش «پروفایل» وبسایت بگیرید و به‌صورت /link کد بفرستید.",
            )
        r = await self.client.post(
            f"{self.core}/api/v1/auth/telegram/link",
            headers={"X-Bot-Secret": self.secret, "Accept": "application/json"},
            json={
                "code": code,
                "telegram_id": ctx.user["id"],
                "first_name": ctx.user.get("first_name"),
                "last_name": ctx.user.get("last_name"),
                "username": ctx.user.get("username"),
                "store_id": (await self.store_info())["id"],
            },
        )  # Core binds the session to THIS bot's store
        if r.status_code >= 500:
            r.raise_for_status()
        await self.send(
            ctx.chat_id,
            "حساب تلگرام به حساب وب شما متصل شد ✅"
            if r.status_code < 400
            else f"⚠️ {self._err(r)}",
        )

    # ----- website login approved here (Core: /api/v1/auth/telegram/web/bot/*) -----
    async def _web_login_call(self, action: str, body: dict) -> tuple[int, dict]:
        r = await self.client.post(
            f"{self.core}/api/v1/auth/telegram/web/bot/{action}",
            headers={"X-Bot-Secret": self.secret, "Accept": "application/json"},
            json=body,
        )
        if r.status_code >= 500:
            r.raise_for_status()  # transient: let the runner retry the update
        try:
            data = r.json()
        except ValueError:
            data = {}
        return r.status_code, data if isinstance(data, dict) else {}

    def _profile(self, ctx: Ctx) -> dict:
        u = ctx.user
        return {
            "telegram_id": u["id"],
            "first_name": u.get("first_name"),
            "last_name": u.get("last_name"),
            "username": u.get("username"),
            "language_code": u.get("language_code"),
        }

    @staticmethod
    def _ago(seconds) -> str:
        n = int(seconds or 0)
        return f"{n} ثانیه پیش" if n < 60 else f"{n // 60} دقیقه پیش"

    def _web_login_view(
        self,
        sid: str,
        choices: list,
        number_match: bool,
        *,
        info: dict | None = None,
        note: str = "",
        store_name: str | None = None,
    ) -> tuple[str, list]:
        """Identity-confirmation card: who asks (device / IP / age), how long it stays valid, what to do, and an
        always-visible «not me» exit. Callback data is unchanged (wla:<sid>:<choice>, wld:<sid>)."""
        lines = ["🔐 <b>تأیید هویت برای ورود به وب‌سایت</b>"]
        if store_name:
            lines.append(f"🏬 {esc(store_name)}")
        lines += [self.LINE]
        if info:
            lines += [
                f"🖥 دستگاه: <b>{esc(info.get('device'))}</b>",
                f"🌐 آی‌پی: <code>{esc(info.get('ip') or '-')}</code>",
                f"🕒 درخواست: {self._ago(info.get('age_seconds'))}",
            ]
            if info.get("expires_in") is not None:
                lines.append(f"⏳ اعتبار: {self._left(info.get('expires_in'))}")
            lines.append(self.LINE)
        if note:
            lines += [note, ""]
        if number_match:
            lines += [
                "اگر همین الان خودتان در وب‌سایت «ورود با تلگرام» را زده‌اید:",
                "",
                "1️⃣ عددی را که <b>روی صفحهٔ وب‌سایت</b> می‌بینید پیدا کنید",
                "2️⃣ همان عدد را از دکمه‌های زیر بزنید",
            ]
            rows = [[(str(c), f"wla:{sid}:{c}") for c in choices]]
        else:
            lines += [
                "اگر همین الان خودتان در وب‌سایت «ورود با تلگرام» را زده‌اید، تأیید کنید:"
            ]
            rows = [[("✅ بله، خودم هستم", f"wla:{sid}:ok")]]
        lines += [
            "",
            "🛡 این عدد را برای هیچ‌کس نفرستید. اگر این درخواست را شما نداده‌اید یا کسی از شما خواسته این‌جا چیزی را تأیید کنید، «این من نبودم» را بزنید.",
        ]
        rows.append([("⛔ این من نبودم", f"wld:{sid}")])
        return "\n".join(lines), rows

    @staticmethod
    def _left(seconds) -> str:
        n = max(0, int(seconds or 0))
        return f"{n} ثانیه دیگر" if n < 60 else f"{n // 60} دقیقه دیگر"

    async def cmd_web_login(self, ctx, sid):
        store = await self.store_info()
        status, d = await self._web_login_call(
            "inspect",
            {
                **self._profile(ctx),
                "session_id": sid.strip()[:32],
                "store_id": store["id"],
            },
        )
        if status >= 400:
            return await self.send(ctx.chat_id, f"⚠️ {self._err_of(d)}")
        if d.get("auto_approved"):
            # Trusted browser: opening the link was the whole approval. No number to match, nothing to tap.
            return await self.screen(
                ctx,
                "✅ <b>ورود تأیید شد</b>\n"
                + self.LINE
                + f"\n🖥 {esc(d.get('device'))}\n🌐 <code>{esc(d.get('ip') or '-')}</code>\n"
                "این مرورگر قبلاً تأیید شده بود، پس نیازی به تأیید دستی نبود. به مرورگر برگردید.\n\n"
                "🛡 اگر این ورود از طرف شما نبود: /devices",
                [[("⛔ این من نبودم", "wdr:all")]],
            )
        if d.get("auto_reason"):
            return await self.screen(ctx, self.WEB_LOGIN_DENIED.get(d["auto_reason"], "⛔ این درخواست ورود بسته شد."))
        text, rows = self._web_login_view(
            sid.strip()[:32],
            d.get("choices") or [],
            bool(d.get("number_match")),
            info=d,
            store_name=store.get("name"),
        )
        await self.screen(ctx, text, rows)

    async def cb_web_login(self, ctx, rest):
        sid, _, choice = rest.partition(":")
        store = await self.store_info()
        status, d = await self._web_login_call(
            "decide",
            {
                **self._profile(ctx),
                "session_id": sid,
                "store_id": store["id"],
                "action": "approve",
                "choice": choice,
            },
        )
        if status >= 400:
            return await self.screen(ctx, f"⚠️ {esc(self._err_of(d))}")
        result = d.get("result")
        if result == "approved":
            return await self.screen(
                ctx,
                "✅ <b>ورود تأیید شد</b>\n"
                + self.LINE
                + "\nبه مرورگر برگردید؛ چند ثانیهٔ دیگر وارد حساب‌تان می‌شوید.\n\n🛡 اگر خودتان این ورود را شروع نکرده بودید، بلافاصله با پشتیبانی تماس بگیرید.",
            )
        if result == "retry":
            note = f"❌ عدد انتخاب‌شده درست نبود. <b>{int(d.get('remaining') or 0)}</b> فرصت دیگر دارید."
            text, rows = self._web_login_view(
                sid,
                d.get("choices") or [],
                True,
                note=note,
                store_name=store.get("name"),
            )
            return await self.screen(ctx, text, rows)
        await self.screen(
            ctx,
            self.WEB_LOGIN_DENIED.get(
                d.get("reason") or "", "⛔ این درخواست ورود بسته شد."
            ),
        )

    async def cb_web_login_deny(self, ctx, sid):
        store = await self.store_info()
        status, d = await self._web_login_call(
            "decide",
            {
                **self._profile(ctx),
                "session_id": sid,
                "store_id": store["id"],
                "action": "deny",
            },
        )
        if status >= 400:
            return await self.screen(ctx, f"⚠️ {esc(self._err_of(d))}")
        await self.screen(ctx, self.WEB_LOGIN_DENIED["user_denied"])

    # ----- trusted browsers (/devices): list and "this was not me" -----
    @staticmethod
    def _span(seconds) -> str:
        n = max(0, int(seconds or 0))
        if n < 3600:
            return f"{max(1, n // 60)} دقیقه"
        if n < 86400:
            return f"{n // 3600} ساعت"
        return f"{n // 86400} روز"

    async def cmd_devices(self, ctx, arg):
        store = await self.store_info()
        status, d = await self._web_login_call("devices", {"telegram_id": ctx.user["id"], "store_id": store["id"]})
        if status >= 400:
            return await self.screen(ctx, f"⚠️ {esc(self._err_of(d))}")
        devices = d.get("devices") or []
        if not devices:
            return await self.screen(
                ctx,
                "🔐 <b>مرورگرهای مطمئن</b>\n" + self.LINE + "\nهیچ مرورگر مطمئنی ثبت نشده است. ورود بعدی شما با تأیید دستی انجام می‌شود.",
            )
        lines = ["🔐 <b>مرورگرهای مطمئن</b>", self.LINE]
        rows = []
        for i, dev in enumerate(devices, 1):
            lines.append(
                f"{i}. 🖥 <b>{esc(dev.get('label') or 'دستگاه ناشناس')}</b>\n"
                f"   🌐 <code>{esc(dev.get('last_ip') or '-')}</code> · آخرین ورود: {self._span(dev.get('last_seen_ago_seconds'))} پیش\n"
                f"   ⏳ اعتبار: {self._span(dev.get('expires_in_seconds'))} دیگر"
            )
            rows.append([(f"🗑 حذف مورد {i}", f"wdr:{dev['id']}")])
        lines += [
            "",
            "ورود از این مرورگرها بدون عدد (و در شبکهٔ آشنا بدون هیچ مرحله‌ای) انجام می‌شود. اگر موردی را نمی‌شناسید، حذف کنید.",
        ]
        rows.append([("⛔ همه را حذف کن و از همه‌جا خارج شو", "wdr:all")])
        await self.screen(ctx, "\n".join(lines), rows)

    async def cb_device_revoke(self, ctx, rest):
        store = await self.store_info()
        target = rest.strip()
        body = {"telegram_id": ctx.user["id"], "store_id": store["id"], "device_id": None if target in ("", "all") else target[:32]}
        status, d = await self._web_login_call("revoke", body)
        if status >= 400:
            return await self.screen(ctx, f"⚠️ {esc(self._err_of(d))}")
        n = int(d.get("revoked") or 0)
        text = (
            f"✅ همهٔ مرورگرهای مطمئن ({n}) حذف شد و نشست‌های وب شما بسته شد."
            if body["device_id"] is None
            else ("✅ مرورگر حذف شد؛ ورود بعدی از آن با تأیید دستی است." if n else "ℹ️ این مرورگر قبلاً حذف شده بود.")
        )
        await self.screen(ctx, text, [[("🔐 مرورگرهای مطمئن", "menu:devices")]])

    @staticmethod
    def _err_of(d: dict) -> str:
        e = d.get("error") if isinstance(d.get("error"), dict) else {}
        return e.get("message") or "درخواست انجام نشد."

    # ----- engagement / support -----
    async def cmd_referral(self, ctx, arg):
        data = await self.api(ctx, "GET", "/api/v1/me/referrals")
        bot = await self.tg("getMe", {})
        username = bot.get("username", "MelorinBot")
        code = data.get("referral_code") or ctx.user["id"]
        text = referral_text(data, f"https://t.me/{username}?start=ref_{code}")
        await self.send(ctx.chat_id, text, html=True)
