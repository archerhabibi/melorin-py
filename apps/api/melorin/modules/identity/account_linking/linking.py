"""Attach / detach login identities and link two persons (identity level only: no money moves here, see ``consolidation``)."""

import datetime as dt
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.config import get_settings
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.domain.timeutil import aware
from melorin.core.security import new_opaque_token, token_hash
from melorin.domain import account_linking as rules
from melorin.kernel.models.identity import Identity, RefreshToken, User
from melorin.kernel.models.person import AccountLinkEvidence, AccountLinkOperation, Person
from melorin.modules.identity.account_linking import audit, persons
from melorin.modules.identity.lookup import find_identity_any

OP_TTL = dt.timedelta(minutes=10)


def is_expired(op: AccountLinkOperation) -> bool:
    return aware(op.expires_at) < utcnow()


def _snapshot(i: Identity) -> dict:
    return {"identity_id": str(i.id), "provider": i.provider, "status": i.status, "user_id": str(i.user_id), "person_id": str(i.person_id)}


async def new_operation(
    session: AsyncSession,
    user: User,
    person: Person,
    *,
    provider: str,
    operation_type: str,
    status: str = rules.OpStatus.PENDING,
    with_token: bool = False,
    subject_ref: str | None = None,
    store_id: uuid.UUID | None = None,
    data: dict | None = None,
) -> tuple[AccountLinkOperation, str | None]:
    raw = new_opaque_token(24) if with_token else None
    op = AccountLinkOperation(
        person_id=person.id,
        user_id=user.id,
        provider=provider,
        operation_type=operation_type,
        status=str(status),
        token_hash=token_hash("alink" + raw) if raw else None,
        subject_ref=subject_ref,
        store_id=store_id,
        expires_at=utcnow() + OP_TTL,
        data=data,
    )
    session.add(op)
    await session.flush()
    return op, raw


def add_evidence(
    session: AsyncSession,
    op: AccountLinkOperation,
    kind: rules.Evidence,
    *,
    subject: str | None = None,
    ok: bool = True,
    data: dict | None = None,
) -> None:
    session.add(
        AccountLinkEvidence(
            operation_id=op.id,
            evidence_type=str(kind),
            subject_reference=subject,
            result="passed" if ok else "failed",
            verified_at=utcnow() if ok else None,
            data=data,
        )
    )


# ---------------------------------------------------------------------------------------------------- attach
async def attach_identity(
    session: AsyncSession,
    user: User,
    provider: str,
    subject: str,
    *,
    evidence: rules.Evidence,
    data: dict | None = None,
    replace: bool = False,
    operation: AccountLinkOperation | None = None,
) -> str:
    """Attach a *proven* identity to ``user``'s person. Returns ``attached | reactivated | already | replaced``; refuses otherwise.

    ``evidence`` is how the caller proved control of the identity itself (Google token, e-mail code, bot-verified Telegram id).
    """
    person = await persons.ensure_person(session, user)
    persons.ensure_usable(person)
    ident = await find_identity_any(session, provider, subject)
    other_person: uuid.UUID | None = None
    if ident is not None and ident.person_id is None:
        owner = await session.get(User, ident.user_id)
        if owner is not None:
            ident.person_id = (await persons.ensure_person(session, owner)).id
    if ident is not None:
        other_person = ident.person_id
    facts = rules.IdentityFacts(
        exists=ident is not None, active=bool(ident and ident.status == "active"), person_id=str(other_person) if other_person else None
    )
    counts = await persons.active_provider_counts(session, person.id)
    verdict = rules.decide_attach(
        provider=provider,
        target_person_id=str(person.id),
        identity=facts,
        person_active_providers=counts,
        evidence=frozenset({evidence}),
    )
    if verdict is rules.Verdict.ALREADY:
        return "already"
    if verdict is rules.Verdict.REFUSE_UNPROVEN:
        raise AppError("OWNERSHIP_NOT_PROVEN", "مالکیت این هویت هنوز تأیید نشده است.", 403)
    if verdict is rules.Verdict.CONFLICT:
        assert ident is not None
        op = await open_conflict(session, user, person, provider, subject, other_person, evidence, operation)
        await session.commit()  # the conflict record must survive the refusal below
        raise AppError(
            "IDENTITY_IN_USE",
            "این هویت به پروفایل دیگری متصل است. اگر هر دو حساب مال شماست، اتصال را در صفحهٔ «اتصال حساب‌ها» تأیید کنید.",
            409,
            {"operation_id": str(op.id), "status": op.status},
        )
    if verdict is rules.Verdict.REFUSE_TELEGRAM_LIMIT:
        if not replace:
            raise AppError(
                "TELEGRAM_ALREADY_LINKED", "این پروفایل قبلاً یک تلگرام فعال دارد؛ برای تعویض از «تغییر تلگرام» استفاده کنید.", 409
            )
        for old in await persons.identities_of(session, person.id):
            if old.provider == provider:
                before = _snapshot(old)
                old.status, old.revoked_at = "revoked", utcnow()
                audit.log(
                    session,
                    "telegram_replaced",
                    person_id=person.id,
                    actor_id=user.id,
                    operation_id=operation.id if operation else None,
                    before=before,
                    after=_snapshot(old),
                )
        await session.flush()  # free the one-active-telegram slot before the new row takes it
    now = utcnow()
    if ident is None:
        ident = Identity(
            user_id=user.id, person_id=person.id, provider=provider, subject=subject, verified_at=now, data=data, status="active"
        )
        session.add(ident)
        outcome = "attached"
    else:
        before = _snapshot(ident)
        ident.user_id, ident.person_id, ident.status, ident.revoked_at, ident.verified_at = (
            user.id,
            person.id,
            "active",
            None,
            ident.verified_at or now,
        )
        if data:
            ident.data = data
        outcome = "reactivated"
        audit.log(
            session,
            "identity_reactivated",
            person_id=person.id,
            actor_id=user.id,
            operation_id=operation.id if operation else None,
            before=before,
        )
    await session.flush()
    if replace and verdict is rules.Verdict.REFUSE_TELEGRAM_LIMIT:
        outcome = "replaced"
    audit.log(
        session,
        "identity_linked",
        person_id=person.id,
        actor_id=user.id,
        operation_id=operation.id if operation else None,
        after={**_snapshot(ident), "outcome": outcome},
    )
    return outcome


