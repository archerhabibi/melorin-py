"""R01: a customer sees and manages ONLY his own accounts / orders / payments / notifications IN THE STORE HE IS USING.

Whatever he bought in another store or bot (even with the very same login) is invisible there and cannot be opened,
refreshed, QR'd, or renewed from there; other customers' rows are never reachable. Everything is decided in Core
(``core.scope.StoreScope``), so website and bots cannot get it wrong. The last tests are guards that fail if someone adds
a customer route that is not store-scoped again."""

import datetime as dt
import types
import uuid

import pytest
from fastapi import Response

from _db import make_order, make_product, make_store, make_user, open_session
from melorin.core.deps import StoreContext
from melorin.core.errors import AppError
from melorin.core.scope import OwnerScope, StoreScope
from melorin.modules.notifications import router as notif_router
from melorin.kernel.models.notifications import Notification
from melorin.modules.orders import router as orders_router
from melorin.modules.payments import router as pay_router
from melorin.kernel.models.payments import Payment
from melorin.modules.vpn import renewal
from melorin.modules.vpn import router as vpn_router
from melorin.kernel.models.vpn import VpnAccount

NOW = dt.datetime.now(dt.UTC)


def _ctx(store, user):
    return StoreContext(store=store, user=user, membership=None)


async def _account(s, *, user, store, product, name):
    order = await make_order(s, user=user, store=store, product=product)
    a = VpnAccount(
        username=name,
        user_id=user.id,
        store_id=store.id,
        order_id=order.id,
        product_id=product.id,
        status="active",
        expires_at=NOW + dt.timedelta(days=5),
        traffic_limit_bytes=10 * 1024**3,
        traffic_used_bytes=0,
        subscription_url=f"https://sub.test/{name}",
        links=[],
    )
    s.add(a)
    await s.flush()
    return a, order


async def _world(s):
    """alice shops in BOTH stores with one login; bob only in store A."""
    alice, bob = await make_user(s), await make_user(s)
    store_a, store_b = (
        await make_store(s, kind="reseller", owner=await make_user(s)),
        await make_store(s, kind="reseller", owner=await make_user(s)),
    )
    p = await make_product(s)
    a_in_a, o_in_a = await _account(s, user=alice, store=store_a, product=p, name="alice_in_a")
    a_in_b, o_in_b = await _account(s, user=alice, store=store_b, product=p, name="alice_in_b")
    b_in_a, o_bob = await _account(s, user=bob, store=store_a, product=p, name="bob_in_a")
    pay = lambda u, st: Payment(
        user_id=u.id, store_id=st.id, purpose="wallet_topup", provider="manual_card", amount=1000, currency="IRT", status="pending"
    )  # noqa: E731
    pay_a, pay_b, pay_bob = pay(alice, store_a), pay(alice, store_b), pay(bob, store_a)
    note = lambda u, st, t: Notification(user_id=u.id, store_id=st.id, kind="vpn_account", title=t, body="x")  # noqa: E731
    s.add_all([pay_a, pay_b, pay_bob, note(alice, store_a, "in-a"), note(alice, store_b, "in-b"), note(bob, store_a, "bob-a")])
    await s.commit()
    return types.SimpleNamespace(**locals())


# ------------------------------------------------------------------ accounts
async def test_accounts_are_visible_only_in_the_store_they_were_bought_in():
    async with open_session() as s:
        w = await _world(s)
        in_a = await vpn_router.mine(_ctx(w.store_a, w.alice), s, Response(), q=None, state=None, limit=100, offset=0)
        in_b = await vpn_router.mine(_ctx(w.store_b, w.alice), s, Response(), q=None, state=None, limit=100, offset=0)
        assert [a.username for a in in_a] == ["alice_in_a"] and [a.username for a in in_b] == ["alice_in_b"]
        # search cannot cross the line either
        found = await vpn_router.mine(_ctx(w.store_a, w.alice), s, Response(), q="alice_in_b", state=None, limit=100, offset=0)
        assert found == []
        assert (await vpn_router.summary(_ctx(w.store_a, w.alice), s))["total"] == 1
        assert (await vpn_router.summary(_ctx(w.store_b, w.bob), s))["total"] == 0  # bob has nothing in B


