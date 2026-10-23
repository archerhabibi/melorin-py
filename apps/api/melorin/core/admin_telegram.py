"""The main admin's numeric Telegram ID.

Admin alerts (a provisioning failure, a new reseller application, the manual set-up tasks of a new reseller) reach the admin
through the main Telegram bot. A Telegram bot can only write to a numeric chat ID, so the installer asks for it and Core links
it to the admin account as an ordinary ``telegram`` identity: the same row the notification worker already looks up.

Admins still never sign in through Telegram (``ADMIN_USE_PANEL``); the identity is only a delivery address.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.kernel.models.identity import Identity, User

_ID = re.compile(r"^[1-9][0-9]{4,14}$")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def parse_telegram_id(raw: object) -> str:
    """'  ۱۲۳۴۵۶۷۸۹ ' -> '123456789'. A Telegram user ID is a positive integer of 5-15 digits (never a @username)."""
    value = str(raw if raw is not None else "").translate(_DIGITS).strip()
    if not _ID.match(value):
        raise AppError(
            "INVALID_TELEGRAM_ID",
            "آیدی عددی تلگرام معتبر نیست؛ فقط عدد (۵ تا ۱۵ رقم) بفرستید، نه @username. آن را از ربات @userinfobot بگیرید.",
            422,
        )
    return value


def admin_telegram_id(user_identities) -> str | None:
    """The Telegram ID among a user's identities, if any (pure helper for views and tests)."""
    for ident in user_identities:
        if ident.provider == "telegram":
            return ident.subject
    return None


async def current(session: AsyncSession, user_id) -> str | None:
    row = await session.scalar(select(Identity).where(Identity.user_id == user_id, Identity.provider == "telegram"))
    return row.subject if row else None


async def link(session: AsyncSession, admin: User, raw_id: object, *, actor_id=None) -> str:
    """Make ``raw_id`` the admin's Telegram address (replacing an earlier one). Returns the stored ID; the caller commits.

    Refuses an ID that already belongs to another account: Core never merges accounts on its own, and a customer who
    happened to open the bot with that ID keeps his account.
    """
    tg = parse_telegram_id(raw_id)
    taken = await session.scalar(select(Identity).where(Identity.provider == "telegram", Identity.subject == tg))
    if taken is not None and taken.user_id != admin.id:
        raise AppError(
            "TELEGRAM_ID_IN_USE",
            "این آیدی تلگرام قبلاً به حساب دیگری متصل شده است. با آیدی دیگری تلاش کنید.",
            409,
        )
    mine = (await session.scalars(select(Identity).where(Identity.user_id == admin.id, Identity.provider == "telegram"))).all()
    before = mine[0].subject if mine else None
    if taken is None:
        if mine:  # replace: one delivery address per admin
            mine[0].subject, mine[0].verified_at, mine[0].data = tg, utcnow(), {"source": "admin_telegram_id"}
        else:
            session.add(
                Identity(user_id=admin.id, provider="telegram", subject=tg, verified_at=utcnow(), data={"source": "admin_telegram_id"})
            )
    audit.record(
        session,
        "admin.telegram_id_set",
        actor_id=actor_id or admin.id,
        actor_type="admin",
        entity_type="user",
        entity_id=admin.id,
        data={"changed": before != tg},
    )
    return tg
