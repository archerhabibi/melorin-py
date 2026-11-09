"""Admin API - panel orphans: panel users Melorin has no account for (PasarGuard roadmap Phase 1).

Orphans are listed, ignored, recorded as manual or assigned to a customer (a zero-price ``manual`` order that is NOT a sale: see
``domain/order_kinds``). Nothing here deletes anything on a panel.
"""

import datetime as dt
import logging
import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from melorin.core import audit
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.vpn import PanelOrphan
from melorin.modules.vpn import manual_assign

from melorin.modules.panelops import queries

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("melorin.admin.panel_orphans")


class OrphanOut(BaseModel):
    id: uuid.UUID
    panel_id: uuid.UUID
    panel_name: str | None = None
    username: str
    remote_status: str | None = None
    owner_username: str | None = None
    expire_at: dt.datetime | None = None
    traffic_limit_bytes: int = 0
    traffic_used_bytes: int = 0
    as_of: dt.datetime | None = None  # when the panel was last read (the numbers above are a snapshot of that moment)
    status: str
    note: str | None = None
    first_seen_at: dt.datetime | None = None
    last_seen_at: dt.datetime | None = None


class OrphanIgnoreIn(BaseModel):
    note: str | None = Field(default=None, max_length=300)


# ------------------------------------------------------------------------------------------------------------------ orphans
@router.get("/panel-orphans")
async def panel_orphans(
    _: AdminUser, session: Session, status: str | None = "open", panel_id: uuid.UUID | None = None, limit: int = 100, offset: int = 0
):
    total, rows = await queries.orphan_rows(session, status=status, panel_id=panel_id, limit=max(1, min(limit, 500)), offset=max(0, offset))
    return {
        "total": total,
        "items": [
            OrphanOut(
                id=o.id,
                panel_id=o.panel_id,
                panel_name=name,
                username=o.username,
                owner_username=o.owner_username,
                **_orphan_numbers(o),
                status=o.status,
                note=o.note,
                first_seen_at=o.first_seen_at,
                last_seen_at=o.last_seen_at,
            )
            for o, name in rows
        ],
    }


def _orphan_numbers(o: PanelOrphan) -> dict:
    """R7: the dated snapshot of an orphan, flattened for the API (``as_of`` = when the panel was last read)."""
    snap = o.snapshot or {}
    raw = snap.get("expire_at")
    return {
        "remote_status": snap.get("remote_status"),
        "expire_at": dt.datetime.fromisoformat(raw) if raw else None,
        "traffic_limit_bytes": int(snap.get("traffic_limit_bytes") or 0),
        "traffic_used_bytes": int(snap.get("traffic_used_bytes") or 0),
        "as_of": o.last_seen_at,
    }


def _orphan_out(o: PanelOrphan) -> OrphanOut:
    return OrphanOut(
        id=o.id,
        panel_id=o.panel_id,
        username=o.username,
        owner_username=o.owner_username,
        **_orphan_numbers(o),
        status=o.status,
        note=o.note,
        first_seen_at=o.first_seen_at,
        last_seen_at=o.last_seen_at,
    )


async def _set_orphan_status(session, admin, orphan_id: uuid.UUID, status: str, body: OrphanIgnoreIn, action: str) -> OrphanOut:
    o = await session.get(PanelOrphan, orphan_id)
    if not o:
        raise NotFound("کاربر پنل")
    if o.status == "gone":
        raise AppError("ORPHAN_GONE", "این کاربر دیگر در پنل نیست.", 409)
    o.status, o.note = status, (body.note or "").strip() or None
    audit.record(
        session,
        action,
        actor_id=admin.id,
        actor_type="admin",
        entity_type="panel_orphan",
        entity_id=o.id,
        data={"username": o.username, "panel_id": str(o.panel_id)},
    )
    await session.commit()
    return _orphan_out(o)


@router.post("/panel-orphans/{orphan_id}/ignore", response_model=OrphanOut)
async def ignore_orphan(orphan_id: uuid.UUID, body: OrphanIgnoreIn, admin: AdminUser, session: Session):
    """\"This panel user is not ours and that is fine\" (a test, a leftover). It is kept, only hidden from the open list."""
    return await _set_orphan_status(session, admin, orphan_id, "ignored", body, "panel_orphan.ignored")


@router.post("/panel-orphans/{orphan_id}/manual", response_model=OrphanOut)
async def manual_orphan(orphan_id: uuid.UUID, body: OrphanIgnoreIn, admin: AdminUser, session: Session):
    """Record the panel user as a MANUAL ACCOUNT: created by hand on the panel, known and wanted, not sold through Melorin.

    Nothing is written to the panel and nothing is deleted. The user leaves the open list and stays visible under ``status=manual``
    (it goes ``gone`` by itself when the panel user disappears); an admin may later assign it to a store/customer.
    """
    return await _set_orphan_status(session, admin, orphan_id, "manual", body, "panel_orphan.manual")


class OrphanAssignIn(BaseModel):
    store_id: uuid.UUID
    user_id: uuid.UUID = Field(description="the customer (an active member of the store) who will own the account")
    product_id: uuid.UUID = Field(description="the package this account is renewed as later; its price is NOT charged now")
    server_id: uuid.UUID | None = Field(default=None, description="destination to count it on; default = the panel's only enabled one")
    note: str | None = Field(default=None, max_length=300)


class OrphanAssignOut(BaseModel):
    vpn_account_id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    username: str
    store_id: uuid.UUID
    user_id: uuid.UUID
    revenue: str = "excluded"
    excluded_from: list[str] = list(manual_assign.EXCLUDED_FROM)
    owner_matches: bool | None = None
    expected_owner: str | None = None


@router.post("/panel-orphans/{orphan_id}/assign", response_model=OrphanAssignOut)
async def assign_orphan(orphan_id: uuid.UUID, body: OrphanAssignIn, admin: AdminUser, session: Session):
    """Give a panel user (open or recorded as manual) to a store customer.

    Creates the account and a zero-price ``manual`` order that is NOT a sale: no revenue, no commission, no referral reward, no
    loyalty points, no return. Writes nothing to the panel; the sold entitlement is the panel's reading taken now (a panel that does
    not answer: 503, nothing created). ``owner_matches=false`` means the next reconcile will raise ``owner_mismatch`` (decide ``fix_owner``).
    """
    r = await manual_assign.assign_orphan(
        session,
        admin=admin,
        orphan_id=orphan_id,
        store_id=body.store_id,
        user_id=body.user_id,
        product_id=body.product_id,
        server_id=body.server_id,
        note=body.note,
    )
    return OrphanAssignOut(
        vpn_account_id=r.account.id,
        order_id=r.order.id,
        order_number=r.order.number,
        username=r.account.username,
        store_id=r.account.store_id,
        user_id=r.account.user_id,
        owner_matches=r.owner_matches,
        expected_owner=r.expected_owner,
    )


@router.post("/panel-orphans/{orphan_id}/reopen", response_model=OrphanOut)
async def reopen_orphan(orphan_id: uuid.UUID, body: OrphanIgnoreIn, admin: AdminUser, session: Session):
    """Undo ``ignore`` / ``manual``: the panel user is listed as open again."""
    return await _set_orphan_status(session, admin, orphan_id, "open", body, "panel_orphan.reopened")
