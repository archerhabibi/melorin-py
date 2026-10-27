"""Automatic approval of fully proven reseller applications and continuous re-verification of approved stores (docs/21)."""

from __future__ import annotations

import datetime as dt
import uuid

import httpx
import pytest
from sqlalchemy import select

from _db import make_store, make_user, open_session
from melorin.core.config import get_settings
from melorin.core.crypto import encrypt
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.kernel.models.stores import ResellerApplication, ResellerProfile, Store, StoreMembership
from melorin.kernel.models.system import AuditEvent, OutboxEvent
from melorin.modules.reseller import auto_approve, auto_verify, identity, recheck

TOKEN = "123456789:" + "A" * 35
BOT = {"name": "shopbot"}  # what the fake Telegram answers for getMe


def doh(value: str | None):
    def handler(request: httpx.Request) -> httpx.Response:
        answers = [{"type": 16, "data": f'"{value}"'}] if value else []
        return httpx.Response(200, json={"Answer": answers})

    return httpx.MockTransport(handler)


def site(content: str | None):
    return httpx.MockTransport(lambda request: httpx.Response(200 if content else 404, text=content or ""))


@pytest.fixture(autouse=True)
def telegram_up(monkeypatch):
    async def fake(token, **_):
        return BOT["name"]

    BOT["name"] = "shopbot"
    monkeypatch.setattr(identity, "verify_bot", fake)


@pytest.fixture
def auto_on(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "reseller_auto_approve", True)
    monkeypatch.setattr(s, "reseller_auto_approve_min_account_days", 7)
    monkeypatch.setattr(s, "reseller_auto_approve_debt_limit", 0)


async def make_app(s, *, owner_age_days=30, member=True, domain="shop.example.com", bot_username="shopbot"):
    owner = await make_user(s)
    owner.created_at = utcnow() - dt.timedelta(days=owner_age_days)
    main = await make_store(s)
    if member:
        s.add(StoreMembership(store_id=main.id, user_id=owner.id, role="customer"))
    a = ResellerApplication(
        user_id=owner.id,
        target_store_id=main.id,
        store_name="Shop",
        message="x" * 30,
        domain=domain,
        bot_token_enc=encrypt(TOKEN),
        bot_key=f"tg:{uuid.uuid4().int % 10**9}",
        bot_username=bot_username,
        verify_next_at=utcnow(),
    )
    s.add(a)
    await s.flush()
    await s.commit()
    return a


async def actions(s) -> set[str]:
    return set((await s.scalars(select(AuditEvent.action))).all())


# --- automatic approval -----------------------------------------------------------------------------------------------
async def test_fully_proven_application_approves_itself_when_enabled(auto_on):
    async with open_session() as s:
        await make_user(s, super_admin=True)
        a = await make_app(s)
        await auto_verify.verify(s, a, dns_transport=doh(auto_verify.challenge_value(a.id, a.domain)))
        await s.commit()
        assert (a.status, a.auto_approved, a.reviewed_by, a.bot_token_enc) == ("approved", True, None, None)
        store = await s.get(Store, a.store_id)
        assert store.kind == "reseller" and store.domain == a.domain and store.bot_token_enc  # secret moved to the store
        profile = await s.scalar(select(ResellerProfile).where(ResellerProfile.store_id == store.id))
        assert profile.debt_limit == 0 and a.recheck_next_at is not None
        assert "reseller.application_auto_approved" in await actions(s)
        kinds = set((await s.scalars(select(OutboxEvent.payload["kind"].as_string()))).all())
        assert "admin_reseller_auto_approved" in kinds and "admin_reseller_verified" not in kinds


async def test_switch_is_off_by_default(monkeypatch):
    monkeypatch.setattr(get_settings(), "reseller_auto_approve", False)
    async with open_session() as s:
        a = await make_app(s)
        await auto_verify.verify(s, a, dns_transport=doh(auto_verify.challenge_value(a.id, a.domain)))
        assert a.status == "pending" and a.store_id is None and not a.auto_approved