async def test_single_account_endpoints_treat_other_store_and_other_user_as_missing():
    async with open_session() as s:
        w = await _world(s)
        for ctx, target in (
            (_ctx(w.store_a, w.alice), w.a_in_b),  # my own account, but bought in the OTHER store
            (_ctx(w.store_a, w.alice), w.b_in_a),  # another customer's account in the same store
            (_ctx(w.store_b, w.bob), w.a_in_a),  # bob in a store where he has nothing
        ):
            with pytest.raises(AppError, match="NOT_FOUND"):
                await vpn_router.get(target.id, ctx, s)
            with pytest.raises(AppError, match="NOT_FOUND"):
                await vpn_router.qr(target.id, ctx, s)
            with pytest.raises(AppError, match="NOT_FOUND"):
                await vpn_router.refresh(target.id, ctx, s, Response())
        assert (await vpn_router.get(w.a_in_a.id, _ctx(w.store_a, w.alice), s)).username == "alice_in_a"


# ------------------------------------------------------------------ renewal
async def test_an_account_of_another_store_can_be_neither_offered_nor_renewed():
    from melorin.modules.catalog import router as catalog_router

    async with open_session() as s:
        w = await _world(s)
        # the offer / quote lookups go through the same scope: 404
        with pytest.raises(AppError, match="NOT_FOUND"):
            await catalog_router.renewal_info(w.a_in_b.id, _ctx(w.store_a, w.alice), s)
        with pytest.raises(AppError, match="NOT_FOUND"):
            await catalog_router.renewal_info(w.b_in_a.id, _ctx(w.store_a, w.alice), s)
        # and the rule the order itself applies refuses it too (defence in depth)
        for acct, user, store in ((w.a_in_b, w.alice, w.store_a), (w.b_in_a, w.alice, w.store_a), (w.a_in_a, w.bob, w.store_a)):
            with pytest.raises(AppError, match="ACCOUNT_NOT_RENEWABLE"):
                await renewal.check_renewable(s, acct, user_id=user.id, store_id=store.id)
        assert (await renewal.check_renewable(s, w.a_in_a, user_id=w.alice.id, store_id=w.store_a.id)).ok


# ------------------------------------------------------------------ purchases / orders / payments / notifications
async def test_orders_are_listed_and_opened_only_in_their_own_store():
    async with open_session() as s:
        w = await _world(s)
        mine_a = await orders_router.list_orders(_ctx(w.store_a, w.alice), s)
        assert {o.id for o in mine_a} == {w.o_in_a.id}
        assert {o.id for o in await orders_router.list_orders(_ctx(w.store_b, w.alice), s)} == {w.o_in_b.id}
        assert (await orders_router.get_order(w.o_in_a.id, _ctx(w.store_a, w.alice), s)).id == w.o_in_a.id
        for ctx, oid in (
            (_ctx(w.store_a, w.alice), w.o_in_b.id),  # my own purchase made in the other store
            (_ctx(w.store_a, w.alice), w.o_bob.id),  # someone else's purchase in this store
            (_ctx(w.store_b, w.bob), w.o_in_a.id),
        ):
            with pytest.raises(AppError, match="NOT_FOUND"):
                await orders_router.get_order(oid, ctx, s)


async def test_payments_and_topups_are_store_scoped():
    async with open_session() as s:
        w = await _world(s)
        assert {p.id for p in await pay_router.my_payments(_ctx(w.store_a, w.alice), s)} == {w.pay_a.id}
        assert {p.id for p in await pay_router.my_payments(_ctx(w.store_b, w.alice), s)} == {w.pay_b.id}
        assert (await pay_router.get_payment(w.pay_a.id, _ctx(w.store_a, w.alice), s)).id == w.pay_a.id
        for ctx, pid in ((_ctx(w.store_a, w.alice), w.pay_b.id), (_ctx(w.store_a, w.alice), w.pay_bob.id)):
            with pytest.raises(AppError, match="NOT_FOUND"):
                await pay_router.get_payment(pid, ctx, s)
            upload = types.SimpleNamespace(read=None, content_type="image/png")
            with pytest.raises(AppError, match="NOT_FOUND"):  # refused before the file is even read
                await pay_router.upload_receipt(pid, ctx, s, upload)


