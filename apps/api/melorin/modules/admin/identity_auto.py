"""Admin API - automatic identity verification at a glance (docs/21): trusted devices and automatic account merges.

Read-mostly. The only write is revoking trust (one device, or every device of one account), which is always audited.
Nothing here exposes a device key or its hash: the admin sees the browser label, network, usage and expiry.
"""

import datetime as dt
import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from melorin.core import audit
from melorin.core.db import utcnow
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.identity import TrustedDevice, User
from melorin.kernel.models.stores import Store
from melorin.kernel.models.system import AuditEvent

router = APIRouter(prefix="/admin", tags=["admin"])

DEVICE_STATUSES = {"active", "expired", "revoked"}
LIMIT = 500


def _aware(v: dt.datetime) -> dt.datetime:
    return v.replace(tzinfo=v.tzinfo or dt.UTC)


def device_status(d: TrustedDevice, now: dt.datetime) -> str:
    if d.revoked_at is not None:
        return "revoked"
    return "expired" if _aware(d.expires_at) <= now else "active"


def _uid(v) -> uuid.UUID | None:
    try:
        return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))
    except (ValueError, TypeError):
        return None


def _user_card(u: User | None) -> dict | None:
    if u is None:
        return None
    return {"id": u.id, "display_name": u.display_name, "email": u.email, "is_active": bool(u.is_active)}


@router.get("/trusted-devices")
async def trusted_devices(_: AdminUser, session: Session, status: str = "active", q: str | None = None, store_id: uuid.UUID | None = None):
    """Trusted browsers. ``status`` = active | expired | revoked | all; ``q`` matches name, e-mail, label or Telegram id."""
    if status != "all" and status not in DEVICE_STATUSES:
        raise AppError("INVALID_STATUS", "وضعیت نامعتبر است.", 422)
    now = utcnow()
    stmt = select(TrustedDevice, User, Store).join(User, User.id == TrustedDevice.user_id).join(Store, Store.id == TrustedDevice.store_id)
    if store_id:
        stmt = stmt.where(TrustedDevice.store_id == store_id)
    if status == "active":
        stmt = stmt.where(TrustedDevice.revoked_at.is_(None), TrustedDevice.expires_at > now)
    elif status == "expired":
        stmt = stmt.where(TrustedDevice.revoked_at.is_(None), TrustedDevice.expires_at <= now)
    elif status == "revoked":
        stmt = stmt.where(TrustedDevice.revoked_at.is_not(None))
    term = (q or "").strip().lower()[:100]
    if term:
        like = f"%{term}%"
        conds = [func.lower(User.email).like(like), func.lower(User.display_name).like(like), func.lower(TrustedDevice.label).like(like)]
        if term.isdigit():
            conds.append(TrustedDevice.telegram_id == int(term))
        stmt = stmt.where(or_(*conds))
    rows = (await session.execute(stmt.order_by(TrustedDevice.last_seen_at.desc()).limit(LIMIT))).all()
    return [
        {
            "id": d.id,
            "status": device_status(d, now),
            "user": _user_card(u),
            "store_id": s.id,
            "store_name": s.name,
            "telegram_id": d.telegram_id,
            "label": d.label,
            "last_ip": d.last_ip,
            "uses": d.uses,
            "created_at": d.created_at,
            "last_seen_at": d.last_seen_at,
            "expires_at": d.expires_at,
            "revoked_at": d.revoked_at,
        }
        for d, u, s in rows
    ]


@router.get("/trusted-devices/summary")
async def trusted_devices_summary(_: AdminUser, session: Session):
    now = utcnow()
    live = (TrustedDevice.revoked_at.is_(None), TrustedDevice.expires_at > now)
    active = await session.scalar(select(func.count()).select_from(TrustedDevice).where(*live)) or 0
    accounts = await session.scalar(select(func.count(func.distinct(TrustedDevice.user_id))).where(*live)) or 0
    revoked = await session.scalar(select(func.count()).select_from(TrustedDevice).where(TrustedDevice.revoked_at.is_not(None))) or 0
    since = now - dt.timedelta(days=30)
    merges = await session.scalar(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "identity.auto_merged", AuditEvent.created_at >= since)
    )
    return {"active_devices": active, "accounts": accounts, "revoked_devices": revoked, "auto_merges_30d": merges or 0}


class RevokeIn(BaseModel):
    user_id: uuid.UUID
    store_id: uuid.UUID | None = None


@router.post("/trusted-devices/{device_id}/revoke")
async def revoke_trusted_device(device_id: uuid.UUID, admin: AdminUser, session: Session):
    d = await session.get(TrustedDevice, device_id, with_for_update=True)
    if not d or d.revoked_at is not None:
        raise NotFound("دستگاه مورداعتماد")
    d.revoked_at = utcnow()
    audit.record(
        session,
        "trusted_device.revoked_by_admin",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="trusted_device",
        entity_id=d.id,
        store_id=d.store_id,
        data={"user_id": str(d.user_id), "label": d.label},
    )
    await session.commit()
    return {"ok": True}


@router.post("/trusted-devices/revoke-account")
async def revoke_account_devices(body: RevokeIn, admin: AdminUser, session: Session):
    """Revoke every live device of one account (optionally only in one store). The account's web sessions are untouched."""
    from melorin.channels.telegram import trust

    store_ids = (
        [body.store_id]
        if body.store_id
        else list(
            (
                await session.scalars(
                    select(TrustedDevice.store_id)
                    .where(TrustedDevice.user_id == body.user_id, TrustedDevice.revoked_at.is_(None))
                    .distinct()
                )
            ).all()
        )
    )
    count = 0
    for sid in store_ids:
        count += await trust.revoke_for_user(session, body.user_id, sid)
    audit.record(
        session,
        "trusted_device.account_revoked_by_admin",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="user",
        entity_id=body.user_id,
        data={"revoked": count, "store_id": str(body.store_id) if body.store_id else None},
    )
    await session.commit()
    return {"ok": True, "revoked": count}


@router.get("/identity-auto-merges")
async def identity_auto_merges(_: AdminUser, session: Session, days: int = 90):
    """Accounts that were folded together automatically (newest first): who was kept, which empty shell was archived, which rule applied."""
    days = max(1, min(int(days), 365))
    since = utcnow() - dt.timedelta(days=days)
    events = (
        await session.scalars(
            select(AuditEvent)
            .where(AuditEvent.action == "identity.auto_merged", AuditEvent.created_at >= since)
            .order_by(AuditEvent.created_at.desc())
            .limit(LIMIT)
        )
    ).all()
    wanted: set[uuid.UUID] = set()
    for e in events:
        wanted.update(x for x in (_uid((e.data or {}).get("keeper")), _uid((e.data or {}).get("shell"))) if x)
    users = {u.id: u for u in (await session.scalars(select(User).where(User.id.in_(wanted)))).all()} if wanted else {}
    return [
        {
            "id": e.id,
            "created_at": e.created_at,
            "rule": (e.data or {}).get("rule"),
            "providers": (e.data or {}).get("providers") or [],
            "keeper": _user_card(users.get(_uid((e.data or {}).get("keeper")))),
            "shell": _user_card(users.get(_uid((e.data or {}).get("shell")))),
        }
        for e in events
    ]
