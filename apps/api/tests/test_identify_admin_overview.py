"""Admin view of automatic identity verification (docs/21): trusted devices and automatic merges, over HTTP."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import select

from _http import PASSWORD, add_user, api_client, totp_now
from melorin.core import audit
from melorin.core.db import utcnow
from melorin.kernel.models.identity import TrustedDevice
from melorin.kernel.models.system import AuditEvent

AUTH = "/api/v1/auth"
ADMIN = "/api/v1/admin"
READ = ["/trusted-devices", "/trusted-devices/summary", "/identity-auto-merges"]


async def admin_headers(c, maker):
    await add_user(maker, email="root@example.com", admin=True, totp=True)
    r = await c.post(f"{AUTH}/password/login", json={"email": "root@example.com", "password": PASSWORD, "totp_code": totp_now()})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def device(maker, user, store, *, label="Chrome · Windows", days=30, revoked=False, tg=111):
    async with maker() as s:
        d = TrustedDevice(
            user_id=user.id,
            store_id=store.id,
            telegram_id=tg,
            key_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            label=label,
            last_ip="203.0.113.7",
            last_seen_at=utcnow(),
            expires_at=utcnow() + dt.timedelta(days=days),
            revoked_at=utcnow() if revoked else None,
        )
        s.add(d)
        await s.commit()
        return d.id


@pytest.mark.parametrize("path", READ)
async def test_surface_is_closed_to_anonymous_and_customers(path):
    async with api_client() as (c, maker, _):
        assert (await c.get(f"{ADMIN}{path}")).status_code == 401
        await add_user(maker, email="cust@example.com")
        login = await c.post(f"{AUTH}/password/login", json={"email": "cust@example.com", "password": PASSWORD})
        h = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert (await c.get(f"{ADMIN}{path}", headers=h)).status_code == 403


async def test_writes_are_closed_to_customers():
    async with api_client() as (c, maker, _):
        await add_user(maker, email="cust@example.com")
        login = await c.post(f"{AUTH}/password/login", json={"email": "cust@example.com", "password": PASSWORD})
        h = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert (await c.post(f"{ADMIN}/trusted-devices/{uuid.uuid4()}/revoke", headers=h)).status_code == 403
        assert (await c.post(f"{ADMIN}/trusted-devices/revoke-account", headers=h, json={"user_id": str(uuid.uuid4())})).status_code == 403


async def test_list_filters_by_status_and_never_leaks_the_key():
    async with api_client() as (c, maker, main):
        h = await admin_headers(c, maker)
        u = await add_user(maker, email="a@example.com")
        live = await device(maker, u, main)
        dead = await device(maker, u, main, revoked=True, label="Firefox · Linux")
        old = await device(maker, u, main, days=-1, label="Safari · macOS")
        by = lambda st: c.get(f"{ADMIN}/trusted-devices", params={"status": st}, headers=h)
        assert [r["id"] for r in (await by("active")).json()] == [str(live)]
        assert [r["id"] for r in (await by("revoked")).json()] == [str(dead)]
        assert [r["id"] for r in (await by("expired")).json()] == [str(old)]
        assert len((await by("all")).json()) == 3
        row = (await by("active")).json()[0]
        assert row["user"]["email"] == "a@example.com" and row["store_name"] and row["status"] == "active"
        assert "key_hash" not in row and "key" not in row
        assert (await by("bogus")).status_code == 422


async def test_search_matches_email_label_and_telegram_id():
    async with api_client() as (c, maker, main):
        h = await admin_headers(c, maker)
        a, b = await add_user(maker, email="alice@example.com"), await add_user(maker, email="bob@example.com")
        da = await device(maker, a, main, label="Chrome · Windows", tg=555)
        await device(maker, b, main, label="Firefox · Linux", tg=777)
        ids = lambda q: c.get(f"{ADMIN}/trusted-devices", params={"q": q, "status": "all"}, headers=h)
        assert [r["id"] for r in (await ids("alice")).json()] == [str(da)]
        assert [r["id"] for r in (await ids("firefox")).json()] and len((await ids("firefox")).json()) == 1
        assert [r["id"] for r in (await ids("555")).json()] == [str(da)]


async def test_revoke_one_device_is_audited_and_not_repeatable():
    async with api_client() as (c, maker, main):
        h = await admin_headers(c, maker)
        u = await add_user(maker, email="a@example.com")
        d = await device(maker, u, main)
        assert (await c.post(f"{ADMIN}/trusted-devices/{d}/revoke", headers=h)).json() == {"ok": True}
        assert (await c.post(f"{ADMIN}/trusted-devices/{d}/revoke", headers=h)).status_code == 404
        async with maker() as s:
            assert (await s.get(TrustedDevice, d)).revoked_at is not None
            assert "trusted_device.revoked_by_admin" in (await s.scalars(select(AuditEvent.action))).all()


async def test_revoke_account_hits_every_store_of_that_account_only():
    async with api_client() as (c, maker, main):
        h = await admin_headers(c, maker)
        a, b = await add_user(maker, email="a@example.com"), await add_user(maker, email="b@example.com")
        await device(maker, a, main)
        await device(maker, a, main, label="Edge · Windows")
        keep = await device(maker, b, main)
        r = await c.post(f"{ADMIN}/trusted-devices/revoke-account", headers=h, json={"user_id": str(a.id)})
        assert r.json() == {"ok": True, "revoked": 2}
        active = (await c.get(f"{ADMIN}/trusted-devices", headers=h)).json()
        assert [x["id"] for x in active] == [str(keep)]


async def test_summary_counts():
    async with api_client() as (c, maker, main):
        h = await admin_headers(c, maker)
        u = await add_user(maker, email="a@example.com")
        await device(maker, u, main)
        await device(maker, u, main, revoked=True)
        async with maker() as s:
            audit.record(s, "identity.auto_merged", actor_type="system", data={"keeper": str(u.id), "shell": str(u.id), "rule": "x", "providers": []})
            await s.commit()
        assert (await c.get(f"{ADMIN}/trusted-devices/summary", headers=h)).json() == {
            "active_devices": 1,
            "accounts": 1,
            "revoked_devices": 1,
            "auto_merges_30d": 1,
        }


async def test_merges_list_shows_both_sides_and_ignores_old_or_other_events():
    async with api_client() as (c, maker, main):
        h = await admin_headers(c, maker)
        keeper, shell = await add_user(maker, email="keep@example.com"), await add_user(maker, email="shell@example.com")
        async with maker() as s:
            audit.record(s, "identity.auto_merged", actor_type="system", data={"keeper": str(keeper.id), "shell": str(shell.id), "rule": "shell_into_other", "providers": ["google"]})
            audit.record(s, "identity.linked", data={"provider": "email"})
            old = AuditEvent(actor_type="system", action="identity.auto_merged", data={"keeper": str(keeper.id), "shell": str(shell.id), "rule": "old"})
            old.created_at = utcnow() - dt.timedelta(days=200)
            s.add(old)
            await s.commit()
        rows = (await c.get(f"{ADMIN}/identity-auto-merges", headers=h)).json()
        assert len(rows) == 1
        assert (rows[0]["rule"], rows[0]["providers"]) == ("shell_into_other", ["google"])
        assert rows[0]["keeper"]["email"] == "keep@example.com" and rows[0]["shell"]["email"] == "shell@example.com"
        assert len((await c.get(f"{ADMIN}/identity-auto-merges", params={"days": 365}, headers=h)).json()) == 2
