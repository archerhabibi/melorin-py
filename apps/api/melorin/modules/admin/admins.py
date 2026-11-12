"""Admin API - the admin team: who may use the admin panel and with which role (docs/24-Admin-Team-Design.md).

Everything under ``/admin/admins`` belongs to the ``admins`` area, i.e. to the owner role only (``domain/admin_access.py``). ``/admin/me``
is the one call every admin may make: it tells the admin web which screens to show.
"""

import datetime as dt
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field

from melorin.core import audit
from melorin.core.deps import AdminUser, Session
from melorin.core.ratelimit import RateLimit
from melorin.domain import admin_access
from melorin.modules.identity import admin_team
from melorin.modules.identity.admin_team import ROLE_HINTS_FA, ROLE_LABELS_FA, AdminRow

router = APIRouter(prefix="/admin", tags=["admin-team"])


class AdminOut(BaseModel):
    id: uuid.UUID
    email: str | None
    display_name: str | None
    role: str | None
    role_label: str | None
    state: str  # active | invited | invite_expired | suspended
    is_active: bool
    totp_enabled: bool
    is_self: bool
    created_at: dt.datetime
    last_login_at: dt.datetime | None
    invite_expires_at: dt.datetime | None


class RoleOut(BaseModel):
    key: str
    label: str
    description: str
    permissions: list[str]  # "orders:rw", "reports:r", ...


class AdminMeOut(BaseModel):
    id: uuid.UUID
    email: str | None
    display_name: str | None
    role: str | None
    role_label: str | None
    is_owner: bool
    permissions: list[str]


class InviteIn(BaseModel):
    email: EmailStr
    display_name: str | None = Field(default=None, max_length=200)
    role: str = Field(max_length=20)


class InviteOut(BaseModel):
    admin: AdminOut
    # The link is shown once, here. Core stores only its hash and cannot show it again (issue a new invite instead).
    invite_path: str
    invite_url: str | None
    expires_at: dt.datetime
    emailed: bool


class AdminPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=20)
    is_active: bool | None = None


def _out(row: AdminRow, viewer_id: uuid.UUID) -> AdminOut:
    user = row.user
    role = admin_access.role_of(user.admin_roles)
    return AdminOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=role,
        role_label=ROLE_LABELS_FA.get(role) if role else None,
        state=row.state,
        is_active=user.is_active,
        totp_enabled=user.totp_enabled,
        is_self=user.id == viewer_id,
        created_at=user.created_at,
        last_login_at=row.last_login_at,
        invite_expires_at=row.invite_expires_at,
    )


@router.get("/me", response_model=AdminMeOut)
async def admin_me(admin: AdminUser):
    role = admin_access.role_of(admin.admin_roles)
    return AdminMeOut(
        id=admin.id,
        email=admin.email,
        display_name=admin.display_name,
        role=role,
        role_label=ROLE_LABELS_FA.get(role) if role else None,
        is_owner=admin_access.is_owner(admin.admin_roles),
        permissions=admin_access.permissions(admin.admin_roles),
    )


@router.get("/admins/roles", response_model=list[RoleOut])
async def admin_roles(_: AdminUser):
    return [
        RoleOut(key=role, label=ROLE_LABELS_FA[role], description=ROLE_HINTS_FA[role], permissions=admin_access.permissions([role]))
        for role in admin_access.ROLES
    ]


@router.get("/admins", response_model=list[AdminOut])
async def list_admins(admin: AdminUser, session: Session):
    return [_out(row, admin.id) for row in await admin_team.list_admins(session)]


@router.post("/admins", response_model=InviteOut, status_code=201, dependencies=[Depends(RateLimit("admin-team-invite", 30, 3600))])
async def invite_admin(body: InviteIn, admin: AdminUser, session: Session):
    """Invite an e-mail address as admin. Creates an inactive shell; nothing works until the invitee accepts."""
    user, token, expires = await admin_team.create_admin(
        session, email=body.email, display_name=body.display_name, role=body.role, actor=admin
    )
    await session.commit()
    emailed = await admin_team.send_invite_email(user, token, expires, role=body.role)
    row = await admin_team.row_for(session, user)
    return InviteOut(
        admin=_out(row, admin.id),
        invite_path=admin_team.invite_path(token),
        invite_url=admin_team.invite_url(token),
        expires_at=expires,
        emailed=emailed,
    )


@router.patch("/admins/{admin_id}", response_model=AdminOut)
async def patch_admin(admin_id: uuid.UUID, body: AdminPatch, admin: AdminUser, session: Session):
    target = await admin_team.get_admin(session, admin_id)
    await admin_team.update_admin(session, target, actor=admin, display_name=body.display_name, role=body.role, is_active=body.is_active)
    await session.commit()
    return _out(await admin_team.row_for(session, target), admin.id)


@router.post("/admins/{admin_id}/reset-access", response_model=InviteOut)
async def reset_admin_access(admin_id: uuid.UUID, admin: AdminUser, session: Session):
    """Lost phone or suspected compromise (also: send an expired invite again): wipes the password and authenticator, ends every
    session and issues a fresh invite."""
    target = await admin_team.get_admin(session, admin_id)
    token, expires = await admin_team.reset_access(session, target, actor=admin)
    await session.commit()
    role = admin_access.role_of(target.admin_roles) or admin_access.VIEWER
    emailed = await admin_team.send_invite_email(target, token, expires, role=role)
    row = await admin_team.row_for(session, target)
    return InviteOut(
        admin=_out(row, admin.id),
        invite_path=admin_team.invite_path(token),
        invite_url=admin_team.invite_url(token),
        expires_at=expires,
        emailed=emailed,
    )


@router.post("/admins/{admin_id}/revoke-sessions")
async def revoke_admin_sessions(admin_id: uuid.UUID, admin: AdminUser, session: Session):
    """Sign the admin out everywhere (their refresh tokens end; an access token lives at most a few minutes)."""
    target = await admin_team.get_admin(session, admin_id)
    await admin_team.revoke_sessions(session, target.id)
    audit.record(session, "admin.sessions_revoked", actor_id=admin.id, actor_type="admin", entity_type="user", entity_id=target.id)
    await session.commit()
    return {"ok": True}


@router.delete("/admins/{admin_id}", status_code=204)
async def remove_admin(admin_id: uuid.UUID, admin: AdminUser, session: Session):
    """Take the person out of the team (the account is kept, inactive and hidden, so the audit trail still resolves)."""
    target = await admin_team.get_admin(session, admin_id)
    await admin_team.remove_admin(session, target, actor=admin)
    await session.commit()
