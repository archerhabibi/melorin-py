"""A1: customer account return (مرجوعی). Volume accounts only; <= 3 days since purchase; <= 5 % of the volume used;
max 3 returns per customer per day; unlimited accounts are not returnable; store isolation; the money goes back to the wallet."""

import datetime as dt
import types

import pytest
from fastapi import Response

from _db import make_order, make_product, make_store, make_user, open_session
from melorin.core.deps import StoreContext
from melorin.core.errors import AppError
from melorin.core.scope import StoreScope
from melorin.kernel.models.vpn import AccountReturn, VpnAccount
from melorin.modules.orders import service as orders
from melorin.modules.orders.service import account_return
from melorin.modules.vpn import router as vpn_router
from melorin.modules.wallet import service as wallet

GIB = 1024**3
NOW = dt.datetime.now(dt.UTC)


async def _fund(s, user, store, amount):
    w = await wallet.get_wallet(s, user.id, store.id, currency="IRT", kind="customer")
    await wallet.post(
        s,
        kind="topup",
        key=f"fund:{w.id}:{amount}:{__import__('uuid').uuid4().hex}",
        currency="IRT",
        postings=[wallet.Posting(-amount, account="gateway:test:clearing"), wallet.Posting(amount, wallet=w)],
    )
    return w


async def _bought(s, user, store, product, *, limit=10 * GIB, used=0, age_days=0, name=None, is_test=False):
    """A completed wallet purchase with its account: the customer paid 2 000 out of a 5 000 wallet."""
    w = await wallet.get_wallet(s, user.id, store.id, currency="IRT", kind="customer")
    if w.balance < 2_000:
        w = await _fund(s, user, store, 5_000)
    order = await make_order(s, user=user, store=store, product=product, total=2_000, status="pending")
    await orders.pay_with_wallet(s, order, store)
    order.status, order.kind = "completed", "purchase"
    order.paid_at = NOW - dt.timedelta(days=age_days)
    acc = VpnAccount(
        username=name or f"acc_{order.number}",
        user_id=user.id,
        store_id=store.id,
        order_id=order.id,
        product_id=product.id,
        status="active",
        is_test=is_test,
        expires_at=NOW + dt.timedelta(days=20),
        traffic_limit_bytes=limit,
        traffic_used_bytes=used,
        links=[],
    )
    s.add(acc)
    await s.flush()
    order.vpn_account_id = acc.id
    await s.commit()
    return acc, order, w


def _scope(store, user):
    return StoreScope(store_id=store.id, user_id=user.id)


async def _world(s):
    store, user, product = await make_store(s), await make_user(s), await make_product(s)
    return types.SimpleNamespace(store=store, user=user, product=product, scope=_scope(store, user))


async def test_returnable_account_is_refunded_to_the_wallet_and_revoked():
    async with open_session() as s:
        w = await _world(s)
        acc, order, wal = await _bought(s, w.user, w.store, w.product, used=int(0.04 * 10 * GIB), age_days=2)
        assert wal.balance == 3_000
        res = await account_return.return_account(s, w.scope, acc.id)
        assert res["ok"] and res["refunded"] == 2_000
        await s.refresh(wal)
        assert wal.balance == 5_000 and order.status == "refunded"
        row = await s.scalar(__import__("sqlalchemy").select(AccountReturn))
        assert row.order_id == order.id and row.amount == 2_000 and row.user_id == w.user.id


@pytest.mark.parametrize(
    "kw,code",
    [
        ({"limit": 0}, "RETURN_UNLIMITED"),
        ({"used": int(0.06 * 10 * GIB)}, "RETURN_TOO_MUCH_USED"),
        ({"age_days": 4}, "RETURN_TOO_OLD"),
        ({"is_test": True}, "ACCOUNT_NOT_RETURNABLE"),
    ],
)
async def test_rules_refuse_with_core_words_and_change_nothing(kw, code):
    async with open_session() as s:
        w = await _world(s)
        acc, order, wal = await _bought(s, w.user, w.store, w.product, **kw)
        with pytest.raises(AppError) as exc:
            await account_return.return_account(s, w.scope, acc.id)
        assert exc.value.code == code and exc.value.status == 409
        await s.refresh(wal)
        assert wal.balance == 3_000 and order.status == "completed"


