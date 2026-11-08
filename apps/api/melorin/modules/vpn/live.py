"""PanelLiveView (R1): what the PANEL says about an account right now, for display.

Mediator rule: used traffic, current limit, expiry and status belong to the panel. Melorin reads them when it has to show them and
keeps them only in a short in-memory cache (seconds, never a database column). When the panel cannot answer, the caller gets
``None`` and the UI says "temporarily unavailable"; it never falls back to an old number (decision 9).

Rolled out behind the setting ``vpn.live_view`` (default off): with it off every channel behaves exactly as before.

* :func:`read` reads a page of accounts (grouped per panel, one adapter per panel, bounded concurrency, short TTL cache);
* :func:`overlay` puts a reading onto the ``VpnAccountOut`` a channel is about to return.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import logging
import time
import types
import uuid

from sqlalchemy import select

from melorin.core import settings_store
from melorin.core.db import utcnow
from melorin.kernel.models.vpn import Panel, VpnAccount
from melorin.modules.vpn import inquiry
from melorin.modules.vpn.adapters.registry import build_adapter, seed_adapter
from melorin.modules.vpn.schemas import VpnAccountOut

log = logging.getLogger("melorin.vpn.live")

SETTING = "vpn.live_view"
TTL_SECONDS = 20.0  # a reading
FAIL_TTL_SECONDS = 5.0  # "the panel could not answer": try again soon, but never once per tap
CONCURRENCY = 5  # parallel single-user reads per panel
MAX_ACCOUNTS = 200  # one call never reads more than a page
CACHE_LIMIT = 5000
UNAVAILABLE_NOTE = "اطلاعات زنده از پنل موقتاً در دسترس نیست."


@dataclasses.dataclass(frozen=True)
class LiveReading:
    status: str
    remote_status: str | None
    expires_at: dt.datetime | None
    traffic_limit_bytes: int
    traffic_used_bytes: int
    online_at: dt.datetime | None
    subscription_url: str | None
    links: list | None


_cache: dict[uuid.UUID, tuple[float, LiveReading | None]] = {}


def clear_cache() -> None:
    _cache.clear()


async def enabled(session) -> bool:
    return bool(await settings_store.get(session, SETTING))


def _reading(remote) -> LiveReading:
    return LiveReading(
        status=remote.status,
        remote_status=getattr(remote, "remote_status", None),
        expires_at=remote.expire_at,
        traffic_limit_bytes=int(remote.traffic_limit_bytes or 0),
        traffic_used_bytes=int(remote.traffic_used_bytes or 0),
        online_at=getattr(remote, "online_at", None),
        subscription_url=getattr(remote, "subscription_url", None),
        links=list(getattr(remote, "links", None) or []) or None,
    )


def _cached(account_id: uuid.UUID, now: float):
    hit = _cache.get(account_id)
    if hit is None:
        return False, None
    at, value = hit
    if now - at <= (TTL_SECONDS if value is not None else FAIL_TTL_SECONDS):
        return True, value
    return False, None


async def _read_panel(panel: Panel, accounts: list[VpnAccount]) -> dict[uuid.UUID, LiveReading | None]:
    out: dict[uuid.UUID, LiveReading | None] = {}
    adapter = None
    try:
        adapter = build_adapter(panel)
        gate = asyncio.Semaphore(CONCURRENCY)

        async def one(account: VpnAccount):
            async with gate:
                try:
                    remote = await seed_adapter(adapter, account).get_account(account.username)
                except Exception:  # a panel error is "no answer", never a guess
                    log.info("live read failed account=%s", account.id, exc_info=True)
                    return account.id, None
                return account.id, (_reading(remote) if remote is not None else None)

        for account_id, reading in await asyncio.gather(*(one(a) for a in accounts)):
            out[account_id] = reading
    except Exception:
        log.info("live read: panel unavailable panel=%s", panel.id, exc_info=True)
        out = {a.id: None for a in accounts}
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            try:
                res = close()
                if hasattr(res, "__await__"):
                    await res
            except Exception:
                log.debug("live read: adapter close failed panel=%s", panel.id, exc_info=True)
    return out


async def read(session, accounts: list[VpnAccount]) -> dict[uuid.UUID, LiveReading | None]:
    """A live reading per account id (``None`` = the panel could not answer, or has no such user). Accounts without a panel are absent."""
    now = time.monotonic()
    result: dict[uuid.UUID, LiveReading | None] = {}
    todo: dict[uuid.UUID, list[VpnAccount]] = {}
    for account in accounts[:MAX_ACCOUNTS]:
        if not account.panel_id:
            continue
        hit, value = _cached(account.id, now)
        if hit:
            result[account.id] = value
        else:
            todo.setdefault(account.panel_id, []).append(account)
    if todo:
        panels = {p.id: p for p in (await session.scalars(select(Panel).where(Panel.id.in_(list(todo))))).all()}
        fresh: list[dict] = []
        for panel_id, group in todo.items():
            panel = panels.get(panel_id)
            fresh.append(await _read_panel(panel, group) if panel is not None else {a.id: None for a in group})
        if len(_cache) > CACHE_LIMIT:
            _cache.clear()
        stamp = time.monotonic()
        for part in fresh:
            for account_id, reading in part.items():
                _cache[account_id] = (stamp, reading)
                result[account_id] = reading
    return result


def overlay(out: VpnAccountOut, reading: LiveReading | None, *, now: dt.datetime | None = None) -> VpnAccountOut:
    """``out`` with the panel's numbers on it, or with NO numbers (``live=False``) when the panel did not answer."""
    if reading is None:
        return out.model_copy(
            update={
                "live": False,
                "live_note": UNAVAILABLE_NOTE,
                "traffic_used_bytes": 0,
                "usage_percent": None,
                "days_left": None,
                "health": "unavailable",
            }
        )
    now = now or utcnow()
    shadow = types.SimpleNamespace(
        expires_at=reading.expires_at,
        traffic_limit_bytes=reading.traffic_limit_bytes,
        traffic_used_bytes=reading.traffic_used_bytes,
        status=out.status,
    )
    return out.model_copy(
        update={
            "live": True,
            "live_note": None,
            "expires_at": reading.expires_at,
            "traffic_limit_bytes": reading.traffic_limit_bytes,
            "traffic_used_bytes": reading.traffic_used_bytes,
            "days_left": inquiry.days_left(shadow, now),
            "usage_percent": inquiry.usage_percent(shadow),
            "health": inquiry.health(shadow, now),
            **({"subscription_url": reading.subscription_url} if reading.subscription_url else {}),
        }
    )


