"""Automatic settlement of identity-link conflicts (docs/21, decision in ``melorin.domain.identity_auto_link``).

``try_auto_resolve`` is called right after a conflict review is queued (same transaction) and by the worker sweep. When it
is provably safe the empty-shell account is folded into the account that holds the records; otherwise the review stays
open for an admin. Every automatic step is audited and leaves the review row behind (status ``linked``, no resolver,
note ``auto:<rule>``), so nothing is hidden.
"""

import datetime as dt
import logging
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit
from melorin.core.config import get_settings
from melorin.core.db import utcnow
from melorin.domain.identity_auto_link import Account, Outcome, Resolution, resolve
from melorin.kernel.base import Base
from melorin.kernel.models.identity import Identity, IdentityLinkReview, RefreshToken, TrustedDevice, User
from melorin.kernel.models.stores import StoreMembership
from melorin.kernel.models.wallet import LedgerEntry, Wallet

log = logging.getLogger(__name__)

# Reasons that are queued only after the person proved the identity (e-mail code / Google token) or that name exactly one
# other account. Ambiguous reasons (several candidates) are never touched.
AUTO_REASONS = {
    "verified_email_matches_other_user",
    "google_account_belongs_to_other_user",
    "multiple_verified_email_users",
    "email_field_conflict",
}

# Tables whose rows about a user carry no business value: they follow the identity (or die with the shell).
DISPOSABLE_TABLES = {
    "identities",
    "identity_link_reviews",
    "terms_acceptances",
    "notifications",
    "refresh_tokens",
    "verification_codes",
    "telegram_login_sessions",
    "trusted_devices",
    "store_memberships",
    "wallets",  # judged separately: only an untouched zero wallet is disposable
}


def enabled() -> bool:
    return bool(get_settings().identity_auto_link)


def _ts(value: dt.datetime | None) -> int:
    if value is None:
        return 0
    return int(value.replace(tzinfo=value.tzinfo or dt.UTC).timestamp())


async def shell_blockers(session: AsyncSession, user: User) -> list[str]:
    """Why ``user`` is NOT an empty shell (empty list = a shell). Table names, discovered from the schema itself, so a table
    added tomorrow protects its rows without anyone remembering to list it here."""
    blockers: list[str] = []
    if user.password_hash:
        blockers.append("password")
    if user.totp_enabled:
        blockers.append("2fa")
    if user.is_super_admin or (user.admin_roles or []):
        blockers.append("admin")
    for table in Base.metadata.sorted_tables:
        if table.name in DISPOSABLE_TABLES:
            continue
        for col in table.columns:
            if not any(fk.target_fullname == "users.id" for fk in col.foreign_keys):
                continue
            if await session.scalar(select(1).select_from(table).where(col == user.id).limit(1)):
                blockers.append(f"{table.name}.{col.name}")
    if await session.scalar(select(1).select_from(Wallet).where(Wallet.user_id == user.id, Wallet.balance != 0).limit(1)):
        blockers.append("wallets.balance")
    if await session.scalar(
        select(1).select_from(LedgerEntry).join(Wallet, Wallet.id == LedgerEntry.wallet_id).where(Wallet.user_id == user.id).limit(1)
    ):
        blockers.append("ledger_entries")
    return blockers


async def _account(session: AsyncSession, user: User) -> Account:
    return Account(
        user_id=str(user.id),
        is_shell=not await shell_blockers(session, user),
        eligible=bool(user.is_active) and not user.is_super_admin and not (user.admin_roles or []),
        created_rank=_ts(user.created_at),
    )


