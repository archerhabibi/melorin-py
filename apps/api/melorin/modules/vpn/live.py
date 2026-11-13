"""PanelLiveView (R1): what the PANEL says about an account right now, for display.

Mediator rule: used traffic, current limit, expiry and status belong to the panel. Melorin reads them when it has to show them and
keeps them only in a short in-memory cache (seconds, never a database column). When the panel cannot answer, the caller gets
``None`` and the UI says "temporarily unavailable"; it never falls back to an old number (decision 9).

The setting ``vpn.live_view`` (default ON since R9/R10: Melorin has no stored copy to fall back on) can still switch it off for an
incident; the account then shows only what Melorin sold (``sold_*``) with no usage.

* :func:`read` reads a page of accounts (grouped per panel, one adapter per panel, bounded concurrency, short TTL cache);
* :func:`overlay` puts a reading onto the ``VpnAccountOut`` a channel is about to return.
"""

from __future__ import annotations

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
from melorin.modules.vpn import freshness, inquiry
from melorin.modules.panel_integrations.adapters.registry import build_adapter, seed_adapter
from melorin.modules.panel_integrations.reader import PanelReader
from melorin.modules.panel_integrations.adapters.lifecycle import close_adapter
from melorin.modules.vpn.schemas import VpnAccountOut

log = logging.getLogger("melorin.vpn.live")

SETTING = "vpn.live_view"
TTL_SECONDS = freshness.READING_TTL_SECONDS  # a reading (aliases of the ``freshness`` policy)
FAIL_TTL_SECONDS = freshness.READING_FAIL_TTL_SECONDS  # "the panel could not answer": try again soon, but never once per tap
CONCURRENCY = freshness.READ_CONCURRENCY  # parallel single-user reads per panel
MAX_ACCOUNTS = freshness.READ_MAX_ACCOUNTS  # one call never reads more than a page
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
    value = await settings_store.get(session, SETTING)
    return True if value is None else bool(value)


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
    adapter = None
    try:
        adapter = build_adapter(panel)

        def failed(account: VpnAccount, exc: Exception) -> None:  # a panel error is "no answer", never a guess
            log.info("live read failed account=%s", account.id, exc_info=exc)

        remotes = await PanelReader(adapter, seed=seed_adapter).read_many(accounts, concurrency=CONCURRENCY, on_error=failed)
        return {account_id: (_reading(remote) if remote is not None else None) for account_id, remote in remotes.items()}
    except Exception:
        log.info("live read: panel unavailable panel=%s", panel.id, exc_info=True)
        return {a.id: None for a in accounts}
    finally:
        await close_adapter(adapter)


async def read(session, accounts: list[VpnAccount], *, fresh: bool = False) -> dict[uuid.UUID, LiveReading | None]:
    """A live reading per account id (``None`` = the panel could not answer, or has no such user). Accounts without a panel are absent."""
    now = time.monotonic()
    result: dict[uuid.UUID, LiveReading | None] = {}
    todo: dict[uuid.UUID, list[VpnAccount]] = {}
    for account in accounts[:MAX_ACCOUNTS]:
        if not account.panel_id:
            continue
        hit, value = (False, None) if fresh else _cached(account.id, now)
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
                "traffic_used_bytes": None,
                "usage_percent": None,
                "days_left": None,
                "health": "unavailable",
                "state_note": None,
                "suggested_action": None,
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
            **dict(
                zip(
                    ("state_note", "suggested_action"),
                    inquiry.state_hint(reading.remote_status, inquiry.health(shadow, now), can_renew=out.can_renew),
                    strict=True,
                )
            ),
            **({"subscription_url": reading.subscription_url} if reading.subscription_url else {}),
        }
    )


async def page_readings(session, accounts: list[VpnAccount]) -> dict[uuid.UUID, LiveReading | None]:
    """Readings for a page (empty when the view is switched off or the page has no panel account)."""
    if not accounts or not await enabled(session):
        return {}
    return await read(session, accounts)


async def overlay_page(
    session, outs: list[VpnAccountOut], accounts: list[VpnAccount], readings: dict[uuid.UUID, LiveReading | None] | None = None
) -> list[VpnAccountOut]:
    """The one call a route makes. ``readings`` may be passed when the route already read the page (e.g. for return eligibility)."""
    if not outs:
        return outs
    if readings is None:
        readings = await page_readings(session, accounts)
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


def _stored_link(account: VpnAccount) -> str | None:
    """The link as delivered (``delivery_snapshot``): a fallback only, never a reader of truth."""
    url, links = inquiry.delivered_link(account)
    return url or (links[0] if isinstance(links, list) and links else None)


async def current_link(session, account: VpnAccount) -> str | None:
    """R8: the subscription link as the PANEL has it now (it changes on ``revoke_sub``).

    The stored value is only a *delivery snapshot* (what was handed to the customer); it is used when the panel cannot answer,
    because a QR for the last delivered link is better than none. Accounts without a panel use the stored link.
    """
    if not account.panel_id:
        return _stored_link(account)
    reading = (await read(session, [account])).get(account.id)
    if reading is not None:
        return reading.subscription_url or (reading.links[0] if reading.links else None) or _stored_link(account)
    return _stored_link(account)


async def strict_reading(session, account: VpnAccount) -> LiveReading | None:
    """Money paths (refunds): a FRESH panel reading, never the cache. A panel that cannot answer (or has no such user) raises
    :class:`inquiry.PanelUnavailable` instead of letting the caller decide on an old number. An account without a panel has nothing
    to read: ``None``."""
    if not account.panel_id:
        return None
    reading = (await read(session, [account], fresh=True)).get(account.id)
    if reading is None:
        raise inquiry.PanelUnavailable()
    return reading


async def card(session, account: VpnAccount) -> VpnAccountOut:
    """One account as a card with the panel's numbers on it (what an action route returns after it changed something)."""
    return (await overlay_page(session, [inquiry.account_out(account)], [account]))[0]


async def owner_cards(session, rows, owner_id: uuid.UUID):
    """The store owner's cards (``rows`` = ``[(account, holder)]``) with the panel's numbers on them."""
    outs = [inquiry.owner_account_out(a, u, owner_id=owner_id) for a, u in rows]
    return await overlay_page(session, outs, [a for a, _ in rows])
