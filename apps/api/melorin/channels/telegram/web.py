"""Website login approved inside the Telegram bot.

Design (docs/TELEGRAM-WEB-LOGIN.md): an OAuth device-authorization style flow with browser binding.

* The browser creates a session and receives two values: a *public id* (goes into the ``t.me`` deep link / QR code)
  and a *poll token* (secret, never leaves the browser; only its SHA-256 is stored).
* The bot shows the requester's device/IP and asks the user to pick the *number matching code* that is displayed on
  the website (phishing resistance: a link relayed to a victim is useless without the code on the attacker's screen).
* Tokens are issued only to the holder of the poll token, exactly once, atomically (row lock + status transition).

* Automatic verification (docs/21-Automatic-Identity-Verification.md): a browser approved once becomes a *trusted
  device* (``trust.py``). Its next login skips the number match (``auto``: opening the bot link is the approval) or the
  bot altogether (``silent``: same network, seen recently). An unknown browser always gets the manual number match.

Everything here is transport independent; routers/bot runners only call these functions.
"""

import datetime as dt
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.channels.telegram import trust
from melorin.core import audit, events, flags, integrations
from melorin.core.config import get_settings
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.core.ratelimit import hit
from melorin.core.security import new_opaque_token, token_hash
from melorin.modules.identity import service
from melorin.kernel.models.identity import RefreshToken, TelegramLoginSession, TrustedDevice, User
from melorin.modules.identity.schemas import TelegramProfile, TokenPair
from melorin.kernel.models.stores import Store

POLL_INTERVAL_SECONDS = 2
MAX_WRONG_CHOICES = 2
APPROVALS_PER_HOUR = 10
OPEN_STATES = ("pending", "scanned")
_DUMMY_HASH = token_hash("telegram-web-login-dummy")


def ttl_seconds(cfg: dict | None = None) -> int:
    """Request lifetime. ``cfg`` is the panel config (Admin > Settings > Telegram); without it the env default applies."""
    if cfg is not None:
        return integrations.telegram_ttl(cfg)
    return max(60, min(600, int(get_settings().telegram_web_login_ttl_seconds)))


def _aware(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=value.tzinfo or dt.UTC)


def seconds_left(row: TelegramLoginSession) -> int:
    return max(0, int((_aware(row.expires_at) - utcnow()).total_seconds()))


# ---------------- display helpers ----------------
_BROWSERS = (
    ("Edg/", "Edge"),
    ("OPR/", "Opera"),
    ("Firefox/", "Firefox"),
    ("SamsungBrowser/", "Samsung Internet"),
    ("Chrome/", "Chrome"),
    ("CriOS/", "Chrome"),
    ("Safari/", "Safari"),
)
_SYSTEMS = (
    ("Windows", "Windows"),
    ("Android", "Android"),
    ("iPhone", "iOS"),
    ("iPad", "iOS"),
    ("Mac OS X", "macOS"),
    ("CrOS", "ChromeOS"),
    ("Linux", "Linux"),
)


def device_label(user_agent: str | None) -> str:
    """Coarse "Browser · OS" text for the confirmation screen. Display only; never used for decisions."""
    ua = user_agent or ""
    browser = next((name for needle, name in _BROWSERS if needle in ua), None)
    system = next((name for needle, name in _SYSTEMS if needle in ua), None)
    parts = [p for p in (browser, system) if p]
    return " · ".join(parts) if parts else "دستگاه ناشناس"


def _codes() -> tuple[str, list[str]]:
    """One correct two-digit code and two decoys, all distinct."""
    picked = secrets.SystemRandom().sample(range(10, 100), 3)
    return str(picked[0]), [str(x) for x in picked[1:]]


def choices_of(row: TelegramLoginSession) -> list[str]:
    """Shuffled on every call, so the position of the right answer leaks nothing."""
    out = [row.match_code, *list(row.decoys or [])]
    secrets.SystemRandom().shuffle(out)
    return out


def number_match_enabled(cfg: dict | None = None) -> bool:
    if cfg is not None:
        return bool(cfg.get("number_match"))
    return bool(get_settings().telegram_web_login_number_match)


def normalise_bot_username(value: str | None) -> str | None:
    name = (value or "").strip().lstrip("@")
    return name if re.fullmatch(r"[A-Za-z0-9_]{3,64}", name) else None


