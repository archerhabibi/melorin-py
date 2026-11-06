"""Customer notices about one VPN account (PG-06). One place builds the text and, above all, the dedup key.

The dedup key carries the *period* (a token derived from ``expires_at``): a renewal starts a new period, so the next expiry /
low-traffic notice is a new event instead of being swallowed by the key of the previous period. Together with the flag reset in
:func:`reset_for_renewal` this fixes "after the first renewal the near-expiry warning is never sent again".
"""

import datetime as dt

from melorin.core import events

# Percent of the traffic package at which the customer is warned (each level at most once per package).
TRAFFIC_LOW_LEVELS = (80, 90)


def period_token(account) -> str:
    """Stable id of the account's current package period (changes on every renewal, ignores second-level clock drift)."""
    at = getattr(account, "expires_at", None)
    if at is None:
        return "open"
    at = at if at.tzinfo else at.replace(tzinfo=dt.UTC)
    return str(int(at.timestamp()) // 3600)


def traffic_percent(account) -> int | None:
    limit, used = int(account.traffic_limit_bytes or 0), int(account.traffic_used_bytes or 0)
    return None if limit <= 0 else int(used * 100 // limit)


def traffic_level(percent: int | None) -> int:
    """Highest warning level reached at ``percent`` (0 = below every level)."""
    return max((lv for lv in TRAFFIC_LOW_LEVELS if percent is not None and percent >= lv), default=0)


def reset_for_renewal(account) -> None:
    """A successful renewal starts a fresh package: every per-period notice flag starts over."""
    account.near_expiry_notified = False
    account.traffic_notified_level = 0


async def _emit(session, account, kind: str, title: str, body: str, key: str) -> None:
    await events.emit(
        session,
        events.NOTIFY,
        {"user_id": account.user_id, "store_id": account.store_id, "kind": kind, "title": title, "body": body, "dedup_key": key},
        dedup_key=key,
    )


async def expired(session, account) -> None:
    await _emit(session, account, "vpn_expired", "اکانت منقضی شد", "اکانت VPN شما منقضی شده است.", f"notify:expired:{account.id}:{period_token(account)}")


async def near_expiry(session, account) -> None:
    await _emit(
        session,
        account,
        "vpn_near_expiry",
        "انقضای اکانت نزدیک است",
        "اکانت VPN شما به‌زودی منقضی می‌شود.",
        f"notify:near-expiry:{account.id}:{period_token(account)}",
    )


async def traffic_low(session, account, level: int) -> None:
    await _emit(
        session,
        account,
        "vpn_traffic_low",
        "حجم اکانت رو به اتمام است",
        f"بیش از {level}٪ از حجم اکانت VPN شما مصرف شده است.",
        f"notify:traffic-low:{account.id}:{period_token(account)}:{level}",
    )


async def traffic_exhausted(session, account) -> None:
    await _emit(
        session,
        account,
        "vpn_traffic_exhausted",
        "حجم اکانت تمام شد",
        "حجم اکانت VPN شما تمام شده است؛ برای ادامه، اکانت را تمدید کنید.",
        f"notify:traffic-exhausted:{account.id}:{period_token(account)}",
    )


async def disabled_by_panel(session, account) -> None:
    await _emit(
        session,
        account,
        "vpn_disabled",
        "اکانت غیرفعال شد",
        "اکانت VPN شما غیرفعال شده است؛ در صورت نیاز با پشتیبانی تماس بگیرید.",
        f"notify:disabled:{account.id}:{period_token(account)}",
    )
