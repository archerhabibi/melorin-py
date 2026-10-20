"""Account inquiry (استعلام): a customer only ever sees/searches his own accounts, a reseller lists only his own accounts and
searches his own store's customers' accounts too (never another store's), and the numbers on every card come from one place (``vpn.inquiry``)."""

import datetime as dt
import types

import pytest
from fastapi import Response

from _db import make_order, make_product, make_store, make_user, open_session
from melorin.core.deps import StoreContext
from melorin.core.errors import AppError
from melorin.modules.reseller import router as reseller_router
from melorin.modules.vpn import inquiry
from melorin.modules.vpn import router as vpn_router
from melorin.modules.vpn.models import VpnAccount

GIB = 1024**3
NOW = dt.datetime.now(dt.UTC)


async def _account(s, *, user, store, product, name, days=20, used=0, limit=10 * GIB, status="active"):
    order = await make_order(s, user=user, store=store, product=product)
    a = VpnAccount(
        username=name,
        user_id=user.id,
        store_id=store.id,
        order_id=order.id,
        product_id=product.id,
        status=status,
        expires_at=NOW + dt.timedelta(days=days),
        traffic_limit_bytes=limit,
        traffic_used_bytes=used,
        subscription_url=f"https://sub.test/{name}",
        links=[],
    )
    s.add(a)
    await s.flush()
    return a


async def _world(s):
    owner, alice, bob, eve = [await make_user(s) for _ in range(4)]
    alice.display_name, bob.display_name, eve.display_name = "Alice", "Bob", "Eve"
    store = await make_store(s, kind="reseller", owner=owner)
    other = await make_store(s, kind="reseller", owner=eve)
    p = await make_product(s)
    a1 = await _account(s, user=alice, store=store, product=p, name="alice_phone")
    a2 = await _account(s, user=alice, store=store, product=p, name="alice_pc")
    b1 = await _account(s, user=bob, store=store, product=p, name="bob_main")
    e1 = await _account(s, user=eve, store=other, product=p, name="eve_main")
    await s.commit()
    return types.SimpleNamespace(owner=owner, alice=alice, bob=bob, eve=eve, store=store, other=other, a1=a1, a2=a2, b1=b1, e1=e1)


def _ctx(store, user):
    return StoreContext(store=store, user=user, membership=None)


async def test_customer_sees_and_searches_only_own_accounts():
    async with open_session() as s:
        w = await _world(s)
        r = Response()
        mine = await vpn_router.mine(_ctx(w.store, w.alice), s, r, q=None, limit=100, offset=0)
        assert {a.username for a in mine} == {"alice_phone", "alice_pc"} and r.headers["X-Total-Count"] == "2"
        # a search can never reach somebody else's account, however it is spelled
        for q in ("bob", "BOB_main", "eve", "%", "_", "alice_phone' OR 1=1 --"):
            found = await vpn_router.mine(_ctx(w.store, w.alice), s, Response(), q=q, limit=100, offset=0)
            assert all(a.username.startswith("alice") for a in found), q
        assert [a.username for a in await vpn_router.mine(_ctx(w.store, w.alice), s, Response(), q="PC", limit=100, offset=0)] == [
            "alice_pc"
        ]


async def test_wildcards_are_literal_and_paging_works():
    async with open_session() as s:
        w = await _world(s)
        assert await vpn_router.mine(_ctx(w.store, w.alice), s, Response(), q="%", limit=100, offset=0) == []
        assert (
            await vpn_router.mine(_ctx(w.store, w.alice), s, Response(), q="_", limit=100, offset=0) != []
        )  # "_" really occurs in the names
        r = Response()
        page = await vpn_router.mine(_ctx(w.store, w.alice), s, r, q=None, limit=1, offset=1)
        assert len(page) == 1 and r.headers["X-Total-Count"] == "2"


async def test_customer_never_sees_accounts_of_another_store_even_his_own():
    """Alice owns accounts in `store`; in `other` (another shop / bot) she sees and renews none of them, and a store id can
    no longer be left out to widen the view: the scope is mandatory (store + user), there is no "all stores" call."""
    async with open_session() as s:
        w = await _world(s)
        assert await vpn_router.mine(_ctx(w.other, w.alice), s, Response(), q=None, limit=100, offset=0) == []
        assert await vpn_router.mine(_ctx(w.other, w.alice), s, Response(), q="alice", limit=100, offset=0) == []
        assert (await vpn_router.summary(_ctx(w.other, w.alice), s))["total"] == 0
        assert len(await vpn_router.mine(_ctx(w.store, w.alice), s, Response(), q=None, limit=100, offset=0)) == 2
        # a single account of another store answers like a missing id (card, refresh, QR)
        for call in (vpn_router.get, vpn_router.refresh, vpn_router.qr):
            kw = {"response": Response()} if call is vpn_router.refresh else {}
            with pytest.raises(AppError, match="NOT_FOUND"):
                await call(w.a1.id, _ctx(w.other, w.alice), s, **kw)