# ---------------- lifecycle ----------------
@dataclass
class Started:
    row: TelegramLoginSession
    poll_token: str
    bot_username: str
    level: str = "manual"  # silent | auto | manual


async def create_session(
    session: AsyncSession,
    store: Store,
    *,
    ip: str | None,
    user_agent: str | None,
    device_key: str | None = None,
    remember: bool = True,
) -> Started:
    bot = normalise_bot_username(store.bot_username)
    cfg = await integrations.get_telegram(session)
    if store.status != "active" or not bot or not integrations.telegram_bot_ready(cfg):
        raise AppError("TELEGRAM_LOGIN_UNAVAILABLE", "ورود با تلگرام برای این فروشگاه فعال نیست.", 503)
    await flags.ensure_enabled(session, "bot", store_id=store.id, channel="telegram")
    code, decoys = _codes()
    poll_token = new_opaque_token(32)
    key_hash = trust.key_hash_of(device_key)
    device = await trust.find_valid(session, key_hash, store.id)
    level = trust.level_for(device, ip, device_label(user_agent))
    row = TelegramLoginSession(
        public_id=secrets.token_urlsafe(12),
        secret_hash=token_hash(poll_token),
        store_id=store.id,
        match_code=code,
        decoys=decoys,
        req_ip=(ip or "")[:64] or None,
        req_ua=(user_agent or "")[:300] or None,
        req_device=device_label(user_agent),
        expires_at=utcnow() + dt.timedelta(seconds=ttl_seconds(cfg)),
        device_key_hash=key_hash,
        remember=bool(remember),
    )
    session.add(row)
    if device is not None and level == "silent":
        if not await _silent_signin(session, row, device, ip):
            level = "manual"  # account no longer eligible: nothing silent, the manual flow decides (and explains)
    row.auto_level = level if level != "manual" else None
    audit.record(
        session,
        "tg_web_login.started",
        actor_type="system",
        entity_type="telegram_login_session",
        entity_id=row.id,
        store_id=store.id,
        data={"device": row.req_device, "level": level},
    )
    await session.commit()
    return Started(row=row, poll_token=poll_token, bot_username=bot, level=level)


async def _silent_signin(session: AsyncSession, row: TelegramLoginSession, device, ip: str | None) -> bool:
    """Trusted browser, same network, seen recently: the session is approved on creation, with no bot step.

    The owner is told in Telegram (once per device and day) and can revoke with /devices. Returns False (and nothing is
    approved) when the account is gone, disabled or an admin; a device of such an account is revoked on the spot.
    """
    user = await session.get(User, device.user_id)
    if user is None or not user.is_active or user.is_super_admin:
        device.revoked_at = utcnow()
        return False
    trust.touch(device, ip)
    row.user_id, row.scanned_telegram_id = user.id, device.telegram_id
    row.status, row.decided_at = "approved", utcnow()
    await _notify_owner(session, row, device, "silent")
    return True


async def _notify_owner(session: AsyncSession, row: TelegramLoginSession, device, level: str) -> None:
    """Tell the account owner about a login that needed no tap. Deduplicated per device per day so it never spams."""
    how = "بدون نیاز به تأیید (مرورگر و شبکهٔ آشنا)" if level == "silent" else "با باز کردن لینک ربات (مرورگر آشنا)"
    await events.emit(
        session,
        events.NOTIFY,
        {
            "user_id": device.user_id,
            "store_id": device.store_id,
            "kind": f"web_login_{level}",
            "title": "🔐 ورود به وب‌سایت با مرورگر مطمئن",
            "body": (
                f"🖥 {row.req_device or 'دستگاه ناشناس'}\n🌐 {row.req_ip or '-'}\n{how}\n\n"
                "اگر این ورود از طرف شما نبود، دستور /devices را بفرستید و «این من نبودم» را بزنید."
            ),
            "dedup_key": f"tg_web_{level}:{device.id}:{utcnow():%Y%m%d}",
        },
    )


async def _locked(session: AsyncSession, public_id: str) -> TelegramLoginSession | None:
    return await session.scalar(select(TelegramLoginSession).where(TelegramLoginSession.public_id == public_id).with_for_update())


def _refresh_expiry(row: TelegramLoginSession) -> bool:
    """Lazily flips an overdue open session to ``expired``; True when the row changed."""
    if row.status in OPEN_STATES and _aware(row.expires_at) <= utcnow():
        row.status = "expired"
        return True
    return False


