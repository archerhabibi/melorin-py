"""PasarGuard webhook (PG-03): what the panel pushes, how Melorin checks and reads it, and how Melorin switches it on at the panel.

**Wire format.** The panel POSTs a JSON *list* of events (a single object is tolerated) with the shared secret in the
``x-webhook-secret`` header. There is no HMAC: the secret itself is the credential, so the endpoint must be HTTPS-only and the
secret never logged. An event is ``{"action", "username", "enqueued_at", "tries"}`` plus, on newer panels, a stable ``id`` (the
same across the panel's own retries), ``by``, ``reason``, ``reset_traffic`` and ``user``. Delivery is at-least-once, so replays
are normal: the ``id`` (or action + username + enqueued_at) is the idempotency key.

**What Melorin trusts.** Only the fact that "something happened to this user". The payload is never used as state: the worker
re-reads the account from the panel (see ``modules/panelops/panel_events.py``), so a forged-but-authenticated, stale or out-of-order
event cannot write wrong data. The payload kept for audit is stripped of links and proxy settings (:func:`sanitize`).

The header name and body shape follow the Marzban/PasarGuard webhook and PasarGuard PR #1180 (``id``/``by``/``reason``); the panel's
OpenAPI does not describe them, so the parser is deliberately tolerant and everything unknown is stored as ``ignored``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from melorin.modules.panel_integrations.adapters.base import ErrorKind, PanelError

SECRET_HEADER = "x-webhook-secret"
MAX_EVENTS_PER_DELIVERY = 500
MAX_BODY_BYTES = 512 * 1024

USER_EVENTS = (
    "user_created",
    "user_updated",
    "user_deleted",
    "user_limited",
    "user_expired",
    "user_enabled",
    "user_disabled",
    "data_usage_reset",
    "data_reset_by_next",
    "subscription_revoked",
    "reached_usage_percent",
    "reached_days_left",
)

# event -> Melorin account status it implies (None = not a status change). Informational: processing re-reads the panel.
EVENT_STATUS = {
    "user_limited": "limited",
    "user_expired": "expired",
    "user_enabled": "active",
    "user_disabled": "disabled",
}

_ACTION_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
# Webhook entries Melorin writes on the panel: we only fill thresholds the panel has none for (never overwrite an admin's choice).
DEFAULT_USAGE_PERCENT = (80, 90)
DEFAULT_DAYS_LEFT = (3,)


@dataclass
class ParsedEvent:
    action: str
    username: str | None
    enqueued_at: dt.datetime | None
    event_id: str | None
    tries: int
    payload: dict
    dedup_key: str = field(default="")


@dataclass
class ParsedBody:
    events: list[ParsedEvent]
    rejected: int = 0  # items that were not usable events (not counted against the delivery: the rest is still processed)


def _header(headers: Mapping[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name:
            return value or ""
    return ""


def verify_secret(headers: Mapping[str, str], expected: str | None) -> bool:
    """Constant-time check of the shared secret. A panel without a stored secret accepts nothing."""
    if not expected:
        return False
    given = _header(headers, SECRET_HEADER)
    return hmac.compare_digest(given.encode("utf-8", "ignore"), expected.encode("utf-8"))


def _to_datetime(value) -> dt.datetime | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        if isinstance(value, int | float):
            return dt.datetime.fromtimestamp(float(value), tz=dt.UTC)
        text = str(value).strip()
        if not text:
            return None
        if re.fullmatch(r"\d+(\.\d+)?", text):
            return dt.datetime.fromtimestamp(float(text), tz=dt.UTC)
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
    except (ValueError, OverflowError, OSError):
        return None


def _finite(value) -> bool:
    """JSON accepts ``Infinity``/``NaN`` (and ``1e999``); PostgreSQL's JSON type does not, so one such value would turn a whole
    delivery into a 5xx that the panel then retries forever. Non-finite numbers are simply not kept."""
    return not (isinstance(value, float) and not math.isfinite(value))


def _short(value, limit: int) -> str | None:
    if value is None or isinstance(value, bool | dict | list):
        return None
    text = str(value).strip()
    return text[:limit] or None


def sanitize(raw: dict) -> dict:
    """What is safe and useful to keep for audit: no subscription links, no proxy settings, no free text from the panel."""
    out: dict = {}
    for key in ("id", "action", "username", "enqueued_at", "tries", "reset_traffic"):
        if raw.get(key) is not None and not isinstance(raw[key], dict | list) and _finite(raw[key]):
            out[key] = raw[key] if isinstance(raw[key], int | float | bool) else str(raw[key])[:200]
    by = raw.get("by")
    if isinstance(by, dict):
        by = by.get("username")
    if _short(by, 64):
        out["by"] = _short(by, 64)
    if _short(raw.get("reason"), 120):
        out["reason"] = _short(raw.get("reason"), 120)
    user = raw.get("user")
    if isinstance(user, dict):
        kept = {
            k: user[k]
            for k in ("status", "expire", "data_limit", "used_traffic")
            if k in user and isinstance(user[k], str | int | float | type(None)) and _finite(user[k])
        }
        admin = user.get("admin")
        if isinstance(admin, dict) and _short(admin.get("username"), 64):
            kept["admin"] = _short(admin.get("username"), 64)
        if kept:
            out["user"] = kept
    return out


def dedup_key_for(
    action: str,
    username: str | None,
    enqueued_at: dt.datetime | None,
    event_id: str | None,
    *,
    fingerprint: str = "",
    received_at: dt.datetime | None = None,
) -> str:
    """The panel's ``id`` when it sends one (stable across its retries); otherwise action + user + the panel's enqueue instant.

    A panel that sends neither an ``id`` nor ``enqueued_at`` gives no stable identity. Using one fixed key would swallow every later
    event of the same action for that user for as long as the row is kept, so the key then carries a content fingerprint and the
    minute the delivery arrived: an immediate re-delivery of the same body is still a duplicate, a genuinely new event is not.
    """
    if event_id:
        return f"id:{event_id}"[:200]
    if enqueued_at:
        return f"{action}:{username or '-'}:{enqueued_at.isoformat()}"[:200]
    minute = int((received_at or dt.datetime.now(dt.UTC)).timestamp() // 60)
    return f"{action}:{username or '-'}:rx{minute}:{fingerprint}"[:200]


def _fingerprint(item: dict) -> str:
    try:
        text = json.dumps(item, sort_keys=True, default=str)
    except (TypeError, ValueError):
        text = repr(item)
    return hashlib.sha1(text.encode("utf-8", "ignore"), usedforsecurity=False).hexdigest()[:12]


MAX_TRIES = 1000


def _parse_item(item: dict, now: dt.datetime) -> ParsedEvent | None:
    action = str(item.get("action") or "").strip().lower()
    if not _ACTION_RE.match(action):
        return None
    username = _short(item.get("username"), 128) or _short(
        (item.get("user") or {}).get("username") if isinstance(item.get("user"), dict) else None, 128
    )
    event_id = _short(item.get("id"), 100)
    enqueued_at = _to_datetime(item.get("enqueued_at"))
    try:
        tries = max(0, min(int(item.get("tries") or 0), MAX_TRIES))
    except (TypeError, ValueError, OverflowError):  # "x", NaN, Infinity
        tries = 0
    return ParsedEvent(
        action=action,
        username=username,
        enqueued_at=enqueued_at,
        event_id=event_id,
        tries=tries,
        payload=sanitize(item),
        dedup_key=dedup_key_for(action, username, enqueued_at, event_id, fingerprint=_fingerprint(item), received_at=now),
    )


def parse_body(body: bytes, *, now: dt.datetime | None = None) -> ParsedBody:
    """Parse one delivery. Raises ``ValueError`` when the body is not JSON at all (the endpoint answers 400); individual unusable
    items are counted in ``rejected`` and skipped - whatever is wrong with one item, it never fails the rest of the delivery."""
    if len(body) > MAX_BODY_BYTES:
        raise ValueError("body too large")
    now = now or dt.datetime.now(dt.UTC)
    try:
        data = json.loads(body, parse_constant=lambda _name: None)  # Infinity / -Infinity / NaN -> null
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("body is not JSON") from exc
    if isinstance(data, dict) and isinstance(data.get("events"), list):
        data = data["events"]
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError("body must be an event or a list of events")
    out = ParsedBody(events=[])
    for item in data[:MAX_EVENTS_PER_DELIVERY]:
        if not isinstance(item, dict):
            out.rejected += 1
            continue
        try:
            event = _parse_item(item, now)
        except Exception:  # a poison item must cost one rejected item, never a 5xx for the whole delivery
            event = None
        if event is None:
            out.rejected += 1
            continue
        out.events.append(event)
    out.rejected += max(0, len(data) - MAX_EVENTS_PER_DELIVERY)
    return out


def webhook_block(settings: dict | None) -> dict:
    block = (settings or {}).get("webhook")
    return dict(block) if isinstance(block, dict) else {}


def describe_webhook(settings: dict | None, url: str | None = None) -> dict:
    """Secret-free summary of the panel's webhook configuration, for the admin UI."""
    block = webhook_block(settings)
    entries = [e for e in block.get("webhooks") or [] if isinstance(e, dict)]
    return {
        "enabled": bool(block.get("enable")),
        "targets": len(entries),
        "melorin_registered": bool(url) and any(e.get("url") == url for e in entries),
        "days_left": list(block.get("days_left") or []),
        "usage_percent": list(block.get("usage_percent") or []),
        "other_targets": sum(1 for e in entries if url and e.get("url") != url),
    }