async def open_conflict(
    session: AsyncSession,
    user: User,
    person: Person,
    provider: str,
    subject: str,
    other_person_id: uuid.UUID | None,
    evidence: rules.Evidence,
    operation: AccountLinkOperation | None = None,
) -> AccountLinkOperation:
    """Record that a proven identity belongs to another person. Nothing moves; the signed-in user may confirm the person link later."""
    op = operation
    if op is None:
        op, _ = await new_operation(
            session, user, person, provider=provider, operation_type=rules.OpType.MERGE, status=rules.OpStatus.CONFLICT, subject_ref=subject
        )
    else:
        op.status = str(rules.OpStatus.CONFLICT)
        op.expires_at = utcnow() + OP_TTL
    op.conflict_person_id = other_person_id
    op.subject_ref = subject
    add_evidence(session, op, evidence, subject=f"{provider}:{subject}")
    audit.log(
        session,
        "conflict_detected",
        person_id=person.id,
        actor_id=user.id,
        operation_id=op.id,
        after={"provider": provider, "other_person_id": str(other_person_id)},
    )
    return op


# ------------------------------------------------------------------------------------------------ person link
async def confirm_person_link(session: AsyncSession, user: User, operation_id: uuid.UUID, *, keep_telegram: str | None = None) -> dict:
    """The signed-in user confirms that the other person (whose identity they just proved) is also theirs."""
    op = await session.get(AccountLinkOperation, operation_id, with_for_update=True)
    if op is None or op.user_id != user.id:
        raise AppError("NOT_FOUND", "عملیات اتصال یافت نشد.", 404)
    if op.status == rules.OpStatus.CONFIRMED:
        return {"status": "confirmed", "person_id": str(op.person_id)}  # idempotent
    if op.status != rules.OpStatus.CONFLICT or op.conflict_person_id is None:
        raise AppError("OPERATION_NOT_CONFIRMABLE", "این درخواست قابل تأیید نیست.", 409)
    if is_expired(op):
        op.status = str(rules.OpStatus.EXPIRED)
        await session.commit()
        raise AppError("OPERATION_EXPIRED", "زمان تأیید این اتصال تمام شده؛ دوباره شروع کنید.", 410)
    # lock both persons in id order: two concurrent confirmations cannot interleave
    first, second = sorted({op.person_id, op.conflict_person_id}, key=str)
    locked = {first: await persons.lock_person(session, first), second: await persons.lock_person(session, second)}
    target, source = locked[op.person_id], locked[op.conflict_person_id]
    if user.person_id != target.id:
        raise AppError("OPERATION_STALE", "این درخواست دیگر معتبر نیست.", 409)
    persons.ensure_usable(target)
    if source.status == "merged":  # somebody linked it meanwhile
        op.status = str(rules.OpStatus.REJECTED)
        await session.commit()
        raise AppError("OPERATION_STALE", "این درخواست دیگر معتبر نیست.", 409)
    persons.ensure_usable(source)
    summary = await link_persons(session, target, source, actor_id=user.id, operation=op, keep_telegram=keep_telegram)
    op.status, op.completed_at = str(rules.OpStatus.CONFIRMED), utcnow()
    add_evidence(session, op, rules.Evidence.SESSION, subject=f"user:{user.id}")
    await session.commit()
    if summary.get("consolidation_required") and get_settings().identity_consolidation_auto_approve:
        summary["consolidation"] = await _continue_with_consolidation(session, user, op.id)
    return summary