async def _open_for_bot(session: AsyncSession, public_id: str, store_id: uuid.UUID, telegram_id: int) -> TelegramLoginSession:
    row = await _locked(session, public_id)
    if row is None:
        raise AppError("SESSION_NOT_FOUND", "این درخواست ورود پیدا نشد. از وب‌سایت دوباره شروع کنید.", 404)
    if row.store_id != store_id:
        raise AppError("STORE_MISMATCH", "این درخواست ورود برای ربات دیگری ساخته شده است.", 409)
    if _refresh_expiry(row):
        await session.commit()
    if row.status not in OPEN_STATES:
        raise AppError("SESSION_CLOSED", "این درخواست ورود دیگر معتبر نیست. از وب‌سایت دوباره شروع کنید.", 410)
    if row.scanned_telegram_id not in (None, telegram_id):
        audit.security_event(session, "tg_web_login_other_account", None, {"session": row.public_id})
        await session.commit()
        raise AppError("SESSION_BUSY", "این درخواست قبلاً در حساب تلگرام دیگری باز شده است.", 409)
    return row


async def inspect(
    session: AsyncSession, public_id: str, store_id: uuid.UUID, telegram_id: int, *, profile: TelegramProfile | None = None
) -> TelegramLoginSession:
    """The user opened the deep link in the bot: bind the session to this Telegram account and show the context.

    For an ``auto`` request (trusted browser) this is also the approval: when the device key behind the session is a live
    trusted device *of this very Telegram account*, the session is approved right here. Anything else (key unknown,
    expired, revoked or belonging to another account) falls back to the manual number match; nothing is ever refused
    just because trust is missing. ``row.auto_level`` tells the caller which way it went.
    """
    row = await _open_for_bot(session, public_id, store_id, telegram_id)
    row.scanned_telegram_id = telegram_id
    row.status = "scanned"
    if row.auto_level == "auto" and profile is not None:
        device = await trust.find_valid(session, row.device_key_hash, row.store_id, telegram_id=telegram_id)
        if device is None:
            row.auto_level = None  # fallback to the number match; the browser learns it from the next poll
            audit.security_event(session, "tg_web_login_auto_fallback", None, {"session": row.public_id, "ip": row.req_ip})
        else:
            cfg = await integrations.get_telegram(session)
            if not integrations.telegram_bot_ready(cfg):
                await _close(session, row, "login_disabled")
                return row
            if not await hit(f"tgweb-approve:{telegram_id}", APPROVALS_PER_HOUR, 3600):
                await _close(session, row, "rate_limited", security="tg_web_login_rate_limited")
                return row
            await _complete(session, row, profile, device=device, via="auto")
            return row
    await session.commit()
    return row


async def _close(session: AsyncSession, row: TelegramLoginSession, reason: str, *, security: str | None = None) -> dict:
    row.status, row.deny_reason, row.decided_at = "denied", reason, utcnow()
    if security:
        audit.security_event(
            session, security, row.user_id, {"session": row.public_id, "ip": row.req_ip, "device": row.req_device, "reason": reason}
        )
    audit.record(
        session,
        "tg_web_login.denied",
        actor_type="system",
        entity_type="telegram_login_session",
        entity_id=row.id,
        store_id=row.store_id,
        data={"reason": reason},
    )
    await session.commit()
    return {"result": "denied", "reason": reason}


async def decide(
    session: AsyncSession, public_id: str, store_id: uuid.UUID, profile: TelegramProfile, action: str, choice: str | None
) -> dict:
    """The Telegram user tapped a button. Business outcomes are returned (never raised) so the bot can render them."""
    row = await _open_for_bot(session, public_id, store_id, profile.telegram_id)
    row.scanned_telegram_id = profile.telegram_id
    cfg = await integrations.get_telegram(session)
    if action != "deny" and not integrations.telegram_bot_ready(cfg):
        # The admin switched Telegram login off while this request was open.
        return await _close(session, row, "login_disabled")
    if action == "deny":
        # "That was not me" is the most valuable phishing signal we get: record it as a security event.
        return await _close(session, row, "user_denied", security="tg_web_login_denied_by_user")
    if not await hit(f"tgweb-approve:{profile.telegram_id}", APPROVALS_PER_HOUR, 3600):
        return await _close(session, row, "rate_limited", security="tg_web_login_rate_limited")
    if number_match_enabled(cfg) and not hmac.compare_digest(str(choice or ""), row.match_code):
        row.attempts += 1
        remaining = MAX_WRONG_CHOICES - row.attempts
        if remaining <= 0:
            return await _close(session, row, "too_many_wrong_choices", security="tg_web_login_wrong_code")
        await session.commit()
        return {"result": "retry", "remaining": remaining, "choices": choices_of(row)}
    return await _complete(session, row, profile, device=None, via="manual")