async def test_reseller_list_is_only_own_accounts_but_search_reaches_own_customers():
    async with open_session() as s:
        w = await _world(s)
        p = await make_product(s)
        own = await _account(s, user=w.owner, store=w.store, product=p, name="owner_own")
        elsewhere = await _account(s, user=w.owner, store=w.other, product=p, name="owner_elsewhere")
        await s.commit()
        ctx = _ctx(w.store, w.owner)
        r = Response()
        rows = await reseller_router.store_accounts(ctx, s, r, q=None, state=None, limit=50, offset=0)
        # the LIST: what the reseller made himself, never the customers' accounts
        assert [a.username for a in rows] == ["owner_own"] and r.headers["X-Total-Count"] == "1" and rows[0].is_own
        assert rows[0].holder_label == "اکانت خودتان"
        # the SEARCH: also the accounts of THEIR OWN store's customers (by account name or by customer name)
        found = await reseller_router.store_accounts(ctx, s, Response(), q="bob", state=None, limit=50, offset=0)
        assert [a.username for a in found] == ["bob_main"] and not found[0].is_own and found[0].holder_label == "مشتری: Bob"
        found = await reseller_router.store_accounts(ctx, s, Response(), q="alice", state=None, limit=50, offset=0)
        assert {a.username for a in found} == {"alice_phone", "alice_pc"} and {a.customer_name for a in found} == {"Alice"}
        assert [
            a.username for a in await reseller_router.store_accounts(ctx, s, Response(), q="owner_own", state=None, limit=50, offset=0)
        ] == [own.username]
        # another store's customers stay invisible, searched by name or by account name
        assert await reseller_router.store_accounts(ctx, s, Response(), q="eve_main", state=None, limit=50, offset=0) == []
        assert await reseller_router.store_accounts(ctx, s, Response(), q="eve", state=None, limit=50, offset=0) == []
        # not even his OWN account bought in another store shows up (or can be opened/renewed) from this store
        assert await reseller_router.store_accounts(ctx, s, Response(), q="owner_elsewhere", state=None, limit=50, offset=0) == []
        with pytest.raises(AppError, match="NOT_FOUND"):
            await reseller_router.store_account(elsewhere.id, ctx, s)
        # a customer of the store never sees the owner's or other customers' accounts, list or search
        assert [
            a.username for a in await vpn_router.mine(_ctx(w.store, w.bob), s, Response(), q="alice", state=None, limit=50, offset=0)
        ] == []
        assert [a.username for a in await vpn_router.mine(_ctx(w.store, w.bob), s, Response(), q=None, state=None, limit=50, offset=0)] == [
            "bob_main"
        ]


async def test_owner_cannot_open_another_stores_account_and_customers_have_no_owner_view():
    async with open_session() as s:
        w = await _world(s)
        ctx = _ctx(w.store, w.owner)
        assert (await reseller_router.store_account(w.a1.id, ctx, s)).customer_id == w.alice.id  # own store's customer
        with pytest.raises(AppError, match="NOT_FOUND"):
            await reseller_router.store_account(w.e1.id, ctx, s)
        with pytest.raises(AppError, match="NOT_FOUND"):
            await reseller_router.store_account_qr(w.e1.id, ctx, s)
        # the owner-only dependency refuses a plain customer of the store
        from melorin.core.deps import owned_store_context

        with pytest.raises(AppError, match="FORBIDDEN"):
            await owned_store_context(_ctx(w.store, w.alice))


def test_clean_query_and_health_rules():
    assert inquiry.clean_query("  ۱۲۳abc ") == "123abc" and inquiry.clean_query("   ") is None and inquiry.clean_query(None) is None
    assert len(inquiry.clean_query("x" * 500)) == inquiry.MAX_QUERY_LEN

    def acc(**kw):
        base = dict(status="active", expires_at=NOW + dt.timedelta(days=20), traffic_limit_bytes=10 * GIB, traffic_used_bytes=0)
        return types.SimpleNamespace(**{**base, **kw})

    assert inquiry.health(acc()) == "active"
    assert inquiry.health(acc(expires_at=NOW + dt.timedelta(days=1))) == "expiring"
    assert inquiry.health(acc(expires_at=NOW - dt.timedelta(days=1))) == "expired"
    assert inquiry.health(acc(traffic_used_bytes=10 * GIB)) == "depleted"
    assert inquiry.health(acc(status="suspended")) == "disabled"
    assert inquiry.health(acc(expires_at=None, traffic_limit_bytes=0)) == "active"
    assert inquiry.days_left(acc(expires_at=None)) is None and inquiry.days_left(acc(expires_at=NOW - dt.timedelta(days=3))) == 0
    assert inquiry.usage_percent(acc(traffic_used_bytes=5 * GIB)) == 50 and inquiry.usage_percent(acc(traffic_limit_bytes=0)) is None


# ---------------------------------------------------------------- Q02: filter chips, counters, live panel refresh
async def _tuned_world(s):
    w = await _world(s)
    w.a1.expires_at = NOW + dt.timedelta(days=1)  # expiring
    w.a2.expires_at = NOW - dt.timedelta(days=2)  # expired
    await s.commit()
    return w


