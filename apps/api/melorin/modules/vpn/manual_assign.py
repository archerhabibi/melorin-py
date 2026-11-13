"""Assign a MANUAL ACCOUNT (a panel user created by hand on the panel) to a store customer (PG-04, decision 1).

Why an order exists at all: ``vpn_accounts.order_id`` and ``product_id`` are NOT NULL, so the account needs an order to hang on.
That order is ``kind="manual"``: ``total = 0``, ``payment_method="free"``, no reseller cost. By the rule written in
:mod:`melorin.domain.order_kinds` it is **not a sale**: it is left out of revenue, wholesale/commission, referral rewards, loyalty
points, "store history" (new-customer rules), returns and the orders topic. A later renewal is a normal ``renewal`` order and
counts as a sale like any other.

What this does NOT do: it writes nothing to the panel and deletes nothing. The panel's user keeps its own numbers; the sold
entitlement (``sold_expires_at`` / ``sold_traffic_bytes``) is rebased on the panel's reading taken *now* (strict: a panel that does
not answer means no assignment, never a guess), exactly like ``accept_panel``. If the panel owner of the user differs from the
store's PasarGuard admin, the normal reconcile reports ``owner_mismatch`` and an admin decides ``fix_owner``; it is reported here
(``owner_matches``) so the admin knows before it happens.
"""

import datetime as dt
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, codes
from melorin.core.db import utcnow
from melorin.core.errors import AppError, NotFound
from melorin.domain.order_kinds import MANUAL
from melorin.domain.product_snapshot import product_snapshot
from melorin.domain.order_state import OrderStatus, VpnStatus
from melorin.kernel.models.catalog import Product
from melorin.kernel.models.identity import User
from melorin.kernel.models.orders import Order, OrderStateTransition
from melorin.kernel.models.stores import Store, StoreMembership
from melorin.kernel.models.vpn import Panel, PanelAdmin, PanelOrphan, Server, VpnAccount
from melorin.modules.vpn import inquiry, sync
from melorin.modules.panel_integrations.adapters.base import PanelError
from melorin.modules.panel_integrations.adapters.registry import build_adapter

log = logging.getLogger("melorin.vpn.manual_assign")

ASSIGNABLE = ("open", "manual")  # an ignored orphan must be re-opened first: "ignore" was a decision, assigning reverses it on purpose

#: what an admin sees in the confirmation text and what the audit row records: the rule is fixed, not a setting.
EXCLUDED_FROM = ("sales", "commission", "referral", "loyalty", "returns")


@dataclass
class Assigned:
    account: VpnAccount
    order: Order
    owner_matches: bool | None  # None = the panel did not say who owns the user, or the store has no PasarGuard admin yet
    expected_owner: str | None


async def _server_for(session: AsyncSession, panel_id: uuid.UUID, server_id: uuid.UUID | None) -> uuid.UUID | None:
    """The destination the account is counted on. Explicit id must belong to the panel; otherwise the panel's only enabled one."""
    if server_id is not None:
        server = await session.get(Server, server_id)
        if not server or server.panel_id != panel_id:
            raise AppError("SERVER_NOT_ON_PANEL", "این مقصد متعلق به پنل این کاربر نیست.", 422)
        return server.id
    rows = (await session.scalars(select(Server.id).where(Server.panel_id == panel_id, Server.is_enabled.is_(True)).limit(2))).all()
    return rows[0] if len(rows) == 1 else None  # several destinations: the admin did not pick one, so none is guessed


