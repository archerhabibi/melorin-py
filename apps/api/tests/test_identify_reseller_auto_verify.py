"""Automatic identity verification of reseller applications (docs/21): domain proof (DNS / HTTP), bot re-check, schedule, gate."""

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
from melorin.kernel.models.stores import ResellerApplication
from melorin.kernel.models.system import AuditEvent, OutboxEvent
from melorin.modules.reseller import auto_verify, identity

TOKEN = "123456789:" + "A" * 35


def doh(value: str | None, *, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "cloudflare-dns.com" and request.url.params["name"].startswith("_melorin-verify.")
        answers = [{"type": 16, "data": f'"{value}"'}] if value else []
        return httpx.Response(status, json={"Answer": answers})

    return httpx.MockTransport(handler)


def site(content: str | None, *, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/.well-known/melorin-verify.txt"
        return httpx.Response(status, text=content or "")

    return httpx.MockTransport(handler)


async def make_app(s, *, domain="shop.example.com", bot=False, token=True, age_days=0):
    owner = await make_user(s)
    main = await make_store(s)
    a = ResellerApplication(
        user_id=owner.id,
        target_store_id=main.id,
        store_name="Shop",
        message="x" * 30,
        domain=domain,
        bot_token_enc=encrypt(TOKEN) if token else None,
        bot_key=f"tg:{uuid.uuid4().int % 10**9}" if token else None,
        bot_verified=bot,
        verify_next_at=utcnow(),
    )
    s.add(a)
    await s.flush()
    if age_days:
        a.created_at = utcnow() - dt.timedelta(days=age_days)
    await s.commit()
    return a


@pytest.fixture(autouse=True)
def telegram_up(monkeypatch):
    async def fake(token, **_):
        return "shopbot"

    monkeypatch.setattr(identity, "verify_bot", fake)


# --- pure -------------------------------------------------------------------------------------------------------------
def test_challenge_is_stable_per_application_and_domain_but_never_shared():
    a, b = uuid.uuid4(), uuid.uuid4()
    assert auto_verify.challenge_code(a, "x.com") == auto_verify.challenge_code(a, "x.com")
    assert auto_verify.challenge_code(a, "x.com") != auto_verify.challenge_code(b, "x.com")
    assert auto_verify.challenge_code(a, "x.com") != auto_verify.challenge_code(a, "y.com")
    assert len(auto_verify.challenge_code(a, "x.com")) == 32


@pytest.mark.parametrize(
    "ip,ok", [("8.8.8.8", True), ("10.0.0.5", False), ("127.0.0.1", False), ("169.254.169.254", False), ("::1", False), ("nope", False)]
)
def test_only_public_addresses_pass(ip, ok):
    assert auto_verify.is_public_ip(ip) is ok


# --- DNS / HTTP proofs ------------------------------------------------------------------------------------------------
async def test_dns_proof_verifies_domain_and_bot_and_alerts_admin():
    async with open_session() as s:
        await make_user(s, super_admin=True)
        await s.commit()
        a = await make_app(s)
        value = auto_verify.challenge_value(a.id, a.domain)
        await auto_verify.verify(s, a, dns_transport=doh(value))
        await s.commit()
        assert (a.domain_verified_at is not None, a.domain_method, a.bot_verified, a.verify_next_at, a.verify_error) == (
            True,
            "dns",
            True,
            None,
            None,
        )
        actions = set((await s.scalars(select(AuditEvent.action))).all())
        assert {"reseller.application_domain_verified", "reseller.application_auto_verified"} <= actions
        assert (
            await s.scalar(select(OutboxEvent.id).where(OutboxEvent.payload["kind"].as_string() == "admin_reseller_verified")) is not None
        )


async def test_http_file_is_the_fallback():
    async with open_session() as s:
        a = await make_app(s)
        value = auto_verify.challenge_value(a.id, a.domain)
        await auto_verify.verify(s, a, dns_transport=doh(None), transport=site(value + "\n"))
        assert (a.domain_method, a.domain_verified_at is not None) == ("http", True)


async def test_wrong_proof_is_recorded_and_retried_with_backoff():
    async with open_session() as s:
        a = await make_app(s)
        await auto_verify.verify(s, a, dns_transport=doh("melorin-verify=" + "0" * 32), transport=site("something else"))
        assert a.domain_verified_at is None and a.verify_error == "domain_proof_not_found" and a.bot_verified
        first = a.verify_next_at
        assert first > utcnow()
        await auto_verify.verify(s, a, dns_transport=doh(None), transport=site(None, status=404))
        assert a.verify_attempts == 2 and a.verify_next_at > first  # back-off grows


async def test_another_applications_code_does_not_count():
    async with open_session() as s:
        a, b = await make_app(s), await make_app(s, domain="other.example.com")
        stolen = auto_verify.challenge_value(b.id, b.domain)
        await auto_verify.verify(s, a, dns_transport=doh(stolen), transport=site(stolen))
        assert a.domain_verified_at is None


async def test_private_hosts_are_refused_without_a_request(monkeypatch):
    async def private(_):
        return False

    monkeypatch.setattr(auto_verify, "host_is_public", private)
    called = []
    monkeypatch.setattr(httpx.AsyncClient, "get", lambda *a, **k: called.append(1))
    assert await auto_verify.check_http("evil.example.com", "v") is False
    assert not called


async def test_http_proof_body_is_capped_and_matched_exactly():
    value = "melorin-verify=" + "a" * 32
    assert await auto_verify.check_http("shop.example.com", value, transport=site(value + "\n")) is True
    # an endless / oversized body is never buffered and never counts, even if it starts with the right value
    big = value + " " + "x" * (auto_verify.MAX_PROOF_BYTES * 8)
    assert await auto_verify.check_http("shop.example.com", value, transport=site(big)) is False
    assert await auto_verify.check_http("shop.example.com", value, transport=site("nope")) is False
    assert await auto_verify.check_http("shop.example.com", value, transport=site(value, status=301)) is False


# --- bot --------------------------------------------------------------------------------------------------------------
async def test_bot_is_rechecked_until_telegram_answers(monkeypatch):
    answers = iter([None, "shopbot"])

    async def flaky(token, **_):
        return next(answers)

    monkeypatch.setattr(identity, "verify_bot", flaky)
    async with open_session() as s:
        a = await make_app(s, domain=None)
        await auto_verify.verify(s, a)
        assert not a.bot_verified and a.verify_error == "telegram_unreachable" and a.verify_next_at is not None
        await auto_verify.verify(s, a)
        assert a.bot_verified and a.bot_username == "shopbot" and a.verify_next_at is None


async def test_rejected_token_is_reported_not_raised(monkeypatch):
    async def rejected(token, **_):
        raise AppError("BOT_TOKEN_REJECTED", "no", 422)

    monkeypatch.setattr(identity, "verify_bot", rejected)
    async with open_session() as s:
        a = await make_app(s, domain=None)
        await auto_verify.verify(s, a)
        assert a.verify_error == "BOT_TOKEN_REJECTED" and not a.bot_verified


# --- schedule / sweep / gate ------------------------------------------------------------------------------------------
async def test_window_expiry_stops_the_retries_and_restart_reopens_it():
    async with open_session() as s:
        a = await make_app(s, age_days=get_settings().reseller_verify_window_days + 1)
        await auto_verify.verify(s, a, dns_transport=doh(None), transport=site(None, status=404))
        assert a.verify_next_at is None
        auto_verify.restart(a)
        assert a.verify_attempts == 0 and a.verify_next_at is not None


async def test_sweep_only_takes_due_pending_applications_and_can_be_switched_off(monkeypatch):
    async with open_session() as s:
        due = await make_app(s, domain=None)
        later = await make_app(s, domain=None)
        later.verify_next_at = utcnow() + dt.timedelta(hours=1)
        done = await make_app(s, domain=None)
        done.status = "cancelled"
        await s.commit()
        assert await auto_verify.sweep(s) == 1
        assert due.bot_verified and not later.bot_verified and not done.bot_verified
        monkeypatch.setattr(get_settings(), "reseller_auto_verify", False)
        later.verify_next_at = utcnow()
        await s.commit()
        assert await auto_verify.sweep(s) == 0


async def test_proof_gate_follows_the_setting(monkeypatch):
    async with open_session() as s:
        a = await make_app(s)
        assert auto_verify.proof_required_blocks(a) is False
        monkeypatch.setattr(get_settings(), "reseller_require_domain_proof", True)
        assert auto_verify.proof_required_blocks(a) is True
        a.domain_verified_at = utcnow()
        assert auto_verify.proof_required_blocks(a) is False
        assert auto_verify.proof_required_blocks(await make_app(s, domain=None)) is False


def test_instructions_never_expose_the_token():
    a = ResellerApplication(id=uuid.uuid4(), domain="shop.example.com", bot_token_enc=encrypt(TOKEN))
    out = auto_verify.instructions(a)
    assert out["dns"]["name"] == "_melorin-verify.shop.example.com" and out["http"]["url"].endswith("/.well-known/melorin-verify.txt")
    assert TOKEN not in str(out) and auto_verify.instructions(ResellerApplication(domain=None)) is None