async def merge(session: AsyncSession, keeper: User, shell: User, *, reason: str, review: IdentityLinkReview | None = None) -> None:
    """Fold ``shell`` into ``keeper``: its identities, e-mail, trusted devices and store memberships move over, its sessions
    end, the account itself is deactivated and archived (kept for the audit trail, never deleted)."""
    now = utcnow()
    shell_idents = (await session.scalars(select(Identity).where(Identity.user_id == shell.id))).all()
    moved = [i.provider for i in shell_idents]
    for ident in shell_idents:
        ident.user_id = keeper.id
    if shell.email:
        email, shell.email = shell.email, None
        await session.flush()  # release the platform-unique e-mail before the keeper takes it
        if not keeper.email:
            keeper.email = email
    keeper.display_name = keeper.display_name or shell.display_name
    keeper.is_guest = bool(keeper.is_guest) and bool(shell.is_guest)
    await session.execute(update(TrustedDevice).where(TrustedDevice.user_id == shell.id).values(user_id=keeper.id))
    held = set((await session.scalars(select(StoreMembership.store_id).where(StoreMembership.user_id == keeper.id))).all())
    for m in (await session.scalars(select(StoreMembership).where(StoreMembership.user_id == shell.id))).all():
        if m.store_id not in held:
            m.user_id = keeper.id
            held.add(m.store_id)
    await session.execute(
        update(RefreshToken).where(RefreshToken.user_id == shell.id, RefreshToken.revoked_at.is_(None)).values(revoked_at=now)
    )
    await session.execute(
        update(IdentityLinkReview)
        .where(IdentityLinkReview.source_user_id == shell.id, IdentityLinkReview.status == "open")
        .values(status="linked", resolution_note=f"auto:{reason}"[:500])
    )
    shell.is_active, shell.archived_at = False, now
    await session.flush()
    for u in (keeper, shell):
        session.expire(u, ["identities"])  # the in-memory collections are stale after the move
    data = {"keeper": str(keeper.id), "shell": str(shell.id), "rule": reason, "providers": moved}
    audit.record(session, "identity.auto_merged", actor_type="system", entity_type="user", entity_id=keeper.id, data=data)
    audit.security_event(session, "identity_auto_merged", keeper.id, data)
    if review is not None:
        review.status, review.resolved_by, review.resolution_note = "linked", None, f"auto:{reason}"[:500]


async def try_auto_resolve(session: AsyncSession, review: IdentityLinkReview) -> Resolution | None:
    """The settled ``Resolution`` when the review was resolved automatically (the caller commits), else ``None``."""
    if not enabled() or review.status != "open" or review.reason not in AUTO_REASONS:
        return None
    candidates = {str(c) for c in (review.candidate_user_ids or [])}
    if len(candidates) != 1:
        return None
    try:
        other_id = uuid.UUID(next(iter(candidates)))
    except ValueError:
        return None
    a, b = await session.get(User, review.source_user_id), await session.get(User, other_id)
    if a is None or b is None:
        return None
    return await try_auto_merge(session, a, b, review=review)


async def try_auto_merge(session: AsyncSession, a: User, b: User, *, review: IdentityLinkReview | None = None) -> Resolution | None:
    """Merge two accounts that provably belong to the same person when the rule allows it. ``None`` = leave it to an admin.
    The caller is responsible for the proof of ownership (e-mail code, Google token, bot link code) and for committing."""
    if not enabled():
        return None
    res = resolve(await _account(session, a), await _account(session, b))
    if res.outcome is not Outcome.MERGE:
        return None
    by_id = {str(a.id): a, str(b.id): b}
    await merge(session, by_id[res.keeper], by_id[res.shell], reason=res.reason, review=review)
    return res


async def sweep(session: AsyncSession, limit: int = 200) -> int:
    """Settle every open review that has become safe since it was queued (e.g. the shell stayed empty). Returns how many."""
    rows = (
        await session.scalars(
            select(IdentityLinkReview)
            .where(IdentityLinkReview.status == "open", IdentityLinkReview.reason.in_(AUTO_REASONS))
            .order_by(IdentityLinkReview.created_at)
            .limit(limit)
            .with_for_update()
        )
    ).all()
    done = 0
    for r in rows:
        if r.status == "open" and await try_auto_resolve(session, r) is not None:
            done += 1
    if done:
        await session.commit()
    return done


async def open_count(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(IdentityLinkReview).where(IdentityLinkReview.status == "open")) or 0)
