"""Upstream-bot panel adapter: buys / (optionally) renews accounts by driving a parent VPN bot as a customer.

Use when the parent bot has no API. A dedicated Telegram *user* session (Telethon StringSession) chats with the parent
bot exactly like a person: menu -> service -> plan -> confirm -> delivery message. The adapter is the only place that
knows this; Core sees an ordinary PanelAdapter.

Panel fields
  base_url     : "https://t.me/<bot_username>"  (informational; no HTTP calls are ever made to it)
  credentials  : {"api_id": 123, "api_hash": "...", "session": "<Telethon StringSession>"}   (stored encrypted)
  config       : see DEFAULTS below. Every button text is configurable because the parent bot may rename its menus.

Honest limits
  * The parent bot names accounts itself, so Melorin's username is mapped to the upstream name (Redis + VpnAccount.panel_ref).
  * Refund (مرجوعی) is real: revoke_account presses "مرجوعی اکانت" and the parent bot credits its wallet back (its rules:
    volume accounts only, <= 3 days, <= 5 % used, 3 per day - the same numbers as Melorin's own return policy).
  * Usage / expiry / status are read live from the parent bot's account screen ("خریدهای من" -> "جستجوی اکانت").
  * suspend/resume are not exposed by the parent bot. Renewal ("تمدید اکانت") is real and ON by default
    (``config.renew.enabled=false`` switches it off): account screen -> renew -> "تمدید با حجم اولیه" -> "تایید تمدید اکانت".
    The parent bot restarts the package from now (new expiry, usage back to 0), exactly what Core's renewal promises.
  * Money safety: the confirm prompt amount must equal the chosen plan price and be <= ``max_price`` or the purchase is cancelled.
  * Calls are serialised by a distributed lock: one chat, one flow at a time.
"""

import asyncio
import datetime as dt
import json
import logging
import re
import time
import uuid

from melorin.modules.vpn.adapters.base import GB, AccountSpec, Capabilities, ErrorKind, PanelAccount, PanelError
from melorin.modules.vpn.adapters.upstream_bot import parsing
from melorin.modules.vpn.adapters.upstream_bot.chat import Button, ChatClient, Msg

log = logging.getLogger("melorin.upstream_bot")

DEFAULTS = {
    "menu_buy": "خرید اکانت",
    "service_button": "سرویس اقتصادی",
    "confirm_button": "تایید خرید",
    "cancel_button": "انصراف",
    "start_command": "/start",
    "menu_purchases": "خریدهای من",
    "search_button": "جستجوی اکانت",
    "refund_button": "مرجوعی اکانت",
    "refund_confirm_button": "تایید میکنم",
    "link_button": "لینک",
    "status_ttl": 60,  # seconds a live read of the account screen is reused
    "max_price": 0,  # toman; 0 = refuse to buy (forces the admin to set a safety cap)
    "step_timeout": 25,
    "delivery_timeout": 60,
    "poll_interval": 1.2,
    "lock_ttl": 180,
    "plans": [],  # optional explicit [{"traffic_gb": 10, "months": 1, "label": "10 گیگ یک ماهه"}]
    # Renewal (verified on the real screens, 24 Oct 2026). Set {"enabled": false} to turn automatic renewals off.
    "renew": {
        "enabled": True,
        "renew_button": "تمدید اکانت",
        "confirm_button": "تایید تمدید",
        "cancel_button": "برگشت",
        "success_words": ["با موفقیت تمدید"],
        "settle_window": 600,  # seconds a confirmed-but-unanswered renewal blocks a second payment (retry reads the account instead)
    },
}

_MEM: dict[str, str] = {}
_LOCKS: dict[str, asyncio.Lock] = {}


def _redis():
    try:
        from melorin.core.redis import get_redis

        return get_redis()
    except Exception:  # pragma: no cover
        return None