class EventsMixin:
    """``EventSource``: verify deliveries and switch the webhook on/off at the panel (the only panel settings Melorin ever writes)."""

    def verify_webhook(self, headers: Mapping[str, str], body: bytes, secret: str) -> bool:  # noqa: ARG002 - body unused: shared-secret scheme
        return verify_secret(headers, secret)

    async def get_webhook_config(self, url: str | None = None) -> dict:
        return describe_webhook(await self.get_settings(), url)

    async def _put_settings(self, settings: dict) -> dict:
        data = await self._req("PUT", "/api/settings", json=settings)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _others(settings: dict) -> dict:
        return {k: v for k, v in settings.items() if k != "webhook"}

    async def _write_webhook(self, settings: dict, block: dict) -> list[str]:
        """Write ``settings`` with ``webhook`` replaced, then read back and verify. Returns warnings (never silent corruption):
        every other settings section must be exactly as before."""
        before = self._others(settings)
        await self._put_settings({**settings, "webhook": block})
        after = await self.get_settings()
        warnings = [f"settings.{k} changed unexpectedly" for k in before if before[k] != after.get(k)]
        got = webhook_block(after)
        if bool(got.get("enable")) != bool(block.get("enable")) or len(got.get("webhooks") or []) != len(block.get("webhooks") or []):
            raise PanelError(ErrorKind.PERMANENT, "the panel did not keep the webhook settings (read-back differs)")
        return warnings

    async def connect_webhook(self, url: str, secret: str, *, usage_percent=DEFAULT_USAGE_PERCENT, days_left=DEFAULT_DAYS_LEFT) -> dict:
        """Register Melorin as a webhook target. Other targets and every other setting stay untouched; thresholds are only filled
        when the panel has none. Idempotent: the same url is replaced, never duplicated."""
        settings = await self.get_settings()
        block = webhook_block(settings)
        entries = [e for e in block.get("webhooks") or [] if isinstance(e, dict) and e.get("url") != url]
        entries.append({"url": url, "secret": secret})
        block["webhooks"], block["enable"] = entries, True
        if not block.get("usage_percent"):
            block["usage_percent"] = list(usage_percent)
        if not block.get("days_left"):
            block["days_left"] = list(days_left)
        warnings = await self._write_webhook(settings, block)
        return {**describe_webhook({"webhook": block}, url), "warnings": warnings}

    async def disconnect_webhook(self, url: str) -> dict:
        """Remove Melorin's target; the webhook stays enabled only when another target remains."""
        settings = await self.get_settings()
        block = webhook_block(settings)
        entries = [e for e in block.get("webhooks") or [] if isinstance(e, dict) and e.get("url") != url]
        block["webhooks"], block["enable"] = entries, bool(entries) and bool(block.get("enable"))
        warnings = await self._write_webhook(settings, block)
        return {**describe_webhook({"webhook": block}, url), "warnings": warnings}
