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
        s.add(TrustedDevice(user_id=shell.id, store_id=store.id, telegram_id=42, key_hash="k" * 64, last_seen_at=utcnow(), expires_at=utcnow()))
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
