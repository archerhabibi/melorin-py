"""Core + Telegram transport for the main bot: per-update Ctx (CoreError re-exported), persistence and HTTP helpers."""

import json
import logging
import httpx

from tgmain.ui import (
    MAIN_MENU,
    keyboard,
    reply_keyboard,
)
from tgmain.errors import CoreError

log = logging.getLogger("melorin.telegram.main")


class Ctx:
    def __init__(self, chat_id, user, pair, update_id, callback_id=None, message_id=None, incoming_id=None):
        self.chat_id, self.user, self.pair = chat_id, user, pair
        self.update_id, self.callback_id = update_id, callback_id
        self.message_id = message_id  # the tapped message (callbacks only) -> edited in place
        self.incoming_id = incoming_id  # the user's own text message (plain messages only) -> may be deleted (secrets)

    @property
    def idem(self) -> str:
        return f"tg-{self.callback_id or self.update_id}"


class TransportMixin:
    """Offset/state persistence, Telegram Bot API calls, Core HTTP calls and in-place screens."""

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
            payload = {
                "chat_id": ctx.chat_id,
                "message_id": ctx.message_id,
                "text": text[:4000],
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True},
            }
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
        r = await self.client.post(
            f"https://api.telegram.org/bot{self.token}/sendPhoto", data=data, files={"photo": ("qr.png", png, "image/png")}
        )
        r.raise_for_status()

    def main_menu_rows(self, chat_id) -> list:
        """Reply-keyboard rows for this chat (reseller bots tailor them: owners get a management button)."""
        return MAIN_MENU

    async def send_main_menu(self, chat_id, text: str) -> None:
        await self.send(chat_id, text, self.main_menu_rows(chat_id), reply=True)

    async def api(self, ctx: Ctx, method: str, path: str, **kw) -> dict | list:
        headers = {"Authorization": f"Bearer {ctx.pair['access_token']}", "Accept": "application/json", **kw.pop("headers", {})}
        r = await self.client.request(method, f"{self.core}{path}", headers=headers, **kw)
        if r.status_code >= 500:
            r.raise_for_status()  # transient: let the runner retry the update
        if r.status_code >= 400:
            raise CoreError(r.status_code, self._err(r), self._code(r))
        return r.json()

    @staticmethod
    def _code(r: httpx.Response) -> str | None:
        try:
            d = r.json()
            e = d.get("error", d) if isinstance(d, dict) else {}
            code = e.get("code") if isinstance(e, dict) else None
            return code if isinstance(code, str) else None
        except Exception:  # noqa: BLE001
            return None

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
            "telegram_id": user["id"],
            "first_name": user.get("first_name"),
            "last_name": user.get("last_name"),
            "username": user.get("username"),
            "language_code": user.get("language_code"),
            "store_id": store["id"],
        }
        if referral:
            body["referral_code"] = referral
        r = await self.client.post(
            f"{self.core}/api/v1/auth/telegram/bot", headers={"X-Bot-Secret": self.secret, "Accept": "application/json"}, json=body
        )
        if r.status_code == 403 and self._code(r) == "ADMIN_USE_PANEL":
            # The Telegram ID of the main admin (given at install time) is only an alert address: admins never get a store session.
            raise CoreError(403, self._err(r), "ADMIN_USE_PANEL")
        r.raise_for_status()
        return r.json()

    # ----- shop: bundle -> (location) -> packages -> (username) -> quote -> pay -----
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

    async def forget_message(self, ctx) -> None:
        """Best-effort removal of a message holding a secret (the bot token). Bots may delete a user's message in private chats."""
        if ctx.incoming_id:
            try:
                await self.tg("deleteMessage", {"chat_id": ctx.chat_id, "message_id": ctx.incoming_id})
            except (httpx.HTTPError, RuntimeError):
                log.warning("could not delete the message that carried the bot token")
