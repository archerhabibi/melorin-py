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
  * Purchases are non-refundable upstream: revoke_account only releases the mapping; Melorin refunds its own customer.
  * suspend/resume/usage are not exposed by the parent bot. Renewal works only when ``config.renew`` is configured.
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
    "max_price": 0,  # toman; 0 = refuse to buy (forces the admin to set a safety cap)
    "step_timeout": 25,
    "delivery_timeout": 60,
    "poll_interval": 1.2,
    "lock_ttl": 180,
    "plans": [],  # optional explicit [{"traffic_gb": 10, "months": 1, "label": "10 گیگ یک ماهه"}]
    "renew": {},  # {"menu": "خریدهای من", "renew_button": "تمدید", "confirm_button": "تایید"}  (unverified flow)
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
                pass


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
                pass
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
        return Capabilities(suspend=False, extend=bool(self.cfg.get("renew")), subscription_url=True, traffic_reset=False)

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
            await c.send_text(self.cfg["menu_buy"])
            m = await self._wait(lambda x: bool(x.buttons), after_id=after)
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
            status="active" if d.get("status") == "active" else "unknown",
            expire_at=exp,
            traffic_limit_bytes=int(d.get("traffic_limit_bytes") or 0),
            traffic_used_bytes=0,
            subscription_url=url,
            links=[url] if url else [],
        )

    def remember(self, username: str, ref: str | None) -> None:
        """Re-seed the mapping from VpnAccount.panel_ref (Redis may have been flushed)."""
        if ref and f"upstream_bot:{self.store.ns}:acc:{username}" not in _MEM:
            _MEM[self.store._k(username)] = json.dumps({"status": "active", "ref": ref}, ensure_ascii=False)

    async def get_account(self, username: str) -> PanelAccount | None:
        d = await self.store.get(username)
        if d and d.get("status") == "pending":
            async with self._lock():
                return await self._recover(username)
        if not d or d.get("status") != "active":
            return None
        return self._account(username, d)

    async def suspend_account(self, username: str) -> None:
        raise PanelError(ErrorKind.PERMANENT, "upstream_bot: the parent bot cannot suspend accounts")

    async def resume_account(self, username: str) -> None:
        raise PanelError(ErrorKind.PERMANENT, "upstream_bot: the parent bot cannot resume accounts")

    async def extend_account(self, username: str, *, expire_at: dt.datetime | None, traffic_bytes: int) -> PanelAccount:
        rcfg = self.cfg.get("renew") or {}
        d = await self.store.get(username)
        if not rcfg:
            raise PanelError(ErrorKind.PERMANENT, "upstream_bot: renewal flow is not configured (config.renew); needs manual handling")
        if not d or not d.get("ref"):
            raise PanelError(ErrorKind.PERMANENT, "upstream_bot: unknown upstream account for renewal")
        cap = int(self.cfg["max_price"] or 0)
        if cap <= 0:
            raise PanelError(ErrorKind.PERMANENT, "upstream_bot: config.max_price must be set before automatic renewals")
        async with self._lock():
            c = self._client()
            after = await self._top_id()
            await c.send_text(rcfg.get("menu", "خریدهای من"))
            lst = await self._wait(lambda x: bool(x.buttons), after_id=after)
            acc = self._find_button(lst, d["ref"]) if lst else None
            if not acc:
                raise PanelError(ErrorKind.PERMANENT, f"upstream_bot: account {d['ref']} not found in the purchases list")
            await c.click(lst, acc)
            det = await self._wait(
                lambda x: any(rcfg.get("renew_button", "تمدید") in b.text for b in x.buttons), after_id=after, watch={lst.id}
            )
            if not det:
                raise PanelError(ErrorKind.PERMANENT, "upstream_bot: renew button not found")
            await c.click(det, self._find_button(det, rcfg.get("renew_button", "تمدید")))
            plans = await self._wait(lambda x: any(parsing.parse_plan_label(b.text) for b in x.buttons), after_id=after, watch={det.id})
            if not plans:
                raise PanelError(ErrorKind.PERMANENT, "upstream_bot: renewal plan list did not appear")
            btn, plan = self._pick_plan(plans, AccountSpec(username, expire_at, traffic_bytes))
            if plan.price > cap:
                raise PanelError(ErrorKind.PERMANENT, f"upstream_bot: renewal price {plan.price} exceeds max_price {cap}")
            await c.click(plans, btn)
            conf = await self._wait(
                lambda x: any(rcfg.get("confirm_button", "تایید") in b.text for b in x.buttons), after_id=after, watch={plans.id}
            )
            amount = parsing.confirm_amount(conf.text) if conf else None
            if not conf or (amount is not None and amount != plan.price):
                raise PanelError(ErrorKind.PERMANENT, "upstream_bot: renewal confirmation missing or price mismatch")
            await c.click(conf, self._find_button(conf, rcfg.get("confirm_button", "تایید")))
            ok = await self._wait(
                lambda x: any(w in x.text for w in rcfg.get("success_words", ["تمدید شد", "با موفقیت"])),
                after_id=after,
                timeout=float(self.cfg["delivery_timeout"]),
            )
            if not ok:
                raise PanelError(ErrorKind.UNKNOWN, "upstream_bot: renewal confirmed but no success message")
            d.update(expire_at=expire_at.isoformat() if expire_at else None, traffic_limit_bytes=int(plan.traffic_gb * GB))
            await self.store.set(username, d)
            return self._account(username, d)

    async def revoke_account(self, username: str) -> None:
        """Upstream purchases are non-refundable and cannot be deleted; only release the local mapping."""
        d = await self.store.get(username)
        if d:
            d["status"] = "revoked"
            await self.store.set(username, d)

    async def close(self) -> None:
        if self._chat is not None:
            await self._chat.close()

    def normalize_status(self, raw: str) -> str:
        return raw if raw in {"active", "disabled", "expired", "limited"} else "unknown"
