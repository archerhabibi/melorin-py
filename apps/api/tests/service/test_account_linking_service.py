# Linking + consolidation against real tables (docs/25).
import uuid

import pytest
from sqlalchemy import select

from _db import make_store, make_user, open_session
from melorin.core.errors import AppError
from melorin.domain.account_linking import Evidence
from melorin.kernel.models.identity import Identity
from melorin.kernel.models.person import AccountLinkAudit, WalletTransfer
from melorin.kernel.models.wallet import LedgerEntry, Wallet
from melorin.modules.identity.account_linking import consolidation, linking, queries, telegram
from melorin.modules.wallet import service as wallets


@pytest.fixture(autouse=True)
def _manual_consolidation(monkeypatch):
    """These tests exercise the manual-approval path (the exception path); automatic mode is the default and is tested separately."""
    from melorin.core.config import get_settings

    monkeypatch.setattr(get_settings(), "identity_consolidation_auto_approve", False)


async def _attach(s, user, provider, subject, ev=Evidence.OAUTH_GOOGLE):
    return await linking.attach_identity(s, user, provider, subject, evidence=ev)


async def _err(coro):
    with pytest.raises(AppError) as e:
        await coro
    return e.value


async def _linked_pair(s):
    a, b = await make_user(s), await make_user(s)
    await _attach(s, a, "google", "ga")
    await _attach(s, b, "google", "gb")
    err = await _err(_attach(s, a, "google", "gb"))
    await linking.confirm_person_link(s, a, uuid.UUID(err.details["operation_id"]))
    await s.refresh(b)
    return a, b, err


async def test_multiple_google_one_telegram_and_conflict_is_never_silent():
    async with open_session() as s:
        a, b = await make_user(s), await make_user(s)
        assert await _attach(s, a, "google", "g1") == "attached"
        assert await _attach(s, a, "google", "g2") == "attached"
        assert await _attach(s, a, "telegram", "100", Evidence.TELEGRAM_BOT) == "attached"
        assert (await _err(_attach(s, a, "telegram", "101", Evidence.TELEGRAM_BOT))).code == "TELEGRAM_ALREADY_LINKED"
        await _attach(s, b, "google", "g3")
        err = await _err(_attach(s, a, "google", "g3"))
        assert err.code == "IDENTITY_IN_USE" and err.details["operation_id"]
        g3 = await s.scalar(select(Identity).where(Identity.subject == "g3"))
        assert g3.person_id == b.person_id


async def test_confirmed_link_moves_accounts_and_unlink_keeps_one_way_in():
    async with open_session() as s:
        a, b, err = await _linked_pair(s)
        assert b.person_id == a.person_id
        again = await linking.confirm_person_link(s, a, uuid.UUID(err.details["operation_id"]))
        assert again["status"] == "confirmed"
        idents = (await s.scalars(select(Identity).where(Identity.person_id == a.person_id))).all()
        assert len(idents) == 2
        await linking.unlink_identity(s, a, idents[0].id)
        assert (await _err(linking.unlink_identity(s, a, idents[1].id))).code == "LAST_LOGIN_METHOD"
        assert await s.scalar(select(AccountLinkAudit.id).where(AccountLinkAudit.action == "persons_linked"))


async def test_telegram_token_is_single_use_and_replace_revokes_old():
    async with open_session() as s:
        a = await make_user(s)
        await _attach(s, a, "telegram", "100", Evidence.TELEGRAM_BOT)
        op, raw = await telegram.start(s, a)
        assert op.operation_type == "replace"
        await telegram.begin_completion(s, await telegram.find_operation(s, raw))
        await linking.attach_identity(s, a, "telegram", "200", evidence=Evidence.TELEGRAM_BOT, replace=True, operation=op)
        old = await s.scalar(select(Identity).where(Identity.subject == "100"))
        assert old.status == "revoked"
        assert await telegram.find_operation(s, raw) is None