class _Store:
    """username -> upstream account metadata. Redis when available, process memory otherwise."""

    def __init__(self, ns: str):
        self.ns = ns

    def _k(self, username: str) -> str:
        return f"upstream_bot:{self.ns}:acc:{username}"

    async def get(self, username: str) -> dict | None:
        r = _redis()
        raw = None
        if r is not None:
            try:
                raw = await r.get(self._k(username))
            except Exception:
                raw = None
        raw = raw or _MEM.get(self._k(username))
        return json.loads(raw) if raw else None

    async def set(self, username: str, data: dict) -> None:
        raw = json.dumps(data, ensure_ascii=False)
        _MEM[self._k(username)] = raw
        r = _redis()
        if r is not None:
            try:
                await r.set(self._k(username), raw)
            except Exception:
                log.warning("upstream_bot: redis write failed for mapping", exc_info=True)

    async def delete(self, username: str) -> None:
        _MEM.pop(self._k(username), None)
        r = _redis()
        if r is not None:
            try:
                await r.delete(self._k(username))
            except Exception:
                log.warning("upstream_bot: redis delete failed", exc_info=True)


class _ChatLock:
    def __init__(self, ns: str, ttl: int, wait: float):
        self.key, self.ttl, self.wait, self.token = f"upstream_bot:{ns}:lock", ttl, wait, uuid.uuid4().hex
        self._local = _LOCKS.setdefault(self.key, asyncio.Lock())
        self._held_redis = False

    async def __aenter__(self):
        await asyncio.wait_for(self._local.acquire(), self.wait)
        r, end = _redis(), time.monotonic() + self.wait
        if r is not None:
            while True:
                try:
                    if await r.set(self.key, self.token, nx=True, ex=self.ttl):
                        self._held_redis = True
                        break
                except Exception:
                    break  # redis down: the process-local lock still serialises this worker
                if time.monotonic() > end:
                    self._local.release()
                    raise PanelError(ErrorKind.TRANSIENT, "upstream_bot: chat is busy, retry later")
                await asyncio.sleep(0.5)
        return self

    async def __aexit__(self, *exc):
        r = _redis()
        if r is not None and self._held_redis:
            try:
                if await r.get(self.key) == self.token:
                    await r.delete(self.key)
            except Exception:
                log.warning("upstream_bot: redis delete failed", exc_info=True)
        self._local.release()


def _months_between(now: dt.datetime, expire_at: dt.datetime | None) -> int:
    if not expire_at:
        return 1
    exp = expire_at if expire_at.tzinfo else expire_at.replace(tzinfo=dt.UTC)
    return max(1, round((exp - now).total_seconds() / 86400 / 30))


