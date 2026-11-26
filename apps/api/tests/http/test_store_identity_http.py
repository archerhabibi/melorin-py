"""ADR-R3 over HTTP: a store is called whatever its owner chooses, and customers see THAT name - never "Melorin" by assumption.

* the e-mail that carries a login code names the store whose website the customer is on;
* the operator can rename the main store after the installer named it (resellers keep their own edit route);
* the public store document - what the storefront renders - carries the new name straight away."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from _db import make_store
from _http import PASSWORD, add_user, api_client, totp_now
from melorin.kernel.models.stores import Store
from melorin.kernel.models.system import AuditEvent

API = "/api/v1"
AUTH = f"{API}/auth"
ADMIN = f"{API}/admin"


@pytest.fixture
def mailbox(monkeypatch):
    sent: list[dict] = []

    async def fake_send(to, subject, body):
        sent.append({"to": to, "subject": subject, "body": body})

    async def available():
        return True

    monkeypatch.setattr("melorin.modules.identity.service.send_email", fake_send)
    monkeypatch.setattr("melorin.modules.identity.service.email_available", available)
    return sent


async def _admin(c, maker, email="root@example.com"):
    await add_user(maker, email=email, admin=True, totp=True)
    r = await c.post(f"{AUTH}/password/login", json={"email": email, "password": PASSWORD, "totp_code": totp_now()})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _rename(maker, store_id, name):
    async with maker() as s:
        (await s.get(Store, store_id)).name = name
        await s.commit()


# --- the login-code e-mail names the store ----------------------------------------------------------------------------


async def test_login_code_email_is_sent_in_the_name_of_the_main_store(mailbox):
    async with api_client() as (c, maker, main):
        await _rename(maker, main.id, "Paris VPN")
        r = await c.post(f"{AUTH}/email/request-code", json={"email": "a@example.com"})
        assert r.status_code == 200, r.text
    assert [m["subject"] for m in mailbox] == ["کد ورود Paris VPN"]
    assert "melorin" not in mailbox[0]["subject"].casefold()


async def test_login_code_email_on_a_reseller_website_names_that_reseller(mailbox):
    async with api_client() as (c, maker, main):
        await _rename(maker, main.id, "Main Shop")
        async with maker() as s:
            reseller = await make_store(s, kind="reseller")
            reseller.name, reseller.domain, reseller.site_enabled = "Tehran Net", "tehran.example.com", True
            await s.commit()
        r = await c.post(f"{AUTH}/email/request-code", json={"email": "b@example.com"}, headers={"host": "tehran.example.com"})
        assert r.status_code == 200, r.text
        r = await c.post(f"{AUTH}/email/request-code", json={"email": "c@example.com"}, headers={"host": "localhost"})
        assert r.status_code == 200, r.text
    assert [m["subject"] for m in mailbox] == ["کد ورود Tehran Net", "کد ورود Main Shop"]


async def test_link_email_start_for_a_signed_in_customer_names_the_store(mailbox):
    async with api_client() as (c, maker, main):
        await _rename(maker, main.id, "Paris VPN")
        code = (await c.post(f"{AUTH}/email/request-code", json={"email": "me@example.com"})).json()["dev_code"]
        r = await c.post(f"{AUTH}/email/verify-code", json={"email": "me@example.com", "code": code})
        assert r.status_code == 200, r.text
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post(f"{API}/identity/link/email/start", headers=h, json={"email": "other@example.com"})
        assert r.status_code == 200, r.text
    assert [m["subject"] for m in mailbox] == ["کد ورود Paris VPN", "کد ورود Paris VPN"]


async def test_reauth_email_for_a_signed_in_customer_names_the_store(mailbox, monkeypatch):
    async def fake_send(to, subject, body):
        mailbox.append({"to": to, "subject": subject, "body": body})

    async def available():
        return True

    monkeypatch.setattr("melorin.modules.identity.account_linking.reauth.send_email", fake_send)
    monkeypatch.setattr("melorin.modules.identity.account_linking.reauth.email_available", available)
    async with api_client() as (c, maker, main):
        await _rename(maker, main.id, "Paris VPN")
        code = (await c.post(f"{AUTH}/email/request-code", json={"email": "me@example.com"})).json()["dev_code"]
        r = await c.post(f"{AUTH}/email/verify-code", json={"email": "me@example.com", "code": code})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        assert (await c.get(f"{API}/identity/reauth", headers=h)).json() == {"method": "email_code"}
        r = await c.post(f"{API}/identity/reauth/email/start", headers=h)
        assert r.status_code == 200, r.text
    assert mailbox[-1]["subject"] == "کد تأیید تغییر روش ورود Paris VPN"


# --- the operator renames the main store ------------------------------------------------------------------------------


async def test_admin_renames_the_main_store_and_the_public_document_follows():
    async with api_client() as (c, maker, main):
        h = await _admin(c, maker)
        r = await c.patch(f"{ADMIN}/stores/main", headers=h, json={"name": "  Paris   VPN "})
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "Paris VPN" and r.json()["slug"] == main.slug and r.json()["kind"] == "main"

        public = await c.get(f"{API}/stores/main")
        assert public.status_code == 200 and public.json()["name"] == "Paris VPN"
        listed = await c.get(f"{ADMIN}/stores", headers=h)
        assert [s["name"] for s in listed.json() if s["kind"] == "main"] == ["Paris VPN"]

        async with maker() as s:
            ev = await s.scalar(select(AuditEvent).where(AuditEvent.action == "store.renamed"))
            assert ev is not None and ev.store_id == main.id and ev.data["after"] == {"name": "Paris VPN"}


async def test_renaming_to_the_same_name_writes_no_audit_event():
    async with api_client() as (c, maker, main):
        h = await _admin(c, maker)
        await _rename(maker, main.id, "Same")
        assert (await c.patch(f"{ADMIN}/stores/main", headers=h, json={"name": "Same"})).status_code == 200
        async with maker() as s:
            assert (await s.scalar(select(AuditEvent).where(AuditEvent.action == "store.renamed"))) is None


@pytest.mark.parametrize("name", ["", "   ", "x" * 201, "a\x00b"])
async def test_renaming_the_main_store_refuses_unusable_names(name):
    async with api_client() as (c, maker, main):
        h = await _admin(c, maker)
        r = await c.patch(f"{ADMIN}/stores/main", headers=h, json={"name": name})
        assert r.status_code == 422, r.text
        async with maker() as s:
            assert (await s.get(Store, main.id)).name == main.name


async def test_only_an_admin_session_can_rename_the_main_store():
    async with api_client() as (c, maker, main):
        assert (await c.patch(f"{ADMIN}/stores/main", json={"name": "X"})).status_code in (401, 403)
        # a real customer session (e-mail code on the website) is not an admin
        code = (await c.post(f"{AUTH}/email/request-code", json={"email": "cust@example.com"})).json()["dev_code"]
        r = await c.post(f"{AUTH}/email/verify-code", json={"email": "cust@example.com", "code": code})
        assert r.status_code == 200, r.text
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        assert (await c.patch(f"{ADMIN}/stores/main", headers=h, json={"name": "X"})).status_code in (401, 403)
        async with maker() as s:
            assert (await s.get(Store, main.id)).name == main.name


async def test_rename_without_a_main_store_is_a_clean_404():
    async with api_client(with_main_store=False) as (c, maker, _):
        h = await _admin(c, maker)
        assert (await c.patch(f"{ADMIN}/stores/main", headers=h, json={"name": "X"})).status_code == 404
