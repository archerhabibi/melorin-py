"""Customer notices about one VPN account (PG-06). One place builds the text and, above all, the dedup key.

The dedup key carries the *period* (a token derived from ``expires_at``): a renewal starts a new period, so the next expiry /
low-traffic notice is a new event instead of being swallowed by the key of the previous period. Together with the flag reset in
:func:`reset_for_renewal` this fixes "after the first renewal the near-expiry warning is never sent again".
"""

import datetime as dt

from melorin.core import events

# Percent of the traffic package at which the customer is warned (each level at most once per package). A store may replace
# these with its own list (``stores.vpn_notice_settings["traffic_low_levels"]``); see :func:`levels_for_store`.
TRAFFIC_LOW_LEVELS = (80, 90)
MAX_LEVELS = 4  # more warnings than this is spam, not service


def period_token(account) -> str:
    """Stable id of the account's current package period (changes on every renewal, ignores second-level clock drift)."""
    at = getattr(account, "sold_expires_at", None)  # the SOLD period: it changes on every renewal (R9)
    if at is None:
        return "open"
    at = at if at.tzinfo else at.replace(tzinfo=dt.UTC)
    return str(int(at.timestamp()) // 3600)


def percent_of(limit, used) -> int | None:
    """Whole percent of a package used, from two numbers the caller just read from the panel (R4: never from a stored copy)."""
    limit, used = int(limit or 0), int(used or 0)
    return None if limit <= 0 else int(used * 100 // limit)


def normalize_levels(raw) -> tuple[int, ...]:
    """Validate a store's warning levels: 1-99 whole percents, no duplicates, ascending, at most ``MAX_LEVELS``.

    An empty list is a valid choice ("this store sends no low-traffic warnings"). Anything that is not a list of whole numbers
    raises ``ValueError`` so the admin API can refuse it instead of silently storing garbage.
    """
    if not isinstance(raw, (list, tuple)):
        raise ValueError("traffic_low_levels must be a list of percents")
    out: set[int] = set()
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, int) or not 1 <= item <= 99:
            raise ValueError("every level must be a whole percent between 1 and 99")
        out.add(item)
    if len(out) > MAX_LEVELS:
        raise ValueError(f"at most {MAX_LEVELS} levels")
    return tuple(sorted(out))


def levels_for_store(settings: dict | None) -> tuple[int, ...]:
    """The store's levels, or the platform default when it has none (or a stored value is no longer valid)."""
    if not settings or "traffic_low_levels" not in settings:
        return TRAFFIC_LOW_LEVELS
    try:
        return normalize_levels(settings["traffic_low_levels"])
    except ValueError:
        return TRAFFIC_LOW_LEVELS


def traffic_level(percent: int | None, levels: tuple[int, ...] = TRAFFIC_LOW_LEVELS) -> int:
    """Highest warning level reached at ``percent`` (0 = below every level)."""
    return max((lv for lv in levels if percent is not None and percent >= lv), default=0)


# --------------------------------------------------------------------------------------------- per-store texts (PG-06)
TEXT_KINDS = ("vpn_expired", "vpn_near_expiry", "vpn_traffic_low", "vpn_traffic_exhausted", "vpn_disabled", "vpn_queued_plan_started")
TEXT_TOKENS = ("{store}", "{level}")  # the only placeholders; anything else stays literal text (no format() on admin input)
MAX_TITLE, MAX_BODY = 80, 500


def normalize_texts(raw) -> dict[str, dict[str, str]]:
    """Validate a store's own customer-notice wording: ``{kind: {"title": ..., "body": ...}}``.

    Unknown kinds, empty or over-long text are refused (``ValueError``) so the admin API can answer 422 instead of storing junk.
    """
    if not isinstance(raw, dict):
        raise ValueError("texts must be an object keyed by notice kind")
    out: dict[str, dict[str, str]] = {}
    for kind, item in raw.items():
        if kind not in TEXT_KINDS:
            raise ValueError(f"unknown notice kind: {kind}")
        if not isinstance(item, dict):
            raise ValueError(f"{kind}: expected {{title, body}}")
        title, body = str(item.get("title") or "").strip(), str(item.get("body") or "").strip()
        if not title or not body:
            raise ValueError(f"{kind}: title and body are both required")
        if len(title) > MAX_TITLE or len(body) > MAX_BODY:
            raise ValueError(f"{kind}: title max {MAX_TITLE}, body max {MAX_BODY} characters")
        out[kind] = {"title": title, "body": body}
    return out


def texts_for_store(settings: dict | None) -> dict[str, dict[str, str]]:
    """The store's valid custom texts (an invalid stored value is ignored, never raised at send time)."""
    if not settings or not settings.get("texts"):
        return {}
    try:
        return normalize_texts(settings["texts"])
    except ValueError:
        return {}


def apply_texts(
    settings: dict | None, kind: str, title: str, body: str, *, store_name: str = "", level: int | None = None
) -> tuple[str, str]:
    """The store's wording for ``kind`` (with ``{store}`` / ``{level}`` filled in), or the platform text when it has none."""
    custom = texts_for_store(settings).get(kind)
    if not custom:
        return title, body
    fill = {"{store}": store_name or "", "{level}": "" if level is None else str(level)}

    def _f(text: str) -> str:
        for token, value in fill.items():
            text = text.replace(token, value)
        return text

    return _f(custom["title"]), _f(custom["body"])


def reset_for_renewal(account) -> None:
    """A successful renewal starts a fresh package: every per-period notice flag starts over."""
    account.near_expiry_notified = False
    account.traffic_notified_level = 0


async def _emit(session, account, kind: str, title: str, body: str, key: str, *, level: int | None = None) -> None:
    if account.store_id:  # PG-06: a store may word its own customer notices
        from melorin.kernel.models.stores import Store

        store = await session.get(Store, account.store_id)
        if store is not None and store.vpn_notice_settings:
            title, body = apply_texts(store.vpn_notice_settings, kind, title, body, store_name=store.name or "", level=level)
    await events.emit(
        session,
        events.NOTIFY,
        {"user_id": account.user_id, "store_id": account.store_id, "kind": kind, "title": title, "body": body, "dedup_key": key},
        dedup_key=key,
    )


async def expired(session, account) -> None:
    await _emit(
        session,
        account,
        "vpn_expired",
        "اکانت منقضی شد",
        "اکانت VPN شما منقضی شده است.",
        f"notify:expired:{account.id}:{period_token(account)}",
    )


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
        level=level,
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


async def queued_plan_started(session, account) -> None:
    """PG-09: the prepaid package the customer bought started (the panel switched to it). One notice per new period."""
    await _emit(
        session,
        account,
        "vpn_queued_plan_started",
        "پکیج بعدی شما شروع شد",
        "پکیج تمدیدشدهٔ اکانت VPN شما فعال شد.",
        f"notify:queued-started:{account.id}:{period_token(account)}",
    )
