"""Admin team: invite a new admin, let them enrol, and manage the team (docs/24-Admin-Team-Design.md).

The flow in one paragraph. An owner invites an e-mail address with a role. Core creates an inactive *shell* user (role in
``admin_roles``, no password, no authenticator) and a one-time invite whose token is stored only as a SHA-256. The invitee opens the
link, scans their own authenticator QR code, chooses their own password and proves the authenticator with one code; only then is the
account activated. The owner never sees the password or the authenticator seed, and an unaccepted invite grants nothing.

This module holds every query of that flow so the routers stay free of SQL.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass

import segno
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit
from melorin.core.config import get_settings
from melorin.core.crypto import decrypt, encrypt
from melorin.core.db import utcnow
from melorin.core.email import email_available, send_email
from melorin.core.errors import AppError, NotFound
from melorin.core.security import hash_password, new_opaque_token, token_hash, totp_counter, totp_new_secret
from melorin.domain import admin_access, password_policy
from melorin.domain.timeutil import aware
from melorin.kernel.models.identity import AdminInvite, Identity, RefreshToken, User
from melorin.kernel.models.system import AuditEvent

log = logging.getLogger("melorin.admin_team")

INVITE_TTL = dt.timedelta(hours=72)
MAX_ENROLL_ATTEMPTS = 5

INVITE_INVALID = ("INVITE_INVALID", "لینک دعوت نامعتبر یا منقضی شده است. از مالک بخواهید دعوت تازه‌ای بفرستد.", 400)

ROLE_LABELS_FA: dict[str, str] = {
    admin_access.OWNER: "مالک",
    admin_access.MANAGER: "مدیر عملیات",
    admin_access.FINANCE: "مالی",
    admin_access.SUPPORT: "پشتیبانی",
    admin_access.VIEWER: "مشاهده‌گر",
}
ROLE_HINTS_FA: dict[str, str] = {
    admin_access.OWNER: "دسترسی کامل، از جمله مدیریت ادمین‌ها، تنظیمات و یکپارچه‌سازی‌ها.",
    admin_access.MANAGER: "همه‌ی بخش‌های عملیاتی (سفارش، پرداخت، محصول، زیرساخت، نمایندگان، مشتریان)؛ بدون مدیریت ادمین‌ها و تنظیمات سیستم.",
    admin_access.FINANCE: "سفارش‌ها و پرداخت‌ها (ویرایش)، گزارش‌ها و مشاهده‌ی کاتالوگ، نمایندگان و مشتریان.",
    admin_access.SUPPORT: "مشتریان و تیکت‌ها (ویرایش)، مشاهده‌ی سفارش‌ها، پرداخت‌ها و کاتالوگ.",
    admin_access.VIEWER: "فقط مشاهده‌ی بخش‌های عملیاتی؛ هیچ تغییری ممکن نیست.",
}


def _invalid() -> AppError:
    return AppError(*INVITE_INVALID)


def norm_email(email: str) -> str:
    return email.strip().lower()


def invite_path(token: str) -> str:
    """The fragment keeps the token out of server logs and the Referer header."""
    return f"/#/accept-invite?t={token}"


def invite_url(token: str) -> str | None:
    base = get_settings().admin_web_url
    return f"{base}{invite_path(token)}" if base else None


# ---------------- reading the team ----------------
@dataclass(frozen=True)
class AdminRow:
    user: User
    state: str  # active | invited | invite_expired | suspended
    invite_expires_at: dt.datetime | None
    last_login_at: dt.datetime | None


def state_of(user: User, live_invite: AdminInvite | None) -> str:
    if user.password_hash is None:  # setup (enrolment) not finished
        return "invited" if live_invite is not None else "invite_expired"
    return "active" if user.is_active else "suspended"


def _live(invite: AdminInvite, now: dt.datetime) -> bool:
    return invite.used_at is None and invite.revoked_at is None and aware(invite.expires_at) > now


async def _live_invites(session: AsyncSession, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, AdminInvite]:
    if not user_ids:
        return {}
    now = utcnow()
    rows = (
        await session.scalars(
            select(AdminInvite)
            .where(AdminInvite.user_id.in_(user_ids), AdminInvite.used_at.is_(None), AdminInvite.revoked_at.is_(None))
            .order_by(AdminInvite.created_at)
        )
    ).all()
    return {row.user_id: row for row in rows if _live(row, now)}


async def _last_logins(session: AsyncSession, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, dt.datetime]:
    if not user_ids:
        return {}
    rows = await session.execute(
        select(AuditEvent.actor_id, func.max(AuditEvent.created_at))
        .where(AuditEvent.action == "admin.login", AuditEvent.actor_id.in_(user_ids))
        .group_by(AuditEvent.actor_id)
    )
    return {actor: when for actor, when in rows.all() if actor is not None}


async def list_admins(session: AsyncSession) -> list[AdminRow]:
    users = (
        await session.scalars(
            select(User).where(User.is_super_admin.is_(True), User.archived_at.is_(None)).order_by(User.created_at, User.email)
        )
    ).all()
    ids = [u.id for u in users]
    invites, logins = await _live_invites(session, ids), await _last_logins(session, ids)
    return [
        AdminRow(u, state_of(u, invites.get(u.id)), invites[u.id].expires_at if u.id in invites else None, logins.get(u.id)) for u in users
    ]


async def get_admin(session: AsyncSession, admin_id: uuid.UUID, *, include_removed: bool = False) -> User:
    user = await session.get(User, admin_id)
    if user is None or not user.is_super_admin or (user.archived_at is not None and not include_removed):
        raise NotFound("ادمین")
    return user


async def row_for(session: AsyncSession, user: User) -> AdminRow:
    invites, logins = await _live_invites(session, [user.id]), await _last_logins(session, [user.id])
    invite = invites.get(user.id)
    return AdminRow(user, state_of(user, invite), invite.expires_at if invite else None, logins.get(user.id))


async def active_owner_ids(session: AsyncSession) -> set[uuid.UUID]:
    users = (
        await session.scalars(select(User).where(User.is_super_admin.is_(True), User.is_active.is_(True), User.archived_at.is_(None)))
    ).all()
    return {u.id for u in users if admin_access.is_owner(u.admin_roles) and u.password_hash is not None}


async def _ensure_not_last_owner(session: AsyncSession, target: User) -> None:
    """Defensive: even if a caller bypassed the self-protection rule, the team can never be left without an active owner."""
    if admin_access.is_owner(target.admin_roles) and not (await active_owner_ids(session)) - {target.id}:
        raise AppError("LAST_OWNER", "دست‌کم یک مالک فعال باید باقی بماند.", 409)


# ---------------- inviting ----------------
async def revoke_invites(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(AdminInvite)
        .where(AdminInvite.user_id == user_id, AdminInvite.used_at.is_(None), AdminInvite.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


async def revoke_sessions(session: AsyncSession, user_id: uuid.UUID) -> None:
    """End every refresh-token family of the user. (A short-lived access token dies by itself; ``is_active=False`` kills it at once.)"""
    await session.execute(
        update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)).values(revoked_at=utcnow())
    )


async def issue_invite(session: AsyncSession, user: User, *, created_by: uuid.UUID | None) -> tuple[str, dt.datetime]:
    """A fresh one-time invite for ``user``; earlier ones stop working. Returns the clear token (shown once) and its expiry."""
    await revoke_invites(session, user.id)
    token = new_opaque_token(32)
    expires = utcnow() + INVITE_TTL
    session.add(AdminInvite(user_id=user.id, token_hash=token_hash(token), created_by=created_by, expires_at=expires))
    return token, expires


def check_role(role: str) -> str:
    if role not in admin_access.ROLES:
        raise AppError("ROLE_INVALID", "نقش انتخاب‌شده معتبر نیست.", 422)
    return role


def _reset_credentials(user: User) -> None:
    user.password_hash = None
    user.totp_secret_enc = None
    user.totp_enabled = False
    user.totp_last_counter = None
    user.is_active = False  # nothing works until the new invite is accepted


async def create_admin(
    session: AsyncSession, *, email: str, display_name: str | None, role: str, actor: User
) -> tuple[User, str, dt.datetime]:
    """Create (or restore a removed) admin shell and its first invite. The caller commits. Never touches a customer account."""
    email = norm_email(email)
    check_role(role)
    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None and not (existing.is_super_admin and existing.archived_at is not None):
        if existing.is_super_admin:
            raise AppError("ADMIN_EXISTS", "این ایمیل از قبل ادمین است. برای ارسال دوباره‌ی دعوت از «بازنشانی دسترسی» استفاده کنید.", 409)
        raise AppError(
            "EMAIL_IN_USE_BY_CUSTOMER",
            "این ایمیل به یک حساب مشتری متصل است. حساب مشتری و ادمین جدا هستند؛ از ایمیل دیگری استفاده کنید.",
            409,
        )
    name = (display_name or "").strip() or email.split("@")[0]
    if existing is None:
        user = User(email=email, display_name=name, is_super_admin=True, is_active=False, admin_roles=[role], locale="fa")
        session.add(user)
        await session.flush()
        action = "admin.invited"
    else:  # a removed admin comes back through a brand-new invite and a brand-new password / authenticator
        user = existing
        user.display_name, user.admin_roles, user.archived_at = name, [role], None
        _reset_credentials(user)
        await revoke_sessions(session, user.id)
        action = "admin.re_invited"
    token, expires = await issue_invite(session, user, created_by=actor.id)
    audit.record(
        session, action, actor_id=actor.id, actor_type="admin", entity_type="user", entity_id=user.id, data={"role": role, "email": email}
    )
    return user, token, expires


async def reset_access(session: AsyncSession, target: User, *, actor: User) -> tuple[str, dt.datetime]:
    """Lost phone / suspected compromise: wipe password and authenticator, end every session, send a fresh invite."""
    _forbid_self(target, actor)
    await _ensure_not_last_owner(session, target)
    _reset_credentials(target)
    await revoke_sessions(session, target.id)
    token, expires = await issue_invite(session, target, created_by=actor.id)
    audit.record(session, "admin.access_reset", actor_id=actor.id, actor_type="admin", entity_type="user", entity_id=target.id)
    return token, expires


async def send_invite_email(user: User, token: str, expires: dt.datetime, *, role: str) -> bool:
    """Best effort: the owner always also gets the link on screen, so a mail failure never blocks the invite."""
    link = invite_url(token)
    if not link or not user.email or not await email_available():
        return False
    when = aware(expires).strftime("%Y-%m-%d %H:%M UTC")
    body = (
        f"سلام {user.display_name or ''}،\n\n"
        f"شما به‌عنوان «{ROLE_LABELS_FA[role]}» به پنل مدیریت ملورین دعوت شده‌اید.\n"
        f"برای ساخت رمز عبور و فعال‌سازی ورود دومرحله‌ای، این لینک یک‌بارمصرف را باز کنید:\n{link}\n\n"
        f"اعتبار لینک تا {when}. اگر این دعوت را انتظار نداشتید، آن را نادیده بگیرید."
    )
    try:
        await send_email(user.email, "دعوت به پنل مدیریت ملورین", body)
    except AppError as exc:
        log.warning("admin invite e-mail not sent: %s", exc.code)
        return False
    except OSError as exc:  # SMTP refused / unreachable
        log.warning("admin invite e-mail failed: %s", type(exc).__name__)
        return False
    return True


# ---------------- changing the team ----------------
def _forbid_self(target: User, actor: User) -> None:
    if target.id == actor.id:
        raise AppError("SELF_CHANGE_FORBIDDEN", "این کار روی حساب خودتان ممکن نیست؛ از مالک دیگری بخواهید.", 409)


async def update_admin(
    session: AsyncSession, target: User, *, actor: User, display_name: str | None, role: str | None, is_active: bool | None
) -> None:
    if display_name is not None and display_name.strip():
        target.display_name = display_name.strip()
    if role is not None and role != admin_access.role_of(target.admin_roles):
        _forbid_self(target, actor)
        check_role(role)
        if admin_access.is_owner(target.admin_roles):
            await _ensure_not_last_owner(session, target)
        before = admin_access.role_of(target.admin_roles)
        target.admin_roles = [role]
        audit.record(
            session,
            "admin.role_changed",
            actor_id=actor.id,
            actor_type="admin",
            entity_type="user",
            entity_id=target.id,
            data={"from": before, "to": role},
        )
    if is_active is not None and is_active != target.is_active:
        _forbid_self(target, actor)
        if is_active:
            if target.password_hash is None:
                raise AppError("ADMIN_NOT_SET_UP", "این ادمین هنوز دعوت را نپذیرفته است؛ ابتدا دعوت باید پذیرفته شود.", 409)
            target.is_active = True
            audit.record(session, "admin.reactivated", actor_id=actor.id, actor_type="admin", entity_type="user", entity_id=target.id)
        else:
            await _ensure_not_last_owner(session, target)
            target.is_active = False
            await revoke_sessions(session, target.id)
            audit.record(session, "admin.suspended", actor_id=actor.id, actor_type="admin", entity_type="user", entity_id=target.id)


async def remove_admin(session: AsyncSession, target: User, *, actor: User) -> None:
    """Take the person out of the team. The row stays (audit trail keeps pointing at it) but is inactive, role-less and hidden."""
    _forbid_self(target, actor)
    await _ensure_not_last_owner(session, target)
    target.is_active = False
    target.archived_at = utcnow()
    target.admin_roles = []
    await revoke_invites(session, target.id)
    await revoke_sessions(session, target.id)
    audit.record(session, "admin.removed", actor_id=actor.id, actor_type="admin", entity_type="user", entity_id=target.id)


# ---------------- accepting (public, no session) ----------------
async def _find_live_invite(session: AsyncSession, token: str) -> tuple[AdminInvite, User]:
    invite = await session.scalar(select(AdminInvite).where(AdminInvite.token_hash == token_hash(token or "")).with_for_update())
    if invite is None or not _live(invite, utcnow()):
        raise _invalid()
    user = await session.get(User, invite.user_id)
    if user is None or not user.is_super_admin or user.archived_at is not None:
        raise _invalid()
    return invite, user


@dataclass(frozen=True)
class InviteView:
    email: str
    display_name: str | None
    role: str
    expires_at: dt.datetime


async def inspect_invite(session: AsyncSession, token: str) -> InviteView:
    invite, user = await _find_live_invite(session, token)
    return InviteView(user.email or "", user.display_name, admin_access.role_of(user.admin_roles) or "", invite.expires_at)


@dataclass(frozen=True)
class Enrollment:
    secret: str
    otpauth_url: str
    qr_data_uri: str


def otpauth_url(email: str, secret: str) -> str:
    return f"otpauth://totp/Melorin:{email}?secret={secret}&issuer=Melorin"


async def start_enrollment(session: AsyncSession, token: str) -> Enrollment:
    """Give the invitee a fresh authenticator seed (kept encrypted, not yet active). Calling again replaces the previous seed."""
    _, user = await _find_live_invite(session, token)
    secret = totp_new_secret()
    user.totp_secret_enc, user.totp_enabled = encrypt(secret), False
    url = otpauth_url(user.email or str(user.id), secret)
    qr = segno.make(url, error="m").svg_data_uri(scale=6, border=2)
    return Enrollment(secret=secret, otpauth_url=url, qr_data_uri=qr)


async def accept_invite(session: AsyncSession, token: str, *, password: str, totp_code: str) -> User:
    """Finish the enrolment: password policy, authenticator proof, activation. Wrong codes are counted per invite."""
    invite, user = await _find_live_invite(session, token)
    if invite.attempts >= MAX_ENROLL_ATTEMPTS:
        invite.revoked_at = utcnow()
        await session.commit()
        raise AppError("INVITE_LOCKED", "تعداد تلاش‌های ناموفق زیاد بود و دعوت باطل شد. از مالک بخواهید دعوت تازه‌ای بفرستد.", 429)
    broken = password_policy.violation(password, user.email or "")
    if broken:
        raise AppError(broken, password_policy.MESSAGES_FA[broken], 422)
    if not user.totp_secret_enc:
        raise AppError("ENROLL_FIRST", "ابتدا کد QR را با برنامه‌ی احراز هویت اسکن کنید.", 409)
    counter = totp_counter(decrypt(user.totp_secret_enc) or "", totp_code or "")
    if counter is None:
        invite.attempts += 1
        audit.security_event(session, "admin_invite_totp_failed", user.id)
        await session.commit()
        raise AppError("TOTP_INVALID", "کد نادرست است. کد جدید برنامه را وارد کنید.", 400)
    user.password_hash = await hash_password(password)
    user.totp_enabled, user.totp_last_counter = True, counter
    user.is_active = True
    invite.used_at = utcnow()
    await revoke_invites(session, user.id)  # a second, older link must not outlive the accepted one
    ident = await session.scalar(select(Identity).where(Identity.provider == "email", Identity.subject == user.email))
    if ident is None:
        session.add(Identity(user_id=user.id, provider="email", subject=user.email or "", verified_at=utcnow()))
    elif ident.user_id == user.id and ident.verified_at is None:
        ident.verified_at = utcnow()
    audit.record(session, "admin.invite_accepted", actor_id=user.id, actor_type="admin", entity_type="user", entity_id=user.id)
    return user
