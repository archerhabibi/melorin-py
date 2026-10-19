"""End-to-end purchase in a reseller store through ``orders.create_order`` - the exact call the Telegram bot and the
store website make (SQLite, no HTTP). Covers the happy path and the debt-limit stop, which must be a clean 409 the
bot can show, never a 500 (a 500 is treated as transient by the bots and the purchase silently never completes)."""

import types

import pytest
from sqlalchemy import select

from _db import make_product, make_store, make_user, open_session
import itertools

from melorin.core import codes
from melorin.core.deps import StoreContext
from melorin.core.errors import AppError
from melorin.modules.catalog.models import StoreProduct
from melorin.modules.orders import service as orders
from melorin.modules.orders.models import Order
from melorin.modules.stores.models import ResellerProfile, StoreMembership
from melorin.modules.system.models import OutboxEvent
from melorin.modules.vpn.bundles import Bundle, BundleMember, BundleProduct
from melorin.modules.vpn.models import Panel, Server
from melorin.modules.wallet import service as wallet
from melorin.modules.wallet.models import LedgerTransaction, Wallet


@pytest.fixture(autouse=True)
def _sqlite_order_numbers(monkeypatch):
    """SQLite has no ``nextval``; everything else in ``create_order`` runs for real."""
    counter = itertools.count(1)

    async def next_code(session, sequence):
        return f"T{next(counter):05d}"

    monkeypatch.setattr(codes, "next_code", next_code)


async def _fund(s, user, store, amount, *, kind="customer", currency="IRT"):
    w = await wallet.get_wallet(s, user.id, store.id, currency=currency, kind=kind)
    await wallet.post(
        s,
        kind="topup",
        key=f"fund:{w.id}:{amount}",
        currency=currency,
        postings=[wallet.Posting(-amount, account="gateway:test:clearing"), wallet.Posting(amount, wallet=w)],
    )
    return w


async def _setup(s, *, debt_limit, customer_funds=100_000, credit=0):
    main = await make_store(s)
    owner, customer = await make_user(s), await make_user(s)
    reseller = await make_store(s, kind="reseller", owner=owner)
    s.add(ResellerProfile(store_id=reseller.id, user_id=owner.id, debt_limit=debt_limit, sales_enabled=True))
    product = await make_product(s, price=30_000)
    product.reseller_price = 20_000
    bundle = Bundle(name="B", kind_label="direct", selection_mode="automatic", naming_mode="automatic")
    s.add(bundle)
    panel = Panel(name="p1", kind="mock", base_url="http://x", is_enabled=True, health_status="healthy")
    s.add(panel)
    await s.flush()
    s.add_all([BundleMember(bundle_id=bundle.id, panel_id=panel.id, sort=0), Server(name="srv", panel_id=panel.id)])
    s.add(BundleProduct(bundle_id=bundle.id, product_id=product.id, is_listed=True, sort=0))
    s.add(StoreProduct(store_id=reseller.id, product_id=product.id, is_enabled=True, is_listed=True, customer_price=25_000))
    membership = StoreMembership(store_id=reseller.id, user_id=customer.id, role="customer", status="active")
    s.add(membership)
    await s.flush()
    cust_w = await _fund(s, customer, reseller, customer_funds)
    if credit:
        await _fund(s, owner, main, credit)
    await s.commit()
    ctx = StoreContext(store=reseller, user=customer, membership=membership)
    return types.SimpleNamespace(
        main=main, owner=owner, customer=customer, reseller=reseller, product=product, ctx=ctx, cust_w=cust_w, cust_w_id=cust_w.id
    )


async def test_reseller_purchase_completes_and_books_cost_as_debt():
    async with open_session() as s:
        t = await _setup(s, debt_limit=100_000)
        order = await orders.create_order(s, t.ctx, product_id=t.product.id, idempotency_key="key-reseller-1", channel="telegram")
        assert order.status == "paid" and order.total == 25_000 and order.reseller_cost == 20_000
        assert t.cust_w.balance == 75_000
        credit = await wallet.get_wallet(s, t.owner.id, t.main.id)
        assert credit.balance == -20_000
        topics = (await s.scalars(select(OutboxEvent.topic))).all()
        assert "order.paid" in topics