class UpstreamBotAdapter:
    kind = "upstream_bot"

    def __init__(self, base_url: str, credentials: dict | None = None, config: dict | None = None, chat: ChatClient | None = None, **_):
        self.base_url = (base_url or "").strip()
        self.creds = credentials or {}
        self.cfg = {**DEFAULTS, **(config or {})}
        m = re.search(r"(?:t\.me/|@)?([A-Za-z0-9_]{5,})/?$", self.base_url)
        self.bot = (self.cfg.get("bot_username") or (m.group(1) if m else "")).lstrip("@")
        if not self.bot:
            raise PanelError(ErrorKind.PERMANENT, "upstream_bot: base_url must be https://t.me/<bot_username>")
        self._chat = chat
        self.store = _Store(self.bot.lower())

    # ----------------------------------------------------------------- plumbing
    def _client(self) -> ChatClient:
        if self._chat is None:
            try:
                api_id, api_hash, session = int(self.creds["api_id"]), str(self.creds["api_hash"]), str(self.creds["session"])
            except (KeyError, ValueError, TypeError) as exc:
                raise PanelError(ErrorKind.PERMANENT, "upstream_bot: credentials need api_id, api_hash and session") from exc
            from melorin.modules.vpn.adapters.upstream_bot.telethon_chat import TelethonChat

            self._chat = TelethonChat(api_id, api_hash, session, self.bot, timeout=float(self.cfg["step_timeout"]))
        return self._chat

    def _lock(self) -> _ChatLock:
        return _ChatLock(self.bot.lower(), int(self.cfg["lock_ttl"]), float(self.cfg["delivery_timeout"]) + 30)

    async def _top_id(self) -> int:
        msgs = await self._client().recent(5)
        return max((m.id for m in msgs), default=0)

    async def _wait(self, pred, *, after_id: int, watch: set[int] | None = None, timeout: float | None = None) -> Msg | None:
        """First message (newest first) matching ``pred`` that is new (id > after_id) or one of ``watch`` (edited in place)."""
        end = time.monotonic() + float(timeout or self.cfg["step_timeout"])
        while True:
            for m in await self._client().recent(12):
                if (m.id > after_id or (watch and m.id in watch)) and pred(m):
                    return m
            if time.monotonic() > end:
                return None
            await asyncio.sleep(float(self.cfg["poll_interval"]))

    @staticmethod
    def _find_button(msg: Msg, needle: str) -> Button | None:
        for b in msg.buttons:
            if needle and needle in b.text:
                return b
        return None

    async def _menu(self, label: str) -> tuple[int, Msg]:
        """Reset the chat with /start, then press the main-menu button whose text contains ``label``.

        The reply keyboard is taken from the parent bot itself, so the exact button text (emoji included) is sent as-is.
        Returns (id of the newest message before pressing, the message that carried the button).
        """
        c = self._client()
        after = await self._top_id()
        await c.send_text(self.cfg["start_command"])
        m = await self._wait(lambda x: self._find_button(x, label) is not None, after_id=after)
        if not m:
            raise PanelError(ErrorKind.TRANSIENT, f"upstream_bot: main menu button '{label}' did not appear after /start")
        mark = await self._top_id()
        await c.click(m, self._find_button(m, label))
        return mark, m

    async def _open_detail(self, ref: str) -> tuple[int, Msg, parsing.AccountDetail]:
        """Main menu -> my purchases -> search -> send the upstream name -> the account screen (with its buttons)."""
        c = self._client()
        mark, _ = await self._menu(self.cfg["menu_purchases"])
        sm = await self._wait(lambda x: self._find_button(x, self.cfg["search_button"]) is not None, after_id=mark)
        if not sm:
            raise PanelError(ErrorKind.TRANSIENT, "upstream_bot: purchases screen / search button did not appear")
        mark2 = await self._top_id()
        await c.click(sm, self._find_button(sm, self.cfg["search_button"]))
        ask = await self._wait(lambda x: "اسم اکانت" in x.text or "نام اکانت" in x.text, after_id=mark2)
        if not ask:
            raise PanelError(ErrorKind.TRANSIENT, "upstream_bot: search prompt did not appear")
        mark3 = await self._top_id()
        await c.send_text(ref)
        det = await self._wait(lambda x: (d := parsing.parse_account_detail(x.text)) is not None and d.name == ref, after_id=mark3)
        if not det:
            raise PanelError(ErrorKind.PERMANENT, f"upstream_bot: account {ref} was not found in the parent bot")
        return mark3, det, parsing.parse_account_detail(det.text)

    def _pick_plan(self, msg: Msg, spec: AccountSpec) -> tuple[Button, parsing.PlanButton]:
        gb = round(spec.traffic_bytes / GB, 2) if spec.traffic_bytes else 0
        months = _months_between(dt.datetime.now(dt.UTC), spec.expire_at)
        for p in self.cfg["plans"]:
            if float(p.get("traffic_gb", -1)) == gb and int(p.get("months", 1)) == months:
                b = self._find_button(msg, p["label"])
                parsed = parsing.parse_plan_label(b.text) if b else None
                if b and parsed:
                    return b, parsed
        for b in msg.buttons:
            p = parsing.parse_plan_label(b.text)
            if p and abs(p.traffic_gb - gb) < 0.01 and p.months == months:
                return b, p
        raise PanelError(ErrorKind.PERMANENT, f"upstream_bot: no plan for {gb} GB / {months} month(s) in the parent bot menu")

    # ----------------------------------------------------------------- PanelAdapter
    async def health_check(self) -> bool:
        try:
            await self._client().recent(1)
            return True
        except PanelError:
            return False

    def capabilities(self) -> Capabilities:
        return Capabilities(
            suspend=False, extend=bool((self.cfg.get("renew") or {}).get("enabled")), subscription_url=True, traffic_reset=False
        )

    async def create_account(self, spec: AccountSpec) -> PanelAccount:
        cap = int(self.cfg["max_price"] or 0)
        if cap <= 0:
            raise PanelError(ErrorKind.PERMANENT, "upstream_bot: config.max_price (toman) must be set before automatic purchases")
        # A previous attempt may have bought and timed out: never pay twice for the same Melorin username.
        known = await self.store.get(spec.username)
        if known and known.get("status") == "active":
            return self._account(spec.username, known)
        async with self._lock():
            recovered = await self._recover(spec.username)
            if recovered:
                return recovered
            c = self._client()
            after = await self._top_id()
            after, _ = await self._menu(self.cfg["menu_buy"])
            m = await self._wait(lambda x: self._find_button(x, self.cfg["service_button"]) is not None, after_id=after)
            if not m:
                raise PanelError(ErrorKind.TRANSIENT, "upstream_bot: no response to the buy menu")
            svc = self._find_button(m, self.cfg["service_button"])
            if not svc:
                raise PanelError(ErrorKind.PERMANENT, f"upstream_bot: service button '{self.cfg['service_button']}' not found")
            await c.click(m, svc)
            plans = await self._wait(lambda x: any(parsing.parse_plan_label(b.text) for b in x.buttons), after_id=after, watch={m.id})
            if not plans:
                raise PanelError(ErrorKind.TRANSIENT, "upstream_bot: plan list did not appear")
            btn, plan = self._pick_plan(plans, spec)
            if plan.price > cap:
                raise PanelError(ErrorKind.PERMANENT, f"upstream_bot: plan price {plan.price} exceeds max_price {cap}")
            await c.click(plans, btn)
            conf = await self._wait(lambda x: parsing.is_confirm_prompt(x.text) and bool(x.buttons), after_id=after, watch={plans.id})
            if not conf:
                raise PanelError(ErrorKind.TRANSIENT, "upstream_bot: confirmation prompt did not appear")
            amount = parsing.confirm_amount(conf.text)
            if amount != plan.price or amount > cap:
                cancel = self._find_button(conf, self.cfg["cancel_button"])
                if cancel:
                    await c.click(conf, cancel)
                raise PanelError(
                    ErrorKind.PERMANENT, f"upstream_bot: price mismatch (menu {plan.price}, confirm {amount}); purchase cancelled"
                )
            ok = self._find_button(conf, self.cfg["confirm_button"])
            if not ok:
                raise PanelError(ErrorKind.PERMANENT, f"upstream_bot: confirm button '{self.cfg['confirm_button']}' not found")
            await self.store.set(spec.username, {"status": "pending", "started": time.time(), "after_id": after, "price": plan.price})
            await c.click(conf, ok)  # --- point of no return: from here a failure is UNKNOWN, never TRANSIENT ---
            done = await self._wait(
                lambda x: parsing.parse_purchase_result(x.text) is not None, after_id=after, timeout=float(self.cfg["delivery_timeout"])
            )
            if not done:
                low = await self._wait(lambda x: parsing.is_insufficient_balance(x.text), after_id=after, timeout=3)
                if low:
                    await self.store.delete(spec.username)
                    raise PanelError(ErrorKind.PERMANENT, "upstream_bot: parent bot wallet balance is too low, top it up")
                raise PanelError(ErrorKind.UNKNOWN, "upstream_bot: purchase confirmed but no delivery message yet")
            return await self._finish(spec, done, plan)

    async def _finish(self, spec: AccountSpec, msg: Msg, plan: parsing.PlanButton) -> PanelAccount:
        res = parsing.parse_purchase_result(msg.text)
        assert res is not None
        data = {
            "status": "active",
            "ref": res.name,
            "subscription_url": res.subscription_url,
            "expire_at": spec.expire_at.isoformat() if spec.expire_at else None,
            "traffic_limit_bytes": int(plan.traffic_gb * GB),
            "price": plan.price,
            "bought_at": time.time(),
        }
        await self.store.set(spec.username, data)
        return self._account(spec.username, data)

    async def _recover(self, username: str) -> PanelAccount | None:
        """After a timeout: look for a delivery message that arrived after the pending purchase started."""
        rec = await self.store.get(username)
        if not rec or rec.get("status") != "pending":
            return None
        for m in await self._client().recent(20):
            if (
                m.id > int(rec.get("after_id", 0))
                and m.date_ts >= float(rec.get("started", 0)) - 5
                and parsing.parse_purchase_result(m.text)
            ):
                taken = parsing.parse_purchase_result(m.text).name
                if await self._name_taken(taken):
                    continue
                res = parsing.parse_purchase_result(m.text)
                data = {**rec, "status": "active", "ref": res.name, "subscription_url": res.subscription_url, "bought_at": time.time()}
                await self.store.set(username, data)
                return self._account(username, data)
        return None

    async def _name_taken(self, upstream_name: str) -> bool:
        r = _redis()
        if r is None:
            return any(
                json.loads(v).get("ref") == upstream_name for k, v in _MEM.items() if k.startswith(f"upstream_bot:{self.store.ns}:acc:")
            )
        try:
            async for k in r.scan_iter(f"upstream_bot:{self.store.ns}:acc:*"):
                raw = await r.get(k)
                if raw and json.loads(raw).get("ref") == upstream_name:
                    return True
        except Exception:
            return False
        return False

    @staticmethod
    def _account(username: str, d: dict) -> PanelAccount:
        exp = dt.datetime.fromisoformat(d["expire_at"]) if d.get("expire_at") else None
        url = d.get("subscription_url")
        return PanelAccount(
            ref=d.get("ref") or username,
            username=username,
            status=(d.get("upstream_status") or "active") if d.get("status") == "active" else "unknown",
            expire_at=exp,
            traffic_limit_bytes=int(d.get("traffic_limit_bytes") or 0),
            traffic_used_bytes=int(d.get("traffic_used_bytes") or 0),
            subscription_url=url,
            links=[url] if url else [],
        )

    def remember(self, username: str, ref: str | None, subscription_url: str | None = None) -> None:
        """Re-seed the mapping from VpnAccount.panel_ref / subscription_url (Redis may have been flushed)."""
        key = self.store._k(username)
        if ref and key not in _MEM:
            _MEM[key] = json.dumps({"status": "active", "ref": ref, "subscription_url": subscription_url}, ensure_ascii=False)

    async def get_account(self, username: str) -> PanelAccount | None:
        d = await self.store.get(username)
        if d and d.get("status") == "pending":
            async with self._lock():
                return await self._recover(username)
        if not d or d.get("status") != "active":
            return None
        fresh_needed = bool(d.get("renew_pending"))
        ttl = float(self.cfg["status_ttl"])
        if not fresh_needed and time.time() - float(d.get("checked_at", 0)) < ttl:
            return self._account(username, d)
        try:
            async with self._lock():
                _, _, det = await self._open_detail(d["ref"])
                d = await self._apply_detail(username, d, det)
                if not d.get("subscription_url"):
                    d["subscription_url"] = await self._fetch_link(d["ref"])
                    await self.store.set(username, d)
        except PanelError as e:
            if e.kind == ErrorKind.PERMANENT and "not found" in e.message:
                return None  # the parent bot no longer knows it (e.g. refunded): Core records missing_on_panel
            log.warning("upstream_bot: live read failed for %s: %s - serving last known data", username, e.message)
        return self._account(username, d)

    async def _apply_detail(self, username: str, d: dict, det: parsing.AccountDetail) -> dict:
        d = {**d}
        limit = det.used_bytes + det.remaining_bytes if det.remaining_bytes is not None else d.get("traffic_limit_bytes", 0)
        d.update(
            expire_at=det.expire_at.isoformat() if det.expire_at else d.get("expire_at"),
            traffic_limit_bytes=int(limit),
            traffic_used_bytes=int(det.used_bytes),
            upstream_status=det.status,
            checked_at=time.time(),
        )
        d.pop("renew_pending", None)
        await self.store.set(username, d)
        return d

    async def _fetch_link(self, ref: str) -> str | None:
        """Best effort: press 'دریافت لینک و QR' and read the first /sub/ link. Never raises."""
        try:
            _, msg, _ = await self._open_detail(ref)
            btn = self._find_button(msg, self.cfg["link_button"])
            if not btn:
                return None
            mark = await self._top_id()
            await self._client().click(msg, btn)
            got = await self._wait(lambda x: bool(re.search(r"https?://\S+/sub/", x.text)), after_id=mark, watch={msg.id}, timeout=10)
            m = re.search(r"https?://\S+/sub/\S+", got.text) if got else None
            return m.group(0).rstrip(".,)") if m else None
        except PanelError:
            return None

    async def suspend_account(self, username: str) -> None:
        raise PanelError(ErrorKind.PERMANENT, "upstream_bot: the parent bot cannot suspend accounts")

    async def resume_account(self, username: str) -> None:
        raise PanelError(ErrorKind.PERMANENT, "upstream_bot: the parent bot cannot resume accounts")

    async def extend_account(self, username: str, *, expire_at: dt.datetime | None, traffic_bytes: int) -> PanelAccount:
        """Renew through the parent bot ("تمدید اکانت" -> "تمدید با حجم اولیه" -> "تایید تمدید اکانت").

        The parent bot restarts the package from now: new expiry, usage back to zero. Only the original volume is renewed
        automatically; a different volume ("تمدید و افزایش N گیگ") needs manual handling (PERMANENT, nothing is paid).
        Money safety: price comes from the chosen button and must be <= max_price; the confirm prompt must name this account;
        its printed amount is 0 in the real bot, so only 0 / the option price are accepted. After the confirm click every failure
        is UNKNOWN and a retry first reads the account screen: it never pays twice for one renewal.
        """
        r = {**DEFAULTS["renew"], **(self.cfg.get("renew") or {})}
        if not r.get("enabled"):
            raise PanelError(ErrorKind.PERMANENT, "upstream_bot: renewal is not enabled (config.renew.enabled); needs manual handling")
        d = await self.store.get(username)
        if not d or not d.get("ref"):
            raise PanelError(ErrorKind.PERMANENT, "upstream_bot: unknown upstream account for renewal")
        cap = int(self.cfg["max_price"] or 0)
        if cap <= 0:
            raise PanelError(ErrorKind.PERMANENT, "upstream_bot: config.max_price must be set before automatic renewals")
        ref = d["ref"]
        async with self._lock():
            c = self._client()
            _, det_msg, before = await self._open_detail(ref)
            if d.get("renew_started"):
                # an earlier attempt pressed confirm: decide from the account screen, never by paying again
                if self._renew_landed(d, before):
                    return await self._renew_done(username, d, before)
                if time.time() - float(d["renew_started"]) < float(r["settle_window"]):
                    raise PanelError(
                        ErrorKind.UNKNOWN, "upstream_bot: a renewal was confirmed moments ago and has not shown up yet; not paying twice"
                    )
                for k in ("renew_started", "renew_before_expire", "renew_before_renewed", "renew_price"):
                    d.pop(k, None)  # window over and nothing changed upstream: that confirm never took effect
            btn = self._find_button(det_msg, r["renew_button"])
            if not btn:
                raise PanelError(ErrorKind.PERMANENT, f"upstream_bot: button '{r['renew_button']}' not on the account screen")
            mark = await self._top_id()
            await c.click(det_msg, btn)
            opts = await self._wait(lambda x: parsing.parse_renew_screen(x.text) is not None, after_id=mark, watch={det_msg.id})
            if not opts:
                await self._raise_unrecognised(mark, "renewal options did not appear")
            screen = parsing.parse_renew_screen(opts.text)
            if screen.name != ref:
                raise PanelError(ErrorKind.PERMANENT, f"upstream_bot: renewal screen is for {screen.name}, expected {ref}")
            want_gb = round(traffic_bytes / GB, 2) if traffic_bytes else 0
            if abs(want_gb - screen.initial_gb) > 0.01:
                await self._cancel_flow(opts)
                raise PanelError(
                    ErrorKind.PERMANENT,
                    f"upstream_bot: parent bot renews {screen.initial_gb:g} GB (initial volume) but {want_gb:g} GB was requested; needs manual handling",
                )
            option = next(((b, o) for b in opts.buttons if (o := parsing.parse_renew_option(b.text)) and o.kind == "initial"), None)
            if not option:
                raise PanelError(ErrorKind.PERMANENT, "upstream_bot: 'renew with the initial volume' button not found")
            obtn, opt = option
            if opt.price > cap:
                await self._cancel_flow(opts)
                raise PanelError(ErrorKind.PERMANENT, f"upstream_bot: renewal price {opt.price} exceeds max_price {cap}")
            balance = await self._balance_after(mark)
            if balance is not None and balance < opt.price:
                await self._cancel_flow(opts)
                raise PanelError(
                    ErrorKind.PERMANENT,
                    f"upstream_bot: parent bot wallet balance {balance} is below the renewal price {opt.price}, top it up",
                )
            mark2 = await self._top_id()
            await c.click(opts, obtn)
            conf = await self._wait(
                lambda x: parsing.is_renew_confirm_prompt(x.text, ref) and bool(x.buttons), after_id=mark2, watch={opts.id}
            )
            if not conf:
                await self._raise_unrecognised(mark2, "renewal confirmation did not appear")
            amount = parsing.renew_confirm_amount(conf.text)
            ok = self._find_button(conf, r["confirm_button"])
            if amount not in (None, 0, opt.price) or amount is not None and amount > cap:
                await self._cancel_flow(conf, r["cancel_button"])
                raise PanelError(ErrorKind.PERMANENT, f"upstream_bot: renewal confirmation shows {amount}, expected {opt.price}; cancelled")
            if not ok:
                raise PanelError(ErrorKind.PERMANENT, f"upstream_bot: confirm button '{r['confirm_button']}' not found")
            d.update(
                renew_pending=True,  # get_account must now read fresh, never from cache
                renew_started=time.time(),
                renew_before_expire=before.expire_at.isoformat() if before.expire_at else None,
                renew_before_renewed=before.renewed_at.isoformat() if before.renewed_at else None,
                renew_price=opt.price,
            )
            await self.store.set(username, d)
            mark3 = await self._top_id()
            await c.click(conf, ok)  # --- point of no return: from here a failure is UNKNOWN, never TRANSIENT ---
            done = await self._wait(
                lambda x: any(w in x.text for w in r["success_words"]) and parsing.parse_renew_success(x.text, ref),
                after_id=mark3,
                watch={conf.id},
                timeout=float(self.cfg["delivery_timeout"]),
            )
            if not done:
                raise PanelError(
                    ErrorKind.UNKNOWN, "upstream_bot: renewal confirmed but no success message yet; the account screen decides on retry"
                )
            charged = await self._wait(lambda x: parsing.parse_charged_amount(x.text) is not None, after_id=mark3, timeout=5)
            if charged:
                d["renew_charged"] = parsing.parse_charged_amount(charged.text)
                if d["renew_charged"] != opt.price:  # money already moved: keep the renewal, make the anomaly loud
                    log.error("upstream_bot: %s renewed but the parent bot charged %s instead of %s", ref, d["renew_charged"], opt.price)
            _, _, after = await self._open_detail(ref)  # trust the account screen, not our own arithmetic
            if not self._renew_landed(d, after):
                raise PanelError(ErrorKind.UNKNOWN, "upstream_bot: success message seen but the account screen did not change")
            return await self._renew_done(username, d, after)

    @staticmethod
    def _renew_landed(d: dict, det: parsing.AccountDetail) -> bool:
        """Did the account screen change since the confirm click (new expiry or a new renewal date)?"""
        be, br = d.get("renew_before_expire"), d.get("renew_before_renewed")
        if det.expire_at is not None and det.expire_at.isoformat() != be:
            return True
        return det.renewed_at is not None and det.renewed_at.isoformat() != br

    async def _renew_done(self, username: str, d: dict, det: parsing.AccountDetail) -> PanelAccount:
        d = await self._apply_detail(username, d, det)
        for k in ("renew_started", "renew_before_expire", "renew_before_renewed"):
            d.pop(k, None)
        d["renewed_at_ts"] = time.time()
        await self.store.set(username, d)
        return self._account(username, d)

    async def _balance_after(self, mark: int) -> int | None:
        """The parent bot prints 'موجودی حساب شما: N تومان' right after the renew button. None when it did not."""
        m = await self._wait(lambda x: parsing.parse_balance(x.text) is not None, after_id=mark, timeout=3)
        return parsing.parse_balance(m.text) if m else None

    async def _cancel_flow(self, msg: Msg, label: str | None = None) -> None:
        """Best effort: press the cancel/back button of a half-finished flow so nothing stays armed. Never raises."""
        try:
            for needle in (label, "انصراف", "برگشت"):
                b = self._find_button(msg, needle) if needle else None
                if b:
                    await self._client().click(msg, b)
                    return
        except PanelError:
            log.warning("upstream_bot: could not press cancel on a half-finished flow", exc_info=True)

    async def _raise_unrecognised(self, mark: int, what: str) -> None:
        latest = await self._latest_text(mark)
        if parsing.is_operation_expired(latest):
            raise PanelError(ErrorKind.TRANSIENT, f"upstream_bot: {what}: the parent bot said the operation expired (stale buttons); retry")
        raise PanelError(ErrorKind.PERMANENT, f"upstream_bot: {what} (flow not recognised): {latest}")

    async def revoke_account(self, username: str) -> None:
        """Real refund (مرجوعی) through the parent bot; its wallet is credited back. Idempotent across outbox retries."""
        d = await self.store.get(username)
        if not d or not d.get("ref") or d.get("status") in ("revoked", "pending"):
            return
        if d.get("upstream_refunded"):
            d["status"] = "revoked"
            await self.store.set(username, d)
            return
        async with self._lock():
            c = self._client()
            try:
                _, det_msg, _ = await self._open_detail(d["ref"])
            except PanelError as e:
                if e.kind == ErrorKind.PERMANENT and "not found" in e.message and d.get("refund_started"):
                    # we already pressed confirm earlier and the account is gone upstream: the refund went through
                    d.update(upstream_refunded=True, status="revoked")
                    await self.store.set(username, d)
                    return
                raise
            btn = self._find_button(det_msg, self.cfg["refund_button"])
            if not btn:
                raise PanelError(ErrorKind.PERMANENT, f"upstream_bot: button '{self.cfg['refund_button']}' not on the account screen")
            mark = await self._top_id()
            await c.click(det_msg, btn)
            conf = await self._wait(lambda x: parsing.is_refund_confirm_prompt(x.text), after_id=mark, watch={det_msg.id})
            if not conf:
                reason = await self._latest_text(mark)
                raise PanelError(ErrorKind.PERMANENT, f"upstream_bot: parent bot did not offer a refund: {reason}")
            ok = self._find_button(conf, self.cfg["refund_confirm_button"])
            if not ok:
                raise PanelError(ErrorKind.PERMANENT, f"upstream_bot: button '{self.cfg['refund_confirm_button']}' not found")
            d["refund_started"] = time.time()
            await self.store.set(username, d)
            await c.click(conf, ok)
            done = await self._wait(
                lambda x: parsing.parse_refund_success(x.text), after_id=mark, watch={conf.id}, timeout=float(self.cfg["delivery_timeout"])
            )
            if not done:
                raise PanelError(ErrorKind.UNKNOWN, "upstream_bot: refund confirmed but no success message yet; will be re-checked")
            amount_msg = await self._wait(lambda x: parsing.parse_refund_amount(x.text) is not None, after_id=mark, timeout=5)
            d.update(
                upstream_refunded=True,
                status="revoked",
                refund_amount=parsing.parse_refund_amount(amount_msg.text) if amount_msg else None,
            )
            await self.store.set(username, d)

    async def _latest_text(self, after_id: int) -> str:
        msgs = [m for m in await self._client().recent(6) if m.id > after_id and m.text]
        return (msgs[0].text if msgs else "no answer").strip().replace("\n", " ")[:200]

    async def close(self) -> None:
        if self._chat is not None:
            await self._chat.close()

    def normalize_status(self, raw: str) -> str:
        return raw if raw in {"active", "disabled", "expired", "limited"} else "unknown"
