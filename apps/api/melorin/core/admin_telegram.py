"""The admin's numeric Telegram ID: a *delivery address* for admin alerts, nothing else.

The admin's bot DM is reserved for what is very important (panel / node failures, failed provisioning, customers' payments and receipts;
``domain.messaging_policy``); every other admin notice goes to the Telegram supergroup (Event Center). The DM is sent through the main
Telegram bot, and a Telegram bot can only write to a numeric chat ID, so the installer asks for it.

The ID is stored as a system setting (``admin.telegram_id:<admin user id>``), NOT as a Telegram identity of the admin account. That is
what keeps the two roles apart: opening the bot with that Telegram account signs in an ordinary customer (its own account, wallet,
orders and accounts: it can buy and renew like anybody), while the bot merely recognises the chat as the admin's alert address
(``is_alert_chat``). Admins still sign in only through the panel (``ADMIN_USE_PANEL``).
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, settings_store
from melorin.core.errors import AppError
from melorin.kernel.models.identity import User
from melorin.kernel.models.system import SystemSetting

KEY_PREFIX = "admin.telegram_id:"

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


def _key(user_id) -> str:
    return f"{KEY_PREFIX}{user_id}"


async def current(session: AsyncSession, user_id) -> str | None:
    """The admin's alert address, if one is set."""
    value = await settings_store.get(session, _key(user_id))
    return str(value) if value else None


async def alert_addresses(session: AsyncSession) -> dict[str, str]:
    """``{admin user id: telegram id}`` of every admin that has an alert address."""
    rows = (await session.scalars(select(SystemSetting).where(SystemSetting.key.startswith(KEY_PREFIX)))).all()
    return {r.key[len(KEY_PREFIX) :]: str(r.value) for r in rows if r.value}


async def is_alert_chat(session: AsyncSession, telegram_id: object) -> bool:
    """Whether ``telegram_id`` is an admin's alert address. Recognition only: it grants no rights and changes no session."""
    tg = str(telegram_id or "").strip()
    return bool(tg) and tg in (await alert_addresses(session)).values()


async def link(session: AsyncSession, admin: User, raw_id: object, *, actor_id=None) -> str:
    """Make ``raw_id`` the admin's alert address (replacing an earlier one). Returns the stored ID; the caller commits.

    The ID may also belong to an ordinary customer account (typically the admin's own): the address and the customer identity are
    independent, so nothing is merged and nothing is refused.
    """
    tg = parse_telegram_id(raw_id)
    before = await current(session, admin.id)
    await settings_store.set_value(session, _key(admin.id), tg)
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