async def _complete(session: AsyncSession, row: TelegramLoginSession, profile: TelegramProfile, *, device, via: str) -> dict:
    """The single place where a login attempt is approved. Manual (number match) and automatic (trusted device)
    verification both end here, so every account rule applies to both with no exception."""
    known = await service.find_identity(session, "telegram", str(profile.telegram_id))
    if known is None and not await flags.is_enabled(session, "registration"):
        return await _close(session, row, "registration_closed")
    user, _created = await service.login_with_telegram(session, profile)
    if not user.is_active:
        return await _close(session, row, "account_disabled", security="tg_web_login_inactive_account")
    if user.is_super_admin:
        # Same rule as the storefront Google flow: admins authenticate on the admin panel (password + TOTP) only.
        row.user_id = user.id
        return await _close(session, row, "admin_use_panel", security="tg_web_login_admin_refused")
    row.user_id, row.status, row.decided_at = user.id, "approved", utcnow()
    if device is not None:
        if device.user_id != user.id:  # the key was approved for another account: never mix them up
            row.status, row.user_id = "denied", None
            return await _close(session, row, "device_account_mismatch", security="tg_web_login_device_mismatch")
        trust.touch(device, row.req_ip, row.req_device)
        await _notify_owner(session, row, device, "auto")
    elif row.remember:
        # A manual approval is what earns trust: remember this browser for the next time.
        await trust.remember(
            session,
            key_hash=row.device_key_hash,
            user_id=user.id,
            store_id=row.store_id,
            telegram_id=profile.telegram_id,
            label=row.req_device,
            ip=row.req_ip,
        )
    audit.record(
        session,
        "tg_web_login.approved",
        actor_id=user.id,
        entity_type="telegram_login_session",
        entity_id=row.id,
        store_id=row.store_id,
        data={"device": row.req_device, "via": via},
    )
    await session.commit()
    return {"result": "approved"}


@dataclass
class PollResult:
    status: str
    reason: str | None = None
    expires_in: int = 0
    tokens: TokenPair | None = None
    level: str | None = None
    match_code: str | None = None


async def poll(session: AsyncSession, public_id: str, poll_token: str, request, *, user_agent: str | None = None) -> PollResult:
    """Called by the browser. Issues the Core session exactly once to the holder of the poll token."""
    row = await _locked(session, public_id)
    expected = row.secret_hash if row is not None else _DUMMY_HASH
    if not hmac.compare_digest(token_hash(poll_token), expected) or row is None:
        raise AppError("SESSION_NOT_FOUND", "درخواست ورود پیدا نشد.", 404)
    if _refresh_expiry(row):
        await session.commit()
    if row.status != "approved":
        out = PollResult(row.status, row.deny_reason, seconds_left(row) if row.status in OPEN_STATES else 0)
        if row.status in OPEN_STATES and row.auto_level is None and row.device_key_hash:
            # An ``auto`` attempt fell back to manual: hand the browser (and only it) the number to show.
            out.level = "manual"
            out.match_code = row.match_code if number_match_enabled(await integrations.get_telegram(session)) else None
        return out
    user = await session.get(User, row.user_id)
    if user is None or not user.is_active or user.is_super_admin:
        row.status, row.deny_reason = "denied", "account_disabled" if user is None or not user.is_active else "admin_use_panel"
        await session.commit()
        return PollResult("denied", row.deny_reason)
    from melorin.core import channel as ch

    site = await ch.site_channel(session, request, hint=row.store_id)  # the approval is redeemed on the SAME store's site
    if site.store_id != row.store_id:
        raise ch.mismatch()
    pair = await service.issue_tokens(session, user, site, ua=(user_agent or row.req_ua or "web")[:300])
    row.status, row.consumed_at = "consumed", utcnow()
    audit.record(
        session, "tg_web_login.consumed", actor_id=user.id, entity_type="telegram_login_session", entity_id=row.id, store_id=row.store_id
    )
    await session.commit()
    return PollResult("approved", tokens=pair)