async def overlay_page(session, outs: list[VpnAccountOut], accounts: list[VpnAccount]) -> list[VpnAccountOut]:
    """The one call a route makes: with the flag off (or no panel account on the page) ``outs`` is returned untouched."""
    if not outs or not await enabled(session):
        return outs
    readings = await read(session, accounts)
    return [overlay(o, readings[a.id]) if a.id in readings else o for o, a in zip(outs, accounts, strict=True)]


def overlay_row(row: dict, reading: LiveReading | None, *, now: dt.datetime | None = None) -> dict:
    """Same rule as :func:`overlay` for the plain dict an admin list returns (R6): panel numbers, or NO numbers when it did not answer."""
    if reading is None:
        return {
            **row,
            "live": False,
            "live_note": UNAVAILABLE_NOTE,
            "traffic_used_bytes": None,
            "days_left": None,
            "health": "unavailable",
        }
    now = now or utcnow()
    shadow = types.SimpleNamespace(
        expires_at=reading.expires_at,
        traffic_limit_bytes=reading.traffic_limit_bytes,
        traffic_used_bytes=reading.traffic_used_bytes,
        status=row.get("status"),
    )
    return {
        **row,
        "live": True,
        "live_note": None,
        "expires_at": reading.expires_at,
        "traffic_limit_bytes": reading.traffic_limit_bytes,
        "traffic_used_bytes": reading.traffic_used_bytes,
        "days_left": inquiry.days_left(shadow, now),
        "health": inquiry.health(shadow, now),
    }


async def overlay_rows(session, rows: list[dict], accounts: list[VpnAccount]) -> list[dict]:
    """Admin lists: with the flag off (or no panel account on the page) ``rows`` is returned untouched."""
    if not rows or not await enabled(session):
        return rows
    readings = await read(session, accounts)
    return [overlay_row(r, readings[a.id]) if a.id in readings else r for r, a in zip(rows, accounts, strict=True)]
