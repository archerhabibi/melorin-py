"""PG-06: the daily digest for a store owner.

Mediator rule: the digest says only what Melorin itself owns or did: how many customer notices it sent in the last 24 h (by kind),
how many panel discrepancies are open for this store, and whether the store's panel admin currently blocks selling. It states **no
usage, expiry or account-status number** (those belong to the panel and are read live in the account list).

Opt-in per store (``stores.vpn_notice_settings["daily_digest"] = True``): a store that did not ask gets nothing. A day with nothing
to report sends nothing. One digest per store per UTC day (dedup key), so running the job twice is safe.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import events
from melorin.core.db import utcnow
from melorin.kernel.models.stores import Store
from melorin.kernel.models.system import OutboxEvent
from melorin.kernel.models.vpn import PanelAdmin, ReconciliationIssue, VpnAccount
from melorin.modules.panelops import governance

KIND_LABELS = {
    "vpn_expired": "منقضی‌شده",
    "vpn_near_expiry": "نزدیک انقضا",
    "vpn_traffic_low": "رو به اتمام حجم",
    "vpn_traffic_exhausted": "اتمام حجم",
    "vpn_disabled": "غیرفعال‌شده",
    "vpn_queued_plan_started": "شروع پکیج بعدی",
}


def enabled(settings: dict | None) -> bool:
    return bool(settings and settings.get("daily_digest") is True)


async def build(session: AsyncSession, store: Store, *, now: dt.datetime | None = None) -> dict | None:
    """The facts for ``store`` over the last 24 h, or ``None`` when there is nothing worth a message."""
    now = now or utcnow()
    since = now - dt.timedelta(hours=24)
    sent: dict[str, int] = {}
    rows = await session.scalars(select(OutboxEvent).where(OutboxEvent.topic == events.NOTIFY, OutboxEvent.created_at >= since))
    for row in rows:
        p = row.payload if isinstance(row.payload, dict) else {}
        kind = str(p.get("kind") or "")
        if str(p.get("store_id")) == str(store.id) and kind in KIND_LABELS:
            sent[kind] = sent.get(kind, 0) + 1
    open_issues = len(
        (
            await session.scalars(
                select(ReconciliationIssue.id)
                .join(VpnAccount, VpnAccount.id == ReconciliationIssue.vpn_account_id)
                .where(VpnAccount.store_id == store.id, ReconciliationIssue.status == "open")
            )
        ).all()
    )
    blocked: list[str] = []
    for adm in (await session.scalars(select(PanelAdmin).where(PanelAdmin.store_id == store.id))).all():
        why = governance.sell_blocked(adm)
        if why:
            blocked.append(why)
    if not sent and not open_issues and not blocked:
        return None
    return {"store_id": str(store.id), "since": since.isoformat(), "notices": sent, "open_issues": open_issues, "sell_blocked": blocked}


def render(store: Store, facts: dict) -> tuple[str, str]:
    lines = [f"گزارش روزانهٔ سرویس‌ها برای {store.name}:"]
    for kind, n in sorted(facts["notices"].items()):
        lines.append(f"• {n} اعلان «{KIND_LABELS[kind]}» به مشتریان ارسال شد")
    if facts["open_issues"]:
        lines.append(f"• {facts['open_issues']} مغایرت باز با پنل نیاز به بررسی دارد")
    lines.extend(f"• هشدار فروش: {why}" for why in facts["sell_blocked"])
    lines.append("برای مصرف و تاریخ انقضا، فهرست اکانت‌ها را (که از پنل خوانده می‌شود) ببینید.")
    return "گزارش روزانهٔ VPN", "\n".join(lines)


async def run(session: AsyncSession, *, now: dt.datetime | None = None) -> int:
    """Queue one digest for every opted-in store that has an owner and something to report. Returns how many were queued."""
    now = now or utcnow()
    queued = 0
    for store in (await session.scalars(select(Store).where(Store.owner_user_id.is_not(None), Store.status == "active"))).all():
        if not enabled(store.vpn_notice_settings):
            continue
        facts = await build(session, store, now=now)
        if facts is None:
            continue
        title, body = render(store, facts)
        key = f"notify:digest:{store.id}:{now.date().isoformat()}"
        before = await session.scalar(select(OutboxEvent.id).where(OutboxEvent.dedup_key == key))
        await events.emit_user_notice(
            session, store.owner_user_id, store.id, "vpn_daily_digest", title, body, payload_dedup_key=key, dedup_key=key
        )
        queued += 0 if before else 1
    return queued