async def _assert_no_money_moved(s, t, balance):
    """Checked with fresh queries: after a rollback ORM instances are expired and cannot be lazy-loaded in async code.
    (A row inserted inside a SAVEPOINT survives ``rollback()`` on SQLite's pysqlite driver, so row absence is a
    PostgreSQL-only property; what must hold everywhere is that nothing was charged or marked paid.)"""
    assert await s.scalar(select(Wallet.balance).where(Wallet.id == t.cust_w_id)) == balance
    assert await s.scalar(select(LedgerTransaction.id).where(LedgerTransaction.kind.in_(["purchase", "reseller_cost"]))) is None
    assert await s.scalar(select(Order.id).where(Order.status == "paid")) is None


async def test_reseller_purchase_with_zero_debt_limit_and_no_credit_is_a_clean_409():
    async with open_session() as s:
        t = await _setup(s, debt_limit=0)
        with pytest.raises(AppError) as exc:
            await orders.create_order(s, t.ctx, product_id=t.product.id, idempotency_key="key-reseller-2", channel="telegram")
        assert exc.value.code == "RESELLER_DEBT_LIMIT" and exc.value.status == 409
        await _assert_no_money_moved(s, t, 100_000)


async def test_reseller_purchase_at_the_debt_limit_is_a_clean_409_and_notifies_once():
    async with open_session() as s:
        t = await _setup(s, debt_limit=10_000)
        with pytest.raises(AppError) as exc:
            await orders.create_order(s, t.ctx, product_id=t.product.id, idempotency_key="key-reseller-3", channel="telegram")
        assert exc.value.code == "RESELLER_DEBT_LIMIT" and exc.value.status == 409
        topics = (await s.scalars(select(OutboxEvent.topic))).all()
        assert topics.count("reseller.debt") == 1  # the owner is told sales stopped
        await _assert_no_money_moved(s, t, 100_000)


async def test_reseller_purchase_is_allowed_once_credit_covers_the_cost():
    """Same reseller with debt_limit 0: sales work as soon as the credit wallet holds at least the cost."""
    async with open_session() as s:
        t = await _setup(s, debt_limit=0, credit=20_000)
        order = await orders.create_order(s, t.ctx, product_id=t.product.id, idempotency_key="key-reseller-4", channel="telegram")
        assert order.status == "paid"
        credit = await wallet.get_wallet(s, t.owner.id, t.main.id)
        assert credit.balance == 0


async def test_reseller_reuses_the_existing_main_wallet_and_only_adds_the_debt_limit():
    """A customer with 100k in Main becomes a reseller: the SAME wallet pays the reseller cost (20k) and is untouched by
    the stores' own customer wallets; the owner's own Main purchases still cannot overdraw it."""
    async with open_session() as s:
        t = await _setup(s, debt_limit=150_000, customer_funds=100_000, credit=100_000)
        main_w = await wallet.get_wallet(s, t.owner.id, t.main.id)
        before_ids = set((await s.scalars(select(Wallet.id))).all())
        order = await orders.create_order(s, t.ctx, product_id=t.product.id, idempotency_key="key-reseller-reuse", channel="telegram")
        assert order.status == "paid"
        again = await wallet.get_wallet(s, t.owner.id, t.main.id)
        assert again.id == main_w.id and again.balance == 80_000
        assert set((await s.scalars(select(Wallet.id))).all()) == before_ids  # no extra wallet was created
        # the owner's wallet inside his own store is a different, independent customer wallet
        own_store_w = await wallet.get_wallet(s, t.owner.id, t.reseller.id)
        assert own_store_w.id != main_w.id and own_store_w.balance == 0


async def test_reseller_cost_may_take_the_main_wallet_into_debt_but_not_the_owners_own_purchases():
    async with open_session() as s:
        t = await _setup(s, debt_limit=30_000, customer_funds=100_000, credit=5_000)
        order = await orders.create_order(s, t.ctx, product_id=t.product.id, idempotency_key="key-reseller-debt", channel="telegram")
        assert order.status == "paid"
        main_w = await wallet.get_wallet(s, t.owner.id, t.main.id)
        assert main_w.balance == -15_000  # 5k - 20k, inside the 30k limit
        # an ordinary debit of the same wallet (owner shopping in Main) keeps the strict min_balance=0 rule
        with pytest.raises(AppError):
            await wallet.post(
                s,
                kind="purchase",
                key="owner-own-purchase",
                currency="IRT",
                postings=[wallet.Posting(-1_000, wallet=main_w, min_balance=0), wallet.Posting(1_000, account="store:x:revenue")],
            )
