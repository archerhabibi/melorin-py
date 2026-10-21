"""Two-step reseller application (store name, then domain + bot token)."""

import logging

from tgmain.ui import (
    RESELLER_DOMAIN_ERRORS,
    RESELLER_TOKEN_ERRORS,
    esc,
)
from tgmain.errors import CoreError

log = logging.getLogger("melorin.telegram.main")


class ResellerMixin:
    """Two-step reseller application (store name, then domain + bot token)."""

    # ----- reseller request (two steps: request -> admin approval -> domain + bot token) -----
    async def cmd_reseller(self, ctx, arg):
        if self.channel != "main":  # reseller bots have no sub-resellers: keep the support-ticket request
            self._set_state(ctx.chat_id, {"new_ticket_subject": "🤖 درخواست ربات نماینده و همکاری"})
            return await self.send(ctx.chat_id, "📌 توضیحات خود را برای ثبت درخواست نمایندگی ارسال نمایید.")
        store = await self.store_info()
        apps = [a for a in await self.api(ctx, "GET", "/api/v1/reseller/applications") if str(a.get("target_store_id")) == str(store["id"])]
        last = apps[0] if apps else None  # newest first
        self._set_state(ctx.chat_id, None)
        if last and last["status"] == "awaiting_details":
            self._set_state(ctx.chat_id, {"rs": "domain", "rs_app": last["id"]})
            return await self.send(
                ctx.chat_id,
                f"✅ درخواست نمایندگی «{esc(last['store_name'])}» تأیید شده است.\n\n"
                "برای ساخت فروشگاه دو اطلاعات لازم است.\n<b>مرحلهٔ ۱ از ۲:</b> دامنهٔ فروشگاه را بفرستید (مثال: <code>shop.example.com</code>)\n\n"
                "برای انصراف: /cancel",
                html=True,
            )
        if last and last["status"] == "pending":
            return await self.send(
                ctx.chat_id,
                f"⏳ درخواست نمایندگی «{esc(last['store_name'])}» در حال بررسی مدیریت است.\nپس از تأیید همین‌جا به شما اطلاع داده می‌شود.",
                [[("❌ لغو درخواست", f"rsc:{last['id']}")]],
                html=True,
            )
        if last and last["status"] == "approved":
            return await self.send(ctx.chat_id, "✅ فروشگاه نمایندگی شما فعال است. تنظیمات آن را از «پنل نماینده» در وب‌سایت ادامه دهید.")
        note = f"❌ درخواست قبلی شما رد شد: {esc(last.get('review_reason') or '—')}\n\n" if last and last["status"] == "rejected" else ""
        self._set_state(ctx.chat_id, {"rs": "name"})
        await self.send(
            ctx.chat_id,
            f"{note}🤖 <b>درخواست نمایندگی</b>\nابتدا درخواست شما برای مدیریت ثبت می‌شود؛ پس از تأیید، دامنه و توکن ربات فروشگاه را از شما می‌گیریم.\n\n"
            "<b>مرحلهٔ ۱ از ۲:</b> نام فروشگاه نمایندگی خود را بفرستید:\nبرای انصراف: /cancel",
            html=True,
        )

    async def cb_reseller_cancel(self, ctx, app_id):
        await self.api(ctx, "POST", f"/api/v1/reseller/applications/{app_id}/cancel")
        self._set_state(ctx.chat_id, None)
        await self.screen(ctx, "درخواست نمایندگی لغو شد. هر زمان خواستید با /reseller دوباره ثبت کنید.")

    async def reseller_step(self, ctx, st: dict, text: str) -> None:
        step, text = st["rs"], text.strip()
        if step == "name":
            if not 2 <= len(text) <= 200:
                return await self.send(ctx.chat_id, "نام فروشگاه باید بین ۲ تا ۲۰۰ نویسه باشد. دوباره بفرستید:")
            self._set_state(ctx.chat_id, {"rs": "msg", "rs_name": text})
            await self.send(ctx.chat_id, "توضیحات درخواست را بفرستید (سابقهٔ فروش، تعداد مشتری و …).\nاگر توضیحی ندارید یک «-» بفرستید:")
        elif step == "msg":
            store = await self.store_info()
            try:
                await self.api(
                    ctx,
                    "POST",
                    "/api/v1/reseller/applications",
                    json={
                        "store_name": st["rs_name"],
                        "message": None if text in {"-", "—"} else text[:2000],
                        "target_store_id": store["id"],
                    },
                )
            except CoreError:
                self._set_state(ctx.chat_id, None)
                raise
            self._set_state(ctx.chat_id, None)
            await self.send(
                ctx.chat_id,
                "✅ درخواست نمایندگی شما ثبت شد و در صف بررسی مدیریت است.\nپس از تأیید همین‌جا به شما اطلاع می‌دهیم و دامنه و توکن ربات را می‌گیریم.",
            )
        elif step == "domain":
            self._set_state(ctx.chat_id, {"rs": "token", "rs_app": st["rs_app"], "rs_domain": text[:255]})
            await self.send(
                ctx.chat_id,
                "<b>مرحلهٔ ۲ از ۲:</b> توکن رباتِ فروشگاه را بفرستید (از @BotFather با /newbot بسازید؛ شکل آن <code>123456789:AA…</code> است).\n"
                "توکن رمزنگاری ذخیره می‌شود و پیام شما بعد از دریافت از چت پاک می‌شود.\nبرای انصراف: /cancel",
                html=True,
            )
        elif step == "token":
            try:
                out = await self.api(
                    ctx,
                    "POST",
                    f"/api/v1/reseller/applications/{st['rs_app']}/details",
                    json={"domain": st["rs_domain"], "bot_token": text},
                )
            except CoreError as exc:
                await self.forget_message(ctx)
                if exc.code in RESELLER_DOMAIN_ERRORS:
                    self._set_state(ctx.chat_id, {"rs": "domain", "rs_app": st["rs_app"]})
                    return await self.send(ctx.chat_id, f"⚠️ {exc.message}\nدامنه را دوباره بفرستید:")
                if exc.code in RESELLER_TOKEN_ERRORS:
                    return await self.send(ctx.chat_id, f"⚠️ {exc.message}\nتوکن را دوباره بفرستید:")
                self._set_state(ctx.chat_id, None)
                raise
            await self.forget_message(ctx)
            self._set_state(ctx.chat_id, None)
            await self.send(
                ctx.chat_id,
                f"🎉 فروشگاه «{esc(out['store_name'])}» ساخته شد.\nدامنه: <code>{esc(out['domain'])}</code>\nربات: @{esc(out['bot_username'] or '—')}\n\n"
                "تنظیمات و قیمت‌ها را از «پنل نماینده» در وب‌سایت ادامه دهید.",
                html=True,
            )
