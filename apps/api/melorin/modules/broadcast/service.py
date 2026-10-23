"""پیام همگانی (broadcast): the ONE place that decides who receives a message and sends it.

Who may send what (business rules, enforced here; the panels only show the options Core offers):

* the ADMIN (owner of the project) picks one of
    ``all_own``   his own resellers AND the customers of the Main Store,
    ``resellers`` only his resellers (the owners of the reseller stores),
    ``customers`` only the customers of the Main Store,
    ``everyone``  every customer of the whole project: the Main Store's AND those of every reseller store;
* a RESELLER can only message the customers of HIS OWN store (``customers``); he can never reach another store's people.

Delivery: one ``notification`` outbox event per (person, store). It is stored in the app inbox of that store and, when the
person has Telegram, sent by the bot of THAT store (the reseller's own bot for the reseller's customers), so a message is
only ever visible inside the store it belongs to. The key makes each delivery idempotent; sending is paced (about
``PER_SECOND`` messages per second) so the Telegram limits are respected.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import uuid

from sqlalchemy import func, select

from melorin.core import audit, events
from melorin.core.db import utcnow
from melorin.core.deps import main_store
from melorin.core.errors import AppError
from melorin.kernel.models.identity import User
from melorin.kernel.models.notifications import Broadcast, Notification
from melorin.kernel.models.stores import Store, StoreMembership

ADMIN_AUDIENCES = {
    "all_own": "همهٔ نمایندگان و مشتریان من",
    "resellers": "فقط نمایندگان من",
    "customers": "فقط مشتریان من",
    "everyone": "تمام مشتریان پروژه (شامل مشتریان نمایندگان)",
}
RESELLER_AUDIENCES = {"customers": "مشتریان فروشگاه من"}
TITLE_MAX = 120
BODY_MAX = 3500
PER_SECOND = 20  # pacing of the Telegram sends
DAILY_LIMIT = 10  # broadcasts per sender store in any rolling 24 hours


@dataclasses.dataclass(frozen=True)
class Recipient:
    user_id: uuid.UUID
    store_id: uuid.UUID  # the store (and so the bot / inbox) the message arrives in


def _live_user():
    return (User.is_active.is_(True), User.is_super_admin.is_(False))


async def _customers_of(session, *store_ids: uuid.UUID) -> list[Recipient]:
    if not store_ids:
        return []
    rows = await session.execute(
        select(StoreMembership.user_id, StoreMembership.store_id)
        .join(User, User.id == StoreMembership.user_id)
        .where(StoreMembership.store_id.in_(store_ids), StoreMembership.role == "customer", StoreMembership.status == "active", *_live_user())
    )
    return [Recipient(u, st) for u, st in rows.all()]


async def _reseller_owners(session, main: Store) -> list[Recipient]:
    """Owners of the active reseller stores; the message reaches them through the Main Store's bot and inbox."""
    rows = await session.scalars(
        select(Store.owner_user_id)
        .join(User, User.id == Store.owner_user_id)
        .where(Store.kind == "reseller", Store.status == "active", Store.owner_user_id.is_not(None), *_live_user())
        .distinct()
    )
    return [Recipient(u, main.id) for u in rows.all()]


async def _active_reseller_store_ids(session) -> list[uuid.UUID]:
    return list(await session.scalars(select(Store.id).where(Store.kind == "reseller", Store.status == "active")))


def audiences_for(store: Store) -> dict[str, str]:
    return ADMIN_AUDIENCES if store.kind == "main" else RESELLER_AUDIENCES


async def recipients(session, store: Store, audience: str) -> list[Recipient]:
    """Everyone ``audience`` means for the sender store ``store``, each (person, store) pair once."""
    if audience not in audiences_for(store):
        raise AppError("BROADCAST_AUDIENCE", "گروه گیرنده نامعتبر است.", 422)
    found: list[Recipient] = []
    if store.kind != "main":  # a reseller: ONLY the customers of his own store
        found = await _customers_of(session, store.id)
    else:
        main = store
        if audience in ("resellers", "all_own"):
            found += await _reseller_owners(session, main)
        if audience in ("customers", "all_own"):
            found += await _customers_of(session, main.id)
        if audience == "everyone":
            found += await _customers_of(session, main.id, *await _active_reseller_store_ids(session))
    return list(dict.fromkeys(found))  # de-duplicate, keep order


