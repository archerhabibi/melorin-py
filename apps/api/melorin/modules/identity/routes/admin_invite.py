"""/auth/admin-invite/*: a new admin accepts their invitation (public: the one-time token is the credential).

``inspect`` shows who is invited, ``enroll`` hands out the invitee's own authenticator seed, ``accept`` sets the password after one
authenticator code. No session is issued: the new admin signs in afterwards through the normal password + TOTP login, which proves
the password and the authenticator in one go. Flow and threat model: docs/24-Admin-Team-Design.md.
"""

from fastapi import Depends

from melorin.core.deps import Session
from melorin.core.ratelimit import RateLimit
from melorin.modules.identity import admin_team
from melorin.modules.identity.routes.sign_in import auth
from melorin.modules.identity.schemas import AdminInviteAccept, AdminInviteEnrollment, AdminInviteInfo, AdminInviteToken

# On top of the router-wide limit: an invite token is 256 bits, but a stricter per-IP budget keeps guessing and code brute force dead.
_limit = Depends(RateLimit("admin-invite", 20, 300))


@auth.post("/admin-invite/inspect", response_model=AdminInviteInfo, dependencies=[_limit])
async def admin_invite_inspect(body: AdminInviteToken, session: Session):
    view = await admin_team.inspect_invite(session, body.token)
    return AdminInviteInfo(
        email=view.email,
        display_name=view.display_name,
        role=view.role,
        role_label=admin_team.ROLE_LABELS_FA.get(view.role, view.role),
        expires_at=view.expires_at,
    )


@auth.post("/admin-invite/enroll", response_model=AdminInviteEnrollment, dependencies=[_limit])
async def admin_invite_enroll(body: AdminInviteToken, session: Session):
    enrollment = await admin_team.start_enrollment(session, body.token)
    await session.commit()
    return AdminInviteEnrollment(secret=enrollment.secret, otpauth_url=enrollment.otpauth_url, qr_data_uri=enrollment.qr_data_uri)


@auth.post("/admin-invite/accept", dependencies=[_limit])
async def admin_invite_accept(body: AdminInviteAccept, session: Session):
    user = await admin_team.accept_invite(session, body.token, password=body.password, totp_code=body.totp_code)
    await session.commit()
    return {"ok": True, "email": user.email}