async def _continue_with_consolidation(session: AsyncSession, user: User, operation_id: uuid.UUID) -> dict:
    """One product flow: after proof of ownership and consent, preflight and (when clean) consolidate. A failure here never undoes the link."""
    from melorin.modules.identity.account_linking import consolidation

    try:
        cons = await consolidation.request(session, user, key=f"auto:{operation_id}", actor_type="system")
        await session.commit()
        return {"operation_id": str(cons.id), "status": cons.status}
    except AppError as exc:
        await session.rollback()
        return {"status": "skipped", "code": exc.code}


async def link_persons(
    session: AsyncSession,
    target: Person,
    source: Person,
    *,
    actor_id: uuid.UUID | None,
    operation: AccountLinkOperation | None = None,
    keep_telegram: str | None = None,
    actor_type: str = "user",
) -> dict:
    """Fold ``source`` into ``target``: accounts and identities change owner, wallets stay exactly where they are."""
    if target.id == source.id:
        return {"status": "confirmed", "person_id": str(target.id)}
    t_ids = await persons.identities_of(session, target.id)
    s_ids = await persons.identities_of(session, source.id)
    t_tg = next((i for i in t_ids if i.provider == "telegram"), None)
    s_tg = next((i for i in s_ids if i.provider == "telegram"), None)
    action, revoke_side = rules.telegram_conflict_resolution(t_tg is not None, s_tg is not None, keep_telegram)
    if action == "need_choice":
        raise AppError(
            "TELEGRAM_CHOICE_REQUIRED",
            "هر دو پروفایل یک تلگرام فعال دارند؛ مشخص کنید کدام تلگرام نگه داشته شود (keep_telegram = target | source).",
            409,
            {"operation_id": str(operation.id) if operation else None},
        )
    if revoke_side is not None:
        loser = t_tg if revoke_side == "target" else s_tg
        assert loser is not None
        before = _snapshot(loser)
        loser.status, loser.revoked_at = "revoked", utcnow()
        audit.log(
            session,
            "telegram_replaced",
            person_id=target.id,
            actor_id=actor_id,
            actor_type=actor_type,
            operation_id=operation.id if operation else None,
            before=before,
            after=_snapshot(loser),
            reason="person_link",
        )
        await session.flush()
    moved_accounts = [str(u.id) for u in await persons.accounts_of(session, source.id)]
    await session.execute(update(User).where(User.person_id == source.id).values(person_id=target.id))
    await session.execute(update(Identity).where(Identity.person_id == source.id).values(person_id=target.id))
    await session.execute(
        update(AccountLinkOperation)
        .where(
            AccountLinkOperation.person_id == source.id, AccountLinkOperation.status.in_([rules.OpStatus.PENDING, rules.OpStatus.CONFLICT])
        )
        .values(status=str(rules.OpStatus.REVOKED))
    )
    source.status, source.merged_into_id = "merged", target.id
    if target.central_user_id is None and source.central_user_id is not None:
        target.central_user_id = source.central_user_id
    await session.flush()
    audit.log(
        session,
        "persons_linked",
        person_id=target.id,
        actor_id=actor_id,
        actor_type=actor_type,
        operation_id=operation.id if operation else None,
        before={"source_person_id": str(source.id)},
        after={"moved_accounts": moved_accounts, "wallets_moved": False},
    )
    return {"status": "confirmed", "person_id": str(target.id), "moved_accounts": moved_accounts, "consolidation_required": True}


