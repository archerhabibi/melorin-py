"""Automatic settlement of identity-link conflicts (docs/21): pure decision, shell detection, merge, sweep."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from _db import make_order, make_product, make_store, make_user, open_session
from melorin.core.config import get_settings
from melorin.core.db import utcnow
from melorin.domain.identity_auto_link import Account, Outcome, resolve
from melorin.kernel.models.identity import Identity, IdentityLinkReview, RefreshToken, TrustedDevice, User
from melorin.kernel.models.stores import StoreMembership
from melorin.kernel.models.system import AuditEvent, SecurityEvent
from melorin.kernel.models.wallet import Wallet
from melorin.modules.identity import auto_link


def acc(uid, *, shell=True, eligible=True, rank=0):
    return Account(uid, is_shell=shell, eligible=eligible, created_rank=rank)


# --- pure decision ---------------------------------------------------------------------------------------------------
def test_shell_is_folded_into_the_account_with_records():
    r = resolve(acc("new"), acc("old", shell=False))
    assert (r.outcome, r.keeper, r.shell) == (Outcome.MERGE, "old", "new")
    r = resolve(acc("old", shell=False), acc("new"))
    assert (r.outcome, r.keeper, r.shell) == (Outcome.MERGE, "old", "new")


def test_two_shells_keep_the_older_one():
    r = resolve(acc("a", rank=20), acc("b", rank=10))
    assert (r.keeper, r.shell) == ("b", "a")


def test_two_accounts_with_records_are_never_merged():
    assert resolve(acc("a", shell=False), acc("b", shell=False)).outcome is Outcome.MANUAL


def test_inactive_or_admin_or_identical_accounts_are_never_merged():
    assert resolve(acc("a", eligible=False), acc("b")).outcome is Outcome.MANUAL
    assert resolve(acc("a"), acc("b", eligible=False)).outcome is Outcome.MANUAL
    assert resolve(acc("a"), acc("a")).outcome is Outcome.MANUAL


# --- shell detection (schema driven) ---------------------------------------------------------------------------------
async def _review(s, source, candidate, *, reason="google_account_belongs_to_other_user", email="a@example.com"):
    r = IdentityLinkReview(email=email, source_user_id=source.id, candidate_user_ids=[str(candidate.id)], provider="google", reason=reason)
    s.add(r)
    await s.flush()
    return r


async def test_a_fresh_account_is_a_shell_and_every_kind_of_record_stops_it_being_one():
    async with open_session() as s:
        store = await make_store(s)
        u = await make_user(s)
        assert await auto_link.shell_blockers(s, u) == []
        s.add(StoreMembership(store_id=store.id, user_id=u.id))  # a membership alone is not a business record
        s.add(Wallet(user_id=u.id, store_id=store.id, balance=0))
        await s.flush()
        assert await auto_link.shell_blockers(s, u) == []
        await make_order(s, user=u, store=store, product=await make_product(s))
        assert "orders.user_id" in await auto_link.shell_blockers(s, u)
        w = await make_user(s)
        s.add(Wallet(user_id=w.id, store_id=store.id, balance=5))
        await s.flush()
        assert "wallets.balance" in await auto_link.shell_blockers(s, w)
        p = await make_user(s)
        p.password_hash = "x"
        assert "password" in await auto_link.shell_blockers(s, p)
        a = await make_user(s, super_admin=True)
        assert "admin" in await auto_link.shell_blockers(s, a)


# --- merge -----------------------------------------------------------------------------------------------------------
async def test_google_conflict_is_settled_by_folding_the_shell_into_the_real_account():
    async with open_session() as s:
        store = await make_store(s)
        keeper = await make_user(s)
        keeper.email = "a@example.com"
        await make_order(s, user=keeper, store=store, product=await make_product(s))
        shell = await make_user(s)
        s.add(Identity(user_id=shell.id, provider="telegram", subject="42", verified_at=utcnow()))
        s.add(RefreshToken(user_id=shell.id, token_hash="h" * 64, family_id=uuid.uuid4(), expires_at=utcnow()))
        s.add(
            TrustedDevice(
                user_id=shell.id, store_id=store.id, telegram_id=42, key_hash="k" * 64, last_seen_at=utcnow(), expires_at=utcnow()
            )
        )
        s.add(StoreMembership(store_id=store.id, user_id=shell.id))
        await s.flush()
        review = await _review(s, shell, keeper)
        res = await auto_link.try_auto_resolve(s, review)
        await s.commit()
        assert res is not None and res.keeper == str(keeper.id)
        assert (review.status, review.resolved_by, review.resolution_note) == ("linked", None, "auto:source_is_shell")
        idents = (await s.scalars(select(Identity).where(Identity.user_id == keeper.id))).all()
        assert {i.provider for i in idents} == {"telegram"}
        assert shell.is_active is False and shell.archived_at is not None
        assert (await s.scalar(select(RefreshToken.revoked_at).where(RefreshToken.user_id == shell.id))) is not None
        assert (await s.scalar(select(TrustedDevice.user_id))) == keeper.id
        assert (await s.scalar(select(StoreMembership.user_id))) == keeper.id
        acts = {e.action for e in (await s.scalars(select(AuditEvent))).all()}
        assert "identity.auto_merged" in acts
        assert (await s.scalar(select(SecurityEvent.kind).where(SecurityEvent.kind == "identity_auto_merged"))) is not None


async def test_email_moves_to_the_keeper_and_the_unique_email_is_released():
    async with open_session() as s:
        store = await make_store(s)
        keeper = await make_user(s)
        await make_order(s, user=keeper, store=store, product=await make_product(s))
        shell = await make_user(s)
        shell.email = "a@example.com"
        await s.flush()
        await auto_link.try_auto_resolve(s, await _review(s, shell, keeper, reason="email_field_conflict"))
        await s.commit()
        assert (keeper.email, shell.email) == ("a@example.com", None)


async def test_two_accounts_with_records_stay_in_the_admin_queue():
    async with open_session() as s:
        store = await make_store(s)
        a, b = await make_user(s), await make_user(s)
        for u in (a, b):
            await make_order(s, user=u, store=store, product=await make_product(s))
        review = await _review(s, a, b)
        assert await auto_link.try_auto_resolve(s, review) is None
        assert review.status == "open" and a.is_active and b.is_active


async def test_ambiguous_reviews_and_the_off_switch_are_left_alone(monkeypatch):
    async with open_session() as s:
        store = await make_store(s)
        keeper, other, shell = await make_user(s), await make_user(s), await make_user(s)
        await make_order(s, user=keeper, store=store, product=await make_product(s))
        many = IdentityLinkReview(
            email="a@example.com",
            source_user_id=shell.id,
            candidate_user_ids=[str(keeper.id), str(other.id)],
            provider="google",
            reason="multiple_verified_email_users",
        )
        s.add(many)
        await s.flush()
        assert await auto_link.try_auto_resolve(s, many) is None
        review = await _review(s, shell, keeper)
        monkeypatch.setattr(get_settings(), "identity_auto_link", False)
        assert await auto_link.try_auto_resolve(s, review) is None and review.status == "open"


async def test_sweep_settles_what_became_safe_and_reports_the_count():
    async with open_session() as s:
        store = await make_store(s)
        keeper = await make_user(s)
        await make_order(s, user=keeper, store=store, product=await make_product(s))
        shells = [await make_user(s) for _ in range(3)]
        for sh in shells:
            await _review(s, sh, keeper)
        await s.commit()
        assert await auto_link.sweep(s) == 3
        assert await auto_link.open_count(s) == 0
        assert await auto_link.sweep(s) == 0


# --- wired into the flows ----------------------------------------------------------------------------------------------
async def _email_code(s, email, code="123456"):
    from melorin.core.security import token_hash
    from melorin.kernel.models.identity import VerificationCode
    from datetime import timedelta

    s.add(
        VerificationCode(
            purpose="email_login", target=email, code_hash=token_hash(email + code), expires_at=utcnow() + timedelta(minutes=5)
        )
    )
    await s.flush()
    return code


async def test_attach_email_owned_by_an_empty_shell_moves_to_the_signed_in_account():
    from melorin.modules.identity import service

    async with open_session() as s:
        me, ghost = await make_user(s), await make_user(s)
        me.password_hash = "x"
        s.add(Identity(user_id=ghost.id, provider="email", subject="a@example.com", verified_at=utcnow()))
        await s.flush()
        await service.attach_email(s, me, "a@example.com", await _email_code(s, "a@example.com"))
        assert (await service.find_identity(s, "email", "a@example.com")).user_id == me.id
        assert ghost.is_active is False and await auto_link.open_count(s) == 0


async def test_attach_email_between_two_real_accounts_is_still_reported():
    from melorin.core.errors import AppError
    from melorin.modules.identity import service

    async with open_session() as s:
        me, other = await make_user(s), await make_user(s)
        me.password_hash = other.password_hash = "x"
        s.add(Identity(user_id=other.id, provider="email", subject="a@example.com", verified_at=utcnow()))
        await s.flush()
        with pytest.raises(AppError) as exc:
            await service.attach_email(s, me, "a@example.com", await _email_code(s, "a@example.com"))
        assert exc.value.code == "IDENTITY_LINK_REVIEW" and await auto_link.open_count(s) == 1


async def test_attach_email_from_an_empty_shell_session_ends_that_session_and_keeps_the_real_account():
    from melorin.core.errors import AppError
    from melorin.modules.identity import service

    async with open_session() as s:
        shell, real = await make_user(s), await make_user(s)
        real.password_hash = "x"
        s.add(Identity(user_id=real.id, provider="email", subject="a@example.com", verified_at=utcnow()))
        await s.flush()
        with pytest.raises(AppError) as exc:
            await service.attach_email(s, shell, "a@example.com", await _email_code(s, "a@example.com"))
        assert exc.value.code == "IDENTITY_MERGED" and shell.is_active is False and real.is_active is True


async def test_telegram_link_code_of_an_empty_shell_site_account_folds_into_the_telegram_account():
    from melorin.modules.identity import service
    from melorin.modules.identity.schemas import TelegramProfile

    async with open_session() as s:
        site, tg = await make_user(s), await make_user(s)
        tg.password_hash = "x"
        s.add(Identity(user_id=tg.id, provider="telegram", subject="77", verified_at=utcnow()))
        await s.flush()
        code = await service.create_link_code(s, site)
        user = await service.link_telegram(s, code, TelegramProfile(telegram_id=77, first_name="T"))
        assert user.id == tg.id and site.is_active is False


async def test_telegram_link_between_two_real_accounts_is_refused():
    from melorin.core.errors import AppError
    from melorin.modules.identity import service
    from melorin.modules.identity.schemas import TelegramProfile

    async with open_session() as s:
        site, tg = await make_user(s), await make_user(s)
        site.password_hash = tg.password_hash = "x"
        s.add(Identity(user_id=tg.id, provider="telegram", subject="77", verified_at=utcnow()))
        await s.flush()
        code = await service.create_link_code(s, site)
        with pytest.raises(AppError) as exc:
            await service.link_telegram(s, code, TelegramProfile(telegram_id=77, first_name="T"))
        assert exc.value.code == "IDENTITY_IN_USE"


async def test_worker_job_is_registered_and_delegates_to_the_sweep(monkeypatch):
    from pathlib import Path

    from melorin.worker import jobs

    arq = (Path(jobs.__file__).parent / "arq_app.py").read_text()
    assert "cron(identity_auto_link_job" in arq and "identity_auto_link_job," in arq

    async def fake(_s, limit=200):
        return 3

    monkeypatch.setattr(auto_link, "sweep", fake)
    assert await jobs.identity_auto_link_job() == 3
