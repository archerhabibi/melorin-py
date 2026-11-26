"""Mandatory channel membership ("force join"): the join screen and the "✅ I joined" button.

Core decides (``CHANNEL_JOIN_REQUIRED`` from ``/auth/telegram/bot``, with the admin's message and the channels still to
join); the bot only draws it. A ``/start`` payload that arrived while the user was gated (``link_…``, ``wl_…``) is kept in
the chat state and replayed once membership is confirmed, so a deep link is never lost. Referral codes need no replay:
Core records the sign-up (and its referral) before it refuses the session.
"""

import logging

import httpx

from tgmain.client import Ctx
from tgmain.errors import CoreError
from tgmain.ui import JOIN_CHECK_DATA, JOIN_CONFIRMED, JOIN_NOT_YET, esc, join_rows

log = logging.getLogger("melorin.telegram.main")

MAX_START_ARG = 64  # Telegram caps /start payloads at 64 chars


class ChannelJoinMixin:
    async def show_join_gate(self, message: dict, callback: dict | None, text: str, arg: str, exc: CoreError) -> None:
        chat_id = message["chat"]["id"]
        if callback and (callback.get("data") or "") == JOIN_CHECK_DATA:
            # Tapped "I joined" but Core still says no: a pop-up is enough, the screen stays as it is.
            await self.tg("answerCallbackQuery", {"callback_query_id": callback["id"], "text": JOIN_NOT_YET, "show_alert": True})
            return
        if text.lower().startswith("/start") and arg:
            self._merge_state(chat_id, join_start=arg[:MAX_START_ARG])
        channels = [c for c in (exc.details.get("channels") or []) if isinstance(c, dict) and c.get("url")]
        await self.send(chat_id, f"🔒 {esc(exc.message)}", join_rows(channels), html=True)

    async def cb_join_check(self, ctx: Ctx, _rest: str) -> None:
        """Only reached when Core opened a session, i.e. the user is now a member of every required channel."""
        try:
            await self.tg("answerCallbackQuery", {"callback_query_id": ctx.callback_id, "text": JOIN_CONFIRMED})
        except (httpx.HTTPError, RuntimeError):
            log.debug("could not answer the join check callback")
        if ctx.message_id:
            try:
                await self.tg("deleteMessage", {"chat_id": ctx.chat_id, "message_id": ctx.message_id})
            except (httpx.HTTPError, RuntimeError):
                pass  # older than 48 h: it simply stays
        pending = (self.state.get(str(ctx.chat_id)) or {}).get("join_start") or ""
        if pending:
            self._merge_state(ctx.chat_id, join_start=None)
        await self.cmd_start(ctx, pending)
