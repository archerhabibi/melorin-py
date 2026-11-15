"""Account Consolidation: move the wallets of one person's accounts into the central account's wallets, through the ledger.

Never a sum-and-overwrite of a ``balance`` column: every move is a balanced ledger transaction with an idempotency key, the source wallet
is kept (status ``consolidated``) and the before/after totals are reconciled before the operation may complete (docs/25 §6).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.config import get_settings
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.domain import account_linking as rules
from melorin.domain.order_state import OrderStatus as O
from melorin.domain.order_state import PaymentStatus as P
from melorin.kernel.models.identity import User
from melorin.kernel.models.orders import Order
from melorin.kernel.models.payments import Payment
from melorin.kernel.models.person import AccountConsolidationOperation, Person, WalletTransfer
from melorin.kernel.models.stores import ResellerProfile
from melorin.kernel.models.wallet import Wallet
from melorin.modules.identity.account_linking import audit, persons
from melorin.modules.wallet import service as wallet_service

IN_FLIGHT_ORDERS = (
    O.PENDING,
    O.PAYMENT_PENDING,
    O.PAID,
    O.PROCESSING,
    O.PROVISIONING,
    O.PROVISIONING_FAILED,
    O.MANUAL_REVIEW,
    O.REFUND_PENDING,
)
IN_FLIGHT_PAYMENTS = (P.PENDING, P.AWAITING_REVIEW)
OPEN = ("pending_approval", "running")


async def _pending(session: AsyncSession, user_ids: list[uuid.UUID]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}

    def add(uid, code):
        out.setdefault(str(uid), [])
        if code not in out[str(uid)]:
            out[str(uid)].append(code)

    for (uid,) in (
        await session.execute(
            select(Payment.user_id).where(Payment.user_id.in_(user_ids), Payment.status.in_(IN_FLIGHT_PAYMENTS)).distinct()
        )
    ).all():
        add(uid, "payment_in_flight")
    for (uid,) in (
        await session.execute(select(Order.user_id).where(Order.user_id.in_(user_ids), Order.status.in_(IN_FLIGHT_ORDERS)).distinct())
    ).all():
        add(uid, "order_in_flight")
    for (uid,) in (await session.execute(select(ResellerProfile.user_id).where(ResellerProfile.user_id.in_(user_ids)))).all():
        add(uid, "reseller_account")  # reseller costs may use the debt limit of THIS wallet: never moved automatically
    return out


async def _central_choice(person: Person, accounts: list[User]) -> User:
    for a in accounts:
        if person.central_user_id == a.id:
            return a
    return accounts[0]  # the oldest account keeps living as the central one


async def build_plan(
    session: AsyncSession, person: Person, central: User, accounts: list[User], *, create_wallets: bool
) -> tuple[rules.Plan, list[Wallet]]:
    source_ids = [a.id for a in accounts if a.id != central.id]
    wallets = (
        list(
            (
                await session.scalars(
                    select(Wallet)
                    .where(Wallet.user_id.in_(source_ids), Wallet.kind == "customer", Wallet.status == "active")
                    .order_by(Wallet.id)
                )
            ).all()
        )
        if source_ids
        else []
    )
    await wallet_service.lock_wallets(session, wallets)
    central_wallets: dict[tuple[str, str], str] = {}
    for w in wallets:
        if w.balance > 0 and create_wallets:
            cw = await wallet_service.get_wallet(session, central.id, w.store_id, currency=w.currency, route=False)
            central_wallets[(str(w.store_id), w.currency)] = str(cw.id)
    facts = [rules.WalletFacts(str(w.id), str(w.user_id), str(w.store_id), w.currency, int(w.balance)) for w in wallets]
    plan = rules.plan_consolidation(
        central_user_id=str(central.id), sources=facts, central_wallets=central_wallets, pending_by_user=await _pending(session, source_ids)
    )
    if not create_wallets:  # dry run: a missing central wallet is not a blocker, it will be created on execute
        plan.blockers = [b for b in plan.blockers if b.code != "central_wallet_missing"]
    return plan, wallets


def _plan_json(plan: rules.Plan) -> dict:
    return {
        "ok": plan.ok,
        "transfers": [{"source_wallet": s, "target_wallet": t, "amount": a, "currency": c} for s, t, a, c in plan.transfers],
        "blockers": [{"code": b.code, "user_id": b.user_id, "detail": b.detail} for b in plan.blockers],
    }


async def request(session: AsyncSession, user: User, *, key: str, actor_type: str = "user") -> AccountConsolidationOperation:
    person = await persons.ensure_person(session, user)
    persons.ensure_usable(person)
    full_key = f"consolidate:{person.id}:{key}"
    same = await session.scalar(select(AccountConsolidationOperation).where(AccountConsolidationOperation.idempotency_key == full_key))
    if same is not None:
        return same
    live = await session.scalar(
        select(AccountConsolidationOperation).where(
            AccountConsolidationOperation.target_person_id == person.id, AccountConsolidationOperation.status.in_(OPEN)
        )
    )
    if live is not None:
        return live
    accounts = [a for a in await persons.accounts_of(session, person.id) if a.is_active]
    if len(accounts) < 2:
        raise AppError("NOTHING_TO_CONSOLIDATE", "برای یکپارچه‌سازی دست‌کم دو حساب متصل لازم است.", 409)
    if any(a.is_super_admin or (a.admin_roles or []) for a in accounts):
        raise AppError("ADMIN_ACCOUNT", "حساب مدیر قابل یکپارچه‌سازی نیست.", 409)
    central = await _central_choice(person, accounts)
    plan, _ = await build_plan(session, person, central, accounts, create_wallets=False)
    op = AccountConsolidationOperation(
        target_person_id=person.id,
        central_user_id=central.id,
        source_user_ids=[str(a.id) for a in accounts if a.id != central.id],
        status="blocked" if not plan.ok else "pending_approval",
        idempotency_key=full_key,
        initiated_by=user.id,
        preflight=_plan_json(plan),
    )
    session.add(op)
    await session.flush()
    audit.log(
        session,
        "consolidation_requested",
        person_id=person.id,
        actor_id=user.id,
        actor_type=actor_type,
        operation_id=op.id,
        after={"status": op.status, "blockers": len(plan.blockers)},
    )
    if plan.ok and get_settings().identity_consolidation_auto_approve:
        await execute(session, op, approver_id=None, actor_type="system")
    return op


async def execute(
    session: AsyncSession, op: AccountConsolidationOperation, *, approver_id: uuid.UUID | None, actor_type: str = "admin"
) -> AccountConsolidationOperation:
    """Run (or safely re-run) a consolidation. Completed operations are returned untouched; a failure leaves everything as it was."""
    locked = await session.get(AccountConsolidationOperation, op.id, with_for_update=True, populate_existing=True)
    assert locked is not None
    op = locked
    if op.status == "completed":
        return op
    if op.status not in ("pending_approval", "failed", "blocked"):
        raise AppError("CONSOLIDATION_NOT_RUNNABLE", "این عملیات در وضعیت فعلی قابل اجرا نیست.", 409)
    person = await persons.lock_person(session, op.target_person_id)
    persons.ensure_usable(person)
    accounts = [a for a in await persons.accounts_of(session, person.id) if a.is_active]
    central = next((a for a in accounts if a.id == op.central_user_id), None)
    if central is None:
        raise AppError("CONSOLIDATION_STALE", "حساب مرکزی دیگر معتبر نیست.", 409)
    plan, wallets = await build_plan(session, person, central, accounts, create_wallets=True)
    op.preflight = _plan_json(plan)
    if not plan.ok:
        op.status = "blocked"
        audit.log(
            session,
            "consolidation_blocked",
            person_id=person.id,
            actor_id=approver_id,
            actor_type=actor_type,
            operation_id=op.id,
            after=op.preflight,
        )
        await session.commit()
        raise AppError(
            "CONSOLIDATION_BLOCKED",
            "یکپارچه‌سازی کیف پول به دلیل تعارض مالی متوقف شد؛ حساب‌ها همچنان متصل‌اند.",
            409,
            {"blockers": op.preflight["blockers"]},
        )
    op.status, op.approved_by, op.started_at = "running", approver_id, utcnow()
    await session.flush()
    total_before = sum(w.balance for w in wallets)
    central_before = 0
    try:
        async with session.begin_nested():
            moved = 0
            by_id = {str(w.id): w for w in wallets}
            for src_id, dst_id, amount, currency in plan.transfers:
                src, dst = by_id[src_id], await session.get(Wallet, uuid.UUID(dst_id), with_for_update=True, populate_existing=True)
                assert dst is not None
                central_before += dst.balance
                tx, _ = await wallet_service.post(
                    session,
                    kind="consolidation_transfer",
                    key=f"consolidation:{op.id}:{src.id}",
                    currency=currency,
                    store_id=src.store_id,
                    actor_id=approver_id,
                    memo=f"person consolidation {op.id}",
                    postings=[wallet_service.Posting(-amount, wallet=src, min_balance=0), wallet_service.Posting(amount, wallet=dst)],
                )
                session.add(
                    WalletTransfer(
                        consolidation_id=op.id,
                        source_wallet_id=src.id,
                        target_wallet_id=dst.id,
                        amount=amount,
                        currency=currency,
                        ledger_transaction_id=tx.id,
                        status="done",
                    )
                )
                moved += amount
            for w in wallets:  # every source wallet, empty ones included, is retired and routed to the central wallet
                if w.balance != 0:
                    raise AppError("CONSOLIDATION_RECONCILE", "مانده کیف پول مبدأ پس از انتقال صفر نشد.", 500)
                target = await wallet_service.get_wallet(session, central.id, w.store_id, currency=w.currency, route=False)
                w.status, w.consolidated_into_id = "consolidated", target.id
            if moved != total_before:
                raise AppError("CONSOLIDATION_RECONCILE", "جمع انتقال‌ها با موجودی مبدأ برابر نیست.", 500)
    except Exception as exc:
        op.status = "failed"
        op.failure_reason = (exc.message if isinstance(exc, AppError) else type(exc).__name__)[:500]
        audit.log(
            session,
            "consolidation_failed",
            person_id=person.id,
            actor_id=approver_id,
            actor_type=actor_type,
            operation_id=op.id,
            reason=op.failure_reason,
        )
        await session.commit()
        raise
    person.central_user_id = central.id
    op.status, op.completed_at = "completed", utcnow()
    audit.log(
        session,
        "consolidation_completed",
        person_id=person.id,
        actor_id=approver_id,
        actor_type=actor_type,
        operation_id=op.id,
        before={"total": int(total_before)},
        after={"central_user_id": str(central.id), "moved": int(moved)},
    )
    await session.commit()
    return op