async def assign_orphan(
    session: AsyncSession,
    *,
    admin: User,
    orphan_id: uuid.UUID,
    store_id: uuid.UUID,
    user_id: uuid.UUID,
    product_id: uuid.UUID,
    server_id: uuid.UUID | None = None,
    note: str | None = None,
    now: dt.datetime | None = None,
) -> Assigned:
    now = now or utcnow()
    orphan = await session.scalar(select(PanelOrphan).where(PanelOrphan.id == orphan_id).with_for_update())
    if not orphan:
        raise NotFound("کاربر پنل")
    if orphan.status == "gone":
        raise AppError("ORPHAN_GONE", "این کاربر دیگر در پنل نیست.", 409)
    if orphan.status not in ASSIGNABLE:
        raise AppError("ORPHAN_NOT_ASSIGNABLE", "ابتدا کاربر پنل را دوباره باز کنید (reopen) یا به‌عنوان «دستی» ثبت کنید.", 409)
    if len(orphan.username) > 64:
        raise AppError("USERNAME_TOO_LONG", "نام کاربری این اکانت بیش از ۶۴ نویسه است و قابل ثبت نیست.", 422)
    if await session.scalar(select(VpnAccount.id).where(VpnAccount.username == orphan.username)):
        raise AppError("USERNAME_TAKEN", "اکانتی با این نام کاربری از قبل در ملورین ثبت شده است.", 409)

    store = await session.get(Store, store_id)
    if not store:
        raise NotFound("فروشگاه")
    user = await session.get(User, user_id)
    if not user or user.archived_at is not None or not user.is_active:
        raise NotFound("مشتری")
    member = await session.scalar(select(StoreMembership).where(StoreMembership.store_id == store.id, StoreMembership.user_id == user.id))
    if member is None or member.status != "active":
        raise AppError("NOT_A_MEMBER", "این کاربر عضو فعال این فروشگاه نیست؛ ابتدا او را به فروشگاه اضافه کنید.", 409)
    product = await session.get(Product, product_id)
    if not product or product.is_test or product.archived_at is not None:
        raise NotFound("محصول")

    panel = await session.get(Panel, orphan.panel_id)
    if not panel:
        raise NotFound("پنل")
    server = await _server_for(session, panel.id, server_id)

    # A strict, fresh reading: the entitlement is rebased on what the panel says NOW. No answer = no assignment.
    try:
        remote = await build_adapter(panel).get_account(orphan.username)
    except PanelError as e:
        raise inquiry.PanelUnavailable() from e
    if remote is None:
        raise AppError("ORPHAN_GONE", "این کاربر دیگر در پنل نیست.", 409)

    admin_row = await session.scalar(select(PanelAdmin).where(PanelAdmin.panel_id == panel.id, PanelAdmin.store_id == store.id))
    expected_owner = admin_row.username if admin_row else None
    owner = getattr(remote, "owner", None)
    owner_matches = (owner == expected_owner) if (owner and expected_owner) else None

    order = Order(
        number=await codes.next_code(session, codes.ORDER_SEQ),
        user_id=user.id,
        store_id=store.id,
        product_id=product.id,
        kind=MANUAL,
        status=OrderStatus.COMPLETED,
        payment_method="free",
        channel="admin",
        currency=store.currency,
        unit_price=0,
        discount=0,
        total=0,
        reseller_cost=None,  # nothing was bought wholesale: no debit, nothing to settle with the reseller
        pricing_snapshot={
            "manual": True,
            "revenue": "excluded",
            "excluded_from": list(EXCLUDED_FROM),
            "orphan_id": str(orphan.id),
            "assigned_by": str(admin.id),
        },
        product_snapshot=product_snapshot(product),
        idempotency_key=f"manual:{orphan.id}",  # one assignment per panel user; a repeat cannot create a second order
        paid_at=now,
        completed_at=now,
    )
    session.add(order)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise AppError("ALREADY_ASSIGNED", "این کاربر پنل قبلاً اختصاص داده شده است.", 409) from e
    session.add(
        OrderStateTransition(
            order_id=order.id,
            from_status=OrderStatus.PENDING,
            to_status=OrderStatus.COMPLETED,
            reason="manual account assignment",
            actor_id=admin.id,
        )
    )

    account = VpnAccount(
        username=orphan.username,
        user_id=user.id,
        store_id=store.id,
        order_id=order.id,
        product_id=product.id,
        server_id=server,
        panel_id=panel.id,
        panel_ref=str(remote.ref) if remote.ref is not None else (str(orphan.remote_id) if orphan.remote_id is not None else None),
        status=VpnStatus.ACTIVE,
        is_test=False,
        placement={
            "manual": True,
            "orphan_id": str(orphan.id),
            "panel_id": str(panel.id),
            "server_id": str(server) if server else None,
            "assigned_at": now.isoformat(),
        },
    )
    session.add(account)
    await session.flush()
    sync.record_sale(account, remote.expire_at, remote.traffic_limit_bytes)  # R10: the entitlement is what the panel holds right now
    account.delivery_snapshot = sync.delivery_snapshot(remote, now=now)
    await sync.apply_remote(session, account, remote, now=now, notify=False)  # derive the status bucket; no customer notice for an import
    order.vpn_account_id = account.id

    orphan.status, orphan.note = "gone", f"assigned to account {account.id}"[:300]  # same end state as link_existing: Melorin knows it now
    audit.record(
        session,
        "vpn_account.manual_assigned",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="vpn_account",
        entity_id=account.id,
        store_id=store.id,
        data={
            "username": account.username,
            "order_id": str(order.id),
            "order_number": order.number,
            "panel_id": str(panel.id),
            "user_id": str(user.id),
            "product_id": str(product.id),
            "owner_matches": owner_matches,
            "excluded_from": list(EXCLUDED_FROM),
            "note": (note or "").strip()[:300] or None,
        },
    )
    await session.commit()
    return Assigned(account=account, order=order, owner_matches=owner_matches, expected_owner=expected_owner)