# --------------------------------------------------------------------------------------------------- unlink
async def unlink_identity(session: AsyncSession, user: User, identity_id: uuid.UUID) -> dict:
    """Revoke one login method of the caller's person. Never deletes the person, the accounts, orders or wallets."""
    person = await persons.ensure_person(session, user)
    persons.ensure_usable(person)
    target = await session.get(Identity, identity_id, with_for_update=True)
    if target is None or target.person_id != person.id:
        raise AppError("NOT_FOUND", "روش ورود یافت نشد.", 404)
    active = await persons.identities_of(session, person.id)
    usable_others = [i for i in active if i.id != target.id and i.verified_at is not None]
    ok, why = rules.can_unlink(
        active_methods=len(active),
        is_target_last_usable=not usable_others,
        target_provider=target.provider,
        target_is_active=target.status == "active",
    )
    if not ok:
        if why == "not_active":
            return {"status": "revoked", "identity_id": str(target.id)}  # idempotent
        audit.log(session, "unlink_refused", person_id=person.id, actor_id=user.id, after={"identity_id": str(target.id), "reason": why})
        await session.commit()
        raise AppError("LAST_LOGIN_METHOD", "این آخرین روش ورود شماست؛ ابتدا یک روش دیگر اضافه کنید.", 409)
    before = _snapshot(target)
    target.status, target.revoked_at = "revoked", utcnow()
    op, _ = await new_operation(
        session,
        user,
        person,
        provider=target.provider,
        operation_type=rules.OpType.UNLINK,
        status=rules.OpStatus.CONFIRMED,
        subject_ref=target.provider,
    )
    op.completed_at = utcnow()
    add_evidence(session, op, rules.Evidence.SESSION, subject=f"user:{user.id}")
    # sessions of the account the identity belonged to end: a revoked method must not keep a door open
    await session.execute(
        update(RefreshToken).where(RefreshToken.user_id == target.user_id, RefreshToken.revoked_at.is_(None)).values(revoked_at=utcnow())
    )
    audit.log(
        session, "identity_unlinked", person_id=person.id, actor_id=user.id, operation_id=op.id, before=before, after=_snapshot(target)
    )
    await session.commit()
    return {"status": "revoked", "identity_id": str(target.id)}


async def reject_operation(session: AsyncSession, user: User, operation_id: uuid.UUID) -> dict:
    op = await session.get(AccountLinkOperation, operation_id, with_for_update=True)
    if op is None or op.user_id != user.id:
        raise AppError("NOT_FOUND", "عملیات اتصال یافت نشد.", 404)
    if op.status in (rules.OpStatus.PENDING, rules.OpStatus.CONFLICT, rules.OpStatus.CANDIDATE):
        op.status = str(rules.OpStatus.REJECTED)
        audit.log(session, "link_rejected", person_id=op.person_id, actor_id=user.id, operation_id=op.id)
        await session.commit()
    return {"status": op.status}


async def expire_stale(session: AsyncSession, limit: int = 500) -> int:
    """Worker sweep: pending / conflict operations whose time ran out become ``expired`` (nothing was activated meanwhile)."""
    rows = (
        await session.scalars(
            select(AccountLinkOperation)
            .where(
                AccountLinkOperation.status.in_([rules.OpStatus.PENDING, rules.OpStatus.CONFLICT]),
                AccountLinkOperation.expires_at < utcnow(),
            )
            .limit(limit)
        )
    ).all()
    for op in rows:
        op.status = str(rules.OpStatus.EXPIRED)
    if rows:
        await session.commit()
    return len(rows)


async def person_id_of_identity(session: AsyncSession, ident: Identity) -> uuid.UUID | None:
    """The person an identity belongs to (a legacy row without one gets it from its account)."""
    if ident.person_id is None:
        owner = await session.get(User, ident.user_id)
        if owner is not None:
            ident.person_id = (await persons.ensure_person(session, owner)).id
    return ident.person_id


async def adopt_identity(
    session: AsyncSession, user: User, provider: str, subject: str, *, data: dict | None = None, verified: bool = True
) -> Identity:
    """Give a brand-new account its first login identity. A revoked row of the same identity is brought back instead of colliding
    with the unique ``(provider, subject)`` slot (only reachable when the caller already found no ACTIVE owner)."""
    now = utcnow()
    stale = await find_identity_any(session, provider, subject)
    if stale is not None:
        stale.user_id, stale.person_id, stale.status, stale.revoked_at = user.id, user.person_id, "active", None
        stale.verified_at = now if verified else stale.verified_at
        stale.data = data if data is not None else stale.data
        await session.flush()
        return stale
    ident = Identity(
        user_id=user.id,
        person_id=user.person_id,
        provider=provider,
        subject=subject,
        data=data,
        verified_at=now if verified else None,
        status="active",
    )
    session.add(ident)
    await session.flush()
    return ident
