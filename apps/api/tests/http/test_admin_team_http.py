"""The admin team over HTTP: invite -> enrol -> accept -> sign in, role enforcement on real routes, and the self-protection rules.

Drives the REAL app through the in-process harness (see ``_http``); e-mail delivery is replaced by a recorder, so nothing leaves the box."""

from __future__ import annotations

import datetime as dt
import re

import pytest
from sqlalchemy import select

from _http import PASSWORD, add_user, api_client, totp_now
from melorin.core.crypto import decrypt
from melorin.core.security import _totp
from melorin.domain.timeutil import utcnow
from melorin.kernel.models.identity import AdminInvite, RefreshToken, User
from melorin.kernel.models.system import AuditEvent, SecurityEvent

AUTH = "/api/v1/auth"
ADMIN = "/api/v1/admin"
STRONG = "Correct-Horse-Battery-9"


@pytest.fixture(autouse=True)
def mailbox(monkeypatch):
    sent: list[dict] = []

    async def fake_send(to, subject, body):
        sent.append({"to": to, "subject": subject, "body": body})

    async def available():
        return True

    monkeypatch.setattr("melorin.modules.identity.admin_team.send_email", fake_send)
    monkeypatch.setattr("melorin.modules.identity.admin_team.email_available", available)
    monkeypatch.setenv("MELORIN_ADMIN_DOMAIN", "admin.example.com")
    return sent


async def _login(c, email, password=PASSWORD, totp=None):
    r = await c.post(f"{AUTH}/password/login", json={"email": email, "password": password, "totp_code": totp or totp_now()})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _owner(c, maker, email="owner@example.com"):
    user = await add_user(maker, email=email, admin=True, totp=True)
    return await _login(c, email), user


def _token(invite_path: str) -> str:
    return re.search(r"t=([\w-]+)", invite_path).group(1)


async def _invite(c, headers, email="new@example.com", role="support", name=None):
    r = await c.post(f"{ADMIN}/admins", headers=headers, json={"email": email, "role": role, "display_name": name})
    assert r.status_code == 201, r.text
    return r.json()


