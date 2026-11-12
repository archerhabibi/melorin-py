"""Core + Telegram transport for the main bot: per-update Ctx (CoreError re-exported), persistence and HTTP helpers."""

import asyncio
import json
import logging
import os
import time
import httpx

from tgmain.ui import (
    MAIN_MENU,
    has_styling,
    keyboard,
    reply_keyboard,
    set_button_styles,
    strip_styling,
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


def atomic_write_json(path, data) -> None:
    """Crash-safe JSON write (T29): unique temp file in the same directory, fsync, then atomic rename.

    A kill between write and rename leaves the previous file intact; a half-written file is never visible.
    """
    import os
    import tempfile
    from pathlib import Path

    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def env_seconds(name: str, default: float) -> float:
    """A positive number of seconds from the environment; a typo or a non-positive value must not stop the bot at import."""
    try:
        value = float(os.getenv(name, "") or default)
    except ValueError:
        return default
    return value if value > 0 else default


class TransportMixin:
    """Offset/state persistence, Telegram Bot API calls, Core HTTP calls and in-place screens."""

    # ---------- persistence ----------
    def _load_offset(self) -> int | None:
        try:
            return int(json.loads(self.offset_file.read_text())["offset"])
        except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError):
            return None

    def _save_offset(self, offset: int) -> None:
        atomic_write_json(self.offset_file, {"offset": offset})
        self.offset = offset

    # Per-chat flow state expires (T29/T60): an abandoned "waiting for receipt" must not hang forever or grow the file without bound.
    STATE_TTL = float(os.getenv("MELORIN_STATE_TTL_SECONDS", "86400"))

    AT_KEY = "__at__"  # reserved key in the (flat, backward compatible) state file: {chat_id: last-write epoch}

    def _load_state(self) -> dict:
        """Read the flat ``{chat_id: state}`` file; ``__at__`` carries per-chat write times and is absent in older files."""
        self.state_at = {}
        try:
            data = json.loads(self.state_file.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        stamps = data.pop(self.AT_KEY, None)
        if isinstance(stamps, dict):
            self.state_at = {str(k): float(v) for k, v in stamps.items() if str(k) in data and isinstance(v, (int, float))}
        now = time.time()
        for chat in data:
            self.state_at.setdefault(str(chat), now)  # no stamp yet: start its clock now
        return data

    def _persist_state(self) -> None:
        atomic_write_json(self.state_file, {**self.state, self.AT_KEY: getattr(self, "state_at", {})})

    def _set_state(self, chat_id, value: dict | None) -> None:
        key = str(chat_id)
        at = self.__dict__.setdefault("state_at", {})
        if value is None:
            self.state.pop(key, None)
            at.pop(key, None)
        else:
            self.state[key] = value
            at[key] = time.time()
        self._persist_state()

    def _expire_state(self, now: float | None = None) -> int:
        """Drop chats whose state is older than ``STATE_TTL``. Returns how many were removed."""
        now = time.time() if now is None else now
        at = self.__dict__.setdefault("state_at", {})
        stale = [c for c in list(self.state) if now - at.get(c, now) > self.STATE_TTL]
        for c in stale:
            self.state.pop(c, None)
            at.pop(c, None)
        if stale:
            self._persist_state()
        return len(stale)

    # ---------- transport ----------
    # Telegram answers 429 with ``parameters.retry_after`` (seconds). Honour it a bounded number of times (T22).
    TG_MAX_RETRIES = 3
    TG_MAX_WAIT = 30.0

    @staticmethod
    def retry_after_of(r: httpx.Response) -> float | None:
        """Seconds Telegram asks us to wait on a 429, or None when the response is not a usable flood-wait."""
        if r.status_code != 429:
            return None
        try:
            wait = float((r.json().get("parameters") or {}).get("retry_after"))
        except (ValueError, TypeError, AttributeError):
            wait = float(r.headers.get("retry-after", "") or 1)
        return max(0.0, wait)

    STYLE_REFRESH_SECONDS = env_seconds("MELORIN_BUTTON_STYLE_REFRESH_SECONDS", 60.0)
    STYLE_RETRY_SECONDS = 10.0
    _styles_at = 0.0

    async def refresh_button_styles(self) -> None:
        """Download the admin's button styling from Core (at most once per ``STYLE_REFRESH_SECONDS``).

        Best effort: on any failure the previous styling stays, and a bot that never reached Core simply sends plain buttons.
        """
        now = time.monotonic()
        last = TransportMixin._styles_at
        if last and now - last < self.STYLE_REFRESH_SECONDS:
            return
        TransportMixin._styles_at = now  # shared by every bot of the process (one Core, one styling): one fetch per interval
        try:
            r = await self.client.get(f"{self.core}/api/v1/telegram/button-styles", timeout=5.0)
            if r.status_code == 200:
                set_button_styles(r.json())
                return
            log.debug("button styles answered %s; keeping the previous ones", r.status_code)
        except (httpx.HTTPError, ValueError):
            log.debug("button styles unavailable; keeping the previous ones")
        # Core not ready yet (the bot came up first, a restart, a 5xx): try again soon instead of waiting a whole interval.
        TransportMixin._styles_at = now - max(0.0, self.STYLE_REFRESH_SECONDS - self.STYLE_RETRY_SECONDS)

    # 400 answers that have nothing to do with a button style: retrying without style would only repeat the same refusal.
    _NOT_STYLE_REASONS = (
        "not modified",
        "message to edit not found",
        "message can't be edited",
        "can't parse entities",
        "chat not found",
        "message is too long",
        "message text is empty",
        "text must be non-empty",
        "reply markup is too long",
        "button_data_invalid",
        "button_url_invalid",
        "wrong http url",
        "url host is empty",
        "wrong file identifier",
        "wrong remote file identifier",
        "user not found",
    )

    @staticmethod
    def _reason_of(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return ""
        return str(body.get("description", "")).lower() if isinstance(body, dict) else ""

    @classmethod
    def _style_refused(cls, response: httpx.Response, markup) -> bool:
        """A 400 on a styled keyboard whose reason is not one of the unrelated ones: worth one retry without the styling."""
        if response.status_code != 400 or not has_styling(markup):
            return False
        reason = cls._reason_of(response)
        return not any(m in reason for m in cls._NOT_STYLE_REASONS)

    async def tg(self, method: str, payload: dict) -> dict:
        try:
            return await self._tg(method, payload)
        except httpx.HTTPStatusError as exc:
            # Telegram refuses a button style / Premium emoji it cannot show (e.g. an invalid id): never lose the message.
            markup = payload.get("reply_markup")
            if self._style_refused(exc.response, markup):
                log.warning("telegram refused styled buttons on %s; retrying without style/icon", method)
                return await self._tg(method, {**payload, "reply_markup": strip_styling(markup)})
            raise

    async def _tg(self, method: str, payload: dict) -> dict:
        for attempt in range(self.TG_MAX_RETRIES + 1):
            r = await self.client.post(f"https://api.telegram.org/bot{self.token}/{method}", json=payload)
            wait = self.retry_after_of(r)
            if wait is not None and attempt < self.TG_MAX_RETRIES and wait <= self.TG_MAX_WAIT:
                log.warning("telegram 429 on %s, waiting %.0fs (retry %d/%d)", method, wait, attempt + 1, self.TG_MAX_RETRIES)
                await asyncio.sleep(wait + 0.5)
                continue
            break
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

    async def send_photo(
        self, chat_id, png: bytes, caption: str, rows=None, *, filename: str = "qr.png", mime: str = "image/png"
    ) -> None:
        data = {"chat_id": str(chat_id), "caption": caption[:1024], "parse_mode": "HTML"}
        if rows:
            data["reply_markup"] = json.dumps(keyboard(rows))
        url = f"https://api.telegram.org/bot{self.token}/sendPhoto"
        r = await self.client.post(url, data=data, files={"photo": (filename, png, mime)})
        if rows and self._style_refused(r, keyboard(rows)):  # styled buttons refused: resend plain
            log.warning("telegram refused styled buttons on sendPhoto; retrying without style/icon")
            data["reply_markup"] = json.dumps(strip_styling(keyboard(rows)))
            r = await self.client.post(url, data=data, files={"photo": (filename, png, mime)})
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

    async def api_file(self, ctx: Ctx, path: str) -> tuple[bytes, str]:
        """GET a binary Core resource (a ticket picture): (content, content type)."""
        headers = {"Authorization": f"Bearer {ctx.pair['access_token']}"}
        r = await self.client.get(f"{self.core}{path}", headers=headers)
        if r.status_code >= 500:
            r.raise_for_status()  # transient: let the runner retry the update
        if r.status_code >= 400:
            raise CoreError(r.status_code, self._err(r), self._code(r))
        return r.content, r.headers.get("content-type", "image/jpeg").split(";")[0].strip()

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
