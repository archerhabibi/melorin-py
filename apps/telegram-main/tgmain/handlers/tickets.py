"""Support tickets and notifications."""

import logging

from tgmain.ui import (
    PRIORITY_LABEL,
    TICKET_ICON,
    TICKET_LABEL,
    esc,
)

log = logging.getLogger("melorin.telegram.main")


class TicketsMixin:
    """Support tickets and notifications."""

    async def cmd_tickets(self, ctx, arg):
        store = await self.store_info()
        ts = await self.api(ctx, "GET", f"/api/v1/stores/{store['id']}/tickets")
        rows = [
            [(f"{TICKET_ICON.get(t['status'], '⚪')} #{t.get('number') or '-'} · {t['subject'][:28]}", f"ticket:{t['id']}")]
            for t in ts[:10]
        ]
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
        rows = (
            [[("🔓 بازگشایی تیکت", f"treopen:{tid}")]]
            if closed
            else [
                [("✍️ پاسخ", f"reply:{tid}"), ("✏️ ویرایش پیام من", f"tedit:{tid}")],
                [("📝 تغییر موضوع", f"tsubj:{tid}"), ("🔒 بستن تیکت", f"tclose:{tid}")],
            ]
        )
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
        await self.send(
            ctx.chat_id,
            f"✏️ <b>ویرایش آخرین پیام شما</b>\n\nمتن فعلی:\n<blockquote>{esc(last['body'][:500])}</blockquote>\nمتن جدید را بفرستید:",
            html=True,
        )

    async def cb_ticket_edit_subject(self, ctx, tid):
        self._set_state(ctx.chat_id, {"edit_subject": tid})
        await self.send(ctx.chat_id, "📝 موضوع جدید تیکت را بفرستید:")

    async def cb_ticket_close(self, ctx, tid):
        await self.api(ctx, "PATCH", f"/api/v1/tickets/{tid}", json={"status": "closed"})
        await self.send(
            ctx.chat_id,
            "🔒 تیکت بسته شد. هر زمان خواستید می‌توانید آن را دوباره باز کنید.",
            [[("📂 مشاهدهٔ تیکت", f"ticket:{tid}")], [("🎫 همهٔ تیکت‌ها", "menu:tickets")]],
        )

    async def cb_ticket_reopen(self, ctx, tid):
        await self.api(ctx, "PATCH", f"/api/v1/tickets/{tid}", json={"status": "open"})
        await self.send(ctx.chat_id, "🔓 تیکت دوباره باز شد.", [[("📂 مشاهدهٔ تیکت", f"ticket:{tid}")]])

    async def cmd_notifications(self, ctx, arg):
        d = await self.api(ctx, "GET", f"/api/v1/stores/{(await self.store_info())['id']}/notifications?unread_only=true&limit=10")
        items = d.get("items", [])
        if not items:
            return await self.send(ctx.chat_id, "اعلان جدیدی ندارید.")
        await self.send(ctx.chat_id, "\n\n".join(f"🔔 {n['title']}\n{n['body']}" for n in items), [[("علامت‌گذاری همه", "readall:1")]])

    async def cb_readall(self, ctx, _):
        await self.api(ctx, "POST", f"/api/v1/stores/{(await self.store_info())['id']}/notifications/read-all")
        await self.send(ctx.chat_id, "همه اعلان‌ها خوانده شد ✅")