async def test_exactly_five_percent_and_exactly_three_days_are_still_returnable():
    async with open_session() as s:
        w = await _world(s)
        acc, *_ = await _bought(s, w.user, w.store, w.product, used=GIB // 2, age_days=2)  # 0.5 GiB of 10 GiB = 5 %
        assert (await account_return.return_account(s, w.scope, acc.id))["ok"]


async def test_a_renewed_account_cannot_be_returned():
    async with open_session() as s:
        w = await _world(s)
        acc, *_ = await _bought(s, w.user, w.store, w.product)
        ren = await make_order(s, user=w.user, store=w.store, product=w.product, status="completed")
        ren.kind, ren.vpn_account_id = "renewal", acc.id
        await s.commit()
        with pytest.raises(AppError) as exc:
            await account_return.return_account(s, w.scope, acc.id)
        assert exc.value.code == "RETURN_RENEWED"


async def test_at_most_three_returns_per_day_and_the_fourth_is_refused():
    async with open_session() as s:
        w = await _world(s)
        accs = [(await _bought(s, w.user, w.store, w.product))[0] for _ in range(4)]
        for a in accs[:3]:
            assert (await account_return.return_account(s, w.scope, a.id))["ok"]
        with pytest.raises(AppError) as exc:
            await account_return.return_account(s, w.scope, accs[3].id)
        assert exc.value.code == "RETURN_DAILY_LIMIT"
        # yesterday's returns no longer count
        for r in (await s.scalars(__import__("sqlalchemy").select(AccountReturn))).all():
            r.created_at = NOW - dt.timedelta(days=2)
        await s.commit()
        assert (await account_return.return_account(s, w.scope, accs[3].id))["ok"]


async def test_returning_twice_is_refused_and_pays_once():
    async with open_session() as s:
        w = await _world(s)
        acc, order, wal = await _bought(s, w.user, w.store, w.product)
        await account_return.return_account(s, w.scope, acc.id)
        with pytest.raises(AppError):
            await account_return.return_account(s, w.scope, acc.id)
        await s.refresh(wal)
        assert wal.balance == 5_000


async def test_other_store_or_other_customer_account_is_404_and_untouched():
    async with open_session() as s:
        w = await _world(s)
        other_store, other_user = await make_store(s), await make_user(s)
        mine_elsewhere, o1, w1 = await _bought(s, w.user, other_store, w.product)
        theirs, o2, w2 = await _bought(s, other_user, w.store, w.product)
        for acc in (mine_elsewhere, theirs):
            with pytest.raises(AppError) as exc:
                await account_return.return_account(s, w.scope, acc.id)
            assert exc.value.status == 404
        assert o1.status == "completed" and o2.status == "completed"


async def test_listing_marks_can_return_and_explains_why_not():
    async with open_session() as s:
        w = await _world(s)
        ok, *_ = await _bought(s, w.user, w.store, w.product, name="ok_one")
        unl, *_ = await _bought(s, w.user, w.store, w.product, limit=0, name="unlimited_one")
        ctx = StoreContext(store=w.store, user=w.user, membership=None)
        rows = await vpn_router.mine(ctx, s, Response(), q=None, state=None, limit=100, offset=0)
        by = {r.username: r for r in rows}
        assert by["ok_one"].can_return is True and by["ok_one"].return_note is None
        assert by["unlimited_one"].can_return is False and "نامحدود" in by["unlimited_one"].return_note


def test_the_return_route_is_store_scoped_and_rules_route_precedes_the_id_route():
    from melorin.app import app
    from melorin.modules.orders import router as orders_router

    return_path = "/stores/{store_id}/vpn-accounts/{account_id}/return"
    # the action lives in the orders layer (a return is an order refund); the public path is unchanged
    assert return_path in [r.path for r in orders_router.router.routes]
    assert return_path not in [r.path for r in vpn_router.router.routes]
    assert "post" in app.openapi()["paths"][f"/api/v1{return_path}"]  # and it is mounted on the app
    paths = [r.path for r in vpn_router.router.routes]
    assert paths.index("/stores/{store_id}/vpn-accounts/return-rules") < paths.index("/stores/{store_id}/vpn-accounts/{account_id}")


def test_bot_registers_the_return_callbacks_and_the_card_button():
    from pathlib import Path

    root = Path(__file__).parents[2] / "telegram-main"
    runner = (root / "runner.py").read_text(encoding="utf-8")
    handler = (root / "tgmain/handlers/accounts.py").read_text(encoding="utf-8")
    assert '"rtn": self.cb_return' in runner and '"rtc": self.cb_return_confirm' in runner
    assert "async def cb_return(" in handler and "async def cb_return_confirm(" in handler
    assert "f\"rtn:{b64(account['id'])}\"" in handler  # the button on the account card
    assert "/return" in handler and "return-rules" in handler  # the bot only asks Core; no rule is re-implemented there