async def cancel(session: AsyncSession, public_id: str, poll_token: str) -> None:
    """The visitor closed the dialog: the link in Telegram stops working immediately."""
    row = await _locked(session, public_id)
    if row is None or not hmac.compare_digest(token_hash(poll_token), row.secret_hash):
        raise AppError("SESSION_NOT_FOUND", "درخواست ورود پیدا نشد.", 404)
    if row.status in OPEN_STATES:
        row.status, row.deny_reason, row.decided_at = "denied", "cancelled", utcnow()
        await session.commit()


async def forget_device(session: AsyncSession, device_key: str) -> int:
    """Browser side "forget this device" (logout everywhere on this browser): holding the key is the proof."""
    key_hash = trust.key_hash_of(device_key)
    if key_hash is None:
        return 0
    res = await session.execute(
        update(TrustedDevice).where(TrustedDevice.key_hash == key_hash, TrustedDevice.revoked_at.is_(None)).values(revoked_at=utcnow())
    )
    await session.commit()
    return int(res.rowcount or 0)


async def list_devices(session: AsyncSession, store_id: uuid.UUID, telegram_id: int) -> list[dict]:
    """Live trusted devices of one Telegram account in one store, newest first (shown by the bot's /devices)."""
    now = utcnow()
    rows = (
        await session.scalars(
            select(TrustedDevice)
            .where(
                TrustedDevice.store_id == store_id,
                TrustedDevice.telegram_id == telegram_id,
                TrustedDevice.revoked_at.is_(None),
                TrustedDevice.expires_at > now,
            )
            .order_by(TrustedDevice.last_seen_at.desc())
        )
    ).all()
    return [
        {
            "id": d.id.hex,
            "label": d.label,
            "last_ip": d.last_ip,
            "uses": d.uses or 0,
            "last_seen_ago_seconds": max(0, int((now - _aware(d.last_seen_at)).total_seconds())),
            "expires_in_seconds": max(0, int((_aware(d.expires_at) - now).total_seconds())),
        }
        for d in rows
    ]


async def revoke_devices(session: AsyncSession, store_id: uuid.UUID, telegram_id: int, device_id: str | None) -> int:
    """ "This was not me": revoke one device (or all) of this Telegram account. Revoking *all* also ends the web sessions
    of that account in this store, so a stolen browser is out immediately, not at the next token refresh."""
    q = update(TrustedDevice).where(
        TrustedDevice.store_id == store_id, TrustedDevice.telegram_id == telegram_id, TrustedDevice.revoked_at.is_(None)
    )
    owner_ids = set()
    if device_id:
        try:
            q = q.where(TrustedDevice.id == uuid.UUID(device_id))
        except ValueError:
            return 0
    else:
        owner_ids = set(
            (
                await session.scalars(
                    select(TrustedDevice.user_id).where(TrustedDevice.store_id == store_id, TrustedDevice.telegram_id == telegram_id)
                )
            ).all()
        )
    count = int((await session.execute(q.values(revoked_at=utcnow()))).rowcount or 0)
    if owner_ids:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id.in_(owner_ids), RefreshToken.store_id == store_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
    audit.security_event(session, "tg_web_login_devices_revoked", None, {"store": str(store_id), "all": device_id is None, "count": count})
    await session.commit()
    return count


async def purge_old(session: AsyncSession, older_than: dt.timedelta = dt.timedelta(days=1)) -> int:
    """Housekeeping: finished login sessions one day after expiry; trusted devices a month after they expired or were
    revoked (kept that long so an investigation still sees which browser was removed and when)."""
    cutoff = utcnow() - older_than
    result = await session.execute(TelegramLoginSession.__table__.delete().where(TelegramLoginSession.expires_at < cutoff))
    stale = utcnow() - dt.timedelta(days=30)
    devices = await session.execute(
        TrustedDevice.__table__.delete().where(
            (TrustedDevice.expires_at < stale) | (TrustedDevice.revoked_at.is_not(None) & (TrustedDevice.revoked_at < stale))
        )
    )
    await session.commit()
    return int((result.rowcount or 0) + (devices.rowcount or 0))
