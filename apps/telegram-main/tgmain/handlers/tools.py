"""PG-10 account tools in the bot: usage, last seen (owner), devices, subscription-link rotation, suspend/resume (owner).

Same Core endpoints and same rules as the site (``{base}/{id}/tools*``): the bot only renders what Core says is available and asks for a
second tap before a write. Connection IPs are never part of this; "last seen" is owner-only. Callbacks (22-char account token each):
``atl|otl`` tools screen, ``atr|otr`` + ``atrc|otrc`` rotate link (ask / do), ``adr|odr`` + ``adrc|odrc`` reset devices (ask / do),
``osp`` + ``ospc`` suspend (ask / do), ``ors`` resume. ``a*`` = the customer's own account, ``o*`` = the store owner's view.
"""

from tgmain.errors import CoreError
from tgmain.ui import esc, gb, unb64

_SCOPE = {"a": "me", "o": "ow"}


def _tools_text(matrix: list, usage, devices, presence) -> list[str]:
    lines = ["🛠 <b>ابزارهای اکانت</b>"]
    if presence:
        seen = "هنوز اتصالی ثبت نشده" if presence.get("never_connected") else f"آخرین اتصال: {esc(str(presence.get('online_at'))[:16].replace('T', ' '))}"
        lines.append(f"🕒 {seen}{' · 🟢 آنلاین' if presence.get('online_now') else ''}")
    if usage:
        lines.append(f"📈 مصرف {usage.get('days')} روز اخیر: <b>{gb(usage.get('total_bytes'))}</b> GB")
    if devices:
        lines.append(f"📱 دستگاه‌ها: {devices.get('count', 0)}")
        lines += [f"  • {esc(d.get('label'))}{' · ' + esc(d['platform']) if d.get('platform') else ''}" for d in (devices.get("items") or [])[:10]]
    if matrix and not any(t["available"] for t in matrix if t["write"]):
        lines.append("برخی ابزارها برای این پنل فعال نیست.")
    return lines


class ToolsMixin:
    """Account tools; mixed into the runner next to AccountsMixin (uses its ``_acc_base`` and ``show_account_card``)."""

    async def _tool_base(self, scope: str, token: str) -> tuple[str, str]:
        acc = unb64(token)
        return acc, f"{await self._acc_base(scope)}/{acc}/tools"

    async def _tools_screen(self, ctx, kind: str, token: str) -> None:
        scope = _SCOPE[kind]
        acc, root = await self._tool_base(scope, token)
        pre = "o" if kind == "o" else ""
        back = [(("↩︎ بازگشت به اکانت"), f"{pre}account:{acc}")]
        matrix = await self.api(ctx, "GET", root)
        ok = {t["tool"] for t in matrix if t["available"]}
        usage = await self.api(ctx, "GET", f"{root}/usage", params={"period": "day", "days": 30}) if "usage" in ok else None
        devices = await self.api(ctx, "GET", f"{root}/devices") if "devices" in ok else None
        presence = await self.api(ctx, "GET", f"{root}/presence") if kind == "o" and "presence" in ok else None
        rows = []
        if "rotate" in ok:
            rows.append([("🔗 لینک اشتراک جدید", f"{kind}tr:{token}")])
        if "devices_manage" in ok and (devices or {}).get("count"):
            rows.append([("📱 ریست همه دستگاه‌ها", f"{kind}dr:{token}")])
        if kind == "o" and "suspend" in ok:
            rows.append([("⏸ تعلیق اکانت", f"osp:{token}"), ("▶️ فعال‌سازی مجدد", f"ors:{token}")])
        await self.screen(ctx, "\n".join(_tools_text(matrix, usage, devices, presence)), rows + [back])

    async def _tool_ask(self, ctx, kind: str, token: str, what: str, do: str) -> None:
        await self.screen(
            ctx,
            f"⚠️ {what}\nادامه می‌دهید؟",
            [[("✅ بله", f"{do}:{token}")], [("↩︎ انصراف", f"{kind}tl:{token}")]],
        )

    async def _tool_do(self, ctx, kind: str, token: str, path: str, done: str, *, body: dict | None = None) -> None:
        acc, root = await self._tool_base(_SCOPE[kind], token)
        try:
            await self.api(ctx, "POST", f"{root}/{path}", json=body or {})
        except CoreError as exc:
            if exc.status not in (403, 404, 409):
                raise
            await self.send(ctx.chat_id, f"⚠️ {esc(str(exc))}", html=True)
        else:
            await self.send(ctx.chat_id, done)
        await self._tools_screen(ctx, kind, token)

    # ---- customer ("a") and owner ("o") entry points ----
    async def cb_tools_a(self, ctx, token):
        await self._tools_screen(ctx, "a", token)

    async def cb_tools_o(self, ctx, token):
        await self._tools_screen(ctx, "o", token)

    async def cb_tool_rotate_ask_a(self, ctx, token):
        await self._tool_ask(ctx, "a", token, "لینک قبلی از کار می‌افتد و باید لینک جدید را در برنامه وارد کنید.", "atrc")

    async def cb_tool_rotate_ask_o(self, ctx, token):
        await self._tool_ask(ctx, "o", token, "لینک قبلی این اکانت از کار می‌افتد.", "otrc")

    async def cb_tool_rotate_a(self, ctx, token):
        await self._tool_do(ctx, "a", token, "rotate-subscription", "✅ لینک جدید ساخته شد.")

    async def cb_tool_rotate_o(self, ctx, token):
        await self._tool_do(ctx, "o", token, "rotate-subscription", "✅ لینک جدید ساخته شد.")

    async def cb_tool_devices_ask_a(self, ctx, token):
        await self._tool_ask(ctx, "a", token, "همه دستگاه‌های ثبت‌شده ریست می‌شوند.", "adrc")

    async def cb_tool_devices_ask_o(self, ctx, token):
        await self._tool_ask(ctx, "o", token, "همه دستگاه‌های ثبت‌شده این اکانت ریست می‌شوند.", "odrc")

    async def cb_tool_devices_a(self, ctx, token):
        await self._tool_do(ctx, "a", token, "devices/reset", "✅ دستگاه‌ها ریست شد.")

    async def cb_tool_devices_o(self, ctx, token):
        await self._tool_do(ctx, "o", token, "devices/reset", "✅ دستگاه‌ها ریست شد.")

    async def cb_tool_suspend_ask(self, ctx, token):
        await self._tool_ask(ctx, "o", token, "اکانت تعلیق می‌شود و مشتری نمی‌تواند وصل شود.", "ospc")

    async def cb_tool_suspend(self, ctx, token):
        await self._tool_do(ctx, "o", token, "suspend", "✅ اکانت تعلیق شد.", body={"reason": "از بات تلگرام"})

    async def cb_tool_resume(self, ctx, token):
        await self._tool_do(ctx, "o", token, "resume", "✅ اکانت فعال شد.")