async def test_notifications_are_store_scoped():
    async with open_session() as s:
        w = await _world(s)
        got = await notif_router.list_notifications(_ctx(w.store_a, w.alice), s, unread_only=False, limit=50)
        assert [n["title"] for n in got["items"]] == ["in-a"] and got["unread"] == 1
        other = (await notif_router.list_notifications(_ctx(w.store_b, w.alice), s, unread_only=False, limit=50))["items"][0]
        with pytest.raises(AppError, match="NOT_FOUND"):
            await notif_router.mark_read(uuid.UUID(str(other["id"])), _ctx(w.store_a, w.alice), s)
        await notif_router.read_all(_ctx(w.store_a, w.alice), s)  # marks only THIS store's notifications
        assert (await notif_router.list_notifications(_ctx(w.store_b, w.alice), s, unread_only=True, limit=50))["unread"] == 1
        assert (await notif_router.list_notifications(_ctx(w.store_a, w.bob), s, unread_only=True, limit=50))["unread"] == 1


# ------------------------------------------------------------------ the scope object itself
def test_scope_builds_both_conditions_and_rejects_foreign_rows():
    uid, sid = uuid.uuid4(), uuid.uuid4()
    scope = StoreScope(store_id=sid, user_id=uid)
    row = types.SimpleNamespace(user_id=uid, store_id=sid)
    assert scope.owns(row) and scope.require(row, "x") is row
    for bad in (
        types.SimpleNamespace(user_id=uuid.uuid4(), store_id=sid),
        types.SimpleNamespace(user_id=uid, store_id=uuid.uuid4()),
        None,
    ):
        assert not scope.owns(bad)
        with pytest.raises(AppError, match="NOT_FOUND"):
            scope.require(bad, "x")
    assert len(scope.where(VpnAccount)) == 2  # user AND store, always both
    owner = OwnerScope(store_id=sid, owner_id=uid)
    assert len(owner.where(VpnAccount)) == 1 and len(owner.own(VpnAccount)) == 2


# ------------------------------------------------------------------ guards
def _customer_routes():
    from melorin.app import app

    def walk(routes):  # include_router() wraps routers in current FastAPI; walk into them or the guard sees nothing
        for r in routes:
            if hasattr(r, "original_router"):
                yield from walk(r.original_router.routes)
            else:
                yield r

    for r in walk(app.routes):
        path = getattr(r, "path", "")
        if (
            any(seg in path for seg in ("/vpn-accounts", "/orders", "/payments", "/notifications"))
            and "/admin" not in path
            and not path.startswith("/reports")
        ):  # /reports/* are admin-only (t01 guard)
            yield path


def test_no_customer_route_exists_outside_a_store():
    """Every customer-facing accounts/orders/payments/notifications route is under /stores/{store_id}/ (the only global
    ones are server-to-server: the payment gateway callback and the store's bank-SMS webhook)."""
    seen = list(_customer_routes())
    assert len(seen) > 10, "the guard must actually see the customer routes"
    server_to_server = ("/payments/callbacks/{provider}", "/payments/bank-sms/{store_id}")  # token-authenticated, no user
    loose = [p for p in seen if "/stores/{store_id}/" not in p and not p.endswith(server_to_server)]
    assert loose == [], f"customer routes without a store scope: {loose}"


def test_customer_routers_never_use_a_bare_current_user_or_hand_written_ownership_checks():
    from pathlib import Path

    root = Path(__file__).parents[1] / "melorin" / "modules"
    for rel in ("vpn/router.py", "orders/router.py", "payments/router.py", "notifications/router.py"):
        src = (root / rel).read_text()
        assert "CurrentUser" not in src, f"{rel}: must resolve a StoreCtx, not a bare user"
        assert ".user_id !=" not in src and ".user_id ==" not in src, f"{rel}: use StoreScope, not hand-written checks"