async def test_consolidation_moves_balance_through_ledger_once():
    async with open_session() as s:
        store = await make_store(s)
        a, b, _ = await _linked_pair(s)
        wb = await wallets.get_wallet(s, b.id, store.id)
        pay = [wallets.Posting(500, wallet=wb), wallets.Posting(-500, account="gateway:x:clearing", min_balance=None)]
        await wallets.post(s, kind="topup", key="t1", currency="IRT", postings=pay)
        op = await consolidation.request(s, a, key="k-12345678")
        assert op.status == "pending_approval"
        assert (await consolidation.request(s, a, key="k-12345678")).id == op.id
        done = await consolidation.execute(s, op, approver_id=None, actor_type="system")
        assert done.status == "completed"
        await consolidation.execute(s, done, approver_id=None)
        central = await wallets.get_wallet(s, a.id, store.id, route=False)
        assert central.balance == 500 and wb.balance == 0 and wb.status == "consolidated"
        assert (await wallets.get_wallet(s, b.id, store.id)).id == central.id
        assert len((await s.scalars(select(WalletTransfer))).all()) == 1
        assert len((await s.scalars(select(LedgerEntry).where(LedgerEntry.wallet_id == wb.id))).all()) == 2
        assert (await queries.person_detail(s, a.person_id))["consolidations"][0]["status"] == "completed"


async def test_reversals_after_consolidation_use_the_active_wallet():
    async with open_session() as s:
        store = await make_store(s)
        a, b, _ = await _linked_pair(s)
        source = await wallets.get_wallet(s, b.id, store.id)
        topup, _ = await wallets.post(
            s,
            kind="topup",
            key="old-topup",
            currency="IRT",
            postings=[wallets.Posting(500, wallet=source), wallets.Posting(-500, account="gateway:clearing")],
        )
        purchase, _ = await wallets.post(
            s,
            kind="purchase",
            key="old-purchase",
            currency="IRT",
            postings=[wallets.Posting(-200, wallet=source, min_balance=0), wallets.Posting(200, account="store:revenue")],
        )
        await s.commit()
        op = await consolidation.request(s, a, key="reversal-consolidation")
        await consolidation.execute(s, op, approver_id=None, actor_type="system")
        central = await wallets.get_wallet(s, a.id, store.id, route=False)
        assert source.status == "consolidated" and source.balance == 0 and central.balance == 300

        refund = await wallets.reverse(s, purchase, key="old-purchase-refund", kind="refund")
        await s.commit()
        assert source.balance == 0 and central.balance == 500
        assert (await wallets.reverse(s, purchase, key="old-purchase-refund", kind="refund")).id == refund.id
        await wallets.reverse(s, topup, key="old-topup-refund", kind="refund")
        await s.commit()
        assert source.balance == 0 and central.balance == 0
        entries = (await s.scalars(select(LedgerEntry))).all()
        assert sum(entry.amount for entry in entries) == 0


async def test_reversal_follows_multiple_consolidations():
    async with open_session() as s:
        store = await make_store(s)
        users = [await make_user(s) for _ in range(3)]
        for user in users[1:]:
            user.person_id = users[0].person_id
        source, middle, active = [await wallets.get_wallet(s, user.id, store.id) for user in users]
        await wallets.post(
            s,
            kind="topup",
            key="chain-topup",
            currency="IRT",
            postings=[wallets.Posting(500, wallet=source), wallets.Posting(-500, account="gateway:clearing")],
        )
        purchase, _ = await wallets.post(
            s,
            kind="purchase",
            key="chain-purchase",
            currency="IRT",
            postings=[wallets.Posting(-200, wallet=source), wallets.Posting(200, account="store:revenue")],
        )
        for index, (old, new) in enumerate(((source, middle), (middle, active))):
            await wallets.post(
                s,
                kind="consolidation_transfer",
                key=f"chain-move-{index}",
                currency="IRT",
                postings=[wallets.Posting(-300, wallet=old), wallets.Posting(300, wallet=new)],
            )
            old.status, old.consolidated_into_id = "consolidated", new.id
        await s.commit()
        await wallets.reverse(s, purchase, key="chain-refund", kind="refund")
        await s.commit()
        assert (source.balance, middle.balance, active.balance) == (0, 0, 500)