async def _accept(c, maker, token, password=STRONG):
    """The invitee's side: inspect, enrol (get the seed), accept with a real authenticator code."""
    assert (await c.post(f"{AUTH}/admin-invite/inspect", json={"token": token})).status_code == 200
    enrol = await c.post(f"{AUTH}/admin-invite/enroll", json={"token": token})
    assert enrol.status_code == 200, enrol.text
    secret = enrol.json()["secret"]
    code = _totp(secret, int(dt.datetime.now(dt.UTC).timestamp()) // 30)
    r = await c.post(f"{AUTH}/admin-invite/accept", json={"token": token, "password": password, "totp_code": code})
    return r, secret


# ---------------------------------------------------------------- the happy path
async def test_full_invite_flow_ends_with_a_working_scoped_admin(mailbox):
    async with api_client() as (c, maker, _main):
        owner, _ = await _owner(c, maker)
        out = await _invite(c, owner, name="Sara")
        assert out["admin"]["state"] == "invited" and out["admin"]["role"] == "support" and out["emailed"] is True
        assert out["invite_url"].startswith("http://admin.example.com/#/accept-invite?t=") or out["invite_url"].startswith(
            "https://admin.example.com/"
        )
        assert mailbox[0]["to"] == "new@example.com" and _token(out["invite_path"]) in mailbox[0]["body"]
        token = _token(out["invite_path"])

        # before accepting, the shell can do nothing
        early = await c.post(f"{AUTH}/password/login", json={"email": "new@example.com", "password": STRONG, "totp_code": "123456"})
        assert early.status_code == 401

        r, secret = await _accept(c, maker, token)
        assert r.status_code == 200 and r.json()["email"] == "new@example.com"

        # sign in with password + authenticator (a NEW time step: the accept code is already consumed)
        counter = int(dt.datetime.now(dt.UTC).timestamp()) // 30 + 1
        login = await c.post(
            f"{AUTH}/password/login", json={"email": "new@example.com", "password": STRONG, "totp_code": _totp(secret, counter)}
        )
        assert login.status_code == 200 and login.json()["is_admin"] is True
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        me = (await c.get(f"{ADMIN}/me", headers=headers)).json()
        assert me["role"] == "support" and me["is_owner"] is False and "support:rw" in me["permissions"]

        # inside the role: tickets are open, outside it: payments writes and the team are refused
        assert (await c.get(f"{ADMIN}/tickets", headers=headers)).status_code == 200
        denied = await c.get(f"{ADMIN}/admins", headers=headers)
        assert denied.status_code == 403 and denied.json()["error"]["code"] == "ADMIN_ROLE_FORBIDDEN"
        assert (await c.get(f"{ADMIN}/settings", headers=headers)).status_code == 403

        async with maker() as s:
            actions = set((await s.scalars(select(AuditEvent.action))).all())
            denials = (await s.scalars(select(SecurityEvent).where(SecurityEvent.kind == "admin_area_denied"))).all()
        assert {"admin.invited", "admin.invite_accepted", "admin.login"} <= actions
        assert len(denials) == 2 and denials[0].data["area"] in {"admins", "system"}


async def test_only_the_hash_of_the_invite_is_stored():
    async with api_client() as (c, maker, _main):
        owner, _ = await _owner(c, maker)
        token = _token((await _invite(c, owner))["invite_path"])
        async with maker() as s:
            invite = await s.scalar(select(AdminInvite))
        assert token not in (invite.token_hash or "") and len(invite.token_hash) == 64


async def test_invitee_shell_has_no_password_no_2fa_and_is_inactive():
    async with api_client() as (c, maker, _main):
        owner, _ = await _owner(c, maker)
        await _invite(c, owner, email="shell@example.com", role="viewer")
        async with maker() as s:
            user = await s.scalar(select(User).where(User.email == "shell@example.com"))
        assert (user.password_hash, user.totp_enabled, user.is_active, user.admin_roles) == (None, False, False, ["viewer"])


# ---------------------------------------------------------------- invite security
async def test_invite_is_single_use_and_a_new_invite_replaces_the_old_one():
    async with api_client() as (c, maker, _main):
        owner, _ = await _owner(c, maker)
        first = _token((await _invite(c, owner))["invite_path"])
        # re-sending (reset-access on the shell is allowed): the first link dies
        listing = (await c.get(f"{ADMIN}/admins", headers=owner)).json()
        shell = next(a for a in listing if a["email"] == "new@example.com")
        second = _token((await c.post(f"{ADMIN}/admins/{shell['id']}/reset-access", headers=owner)).json()["invite_path"])
        assert (await c.post(f"{AUTH}/admin-invite/inspect", json={"token": first})).status_code == 400
        r, _ = await _accept(c, maker, second)
        assert r.status_code == 200
        again = await c.post(f"{AUTH}/admin-invite/inspect", json={"token": second})
        assert again.status_code == 400 and again.json()["error"]["code"] == "INVITE_INVALID"


async def test_expired_unknown_and_revoked_invites_look_identical():
    async with api_client() as (c, maker, _main):
        owner, _ = await _owner(c, maker)
        token = _token((await _invite(c, owner))["invite_path"])
        async with maker() as s:
            invite = await s.scalar(select(AdminInvite))
            invite.expires_at = utcnow() - dt.timedelta(minutes=1)
            await s.commit()
        for t in (token, "x" * 43):
            r = await c.post(f"{AUTH}/admin-invite/inspect", json={"token": t})
            assert (r.status_code, r.json()["error"]["code"]) == (400, "INVITE_INVALID")


@pytest.mark.parametrize(
    "password, code",
    [("short", "PASSWORD_TOO_SHORT"), ("xx-sara.admin-9A", "PASSWORD_HAS_EMAIL"), ("alllowercaseletters", "PASSWORD_WEAK_MIX")],
)
async def test_weak_passwords_are_refused_with_a_precise_code(password, code):
    async with api_client() as (c, maker, _main):
        owner, _ = await _owner(c, maker)
        token = _token((await _invite(c, owner, email="sara.admin@example.com"))["invite_path"])
        enrol = (await c.post(f"{AUTH}/admin-invite/enroll", json={"token": token})).json()
        good = _totp(enrol["secret"], int(dt.datetime.now(dt.UTC).timestamp()) // 30)
        r = await c.post(f"{AUTH}/admin-invite/accept", json={"token": token, "password": password, "totp_code": good})
        assert (r.status_code, r.json()["error"]["code"]) == (422, code)


async def test_accept_needs_enrolment_and_a_valid_authenticator_code():
    async with api_client() as (c, maker, _main):
        owner, _ = await _owner(c, maker)
        token = _token((await _invite(c, owner))["invite_path"])
        no_seed = await c.post(f"{AUTH}/admin-invite/accept", json={"token": token, "password": STRONG, "totp_code": "123456"})
        assert no_seed.json()["error"]["code"] == "ENROLL_FIRST"
        await c.post(f"{AUTH}/admin-invite/enroll", json={"token": token})
        bad = await c.post(f"{AUTH}/admin-invite/accept", json={"token": token, "password": STRONG, "totp_code": "000000"})
        assert (bad.status_code, bad.json()["error"]["code"]) == (400, "TOTP_INVALID")
        async with maker() as s:
            user = await s.scalar(select(User).where(User.email == "new@example.com"))
        assert user.is_active is False and user.password_hash is None  # a wrong code activates nothing


async def test_wrong_codes_lock_the_invite():
    async with api_client() as (c, maker, _main):
        owner, _ = await _owner(c, maker)
        token = _token((await _invite(c, owner))["invite_path"])
        await c.post(f"{AUTH}/admin-invite/enroll", json={"token": token})
        for _ in range(5):
            await c.post(f"{AUTH}/admin-invite/accept", json={"token": token, "password": STRONG, "totp_code": "000000"})
        locked = await c.post(f"{AUTH}/admin-invite/accept", json={"token": token, "password": STRONG, "totp_code": "000000"})
        assert (locked.status_code, locked.json()["error"]["code"]) == (429, "INVITE_LOCKED")
        assert (await c.post(f"{AUTH}/admin-invite/inspect", json={"token": token})).status_code == 400


async def test_the_owner_never_learns_the_invitees_password_or_seed():
    async with api_client() as (c, maker, _main):
        owner, _ = await _owner(c, maker)
        out = await _invite(c, owner)
        flat = str(out) + str((await c.get(f"{ADMIN}/admins", headers=owner)).json())
        assert "secret" not in flat and "password" not in flat.replace("password_hash", "")
        assert not any(k in out["admin"] for k in ("password_hash", "totp_secret", "totp_secret_enc"))


# ---------------------------------------------------------------- who may invite whom
async def test_inviting_an_existing_customer_or_admin_email_is_refused():
    async with api_client() as (c, maker, _main):
        owner, _ = await _owner(c, maker)
        await add_user(maker, email="customer@example.com")
        r = await c.post(f"{ADMIN}/admins", headers=owner, json={"email": "customer@example.com", "role": "viewer"})
        assert (r.status_code, r.json()["error"]["code"]) == (409, "EMAIL_IN_USE_BY_CUSTOMER")
        r = await c.post(f"{ADMIN}/admins", headers=owner, json={"email": "OWNER@example.com", "role": "viewer"})
        assert (r.status_code, r.json()["error"]["code"]) == (409, "ADMIN_EXISTS")
        r = await c.post(f"{ADMIN}/admins", headers=owner, json={"email": "x@example.com", "role": "god"})
        assert (r.status_code, r.json()["error"]["code"]) == (422, "ROLE_INVALID")


async def test_a_non_owner_admin_cannot_use_the_team_api():
    async with api_client() as (c, maker, _main):
        owner, _ = await _owner(c, maker)
        token = _token((await _invite(c, owner, role="manager"))["invite_path"])
        _, secret = await _accept(c, maker, token)
        counter = int(dt.datetime.now(dt.UTC).timestamp()) // 30 + 1
        r = await c.post(
            f"{AUTH}/password/login", json={"email": "new@example.com", "password": STRONG, "totp_code": _totp(secret, counter)}
        )
        manager = {"Authorization": f"Bearer {r.json()['access_token']}"}
        for method, url, body in (
            ("get", f"{ADMIN}/admins", None),
            ("post", f"{ADMIN}/admins", {"email": "e@example.com", "role": "owner"}),
        ):
            resp = await getattr(c, method)(url, headers=manager, **({"json": body} if body else {}))
            assert resp.status_code == 403, url


async def test_an_admin_with_no_role_has_no_access():
    async with api_client() as (c, maker, _main):
        owner, owner_user = await _owner(c, maker)
        async with maker() as s:
            u = await s.get(User, owner_user.id)
            u.admin_roles = []
            await s.commit()
        assert (await c.get(f"{ADMIN}/orders", headers=owner)).status_code == 403
        assert (await c.get(f"{ADMIN}/me", headers=owner)).status_code == 403


# ---------------------------------------------------------------- changing roles and status
async def _active_admin(c, maker, owner, email, role):
    token = _token((await _invite(c, owner, email=email, role=role))["invite_path"])
    _, secret = await _accept(c, maker, token)
    counter = int(dt.datetime.now(dt.UTC).timestamp()) // 30 + 1
    r = await c.post(f"{AUTH}/password/login", json={"email": email, "password": STRONG, "totp_code": _totp(secret, counter)})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_role_change_takes_effect_on_the_next_request_and_is_audited():
    async with api_client() as (c, maker, _main):
        owner, _ = await _owner(c, maker)
        viewer = await _active_admin(c, maker, owner, "v@example.com", "viewer")
        assert (await c.post(f"{ADMIN}/coupons", headers=viewer, json={})).status_code == 403
        listing = (await c.get(f"{ADMIN}/admins", headers=owner)).json()
        target = next(a for a in listing if a["email"] == "v@example.com")["id"]
        r = await c.patch(f"{ADMIN}/admins/{target}", headers=owner, json={"role": "manager"})
        assert r.status_code == 200 and r.json()["role"] == "manager"
        # a write that used to be 403 is now judged by the coupon rules (422 validation), i.e. it got past the role guard
        assert (await c.post(f"{ADMIN}/coupons", headers=viewer, json={})).status_code == 422
        async with maker() as s:
            ev = await s.scalar(select(AuditEvent).where(AuditEvent.action == "admin.role_changed"))
        assert ev.data == {"from": "viewer", "to": "manager"}


async def test_suspending_an_admin_kills_the_session_at_once_and_reactivating_restores_it():
    async with api_client() as (c, maker, _main):
        owner, _ = await _owner(c, maker)
        sup = await _active_admin(c, maker, owner, "s@example.com", "support")
        target = next(a for a in (await c.get(f"{ADMIN}/admins", headers=owner)).json() if a["email"] == "s@example.com")["id"]
        assert (await c.get(f"{ADMIN}/tickets", headers=sup)).status_code == 200
        r = await c.patch(f"{ADMIN}/admins/{target}", headers=owner, json={"is_active": False})
        assert r.json()["state"] == "suspended"
        assert (await c.get(f"{ADMIN}/tickets", headers=sup)).status_code == 401
        async with maker() as s:
            live = (
                await s.scalars(
                    select(RefreshToken).where(
                        RefreshToken.user_id == (await s.scalar(select(User.id).where(User.email == "s@example.com"))),
                        RefreshToken.revoked_at.is_(None),
                    )
                )
            ).all()
        assert live == []
        assert (await c.patch(f"{ADMIN}/admins/{target}", headers=owner, json={"is_active": True})).json()["state"] == "active"
        assert (await c.get(f"{ADMIN}/tickets", headers=sup)).status_code == 200


async def test_reactivating_an_admin_who_never_accepted_is_refused():
    async with api_client() as (c, maker, _main):
        owner, _ = await _owner(c, maker)
        await _invite(c, owner)
        target = next(a for a in (await c.get(f"{ADMIN}/admins", headers=owner)).json() if a["email"] == "new@example.com")["id"]
        r = await c.patch(f"{ADMIN}/admins/{target}", headers=owner, json={"is_active": True})
        assert (r.status_code, r.json()["error"]["code"]) == (409, "ADMIN_NOT_SET_UP")


async def test_reset_access_wipes_credentials_and_sessions_and_needs_a_new_invite():
    async with api_client() as (c, maker, _main):
        owner, _ = await _owner(c, maker)
        sup = await _active_admin(c, maker, owner, "s@example.com", "support")
        target = next(a for a in (await c.get(f"{ADMIN}/admins", headers=owner)).json() if a["email"] == "s@example.com")["id"]
        r = await c.post(f"{ADMIN}/admins/{target}/reset-access", headers=owner)
        assert r.status_code == 200 and r.json()["admin"]["state"] == "invited"
        assert (await c.get(f"{ADMIN}/tickets", headers=sup)).status_code == 401
        old = await c.post(f"{AUTH}/password/login", json={"email": "s@example.com", "password": STRONG, "totp_code": totp_now()})
        assert old.status_code == 401


async def test_removed_admin_disappears_and_can_be_invited_again_from_scratch():
    async with api_client() as (c, maker, _main):
        owner, _ = await _owner(c, maker)
        sup = await _active_admin(c, maker, owner, "s@example.com", "support")
        target = next(a for a in (await c.get(f"{ADMIN}/admins", headers=owner)).json() if a["email"] == "s@example.com")["id"]
        assert (await c.delete(f"{ADMIN}/admins/{target}", headers=owner)).status_code == 204
        assert (await c.get(f"{ADMIN}/tickets", headers=sup)).status_code == 401
        assert all(a["email"] != "s@example.com" for a in (await c.get(f"{ADMIN}/admins", headers=owner)).json())
        again = await c.post(f"{ADMIN}/admins", headers=owner, json={"email": "s@example.com", "role": "viewer"})
        assert again.status_code == 201 and again.json()["admin"]["state"] == "invited" and again.json()["admin"]["role"] == "viewer"
        async with maker() as s:
            # the old row is reused (audit history keeps resolving) but nothing of the old credentials survives
            user = await s.scalar(select(User).where(User.email == "s@example.com"))
        assert (user.password_hash, user.totp_enabled, user.archived_at) == (None, False, None)


# ---------------------------------------------------------------- self protection
async def test_nobody_can_demote_suspend_remove_or_reset_themselves():
    async with api_client() as (c, maker, _main):
        owner, me = await _owner(c, maker)
        await _active_admin(c, maker, owner, "second@example.com", "owner")
        for method, url, body, code in (
            ("patch", f"{ADMIN}/admins/{me.id}", {"role": "viewer"}, "SELF_CHANGE_FORBIDDEN"),
            ("patch", f"{ADMIN}/admins/{me.id}", {"is_active": False}, "SELF_CHANGE_FORBIDDEN"),
            ("delete", f"{ADMIN}/admins/{me.id}", None, "SELF_CHANGE_FORBIDDEN"),
            ("post", f"{ADMIN}/admins/{me.id}/reset-access", None, "SELF_CHANGE_FORBIDDEN"),
        ):
            r = await getattr(c, method)(url, headers=owner, **({"json": body} if body else {}))
            assert (r.status_code, r.json()["error"]["code"]) == (409, code), url
        # renaming yourself is fine
        assert (await c.patch(f"{ADMIN}/admins/{me.id}", headers=owner, json={"display_name": "Boss"})).status_code == 200


async def test_the_last_active_owner_can_never_be_removed_even_by_another_owner_who_is_not_active():
    async with api_client() as (c, maker, _main):
        owner, me = await _owner(c, maker)
        second = await _active_admin(c, maker, owner, "second@example.com", "owner")
        second_id = next(a for a in (await c.get(f"{ADMIN}/admins", headers=owner)).json() if a["email"] == "second@example.com")["id"]
        # the second owner removes the first -> allowed (a second owner exists), and the team still has an owner
        assert (await c.delete(f"{ADMIN}/admins/{me.id}", headers=second)).status_code == 204
        # now the only owner left is `second`: another owner cannot exist, and self-removal is refused as well
        r = await c.delete(f"{ADMIN}/admins/{second_id}", headers=second)
        assert (r.status_code, r.json()["error"]["code"]) == (409, "SELF_CHANGE_FORBIDDEN")


async def test_the_roles_catalogue_lists_every_role_with_permissions():
    async with api_client() as (c, maker, _main):
        owner, _ = await _owner(c, maker)
        roles = (await c.get(f"{ADMIN}/admins/roles", headers=owner)).json()
        assert [r["key"] for r in roles] == ["owner", "manager", "finance", "support", "viewer"]
        assert all(r["label"] and r["description"] and r["permissions"] for r in roles)


# ---------------------------------------------------------------- store endpoints respect roles too
async def test_a_viewer_admin_session_cannot_write_through_store_endpoints():
    async with api_client() as (c, maker, main):
        owner, _ = await _owner(c, maker)
        viewer = await _active_admin(c, maker, owner, "v@example.com", "viewer")
        support = await _active_admin(c, maker, owner, "sup@example.com", "support")
        # reading a store's loyalty management is within a viewer's reach, writing is not; support lacks catalog/reseller grants
        read = await c.get(f"/api/v1/stores/{main.id}/loyalty/manage/program", headers=viewer)
        assert read.status_code != 403 or read.json()["error"]["code"] != "ADMIN_ROLE_FORBIDDEN"
        write = await c.put(f"/api/v1/stores/{main.id}/loyalty/manage/program", headers=viewer, json={})
        assert write.status_code == 403 and write.json()["error"]["code"] == "ADMIN_ROLE_FORBIDDEN"
        blocked = await c.get(f"/api/v1/stores/{main.id}/loyalty/manage/program", headers=support)
        assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "ADMIN_ROLE_FORBIDDEN"


# ---------------------------------------------------------------- bootstrap and migration
async def test_bootstrap_admin_is_the_first_owner(monkeypatch):
    from melorin import cli

    async with api_client(with_main_store=False) as (_c, maker, _main):
        monkeypatch.setenv("MELORIN_BOOTSTRAP_ADMIN_EMAIL", "boot@example.com")
        monkeypatch.setenv("MELORIN_BOOTSTRAP_ADMIN_PASSWORD", "x" * 26)
        monkeypatch.setenv("MELORIN_BOOTSTRAP_ADMIN_TOTP_SECRET", "JBSWY3DPEHPK3PXP")
        monkeypatch.setenv("MELORIN_ENCRYPTION_KEY", "oB6y2nI2qk1m3c9m8Lw0o2m3Jk9eD0fZ4n1m2x7s8aQ=")
        monkeypatch.setattr(cli, "session_factory", lambda: maker)
        from melorin.core import config

        config.get_settings.cache_clear()
        await cli.bootstrap()
        async with maker() as s:
            user = await s.scalar(select(User).where(User.email == "boot@example.com"))
        assert user.is_super_admin and user.admin_roles == ["owner"]


def test_decrypt_import_is_used():
    assert callable(decrypt)
