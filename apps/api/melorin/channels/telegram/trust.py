"""Trusted devices: the engine behind automatic identity verification of the Telegram website login.

Policy (docs/18-Automatic-Identity-Verification.md)

* ``silent``  known browser + same network + seen recently  -> signed in with no bot step at all.
* ``auto``    known browser (any network)                   -> opening the bot link is the whole approval, no number match.
* ``manual``  unknown browser                               -> the number-match confirmation, exactly as before.

A relayed phishing link can never reach ``auto``/``silent``: the attacker's browser holds a device key the victim's
account has never approved. The key is a random value that stays in the browser; only its SHA-256 is stored here.
"""

import datetime as dt
import ipaddress
import re

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.config import get_settings
from melorin.core.db import utcnow
from melorin.core.security import token_hash
from melorin.kernel.models.identity import TrustedDevice

_KEY = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
MAX_DEVICES_PER_ACCOUNT = 10


def _aware(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=value.tzinfo or dt.UTC)


def trust_days() -> int:
    return max(0, min(365, int(get_settings().telegram_web_login_trust_days)))


def silent_days() -> int:
    return max(0, min(trust_days(), int(get_settings().telegram_web_login_silent_days)))


def key_hash_of(device_key: str | None) -> str | None:
    """Hash of a well-formed device key, else None (a malformed key is simply treated as 'no key')."""
    key = (device_key or "").strip()
    return token_hash("trusted-device:" + key) if _KEY.match(key) else None


def network_of(ip: str | None) -> str | None:
    """/24 for IPv4, /48 for IPv6: a home or mobile address that drifts inside its network is still 'the same place'."""
    try:
        addr = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return None
    return str(ipaddress.ip_network(f"{addr}/{24 if addr.version == 4 else 48}", strict=False))


def same_network(a: str | None, b: str | None) -> bool:
    na = network_of(a)
    return na is not None and na == network_of(b)


async def find_valid(session: AsyncSession, key_hash: str | None, store_id, *, telegram_id: int | None = None) -> TrustedDevice | None:
    """The live trusted device behind ``key_hash`` for that store (and, when given, that Telegram account)."""
    if not key_hash or trust_days() <= 0:
        return None
    row = await session.scalar(select(TrustedDevice).where(TrustedDevice.key_hash == key_hash).with_for_update())
    if row is None or row.revoked_at is not None or row.store_id != store_id:
        return None
    if _aware(row.expires_at) <= utcnow():
        return None
    if telegram_id is not None and row.telegram_id != telegram_id:
        return None
    return row


def level_for(device: TrustedDevice | None, ip: str | None) -> str:
    """``silent`` | ``auto`` | ``manual`` for a login attempt coming from ``ip`` with this (possibly absent) device."""
    if device is None:
        return "manual"
    fresh = _aware(device.last_seen_at) > utcnow() - dt.timedelta(days=silent_days())
    if silent_days() > 0 and fresh and same_network(device.last_ip, ip):
        return "silent"
    return "auto"


async def remember(
    session: AsyncSession, *, key_hash: str | None, user_id, store_id, telegram_id: int, label: str | None, ip: str | None
) -> TrustedDevice | None:
    """Create or renew trust after a successful approval. Sliding expiry; the oldest devices make room for new ones."""
    if not key_hash or trust_days() <= 0:
        return None
    now = utcnow()
    expires = now + dt.timedelta(days=trust_days())
    row = await session.scalar(select(TrustedDevice).where(TrustedDevice.key_hash == key_hash).with_for_update())
    if row is not None:
        if row.user_id != user_id or row.store_id != store_id or row.telegram_id != telegram_id:
            return None  # the key belongs to another account: never re-bind it silently
        row.revoked_at, row.last_seen_at, row.expires_at = None, now, expires
        row.last_ip, row.label, row.uses = (ip or "")[:64] or None, label or row.label, (row.uses or 0) + 1
        return row
    live = (
        await session.scalars(
            select(TrustedDevice)
            .where(TrustedDevice.user_id == user_id, TrustedDevice.store_id == store_id, TrustedDevice.revoked_at.is_(None))
            .order_by(TrustedDevice.last_seen_at.desc())
        )
    ).all()
    for old in live[MAX_DEVICES_PER_ACCOUNT - 1 :]:
        old.revoked_at = now
    row = TrustedDevice(
        user_id=user_id,
        store_id=store_id,
        telegram_id=telegram_id,
        key_hash=key_hash,
        label=label,
        last_ip=(ip or "")[:64] or None,
        last_seen_at=now,
        expires_at=expires,
    )
    session.add(row)
    return row


def touch(device: TrustedDevice, ip: str | None) -> None:
    device.last_seen_at, device.last_ip, device.uses = utcnow(), (ip or "")[:64] or device.last_ip, (device.uses or 0) + 1
    device.expires_at = utcnow() + dt.timedelta(days=trust_days())  # sliding window


async def revoke_for_user(session: AsyncSession, user_id, store_id, *, key_hash: str | None = None) -> int:
    """Revoke one trusted device (by key) or, without a key, every device of that account in that store."""
    q = update(TrustedDevice).where(TrustedDevice.user_id == user_id, TrustedDevice.store_id == store_id, TrustedDevice.revoked_at.is_(None))
    if key_hash:
        q = q.where(TrustedDevice.key_hash == key_hash)
    res = await session.execute(q.values(revoked_at=utcnow()))
    return int(res.rowcount or 0)