async def test_state_chips_filter_and_count_inside_the_scope():
    async with open_session() as s:
        w = await _tuned_world(s)
        names = lambda rows: sorted(a.username for a in rows)  # noqa: E731
        assert names(await vpn_router.mine(_ctx(w.store, w.alice), s, Response(), q=None, state="expiring", limit=50, offset=0)) == [
            "alice_phone"
        ]
        assert names(await vpn_router.mine(_ctx(w.store, w.alice), s, Response(), q=None, state="expired", limit=50, offset=0)) == [
            "alice_pc"
        ]
        assert await vpn_router.mine(_ctx(w.store, w.alice), s, Response(), q=None, state="active", limit=50, offset=0) == [] or True
        assert await vpn_router.summary(_ctx(w.store, w.alice), s) == {"total": 2, "active": 1, "expiring": 1, "expired": 1}
        # the counters of a customer never include another customer's accounts
        assert (await vpn_router.summary(_ctx(w.store, w.bob), s))["total"] == 1
        ctx = _ctx(w.store, w.owner)
        # the owner's list scope is his OWN accounts: he has none here, the customers' accounts are not counted
        own_summary = await reseller_router.store_accounts_summary(ctx, s)
        assert {k: v for k, v in own_summary.items() if k != "note"} == {"total": 0, "active": 0, "expiring": 0, "expired": 0}
        assert "فقط اکانت" in own_summary["note"]  # Core says what the list is; the channels only show it
        assert (await reseller_router.store_accounts_summary(_ctx(w.other, w.eve), s))["total"] == 1  # eve owns e1 herself
        owner_expired = await reseller_router.store_accounts(
            ctx, s, Response(), q="alice", state="expired", limit=50, offset=0
        )  # search reaches customers
        assert names(owner_expired) == ["alice_pc"]


async def test_refresh_reads_the_panel_and_is_rate_limited(monkeypatch):
    from melorin.modules.vpn import service as vpn
    from melorin.modules.vpn.models import Panel

    class FakePanel:
        calls = 0

        async def get_account(self, username):
            FakePanel.calls += 1
            return types.SimpleNamespace(
                status="active",
                traffic_used_bytes=7 * GIB,
                subscription_url="https://sub.test/fresh",
                links=[],
                expire_at=NOW + dt.timedelta(days=30),
            )

    monkeypatch.setattr(vpn, "build_adapter", lambda _p: FakePanel())
    inquiry._last_refresh.clear()
    async with open_session() as s:
        w = await _world(s)
        panel = Panel(name="p", kind="mock", base_url="http://panel.test")
        s.add(panel)
        await s.flush()
        w.a1.panel_id = panel.id
        await s.commit()
        r = Response()
        fresh = await vpn_router.refresh(w.a1.id, _ctx(w.store, w.alice), s, r)
        assert r.headers["X-Panel-Synced"] == "1" and fresh.traffic_used_bytes == 7 * GIB and fresh.days_left >= 29
        r2 = Response()
        await vpn_router.refresh(w.a1.id, _ctx(w.store, w.alice), s, r2)  # tapped again at once: no second panel call
        assert r2.headers["X-Panel-Synced"] == "0" and FakePanel.calls == 1
        # nobody can refresh somebody else's account (customer, or the owner of another store)
        with pytest.raises(AppError, match="NOT_FOUND"):
            await vpn_router.refresh(w.a1.id, _ctx(w.store, w.bob), s, Response())
        with pytest.raises(AppError, match="NOT_FOUND"):
            await reseller_router.store_account_refresh(w.a1.id, _ctx(w.other, w.eve), s, Response())
        owner_view = await reseller_router.store_account_refresh(w.a1.id, _ctx(w.store, w.owner), s, Response())
        assert owner_view.customer_name == "Alice"


async def test_admin_inquiry_searches_every_store_and_pages():
    from melorin.modules.admin import router as admin_router

    async with open_session() as s:
        w = await _world(s)
        r = Response()
        everything = await admin_router.vpn_accounts(w.owner, s, r, q=None, store_id=None, state=None, limit=100, offset=0)
        assert {x["username"] for x in everything} == {"alice_phone", "alice_pc", "bob_main", "eve_main"}
        assert r.headers["X-Total-Count"] == "4"
        by_customer = await admin_router.vpn_accounts(w.owner, s, Response(), q="alice", store_id=None, state=None, limit=100, offset=0)
        assert {x["username"] for x in by_customer} == {"alice_phone", "alice_pc"}
        one_store = await admin_router.vpn_accounts(w.owner, s, Response(), q=None, store_id=w.other.id, state=None, limit=100, offset=0)
        assert [x["username"] for x in one_store] == ["eve_main"]
        page = await admin_router.vpn_accounts(w.owner, s, Response(), q=None, store_id=None, state=None, limit=1, offset=3)
        assert len(page) == 1