async def audience_counts(session, store: Store) -> list[dict]:
    return [{"id": k, "label": v, "count": len(await recipients(session, store, k))} for k, v in audiences_for(store).items()]


def _clean(title: str, body: str) -> tuple[str, str]:
    title, body = (title or "").strip(), (body or "").strip()
    if not title or not body:
        raise AppError("BROADCAST_EMPTY", "عنوان و متن پیام را وارد کنید.", 422)
    if len(title) > TITLE_MAX or len(body) > BODY_MAX:
        raise AppError("BROADCAST_TOO_LONG", f"عنوان حداکثر {TITLE_MAX} و متن حداکثر {BODY_MAX} نویسه باشد.", 422)
    return title, body


async def send(session, *, sender: User, store: Store, audience: str, title: str, body: str) -> Broadcast:
    """Queue the message for every recipient of ``audience`` and record it. Commits."""
    title, body = _clean(title, body)
    since = utcnow() - dt.timedelta(days=1)
    # serialise the senders of one store so the daily limit cannot be jumped by parallel requests
    await session.scalar(select(Store.id).where(Store.id == store.id).with_for_update())
    sent_today = int(await session.scalar(select(func.count()).select_from(Broadcast).where(Broadcast.store_id == store.id, Broadcast.created_at >= since)) or 0)
    if sent_today >= DAILY_LIMIT:
        raise AppError("BROADCAST_LIMIT", f"سقف ارسال پیام همگانی ({DAILY_LIMIT} بار در روز) پر شده است.", 429)
    people = await recipients(session, store, audience)
    if not people:
        raise AppError("BROADCAST_NO_RECIPIENTS", "گیرنده‌ای در این گروه وجود ندارد.", 409)
    bc = Broadcast(sender_user_id=sender.id, store_id=store.id, audience=audience, title=title, body=body, recipients=len(people))
    session.add(bc)
    await session.flush()
    for i, r in enumerate(people):
        await events.emit(
            session,
            events.NOTIFY,
            {"user_id": r.user_id, "store_id": r.store_id, "kind": "broadcast", "title": title, "body": body, "dedup_key": key(bc.id, r)},
            dedup_key=key(bc.id, r),
            delay_seconds=i // PER_SECOND,
        )
    audit.record(
        session,
        "broadcast.sent",
        actor_id=sender.id,
        actor_type="admin" if store.kind == "main" else "reseller",
        entity_type="broadcast",
        entity_id=bc.id,
        store_id=store.id,
        data={"audience": audience, "recipients": len(people)},
    )
    await session.commit()
    return bc


def key(broadcast_id: uuid.UUID, r: Recipient) -> str:
    return f"bc:{broadcast_id.hex}:{r.user_id.hex}:{r.store_id.hex}"


async def history(session, store: Store, *, limit: int = 30) -> list[dict]:
    """The latest broadcasts of ``store`` with delivery numbers (queued = events not yet turned into notifications)."""
    rows = (await session.scalars(select(Broadcast).where(Broadcast.store_id == store.id).order_by(Broadcast.created_at.desc()).limit(limit))).all()
    out = []
    for b in rows:
        counts = dict(
            (await session.execute(select(Notification.telegram_status, func.count()).where(Notification.dedup_key.like(f"bc:{b.id.hex}:%")).group_by(Notification.telegram_status))).all()
        )
        made = sum(counts.values())
        out.append(
            {
                "id": b.id,
                "audience": b.audience,
                "audience_label": audiences_for(store).get(b.audience, b.audience),
                "title": b.title,
                "body": b.body,
                "recipients": b.recipients,
                "sent": int(counts.get("sent", 0)),
                "failed": int(counts.get("failed", 0)),
                "no_telegram": int(counts.get("skipped", 0)),
                "queued": max(0, b.recipients - made) + int(counts.get("pending", 0)),
                "created_at": b.created_at,
            }
        )
    return out


async def sender_store_for_admin(session) -> Store:
    return await main_store(session)