@pytest.mark.parametrize("bad_route", ["cycle", "other_store", "other_currency", "other_person", "missing"])
async def test_reversal_rejects_an_invalid_consolidation_route(bad_route):
    async with open_session() as s:
        store, other_store = await make_store(s), await make_store(s)
        user = await make_user(s)
        source = await wallets.get_wallet(s, user.id, store.id)
        topup, _ = await wallets.post(
            s,
            kind="topup",
            key="bad-route-topup",
            currency="IRT",
            postings=[wallets.Posting(500, wallet=source), wallets.Posting(-500, account="gateway:clearing")],
        )
        other_user = await make_user(s) if bad_route == "other_person" else user
        other = await wallets.get_wallet(
            s,
            other_user.id,
            store.id if bad_route in ("other_currency", "other_person") else other_store.id,
            currency="USD" if bad_route == "other_currency" else "IRT",
        )
        source.status = "consolidated"
        source.consolidated_into_id = None if bad_route == "missing" else source.id if bad_route == "cycle" else other.id
        await s.commit()
        with pytest.raises(AppError) as error:
            await wallets.reverse(s, topup, key="bad-route-refund", kind="refund")
        assert error.value.code == "WALLET_ROUTE_INVALID"
        assert source.balance == 500 and other.balance == 0
        assert await wallets.find_reversal(s, topup) is None


async def test_debt_blocks_consolidation_but_keeps_accounts_linked():
    async with open_session() as s:
        store = await make_store(s)
        a, b, _ = await _linked_pair(s)
        wb = await wallets.get_wallet(s, b.id, store.id)
        wb.balance = -50
        op = await consolidation.request(s, a, key="k-debt-1234")
        assert op.status == "blocked"
        assert (await _err(consolidation.execute(s, op, approver_id=None))).code == "CONSOLIDATION_BLOCKED"
        assert b.person_id == a.person_id and (await s.get(Wallet, wb.id)).balance == -50


async def test_consolidation_keeps_stores_isolated_and_conserves_total():
    async with open_session() as s:
        s1, s2 = await make_store(s), await make_store(s)
        a, b, _ = await _linked_pair(s)
        for store, amount, key in ((s1, 300, "iso-1"), (s2, 700, "iso-2")):
            wb = await wallets.get_wallet(s, b.id, store.id)
            pay = [wallets.Posting(amount, wallet=wb), wallets.Posting(-amount, account="gateway:x:clearing", min_balance=None)]
            await wallets.post(s, kind="topup", key=key, currency="IRT", postings=pay)
        op = await consolidation.request(s, a, key="k-iso-12345")
        await consolidation.execute(s, op, approver_id=None, actor_type="system")
        c1 = await wallets.get_wallet(s, a.id, s1.id, route=False)
        c2 = await wallets.get_wallet(s, a.id, s2.id, route=False)
        assert (c1.balance, c2.balance) == (300, 700)  # per-store isolation is preserved
        moved = (await s.scalars(select(WalletTransfer))).all()
        assert sum(t.amount for t in moved) == 1000


async def test_admin_account_is_never_consolidated():
    async with open_session() as s:
        a, b, _ = await _linked_pair(s)
        b.is_super_admin = True
        assert (await _err(consolidation.request(s, a, key="k-admin-1234"))).code == "ADMIN_ACCOUNT"


async def test_auto_flow_consolidates_after_link_without_admin(monkeypatch):
    """Proof of ownership + consent -> preflight -> consolidation in one flow; no manual admin step on the clean path."""
    from melorin.core.config import get_settings

    monkeypatch.setattr(get_settings(), "identity_consolidation_auto_approve", True)
    async with open_session() as s:
        store = await make_store(s)
        a, b, _ = await _linked_pair(s)
        wb = await wallets.get_wallet(s, b.id, store.id)
        pay = [wallets.Posting(700, wallet=wb), wallets.Posting(-700, account="gateway:x:clearing", min_balance=None)]
        await wallets.post(s, kind="topup", key="t-auto", currency="IRT", postings=pay)
        res = await linking._continue_with_consolidation(s, a, uuid.uuid4())
        assert res["status"] == "completed"
        assert (await wallets.get_wallet(s, b.id, store.id)).balance == 700  # routed to the central wallet
        again = await linking._continue_with_consolidation(s, a, uuid.uuid4())
        assert again["status"] in {"completed", "skipped"}
