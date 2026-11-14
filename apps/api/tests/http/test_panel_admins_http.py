"""Panel admins over HTTP: the admin desk (list, credentials, reset, requests) and the reseller view (read-only + change requests).

The service layer is covered in ``test_panel_admins``; this file drives the REAL routes (auth, validation, error envelope, audit,
notifications) through the in-process harness. No panel is ever contacted: the adapter factory is replaced by a recorder."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from _db import make_store, make_user
from _http import PASSWORD, add_user, api_client, totp_now
from melorin.core.crypto import decrypt, encrypt
from melorin.core.security import create_access_token
from melorin.kernel.models.system import AuditEvent, OutboxEvent
from melorin.kernel.models.vpn import Panel, PanelAdmin, PanelAdminChangeRequest

AUTH = "/api/v1/auth"
ADMIN = "/api/v1/admin"
OLD_PASSWORD = "Secret-Pass-12!"
WEBHOOK = "https://discord.com/api/webhooks/123/very-secret-token"


class Recorder:
    """Stands in for the PasarGuard adapter: remembers what the routes pushed."""

    def __init__(self):
        self.calls: list[tuple[int, dict, str | None]] = []

    async def update_admin_profile(self, remote_id, changes, password=None):
        self.calls.append((remote_id, dict(changes), password))

    async def close(self):
        return None


@pytest.fixture
def panel_adapter(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr("melorin.modules.panel_integrations.adapters.registry.build_adapter", lambda panel, server=None: rec)
    return rec


async def _admin(c, maker, email="root@example.com"):
    user = await add_user(maker, email=email, admin=True, totp=True)
    r = await c.post(f"{AUTH}/password/login", json={"email": email, "password": PASSWORD, "totp_code": totp_now()})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, user


def _owner_headers(user, store):
    token, _ = create_access_token(user.id, False, store_id=store.id, channel="site")
    return {"Authorization": f"Bearer {token}"}


async def _world(maker):
    """Two reseller stores, each with an active admin on one PasarGuard panel (the second store is the 'neighbour')."""
    async with maker() as s:
        owner, other_owner = await make_user(s), await make_user(s)
        reseller = await make_store(s, kind="reseller", slug="reseller-aaaa1111", owner=owner)
        neighbour = await make_store(s, kind="reseller", slug="reseller-bbbb2222", owner=other_owner)
        panel = Panel(name="P1", kind="pasarguard", base_url="https://p.example.com", is_enabled=True, config={})
        s.add(panel)
        await s.flush()
        rows = {}
        for store in (reseller, neighbour):
            rows[store.id] = PanelAdmin(
                panel_id=panel.id,
                store_id=store.id,
                username=f"rs_{store.slug[-8:]}",
                password_enc=encrypt(OLD_PASSWORD),
                status="active",
                remote_id=7,
                profile={"profile_title": "Old title"},
            )
            s.add(rows[store.id])
        await s.commit()
        return owner, reseller, other_owner, neighbour, rows


async def _outbox(maker, kind):
    async with maker() as s:
        events = (await s.scalars(select(OutboxEvent).where(OutboxEvent.topic == "notification.send"))).all()
        return [e.payload for e in events if (e.payload or {}).get("kind") == kind]


async def _audit(maker, action):
    async with maker() as s:
        return (await s.scalars(select(AuditEvent).where(AuditEvent.action == action))).all()


# --- the desk is closed -------------------------------------------------------------------------------------------------
async def test_admin_panel_admin_routes_are_closed_to_anonymous_and_customer_sessions():
    async with api_client() as (c, maker, main):
        _, admin = await _admin(c, maker)
        _, _, _, _, rows = await _world(maker)
        row_id = next(iter(rows.values())).id
        customer, _ = create_access_token(admin.id, False, store_id=main.id, channel="site")  # an admin account, but a customer session
        reads = ["/panel-admins", "/panel-admin-requests", f"/panel-admins/{row_id}/credentials"]
        for path in reads:
            assert (await c.get(f"{ADMIN}{path}")).status_code == 401, path
            assert (await c.get(f"{ADMIN}{path}", headers={"Authorization": f"Bearer {customer}"})).status_code == 403, path
        for path, body in (
            ("/panel-admins/sync", {}),
            ("/panel-admins/profile", {"store_id": str(main.id)}),
            (f"/panel-admins/{row_id}/reset-password", None),
        ):
            kw = {"json": body} if body is not None else {}
            method = c.patch if path.endswith("profile") else c.post
            assert (await method(f"{ADMIN}{path}", headers={"Authorization": f"Bearer {customer}"}, **kw)).status_code == 403, path


# --- admin: list / credentials / reset ---------------------------------------------------------------------------------------
async def test_list_never_returns_a_password_and_viewing_credentials_is_audited(panel_adapter):
    async with api_client() as (c, maker, _):
        h, _ = await _admin(c, maker)
        _, reseller, _, _, rows = await _world(maker)
        listed = await c.get(f"{ADMIN}/panel-admins", headers=h)
        assert listed.status_code == 200 and len(listed.json()) == 2
        assert OLD_PASSWORD not in listed.text and all("password" not in item for item in listed.json())
        only = await c.get(f"{ADMIN}/panel-admins", params={"store_id": str(reseller.id)}, headers=h)
        assert [i["username"] for i in only.json()] == ["rs_aaaa1111"] and only.json()[0]["panel_name"] == "P1"
        assert await _audit(maker, "panel_admin.credentials_viewed") == []
        cred = await c.get(f"{ADMIN}/panel-admins/{rows[reseller.id].id}/credentials", headers=h)
        assert cred.status_code == 200
        assert cred.json()["username"] == "rs_aaaa1111" and cred.json()["password"] == OLD_PASSWORD
        assert len(await _audit(maker, "panel_admin.credentials_viewed")) == 1


async def test_reset_password_rotates_the_secret_on_the_panel_and_in_the_database(panel_adapter):
    async with api_client() as (c, maker, _):
        h, _ = await _admin(c, maker)
        _, reseller, _, _, rows = await _world(maker)
        r = await c.post(f"{ADMIN}/panel-admins/{rows[reseller.id].id}/reset-password", headers=h)
        assert r.status_code == 200
        new = r.json()["password"]
        assert new != OLD_PASSWORD and panel_adapter.calls == [(7, {}, new)]
        async with maker() as s:
            assert decrypt((await s.get(PanelAdmin, rows[reseller.id].id)).password_enc) == new
        assert len(await _audit(maker, "panel_admin.password_reset")) == 1
        assert (await c.post(f"{ADMIN}/panel-admins/00000000-0000-0000-0000-000000000000/reset-password", headers=h)).status_code == 404


async def test_admin_edits_one_stores_profile_only_and_bad_values_are_refused(panel_adapter):
    async with api_client() as (c, maker, _):
        h, _ = await _admin(c, maker)
        _, reseller, _, neighbour, rows = await _world(maker)
        ok = await c.patch(
            f"{ADMIN}/panel-admins/profile",
            headers=h,
            json={"store_id": str(reseller.id), "profile": {"profile_title": "Shop", "note": "vip"}},
        )
        assert ok.status_code == 200 and ok.json()["results"][0]["synced"] is True
        assert panel_adapter.calls == [(7, {"profile_title": "Shop", "note": "vip"}, None)]
        async with maker() as s:
            assert (await s.get(PanelAdmin, rows[reseller.id].id)).profile["note"] == "vip"
            assert (await s.get(PanelAdmin, rows[neighbour.id].id)).profile == {"profile_title": "Old title"}
        bad = await c.patch(
            f"{ADMIN}/panel-admins/profile",
            headers=h,
            json={"store_id": str(reseller.id), "profile": {"support_url": "javascript:alert(1)"}},
        )
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "PROFILE_INVALID"
        unknown = await c.patch(
            f"{ADMIN}/panel-admins/profile", headers=h, json={"store_id": "00000000-0000-0000-0000-000000000000", "profile": {}}
        )
        assert unknown.status_code == 404


# --- reseller: read-only view and change requests --------------------------------------------------------------------------
async def test_reseller_sees_only_its_own_admin_without_secrets(panel_adapter):
    async with api_client() as (c, maker, _):
        owner, reseller, other_owner, neighbour, _ = await _world(maker)
        r = await c.get(f"/api/v1/stores/{reseller.id}/reseller/panel-admin", headers=_owner_headers(owner, reseller))
        assert r.status_code == 200
        assert r.json() == [
            {
                "panel_name": "P1",
                "username": "rs_aaaa1111",
                "role": "operator",
                "status": "active",
                "profile": {"profile_title": "Old title"},
                "profile_synced": True,
            }
        ]
        assert OLD_PASSWORD not in r.text and "rs_bbbb2222" not in r.text
        # the neighbour's owner cannot open this store's reseller console, and a plain customer cannot either
        assert (
            await c.get(f"/api/v1/stores/{reseller.id}/reseller/panel-admin", headers=_owner_headers(other_owner, reseller))
        ).status_code == 403
        async with maker() as s:
            customer = await make_user(s)
            await s.commit()
        assert (
            await c.get(f"/api/v1/stores/{reseller.id}/reseller/panel-admin", headers=_owner_headers(customer, reseller))
        ).status_code == 403


async def test_request_lifecycle_file_alert_cancel_and_refile(panel_adapter):
    async with api_client() as (c, maker, _):
        admin_h, admin = await _admin(c, maker)
        owner, reseller, other_owner, neighbour, _ = await _world(maker)
        mine = _owner_headers(owner, reseller)
        base = f"/api/v1/stores/{reseller.id}/reseller/panel-admin/change-requests"
        filed = await c.post(
            base, headers=mine, json={"changes": {"profile_title": "New", "discord_webhook": WEBHOOK}, "message": "rebrand"}
        )
        assert filed.status_code == 201 and filed.json()["status"] == "pending"
        # every active super admin is alerted; the alert names the fields but never copies a value (a webhook URL is a secret)
        alerts = await _outbox(maker, "admin_panel_admin_request")
        assert len(alerts) == 1 and alerts[0]["user_id"] == str(admin.id)
        assert (
            "عنوان پروفایل" in alerts[0]["body"] and "وبهوک دیسکورد" in alerts[0]["body"] and "very-secret-token" not in alerts[0]["body"]
        )
        # one pending request per store; admin-only fields cannot be requested
        assert (await c.post(base, headers=mine, json={"changes": {"profile_title": "Again"}})).json()["error"]["code"] == "REQUEST_PENDING"
        listed = (await c.get(base, headers=mine)).json()
        assert [x["status"] for x in listed] == ["pending"]
        # somebody else's request cannot be withdrawn
        request_id = filed.json()["id"]
        theirs = _owner_headers(other_owner, neighbour)
        assert (
            await c.post(f"/api/v1/stores/{neighbour.id}/reseller/panel-admin/change-requests/{request_id}/cancel", headers=theirs)
        ).status_code == 404
        # the owner withdraws it, the second withdrawal is refused, and a fresh request can be filed
        cancel = f"{base}/{request_id}/cancel"
        assert (await c.post(cancel, headers=mine)).status_code == 200
        assert (await c.post(cancel, headers=mine)).json()["error"]["code"] == "REQUEST_ALREADY_REVIEWED"
        async with maker() as s:
            assert (await s.get(PanelAdminChangeRequest, uuid.UUID(request_id))).status == "cancelled"
        assert (await c.post(base, headers=mine, json={"changes": {"profile_title": "Second"}})).status_code == 201
        assert len(await _audit(maker, "panel_admin.request_cancelled")) == 1
        # a cancelled request can no longer be applied by the admin
        stale = await c.post(f"{ADMIN}/panel-admin-requests/{request_id}/apply", headers=admin_h, json={})
        assert stale.status_code == 409


async def test_admin_applies_an_edited_request_and_the_reseller_is_told(panel_adapter):
    async with api_client() as (c, maker, _):
        admin_h, _ = await _admin(c, maker)
        owner, reseller, _, _, rows = await _world(maker)
        mine = _owner_headers(owner, reseller)
        base = f"/api/v1/stores/{reseller.id}/reseller/panel-admin/change-requests"
        rid = (await c.post(base, headers=mine, json={"changes": {"profile_title": "Wish", "telegram_id": 12345}})).json()["id"]
        queue = (await c.get(f"{ADMIN}/panel-admin-requests", headers=admin_h)).json()
        assert len(queue) == 1 and queue[0]["store_name"] == reseller.name
        assert queue[0]["current_profile"] == {"profile_title": "Old title"}  # the desk can show before -> after
        done = await c.post(
            f"{ADMIN}/panel-admin-requests/{rid}/apply", headers=admin_h, json={"changes": {"profile_title": "Edited"}, "note": "shortened"}
        )
        assert done.status_code == 200 and done.json()["ok"] is True
        assert panel_adapter.calls == [(7, {"profile_title": "Edited"}, None)]
        async with maker() as s:
            req = await s.get(PanelAdminChangeRequest, uuid.UUID(rid))
            assert req.status == "applied" and req.changes == {"profile_title": "Edited"}  # what was really applied is kept
            assert (await s.get(PanelAdmin, rows[reseller.id].id)).profile["profile_title"] == "Edited"
        told = await _outbox(maker, "reseller_panel_admin_request")
        assert len(told) == 1 and told[0]["user_id"] == str(owner.id) and "shortened" in told[0]["body"]
        assert (await c.post(f"{ADMIN}/panel-admin-requests/{rid}/apply", headers=admin_h, json={})).json()["error"][
            "code"
        ] == "REQUEST_ALREADY_REVIEWED"
        history = (await c.get(f"{ADMIN}/panel-admin-requests", params={"status": "applied"}, headers=admin_h)).json()
        assert [h["id"] for h in history] == [rid]


async def test_rejecting_tells_the_reseller_why_and_touches_nothing(panel_adapter):
    async with api_client() as (c, maker, _):
        admin_h, _ = await _admin(c, maker)
        owner, reseller, _, _, rows = await _world(maker)
        mine = _owner_headers(owner, reseller)
        rid = (
            await c.post(
                f"/api/v1/stores/{reseller.id}/reseller/panel-admin/change-requests",
                headers=mine,
                json={"changes": {"support_url": "https://t.me/shop"}},
            )
        ).json()["id"]
        rej = await c.post(f"{ADMIN}/panel-admin-requests/{rid}/reject", headers=admin_h, json={"note": "نیاز به آدرس رسمی"})
        assert rej.status_code == 200
        assert panel_adapter.calls == []
        async with maker() as s:
            assert (await s.get(PanelAdminChangeRequest, uuid.UUID(rid))).status == "rejected"
            assert (await s.get(PanelAdmin, rows[reseller.id].id)).profile == {"profile_title": "Old title"}
        told = await _outbox(maker, "reseller_panel_admin_request")
        assert len(told) == 1 and "نیاز به آدرس رسمی" in told[0]["body"]
        mine_after = (await c.get(f"/api/v1/stores/{reseller.id}/reseller/panel-admin/change-requests", headers=mine)).json()
        assert mine_after[0]["status"] == "rejected" and mine_after[0]["review_note"] == "نیاز به آدرس رسمی"


async def test_two_simultaneous_requests_cannot_both_be_filed_even_when_the_count_check_is_blind(monkeypatch):
    """The friendly ``count`` check is only a first line: the database allows one pending request per store, and the route turns
    its refusal into the same clean ``REQUEST_PENDING`` answer (no 500, no second pending request, no second alert)."""
    import sqlalchemy as sa

    from melorin.modules.reseller.routes import panel_profile

    async with api_client() as (c, maker, _):
        await _admin(c, maker)
        owner, reseller, _, _, _ = await _world(maker)
        mine = _owner_headers(owner, reseller)
        base = f"/api/v1/stores/{reseller.id}/reseller/panel-admin/change-requests"
        assert (await c.post(base, headers=mine, json={"changes": {"profile_title": "First"}})).status_code == 201
        monkeypatch.setattr(panel_profile, "func", type("F", (), {"count": staticmethod(lambda: sa.literal(0))}))  # the check sees nothing
        again = await c.post(base, headers=mine, json={"changes": {"profile_title": "Second"}})
        assert again.status_code == 409 and again.json()["error"]["code"] == "REQUEST_PENDING"
        async with maker() as s:
            pending = (await s.scalars(select(PanelAdminChangeRequest).where(PanelAdminChangeRequest.status == "pending"))).all()
            assert [p.changes for p in pending] == [{"profile_title": "First"}]
        assert len(await _outbox(maker, "admin_panel_admin_request")) == 1
