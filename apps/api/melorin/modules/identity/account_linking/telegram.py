"""Telegram side of linking: a short-lived, single-use, hashed token carries the website's proof to the bot (docs/25 §4)."""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.invariants import require
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.core.security import token_hash
from melorin.domain import account_linking as rules
from melorin.kernel.models.identity import User
from melorin.kernel.models.person import AccountLinkOperation
from melorin.modules.identity.account_linking import audit, linking, persons


async def start(session: AsyncSession, user: User, *, store_id: uuid.UUID | None = None) -> tuple[AccountLinkOperation, str]:
    """The signed-in account asks to attach (or, when the person already has one, replace) its Telegram. Returns (operation, raw token)."""
    person = await persons.ensure_person(session, user)
    persons.ensure_usable(person)
    replace = (await persons.active_provider_counts(session, person.id)).get("telegram", 0) > 0
    # a newer attempt supersedes older pending ones of this account: only one live token at a time
    await session.execute(
        update(AccountLinkOperation)
        .where(
            AccountLinkOperation.user_id == user.id,
            AccountLinkOperation.provider == "telegram",
            AccountLinkOperation.status == rules.OpStatus.PENDING,
            AccountLinkOperation.token_hash.is_not(None),
        )
        .values(status=str(rules.OpStatus.REVOKED), token_hash=None)
    )
    op, raw = await linking.new_operation(
        session,
        user,
        person,
        provider="telegram",
        operation_type=rules.OpType.REPLACE if replace else rules.OpType.LINK,
        with_token=True,
        store_id=store_id,
    )
    raw = require(raw, "raw")
    linking.add_evidence(session, op, rules.Evidence.SESSION, subject=f"user:{user.id}")
    audit.log(
        session, "telegram_link_started", person_id=person.id, actor_id=user.id, operation_id=op.id, after={"type": op.operation_type}
    )
    return op, raw


async def find_operation(session: AsyncSession, raw: str) -> AccountLinkOperation | None:
    return await session.scalar(
        select(AccountLinkOperation).where(AccountLinkOperation.token_hash == token_hash("alink" + (raw or ""))).with_for_update()
    )


async def begin_completion(session: AsyncSession, op: AccountLinkOperation) -> User:
    """Validate the token (single use, not expired, still the same person) and burn it. Returns the account that asked."""
    if op.status != rules.OpStatus.PENDING or linking.is_expired(op):
        if op.status == rules.OpStatus.PENDING:
            op.status = str(rules.OpStatus.EXPIRED)
            await session.commit()
        raise AppError("CODE_INVALID", "کد اتصال نامعتبر یا منقضی است.", 400)
    user = await session.get(User, op.user_id)
    if user is None or not user.is_active or user.person_id != op.person_id:
        raise AppError("CODE_INVALID", "کد اتصال نامعتبر یا منقضی است.", 400)
    op.token_hash = None  # single use, even if the attach below is refused
    return user


async def finish(session: AsyncSession, op: AccountLinkOperation, *, subject: str, outcome: str) -> None:
    linking.add_evidence(session, op, rules.Evidence.TELEGRAM_BOT, subject=f"telegram:{subject}")
    op.status, op.completed_at, op.subject_ref = str(rules.OpStatus.CONFIRMED), utcnow(), subject
    audit.log(
        session,
        "telegram_link_completed",
        person_id=op.person_id,
        actor_id=op.user_id,
        actor_type="bot",
        operation_id=op.id,
        after={"outcome": outcome},
    )