@pytest.mark.parametrize(
    "kwargs,reason",
    [({"owner_age_days": 1}, "account_too_new"), ({"member": False}, "membership_missing")],
)
async def test_guard_rails_leave_the_application_for_an_admin(auto_on, kwargs, reason):
    async with open_session() as s:
        a = await make_app(s, **kwargs)
        await auto_verify.verify(s, a, dns_transport=doh(auto_verify.challenge_value(a.id, a.domain)))
        assert a.status == "pending" and a.store_id is None
        assert reason in await auto_approve.blockers(s, a)


@pytest.mark.parametrize("flag", ["is_super_admin", "is_guest"])
async def test_admins_and_guests_never_auto_approve(auto_on, flag):
    async with open_session() as s:
        a = await make_app(s)
        setattr(await s.get(type(await make_user(s)), a.user_id), flag, True)
        await auto_verify.verify(s, a, dns_transport=doh(auto_verify.challenge_value(a.id, a.domain)))
        assert a.status == "pending" and "applicant_not_eligible" in await auto_approve.blockers(s, a)


async def test_unproven_domain_is_not_enough(auto_on):
    async with open_session() as s:
        a = await make_app(s)
        await auto_verify.verify(s, a, dns_transport=doh(None), transport=site(None))
        assert a.status == "pending" and "domain_unverified" in await auto_approve.blockers(s, a)


async def test_taken_identity_leaves_nothing_half_done(auto_on, monkeypatch):
    async def taken(*a, **k):
        raise AppError("DOMAIN_TAKEN", "x", 409)

    monkeypatch.setattr(identity, "ensure_identity_free", taken)
    async with open_session() as s:
        a = await make_app(s)
        await auto_verify.verify(s, a, dns_transport=doh(auto_verify.challenge_value(a.id, a.domain)))
        assert a.status == "pending" and a.store_id is None and a.bot_token_enc and not a.auto_approved
        assert await s.scalar(select(Store.id).where(Store.kind == "reseller")) is None


async def test_debt_limit_comes_from_the_setting(auto_on, monkeypatch):
    monkeypatch.setattr(get_settings(), "reseller_auto_approve_debt_limit", 500_000)
    async with open_session() as s:
        a = await make_app(s)
        await auto_verify.verify(s, a, dns_transport=doh(auto_verify.challenge_value(a.id, a.domain)))
        profile = await s.scalar(select(ResellerProfile).where(ResellerProfile.store_id == a.store_id))
        assert profile.debt_limit == 500_000


# --- continuous re-verification ---------------------------------------------------------------------------------------
async def approved_store(s, domain="shop.example.com"):
    """An approved, proven reseller whose re-check is due now."""
    BOT["name"] = "shopbot" if domain.startswith("shop") else "otherbot"
    a = await make_app(s, domain=domain, bot_username=BOT["name"])
    value = auto_verify.challenge_value(a.id, a.domain)
    s_ = get_settings()
    old = s_.reseller_auto_approve
    s_.reseller_auto_approve = True
    try:
        await auto_verify.verify(s, a, dns_transport=doh(value))
    finally:
        s_.reseller_auto_approve = old
    assert a.status == "approved"
    a.recheck_next_at = utcnow() - dt.timedelta(minutes=1)
    await s.commit()
    return a, value


async def test_healthy_store_stays_healthy_and_is_rescheduled():
    async with open_session() as s:
        a, value = await approved_store(s)
        assert await recheck.recheck_one(s, a, dns_transport=doh(value)) == "ok"
        assert a.recheck_failures == 0 and a.recheck_next_at > utcnow() + dt.timedelta(hours=23)


async def test_one_failed_round_only_warns_the_owner():
    async with open_session() as s:
        a, _ = await approved_store(s)
        assert await recheck.recheck_one(s, a, dns_transport=doh(None), transport=site(None)) == "warn"
        await s.commit()
        assert (a.recheck_failures, a.recheck_error, a.identity_lost_at) == (1, "domain_proof_missing", None)
        assert a.recheck_next_at < utcnow() + dt.timedelta(hours=7)
        kinds = set((await s.scalars(select(OutboxEvent.payload["kind"].as_string()))).all())
        assert "reseller_identity" in kinds and "admin_reseller_identity_lost" not in kinds


