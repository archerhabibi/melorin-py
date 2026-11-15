"""Read side: the central profile, linked accounts, operations and (for admins) the full picture of one person."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.errors import AppError
from melorin.kernel.models.identity import Identity, User
from melorin.kernel.models.orders import Order
from melorin.kernel.models.person import (
    AccountConsolidationOperation,
    AccountLinkAudit,
    AccountLinkOperation,
    Person,
    WalletTransfer,
)
from melorin.kernel.models.wallet import Wallet
from melorin.modules.identity.account_linking import persons


def identity_card(i: Identity) -> dict:
    data = i.data or {}
    label = i.subject if i.provider != "google" else (data.get("email") or "Google")
    return {
        "id": i.id,
        "provider": i.provider,
        "label": label,
        "subject": i.subject if i.provider != "google" else None,  # a Google `sub` is an opaque id: never shown
        "status": i.status,
        "verified": i.verified_at is not None,
        "account_id": i.user_id,
        "linked_at": i.created_at,
        "last_used_at": i.last_used_at,
        "revoked_at": i.revoked_at,
    }


def operation_card(o: AccountLinkOperation) -> dict:
    return {
        "id": o.id,
        "provider": o.provider,
        "type": o.operation_type,
        "status": o.status,
        "expires_at": o.expires_at,
        "completed_at": o.completed_at,
        "created_at": o.created_at,
        # whether another profile is involved is shown, never WHO it is (docs/25 §13)
        "has_conflict": o.conflict_person_id is not None,
    }


def consolidation_card(c: AccountConsolidationOperation) -> dict:
    return {
        "id": c.id,
        "status": c.status,
        "central_account_id": c.central_user_id,
        "source_account_ids": c.source_user_ids,
        "blockers": (c.preflight or {}).get("blockers", []),
        "transfers": (c.preflight or {}).get("transfers", []),
        "created_at": c.created_at,
        "completed_at": c.completed_at,
        "failure_reason": c.failure_reason,
    }


async def profile(session: AsyncSession, user: User) -> dict:
    person = await persons.ensure_person(session, user)
    accounts = await persons.accounts_of(session, person.id)
    idents = await persons.identities_of(session, person.id, active_only=False)
    return {
        "person_id": person.public_id,
        "status": person.status,
        "current_account_id": user.id,
        "central_account_id": person.central_user_id,
        "accounts": [
            {
                "id": a.id,
                "display_name": a.display_name,
                "is_current": a.id == user.id,
                "is_central": a.id == person.central_user_id,
                "created_at": a.created_at,
            }
            for a in accounts
        ],
        "identities": [identity_card(i) for i in idents if i.status == "active"],
        "history": [identity_card(i) for i in idents if i.status != "active"],
    }


async def operations(session: AsyncSession, person_id: uuid.UUID, limit: int = 50) -> list[dict]:
    rows = (
        await session.scalars(
            select(AccountLinkOperation)
            .where(AccountLinkOperation.person_id == person_id)
            .order_by(AccountLinkOperation.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [operation_card(o) for o in rows]


async def consolidations(session: AsyncSession, person_id: uuid.UUID) -> list[dict]:
    rows = (
        await session.scalars(
            select(AccountConsolidationOperation)
            .where(AccountConsolidationOperation.target_person_id == person_id)
            .order_by(AccountConsolidationOperation.created_at.desc())
        )
    ).all()
    return [consolidation_card(c) for c in rows]


async def orders(session: AsyncSession, person_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[dict]:
    """Unified order history: every account of the person, original order ids and owners untouched."""
    rows = (
        await session.scalars(
            select(Order)
            .join(User, User.id == Order.user_id)
            .where(User.person_id == person_id)
            .order_by(Order.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [
        {
            "id": o.id,
            "number": o.number,
            "account_id": o.user_id,
            "store_id": o.store_id,
            "status": o.status,
            "total": o.total,
            "currency": o.currency,
            "created_at": o.created_at,
        }
        for o in rows
    ]


async def person_detail(session: AsyncSession, person_id: uuid.UUID) -> dict:
    person = await session.get(Person, person_id)
    if person is None:
        raise AppError("NOT_FOUND", "پروفایل یافت نشد.", 404)
    accounts = await persons.accounts_of(session, person.id)
    ids = [a.id for a in accounts]
    wallets = (await session.scalars(select(Wallet).where(Wallet.user_id.in_(ids)).order_by(Wallet.created_at))).all() if ids else []
    order_counts: dict[uuid.UUID, int] = {}
    if ids:
        rows = await session.execute(select(Order.user_id, func.count()).where(Order.user_id.in_(ids)).group_by(Order.user_id))
        order_counts = {uid: int(n) for uid, n in rows.all()}
    idents = await persons.identities_of(session, person.id, active_only=False)
    trail = (
        await session.scalars(
            select(AccountLinkAudit).where(AccountLinkAudit.person_id == person.id).order_by(AccountLinkAudit.created_at.desc()).limit(200)
        )
    ).all()
    transfers = (
        await session.scalars(
            select(WalletTransfer)
            .join(AccountConsolidationOperation, AccountConsolidationOperation.id == WalletTransfer.consolidation_id)
            .where(AccountConsolidationOperation.target_person_id == person.id)
        )
    ).all()
    return {
        "id": person.id,
        "public_id": person.public_id,
        "status": person.status,
        "merged_into_id": person.merged_into_id,
        "central_account_id": person.central_user_id,
        "accounts": [
            {
                "id": a.id,
                "display_name": a.display_name,
                "email": a.email,
                "is_active": a.is_active,
                "orders": int(order_counts.get(a.id, 0)),
            }
            for a in accounts
        ],
        "identities": [identity_card(i) for i in idents],
        "wallets": [
            {
                "id": w.id,
                "account_id": w.user_id,
                "store_id": w.store_id,
                "currency": w.currency,
                "balance": w.balance,
                "status": w.status,
                "consolidated_into_id": w.consolidated_into_id,
            }
            for w in wallets
        ],
        "operations": await operations(session, person.id, 100),
        "consolidations": await consolidations(session, person.id),
        "transfers": [
            {
                "id": t.id,
                "source_wallet_id": t.source_wallet_id,
                "target_wallet_id": t.target_wallet_id,
                "amount": t.amount,
                "currency": t.currency,
                "ledger_transaction_id": t.ledger_transaction_id,
            }
            for t in transfers
        ],
        "audit": [
            {
                "id": a.id,
                "action": a.action,
                "actor_id": a.actor_id,
                "actor_type": a.actor_type,
                "operation_id": a.operation_id,
                "before": a.before,
                "after": a.after,
                "reason": a.reason,
                "at": a.created_at,
            }
            for a in trail
        ],
    }
