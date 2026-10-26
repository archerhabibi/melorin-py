"""Support tickets and notifications."""

import logging
import mimetypes
import os

from tgmain.errors import CoreError
from tgmain.ui import (
    PRIORITY_LABEL,
    TICKET_ICON,
    TICKET_LABEL,
    esc,
)

log = logging.getLogger("melorin.telegram.main")

TICKET_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
SHOWN_MESSAGES = 5  # the thread view shows the last few messages
SHOWN_IMAGES = 3  # ... and sends at most this many of the support pictures among them


class TicketsMixin:
    """Support tickets and notifications."""

    # ----- pictures -----
    async def telegram_image(self, ctx, message) -> tuple[bytes, str] | None:
        """Download the photo (or image file) of a Telegram message: (bytes, content type). Tells the user and returns None if unusable."""
        if message.get("photo"):
            file_id, ctype = message["photo"][-1]["file_id"], "image/jpeg"
        else:
            doc = message["document"]
            file_id = doc["file_id"]
            ctype = (
                doc.get("mime_type")
                or mimetypes.guess_type(doc.get("file_name", ""))[0]
                or ""
            ).lower()
            if ctype not in TICKET_IMAGE_TYPES:
                await self.send(
                    ctx.chat_id,
                    "فقط تصویر (JPG، PNG یا WebP) پذیرفته می‌شود. عکس را به‌صورت «عکس» یا فایل تصویری بفرستید.",
                )
                return None
        info = await self.tg("getFile", {"file_id": file_id})
        max_bytes = int(os.getenv("MELORIN_MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))
        if int(info.get("file_size") or 0) > max_bytes:
            await self.send(ctx.chat_id, "حجم تصویر بیشتر از حد مجاز است.")
            return None
        dl = await self.client.get(
            f"https://api.telegram.org/file/bot{self.token}/{info['file_path']}"
        )
        dl.raise_for_status()
        if len(dl.content) > max_bytes:
            await self.send(ctx.chat_id, "حجم تصویر بیشتر از حد مجاز است.")
            return None
        return dl.content, ctype

    async def ticket_picture(self, ctx, st, message) -> None:
        """A picture sent while a ticket is being written or answered: it becomes (part of) that message. The caption is the text."""
        got = await self.telegram_image(ctx, message)
        if got is None:
            return
        data, ctype = got
        caption = (message.get("caption") or "").strip()[:10_000]
        store = await self.store_info()
        att = await self.api(
            ctx,
            "POST",
            f"/api/v1/stores/{store['id']}/tickets/attachments",
            files={"file": ("ticket-image", data, ctype)},
        )
        if st.get("reply_ticket"):
            await self.send_ticket_reply(ctx, st["reply_ticket"], caption, att["id"])
        else:
            await self.create_ticket(ctx, st["new_ticket_subject"], caption, att["id"])

    async def send_ticket_reply(self, ctx, tid, body: str, attachment_id=None) -> None:
        payload = {"body": body}
        if attachment_id:
            payload["attachment_id"] = attachment_id
        await self.api(ctx, "POST", f"/api/v1/tickets/{tid}/messages", json=payload)
        self._set_state(ctx.chat_id, None)
        await self.send(
            ctx.chat_id,
            "✅ پیام شما ثبت شد؛ پاسخ پشتیبانی همین‌جا به شما اطلاع داده می‌شود.",
            [
                [("📂 مشاهدهٔ تیکت", f"ticket:{tid}")],
                [("🎫 همهٔ تیکت‌ها", "menu:tickets")],
            ],
        )

    async def create_ticket(
        self, ctx, subject: str, body: str, attachment_id=None
    ) -> None:
        store = await self.store_info()
        payload = {"subject": subject, "body": body}
        if attachment_id:
            payload["attachment_id"] = attachment_id
        t = await self.api(
            ctx, "POST", f"/api/v1/stores/{store['id']}/tickets", json=payload
        )
        self._set_state(ctx.chat_id, None)
        await self.send(
            ctx.chat_id,
            f"✅ تیکت شما با شماره <b>#{esc(t.get('number') or '-')}</b> ثبت شد.\nپاسخ پشتیبانی همین‌جا به شما اطلاع داده می‌شود.",
            [
                [("📂 مشاهدهٔ تیکت", f"ticket:{t['id']}")],
                [("🎫 همهٔ تیکت‌ها", "menu:tickets")],
            ],
            html=True,
        )

    async def cmd_tickets(self, ctx, arg):
        store = await self.store_info()
        ts = await self.api(ctx, "GET", f"/api/v1/stores/{store['id']}/tickets")
        rows = [
            [
                (
                    f"{TICKET_ICON.get(t['status'], '⚪')} #{t.get('number') or '-'} · {t['subject'][:28]}",
                    f"ticket:{t['id']}",
                )
            ]
            for t in ts[:10]
        ]
        rows.append([("➕ تیکت جدید", "tnew:1")])
        head = (
            "🎫 <b>تیکت‌های شما</b>\n🟡 باز   🟢 پاسخ داده شد   ⚫ بسته"
            if ts
            else "🎫 هنوز تیکتی ثبت نکرده‌اید."
        )
        await self.screen(ctx, head, rows)

    async def cmd_ticket(self, ctx, arg):
        subject, _, body = arg.partition("|")
        if len(subject.strip()) < 2 or not body.strip():
            return await self.send(
                ctx.chat_id,
                "قالب: /ticket موضوع | متن پیام\nیا از /tickets دکمهٔ «تیکت جدید» را بزنید.",
            )
        store = await self.store_info()
        t = await self.api(
            ctx,
            "POST",
            f"/api/v1/stores/{store['id']}/tickets",
            json={"subject": subject.strip(), "body": body.strip()},
        )
        await self.send(
            ctx.chat_id,
            f"تیکت «{t['subject']}» با شمارهٔ #{t.get('number') or '-'} ثبت شد ✅",
        )

    async def cb_ticket_new(self, ctx, _):
        self._set_state(ctx.chat_id, {"new_ticket_ask_subject": True})
        await self.send(
            ctx.chat_id,
            "➕ <b>تیکت جدید</b>\nموضوع تیکت را بفرستید (مثلاً: اتصال برقرار نمی‌شود):",
            html=True,
        )

    async def cb_ticket(self, ctx, tid):
        t = await self.api(ctx, "GET", f"/api/v1/tickets/{tid}")
        ms = await self.api(ctx, "GET", f"/api/v1/tickets/{tid}/messages")
        lines = []
        shown = ms[-SHOWN_MESSAGES:]
        for m in shown:
            who = "🎧 پشتیبانی" if m["is_staff"] else "👤 شما"
            edited = "  <i>(ویرایش‌شده)</i>" if m.get("edited_at") else ""
            text = esc(m["body"][:600])
            if m.get("attachment_id"):
                text = f"{text}\n🖼 تصویر پیوست".strip() if text else "🖼 تصویر پیوست"
            lines.append(f"<b>{who}</b>{edited}\n{text}")
        hidden = (
            f"<i>… {len(ms) - SHOWN_MESSAGES} پیام قبلی</i>\n\n"
            if len(ms) > SHOWN_MESSAGES
            else ""
        )
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
        await self.screen(
            ctx,
            f"{head}\n━━━━━━━━━━\n{hidden}" + "\n\n".join(lines or ["پیامی نیست."]),
            rows,
        )
        await self.send_support_pictures(ctx, tid, shown)

    async def send_support_pictures(self, ctx, tid, shown) -> None:
        """The customer's own pictures are not echoed back; the support team's are sent as photos (they cannot be shown in text)."""
        pics = [m for m in shown if m["is_staff"] and m.get("attachment_id")][
            -SHOWN_IMAGES:
        ]
        for m in pics:
            try:
                data, ctype = await self.api_file(
                    ctx, f"/api/v1/tickets/{tid}/messages/{m['id']}/attachment"
                )
                await self.send_photo(
                    ctx.chat_id,
                    data,
                    "🎧 تصویر پشتیبانی"
                    + (f"\n{esc(m['body'][:600])}" if m["body"] else ""),
                    filename="ticket-image",
                    mime=ctype,
                )
            except CoreError:
                log.warning(
                    "could not fetch the ticket picture %s", m["id"]
                )  # a missing picture must not hide the thread

    async def cb_reply(self, ctx, tid):
        self._set_state(ctx.chat_id, {"reply_ticket": tid})
        await self.send(
            ctx.chat_id,
            "✍️ متن پاسخ را بفرستید. برای پیوست تصویر، عکس را بفرستید (متن را زیر عکس بنویسید):",
        )

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
        await self.api(
            ctx, "PATCH", f"/api/v1/tickets/{tid}", json={"status": "closed"}
        )
        await self.send(
            ctx.chat_id,
            "🔒 تیکت بسته شد. هر زمان خواستید می‌توانید آن را دوباره باز کنید.",
            [
                [("📂 مشاهدهٔ تیکت", f"ticket:{tid}")],
                [("🎫 همهٔ تیکت‌ها", "menu:tickets")],
            ],
        )

    async def cb_ticket_reopen(self, ctx, tid):
        await self.api(ctx, "PATCH", f"/api/v1/tickets/{tid}", json={"status": "open"})
        await self.send(
            ctx.chat_id,
            "🔓 تیکت دوباره باز شد.",
            [[("📂 مشاهدهٔ تیکت", f"ticket:{tid}")]],
        )

    async def cmd_notifications(self, ctx, arg):
        d = await self.api(
            ctx,
            "GET",
            f"/api/v1/stores/{(await self.store_info())['id']}/notifications?unread_only=true&limit=10",
        )
        items = d.get("items", [])
        if not items:
            return await self.send(ctx.chat_id, "اعلان جدیدی ندارید.")
        await self.send(
            ctx.chat_id,
            "\n\n".join(f"🔔 {n['title']}\n{n['body']}" for n in items),
            [[("علامت‌گذاری همه", "readall:1")]],
        )

    async def cb_readall(self, ctx, _):
        await self.api(
            ctx,
            "POST",
            f"/api/v1/stores/{(await self.store_info())['id']}/notifications/read-all",
        )
        await self.send(ctx.chat_id, "همه اعلان‌ها خوانده شد ✅")