async def test_repeated_failure_alerts_admins_but_does_not_suspend_by_default(monkeypatch):
    monkeypatch.setattr(get_settings(), "reseller_recheck_suspend", False)
    async with open_session() as s:
        await make_user(s, super_admin=True)
        a, _ = await approved_store(s)
        for _ in range(3):
            result = await recheck.recheck_one(s, a, dns_transport=doh(None), transport=site(None))
        await s.commit()
        assert result == "lost" and a.identity_lost_at is not None
        assert (await s.get(Store, a.store_id)).status == "active"
        assert "reseller.identity_lost" in await actions(s)
        kinds = set((await s.scalars(select(OutboxEvent.payload["kind"].as_string()))).all())
        assert "admin_reseller_identity_lost" in kinds


async def test_suspension_is_opt_in_and_recovery_never_unsuspends(monkeypatch):
    monkeypatch.setattr(get_settings(), "reseller_recheck_suspend", True)
    async with open_session() as s:
        a, value = await approved_store(s)
        for _ in range(3):
            await recheck.recheck_one(s, a, dns_transport=doh(None), transport=site(None))
        store = await s.get(Store, a.store_id)
        assert store.status == "suspended"
        assert await recheck.recheck_one(s, a, dns_transport=doh(value)) == "ok"
        assert a.identity_lost_at is None and a.recheck_failures == 0
        assert store.status == "suspended"  # an admin decides
        assert "reseller.identity_recovered" in await actions(s)


async def test_http_proof_is_as_good_as_dns():
    async with open_session() as s:
        a, value = await approved_store(s)
        assert await recheck.recheck_one(s, a, dns_transport=doh(None), transport=site(value)) == "ok"


async def test_revoked_bot_token_counts_as_failure(monkeypatch):
    async def rejected(token, **_):
        raise AppError("BOT_TOKEN_REJECTED", "x", 422)

    async with open_session() as s:
        a, value = await approved_store(s)
        monkeypatch.setattr(identity, "verify_bot", rejected)
        assert await recheck.recheck_one(s, a, dns_transport=doh(value)) == "warn"
        assert a.recheck_error == "bot_rejected"


async def test_token_of_a_different_bot_is_a_failure(monkeypatch):
    async def other(token, **_):
        return "someone_elses_bot"

    async with open_session() as s:
        a, value = await approved_store(s)
        monkeypatch.setattr(identity, "verify_bot", other)
        assert await recheck.recheck_one(s, a, dns_transport=doh(value)) == "warn"
        assert a.recheck_error == "bot_changed"


async def test_telegram_outage_is_neutral(monkeypatch):
    async def down(token, **_):
        return None

    async with open_session() as s:
        a, value = await approved_store(s)
        monkeypatch.setattr(identity, "verify_bot", down)
        assert await recheck.recheck_one(s, a, dns_transport=doh(value)) == "unreachable"
        assert a.recheck_failures == 0 and a.recheck_next_at < utcnow() + dt.timedelta(hours=2)


async def test_sweep_only_takes_due_active_stores_and_respects_the_switch(monkeypatch):
    async with open_session() as s:
        a, value = await approved_store(s)
        b, _ = await approved_store(s, domain="other.example.com")
        BOT["name"] = "shopbot"
        (await s.get(Store, b.store_id)).status = "suspended"  # not re-checked while suspended
        await s.commit()
        monkeypatch.setattr(get_settings(), "reseller_recheck", False)
        assert await recheck.sweep(s, dns_transport=doh(value)) == 0
        monkeypatch.setattr(get_settings(), "reseller_recheck", True)
        assert await recheck.sweep(s, dns_transport=doh(value)) == 1
        assert a.recheck_next_at > utcnow()
