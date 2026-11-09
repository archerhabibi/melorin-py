"""Per-store usage report for the store owner (reseller bot / API).

Mediator rule: usage, limit, expiry and status belong to the PANEL. This module reads them from the panel when the owner asks and
keeps them only in a very short in-memory cache (seconds, never a database column). If a panel cannot answer, its numbers are
absent and the report says so; an old number is never shown in its place (decision 9, same as :mod:`melorin.modules.vpn.live`).

What is read: for every panel where the store has an active panel admin, the users of THAT admin only (``GET /api/users?admin=``,
heaviest first, paged, read-only). Everything in the answer comes from that one reading, so the numbers always agree with each other.

What is never in the answer: IP addresses, connection or device details, subscription links, last-seen times. The report has
account names, volume, a status bucket and two counters. The daily digest (``digest.py``) deliberately carries NO usage number; this
report is a separate, on-demand screen.

Safety: every row must belong to the store's own panel admin. A row owned by someone else (or with no owner shown) means the panel
did not apply the filter, and the whole panel is treated as unavailable instead of leaking another store's accounts.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import time
import uuid

from sqlalchemy import select

from melorin.core.db import utcnow
from melorin.kernel.models.stores import Store
from melorin.kernel.models.vpn import Panel, PanelAdmin
from melorin.modules.vpn.adapters.base import PanelAccount
from melorin.modules.vpn.adapters.registry import build_adapter
from melorin.modules.vpn.live import UNAVAILABLE_NOTE

log = logging.getLogger("melorin.vpn.store_usage")

PAGE = 100  # users per panel call
SCAN_LIMIT = 2000  # users read per panel; more than this and the volume figures are marked incomplete
NEAR_EXPIRY_DAYS = 3  # an active account ending within this many days counts as "near expiry"
NEAR_EXHAUSTION_PERCENT = 90  # an active, limited account at/above this share of its volume (and below 100) is "near exhaustion"
TOP = 5
TTL_SECONDS = 20.0  # a successful reading
STATUS_KEYS = ("active", "on_hold", "limited", "expired", "disabled", "other")
PARTIAL_NOTE = "بعضی پنل‌ها پاسخ ندادند؛ اعداد فقط از پنل‌هایی است که جواب دادند."

_cache: dict[uuid.UUID, tuple[float, dict]] = {}


def clear_cache() -> None:
    _cache.clear()


@dataclasses.dataclass
class PanelReading:
    """What one panel answered for one store: the rows it listed and how many it says exist."""

    name: str
    rows: list[PanelAccount]
    total: int  # the panel's own count for this admin (>= len(rows) when the scan was capped)


def _bucket(account: PanelAccount) -> str:
    status = str(account.remote_status or account.status or "").lower()
    return status if status in STATUS_KEYS[:-1] else "other"


def _percent(account: PanelAccount) -> int | None:
    limit = int(account.traffic_limit_bytes or 0)
    if limit <= 0:
        return None
    return int(min(int(account.traffic_used_bytes or 0) * 100 // limit, 999))


def summarise(readings: list[PanelReading], unavailable: list[str], *, now: dt.datetime) -> dict:
    """The report from what the panels answered (pure: no I/O, so it is easy to test). ``unavailable`` = panels that did not answer."""
    rows = [r for reading in readings for r in reading.rows]
    counts = dict.fromkeys(STATUS_KEYS, 0)
    near_expiry = near_exhaustion = 0
    horizon = now + dt.timedelta(days=NEAR_EXPIRY_DAYS)
    for acc in rows:
        bucket = _bucket(acc)
        counts[bucket] += 1
        if bucket != "active":
            continue
        if acc.expire_at is not None and now <= acc.expire_at <= horizon:
            near_expiry += 1
        pct = _percent(acc)
        if pct is not None and NEAR_EXHAUSTION_PERCENT <= pct < 100:
            near_exhaustion += 1
    total = sum(max(r.total, len(r.rows)) for r in readings)
    complete = not unavailable and all(len(r.rows) >= r.total for r in readings)
    top = sorted(rows, key=lambda a: int(a.traffic_used_bytes or 0), reverse=True)[:TOP]
    return {
        "live": True,
        "note": PARTIAL_NOTE if unavailable else None,
        "taken_at": now,
        "complete": complete,
        "accounts": {"total": total, **counts},
        "usage": {"total_used_bytes": sum(int(a.traffic_used_bytes or 0) for a in rows)},
        "near_expiry": near_expiry,
        "near_expiry_days": NEAR_EXPIRY_DAYS,
        "near_exhaustion": near_exhaustion,
        "near_exhaustion_percent": NEAR_EXHAUSTION_PERCENT,
        "top_consumers": [
            {
                "username": a.username,
                "used_bytes": int(a.traffic_used_bytes or 0),
                "limit_bytes": int(a.traffic_limit_bytes or 0),  # 0 = unlimited
                "percent": _percent(a),
                "status": _bucket(a),
            }
            for a in top
        ],
        "panels": [{"name": r.name, "ok": True} for r in readings] + [{"name": n, "ok": False} for n in unavailable],
    }


def unavailable_report(names: list[str], *, now: dt.datetime) -> dict:
    """No panel answered: no numbers at all, only the reason."""
    return {
        "live": False,
        "note": UNAVAILABLE_NOTE,
        "taken_at": now,
        "complete": False,
        "panels": [{"name": n, "ok": False} for n in names],
    }


async def _read_panel(panel: Panel, username: str) -> PanelReading | None:
    """Every user of ``username`` on ``panel`` (up to ``SCAN_LIMIT``), or ``None`` when the panel cannot answer safely."""
    adapter = None
    try:
        adapter = build_adapter(panel)
        if not hasattr(adapter, "list_owner_accounts"):
            return None
        rows: list[PanelAccount] = []
        total: int | None = None
        while len(rows) < SCAN_LIMIT:
            page, count = await adapter.list_owner_accounts(username, offset=len(rows), limit=PAGE)
            if isinstance(count, int):
                total = count
            if not page:
                break
            rows.extend(page)
            if len(page) < PAGE or (total is not None and len(rows) >= total):
                break
        if any(r.owner != username for r in rows):  # fail closed: the panel did not apply the admin filter
            log.warning("store usage: panel=%s returned rows of another owner; discarded", panel.id)
            return None
        return PanelReading(name=panel.name, rows=rows, total=total if total is not None else len(rows))
    except Exception:  # a panel error is "no answer", never a guess
        log.info("store usage: panel unavailable panel=%s", panel.id, exc_info=True)
        return None
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            try:
                res = close()
                if hasattr(res, "__await__"):
                    await res
            except Exception:
                log.debug("store usage: adapter close failed panel=%s", panel.id, exc_info=True)


async def report(session, store: Store, *, now: dt.datetime | None = None, fresh: bool = False) -> dict:
    """The store's usage report, read from the panels now (a successful reading is reused for ``TTL_SECONDS``)."""
    now = now or utcnow()
    hit = None if fresh else _cache.get(store.id)
    if hit is not None and time.monotonic() - hit[0] <= TTL_SECONDS:
        return hit[1]
    admins = (
        await session.scalars(
            select(PanelAdmin).where(PanelAdmin.store_id == store.id, PanelAdmin.status == "active").order_by(PanelAdmin.created_at)
        )
    ).all()
    readings: list[PanelReading] = []
    unavailable: list[str] = []
    for adm in admins:
        panel = await session.get(Panel, adm.panel_id)
        if panel is None or not panel.is_enabled or (panel.config or {}).get("admin_per_store") is False:
            continue  # not a panel this store has its own admin on: nothing to read
        reading = await _read_panel(panel, adm.username)
        if reading is None:
            unavailable.append(panel.name)
        else:
            readings.append(reading)
    if unavailable and not readings:
        return unavailable_report(unavailable, now=now)  # never cached: ask again next time
    out = summarise(readings, unavailable, now=now)
    if not unavailable:
        if len(_cache) > 500:
            _cache.clear()
        _cache[store.id] = (time.monotonic(), out)
    return out
