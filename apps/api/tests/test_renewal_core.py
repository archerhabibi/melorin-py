"""Renewal is a Core rule shared by the website and the bots: 10-day window after expiry, the account's own package only,
the package's CURRENT price inside the original bundle, and after renewal the account shows exactly the package's time
and volume (usage back to zero). Everything runs through ``orders.create_order`` / ``vpn.provision_order``."""

import datetime as dt
import itertools
import types

import pytest
from sqlalchemy import select

from _db import make_order, make_product, make_store, make_user, open_session
from melorin.core import codes
from melorin.core.deps import StoreContext
from melorin.core.errors import AppError
from melorin.modules.catalog.models import StoreBundlePrice, StoreProduct
from melorin.modules.orders import service as orders
from melorin.modules.orders.models import Order
from melorin.modules.stores.models import ResellerProfile, StoreMembership
from melorin.modules.vpn import allocation, renewal
from melorin.modules.vpn import service as vpn
from melorin.modules.vpn.adapters.base import AccountSpec, ErrorKind, PanelAccount, PanelError
from melorin.modules.vpn.bundles import Bundle, BundleMember, BundleProduct
from melorin.modules.vpn.models import Panel, Server, VpnAccount
from melorin.modules.wallet import service as wallet

GIB = 1024**3
NOW = dt.datetime.now(dt.UTC)


@pytest.fixture(autouse=True)
def _sqlite_order_numbers(monkeypatch):
    counter = itertools.count(1)

    async def next_code(session, sequence):
        return f"R{next(counter):05d}"

    monkeypatch.setattr(codes, "next_code", next_code)


class Panel_:
    """Fake panel that remembers one account; ``can_reset`` toggles the optional reset_traffic capability."""

    kind = "fake"

    def __init__(self, *, used=0, limit=10 * GIB, expire=None, can_reset=True, script=()):
        self.state = PanelAccount(
            ref="r", username="x", status="disabled", expire_at=expire, traffic_limit_bytes=limit, traffic_used_bytes=used,
            subscription_url="https://sub.test/x", links=[],
        )
        self.calls: list[tuple] = []
        self.script = list(script)
        if can_reset:
            self.reset_traffic = self._reset

    async def extend_account(self, username, *, expire_at, traffic_bytes):
        if self.script:
            raise self.script.pop(0)
        self.calls.append(("extend", expire_at, traffic_bytes))
        self.state.expire_at, self.state.traffic_limit_bytes, self.state.status = expire_at, traffic_bytes, "active"
        return self.state

    async def _reset(self, username):
        self.calls.append(("reset",))
        self.state.traffic_used_bytes = 0
        return self.state

    async def get_account(self, username):
        return self.state

    async def close(self):
        return None


async def _fund(s, user, store, amount):
    w = await wallet.get_wallet(s, user.id, store.id, currency="IRT", kind="customer")
    await wallet.post(
        s, kind="topup", key=f"fund:{w.id}:{amount}", currency="IRT",
        postings=[wallet.Posting(-amount, account="gateway:test:clearing"), wallet.Posting(amount, wallet=w)],
    )
    return w


async def _world(s, *, expired_days_ago=3, status="expired", funds=50_000, store_kind="main"):
    main = await make_store(s)
    owner, user = await make_user(s), await make_user(s)
    store = main if store_kind == "main" else await make_store(s, kind="reseller", owner=owner)
    if store_kind == "reseller":
        s.add(ResellerProfile(store_id=store.id, user_id=owner.id, debt_limit=10**9, sales_enabled=True))
    product = await make_product(s, price=2_000)
    other = await make_product(s, price=9_000)
    bundle = Bundle(name="B", kind_label="direct", selection_mode="automatic", naming_mode="automatic", is_enabled=True)
    panel = Panel(name="p1", kind="mock", base_url="http://x", is_enabled=True, health_status="healthy")
    s.add_all([bundle, panel])
    await s.flush()
    server = Server(name="srv", panel_id=panel.id)
    bp = BundleProduct(bundle_id=bundle.id, product_id=product.id, is_listed=True, sort=0)
    s.add_all([BundleMember(bundle_id=bundle.id, panel_id=panel.id, sort=0), server, bp])
    for p in (product, other):
        s.add(StoreProduct(store_id=store.id, product_id=p.id, is_enabled=True, is_listed=True, customer_price=3_000 if store_kind == "reseller" else None))
    membership = StoreMembership(store_id=store.id, user_id=user.id, role="customer", status="active")
    s.add(membership)
    await s.flush()
    first = await make_order(s, user=user, store=store, product=product, total=2_000, status="completed")
    first.bundle_id = bundle.id
    expires = NOW - dt.timedelta(days=expired_days_ago)
    account = VpnAccount(
        username="acc_1", user_id=user.id, store_id=store.id, order_id=first.id, product_id=product.id, server_id=server.id,
        panel_id=panel.id, panel_ref="r", status=status, expires_at=expires, traffic_limit_bytes=10 * GIB, traffic_used_bytes=4 * GIB,
        subscription_url="https://sub.test/x", links=[],
    )
    s.add(account)
    w = await _fund(s, user, store, funds)
    await s.commit()
    ctx = StoreContext(store=store, user=user, membership=membership)
    return types.SimpleNamespace(
        ctx=ctx, store=store, user=user, product=product, other=other, bundle=bundle, bp=bp, account=account, wallet_id=w.id, owner=owner, panel=panel
    )


async def _renew(s, t, *, key="k1", product=None):
    return await orders.create_order(
        s, t.ctx, product_id=(product or t.product).id, idempotency_key=key, kind="renewal", vpn_account_id=t.account.id, channel="web"
    )


async def _balance(s, t):
    return (await wallet.get_wallet(s, t.user.id, t.store.id, currency="IRT", kind="customer")).balance


# ------------------------------------------------------------------ the 10-day window (pure rule)
def _acc(**kw):
    base = dict(is_test=False, status="expired", archived_at=None, expires_at=NOW - dt.timedelta(days=1))
    return types.SimpleNamespace(**{**base, **kw})


def test_window_is_ten_days_after_expiry():
    assert renewal.eligibility(_acc(expires_at=NOW - dt.timedelta(days=9, hours=23)), now=NOW).ok
    late = renewal.eligibility(_acc(expires_at=NOW - dt.timedelta(days=10, minutes=1)), now=NOW)
    assert not late.ok and late.code == "RENEWAL_WINDOW_PASSED"


def test_active_account_and_account_without_expiry_are_renewable():
    assert renewal.eligibility(_acc(status="active", expires_at=NOW + dt.timedelta(days=5)), now=NOW).ok
    assert renewal.eligibility(_acc(expires_at=None), now=NOW).ok


@pytest.mark.parametrize("kw", [dict(is_test=True), dict(status="revoked"), dict(status="archived"), dict(status="pending"), dict(status="provisioning")])
def test_test_revoked_archived_and_unfinished_accounts_are_not_renewable(kw):
    st = renewal.eligibility(_acc(**kw), now=NOW)
    assert not st.ok and st.code == "ACCOUNT_NOT_RENEWABLE"


def test_naive_database_datetimes_are_compared_in_utc():
    naive = (NOW - dt.timedelta(days=2)).replace(tzinfo=None)
    assert renewal.eligibility(_acc(expires_at=naive), now=NOW).ok


# ------------------------------------------------------------------ creating the order
async def test_renewal_charges_the_current_price_of_the_package_in_the_original_bundle():
    async with open_session() as s:
        t = await _world(s)
        t.bp.main_price = 2_500  # the price changed after the first purchase (was 2000)
        await s.commit()
        o = await _renew(s, t)
        assert o.kind == "renewal" and o.total == 2_500 and o.unit_price == 2_500
        assert o.pricing_snapshot["renewal"]["bundle_id"] == str(t.bundle.id)
        assert await _balance(s, t) == 50_000 - 2_500
        assert o.pricing_snapshot["renewal"]["package"]["duration_days"] == 30


async def test_renewal_only_with_the_accounts_own_package():
    async with open_session() as s:
        t = await _world(s)
        with pytest.raises(AppError) as e:
            await _renew(s, t, product=t.other)
        assert e.value.code == "RENEWAL_PRODUCT_MISMATCH"
        assert await _balance(s, t) == 50_000


async def test_renewal_after_the_window_is_refused_and_nothing_is_charged():
    async with open_session() as s:
        t = await _world(s, expired_days_ago=11)
        with pytest.raises(AppError) as e:
            await _renew(s, t)
        assert e.value.code == "RENEWAL_WINDOW_PASSED" and e.value.status == 409
        assert await _balance(s, t) == 50_000


async def test_renewal_on_the_last_day_is_accepted():
    async with open_session() as s:
        t = await _world(s, expired_days_ago=9)
        assert (await _renew(s, t)).status == "paid"


async def test_someone_elses_account_is_not_renewable():
    async with open_session() as s:
        t = await _world(s)
        stranger = await make_user(s)
        s.add(StoreMembership(store_id=t.store.id, user_id=stranger.id, role="customer", status="active"))
        await _fund(s, stranger, t.store, 9_000)
        await s.commit()
        ctx = StoreContext(store=t.store, user=stranger, membership=await s.scalar(select(StoreMembership).where(StoreMembership.user_id == stranger.id)))
        with pytest.raises(AppError) as e:
            await orders.create_order(s, ctx, product_id=t.product.id, idempotency_key="x", kind="renewal", vpn_account_id=t.account.id)
        assert e.value.code == "ACCOUNT_NOT_RENEWABLE"


async def test_second_renewal_while_one_is_in_progress_is_refused_even_with_another_key():
    async with open_session() as s:
        t = await _world(s)
        await _renew(s, t, key="a")
        with pytest.raises(AppError) as e:
            await _renew(s, t, key="b")
        assert e.value.code == "RENEWAL_IN_PROGRESS"
        assert await _balance(s, t) == 50_000 - 2_000  # charged once
        assert (await _renew(s, t, key="a")).id  # the same key still replays the same order


async def test_package_no_longer_sold_blocks_renewal_with_a_clear_reason():
    async with open_session() as s:
        t = await _world(s)
        t.product.is_active = False
        await s.commit()
        with pytest.raises(AppError) as e:
            await _renew(s, t)
        assert e.value.code == "RENEWAL_PRODUCT_UNAVAILABLE"
        assert await allocation.renewal_offers(s, t.store, t.account) == []


async def test_renewal_offer_is_exactly_one_package_at_the_current_price():
    async with open_session() as s:
        t = await _world(s)
        t.bp.main_price = 2_700
        await s.commit()
        offers = await allocation.renewal_offers(s, t.store, t.account)
        assert [(p.id, price) for p, price in offers] == [(t.product.id, 2_700)]


async def test_reseller_renewal_uses_the_resellers_bundle_price_and_never_a_free_renewal():
    async with open_session() as s:
        t = await _world(s, store_kind="reseller")
        s.add(StoreBundlePrice(store_id=t.store.id, bundle_id=t.bundle.id, product_id=t.product.id, customer_price=3_500))
        await s.commit()
        assert (await _renew(s, t)).total == 3_500
    async with open_session() as s:
        t = await _world(s, store_kind="reseller")
        sp = await s.scalar(select(StoreProduct).where(StoreProduct.store_id == t.store.id, StoreProduct.product_id == t.product.id))
        sp.customer_price = None
        await s.commit()
        with pytest.raises(AppError) as e:
            await _renew(s, t)
        assert e.value.code == "RENEWAL_NOT_PRICED"


# ------------------------------------------------------------------ what the account looks like afterwards
async def _paid_renewal(s, t, **kw):
    o = await _renew(s, t, **kw)
    return o


async def test_after_renewal_the_account_equals_the_package_not_old_plus_package(monkeypatch):
    async with open_session() as s:
        t = await _world(s, expired_days_ago=3)
        panel = Panel_(used=4 * GIB, expire=t.account.expires_at)
        monkeypatch.setattr(vpn, "build_adapter", lambda _p: panel)
        o = await _renew(s, t)
        assert await vpn.provision_order(s, o.id) == "completed"
        acc = await s.get(VpnAccount, t.account.id)
        exp = acc.expires_at if acc.expires_at.tzinfo else acc.expires_at.replace(tzinfo=dt.UTC)
        assert abs(exp - (dt.datetime.now(dt.UTC) + dt.timedelta(days=30))) < dt.timedelta(minutes=2)  # from now, not from the old date
        assert acc.traffic_limit_bytes == 10 * GIB and acc.traffic_used_bytes == 0  # the package's volume, usage restarted
        assert acc.status == "active"
        assert panel.calls[0][0] == "extend" and panel.calls[-1] == ("reset",)


async def test_active_account_is_also_restarted_to_the_package_and_the_quote_says_so():
    async with open_session() as s:
        t = await _world(s, status="active", expired_days_ago=-12)  # 12 days still left
        d = renewal.describe(t.account, t.product, now=NOW)
        assert d["duration_days"] == 30 and d["traffic_gb"] == 10 and d["remaining_days_replaced"] == 12


async def test_panel_without_reset_still_gives_the_full_package_volume(monkeypatch):
    async with open_session() as s:
        t = await _world(s)
        panel = Panel_(used=4 * GIB, expire=t.account.expires_at, can_reset=False)
        monkeypatch.setattr(vpn, "build_adapter", lambda _p: panel)
        o = await _renew(s, t)
        assert await vpn.provision_order(s, o.id) == "completed"
        assert panel.calls[-1][2] == 14 * GIB  # 4 GB already used + the 10 GB package -> 10 GB remain
        acc = await s.get(VpnAccount, t.account.id)
        assert acc.traffic_limit_bytes - acc.traffic_used_bytes == 10 * GIB


async def test_unlimited_package_renews_as_unlimited(monkeypatch):
    async with open_session() as s:
        t = await _world(s)
        t.product.traffic_gb = 0
        await s.commit()
        panel = Panel_(used=2 * GIB, limit=10 * GIB, expire=t.account.expires_at)
        monkeypatch.setattr(vpn, "build_adapter", lambda _p: panel)
        o = await _renew(s, t)
        assert await vpn.provision_order(s, o.id) == "completed"
        assert (await s.get(VpnAccount, t.account.id)).traffic_limit_bytes == 0


async def test_a_timed_out_renewal_is_retried_and_never_reported_as_done_just_because_the_account_exists(monkeypatch):
    async with open_session() as s:
        t = await _world(s)
        old = Panel_(used=4 * GIB, expire=t.account.expires_at, script=[PanelError(ErrorKind.UNKNOWN, "timeout")])
        monkeypatch.setattr(vpn, "build_adapter", lambda _p: old)
        o = await _renew(s, t)
        assert await vpn.provision_order(s, o.id) == "retry_scheduled"  # panel still shows the OLD values -> not completed
        assert (await s.get(Order, o.id)).status == "processing"
        assert await vpn.provision_order(s, o.id) == "completed"  # the retry is absolute, so it is safe


async def test_landed_detects_a_renewal_that_really_happened():
    p = types.SimpleNamespace(traffic_gb=10, duration_days=30)
    ok = types.SimpleNamespace(expire_at=NOW + dt.timedelta(days=30), traffic_limit_bytes=10 * GIB, traffic_used_bytes=0)
    old = types.SimpleNamespace(expire_at=NOW - dt.timedelta(days=3), traffic_limit_bytes=10 * GIB, traffic_used_bytes=4 * GIB)
    assert renewal.landed(ok, p, now=NOW) and not renewal.landed(old, p, now=NOW)


# ------------------------------------------------------------------ what the channels read (same functions the HTTP routes run)
async def test_renewal_info_and_quote_endpoints_give_the_same_promise_the_order_keeps():
    from melorin.modules.catalog import router as catalog_router
    from melorin.modules.catalog.schemas import QuoteRequest

    async with open_session() as s:
        t = await _world(s)
        t.bp.main_price = 2_500
        await s.commit()
        info = await catalog_router.renewal_info(t.account.id, t.ctx, s)
        assert info.renewable and info.package.product_id == t.product.id and info.package.price == 2_500
        assert info.after.duration_days == 30 and info.after.traffic_gb == 10 and info.renew_until is not None
        q = await catalog_router.checkout_quote(QuoteRequest(product_id=t.product.id, vpn_account_id=t.account.id), t.ctx, s)
        assert q.total == 2_500 and q.sufficient_funds and q.renewal.duration_days == 30
        o = await _renew(s, t)
        assert o.total == q.total  # a quote never promises what checkout charges differently
        again = await catalog_router.renewal_info(t.account.id, t.ctx, s)
        assert not again.renewable and again.code == "RENEWAL_IN_PROGRESS"


async def test_renewal_info_after_the_window_says_why_and_the_quote_is_refused():
    from melorin.modules.catalog import router as catalog_router
    from melorin.modules.catalog.schemas import QuoteRequest

    async with open_session() as s:
        t = await _world(s, expired_days_ago=12)
        info = await catalog_router.renewal_info(t.account.id, t.ctx, s)
        assert not info.renewable and info.code == "RENEWAL_WINDOW_PASSED" and info.package is None
        with pytest.raises(AppError) as e:
            await catalog_router.checkout_quote(QuoteRequest(product_id=t.product.id, vpn_account_id=t.account.id), t.ctx, s)
        assert e.value.code == "RENEWAL_WINDOW_PASSED"


def test_account_list_tells_the_clients_whether_renewal_is_open():
    from melorin.modules.vpn.router import out

    now = dt.datetime.now(dt.UTC)
    a = VpnAccount(
        id=__import__("uuid").uuid4(), username="u", user_id=__import__("uuid").uuid4(), status="expired", is_test=False,
        expires_at=now - dt.timedelta(days=11), traffic_limit_bytes=0, traffic_used_bytes=0, subscription_url=None, links=None,
        server_id=None, created_at=now, updated_at=now,
    )
    assert out(a).can_renew is False
    a.expires_at = now - dt.timedelta(days=9)
    assert out(a).can_renew is True and out(a).renew_until is not None


# ------------------------------------------------------------------ the reseller renews: own accounts + own customers only
def _owner_ctx(t, store=None, user=None):
    return StoreContext(store=store or t.store, user=user or t.owner, membership=None)


async def test_reseller_renews_a_customers_account_in_his_own_store():
    from melorin.modules.reseller import router as rr

    async with open_session() as s:
        t = await _world(s, store_kind="reseller")
        info = await rr.store_account_renewal(t.account.id, _owner_ctx(t), s)
        assert info.renewable and info.package.product_id == t.product.id  # the same promise the customer would get
        o = await rr.store_account_renew(t.account.id, rr.OwnerRenewIn(), _owner_ctx(t), s, idempotency_key="owner-renew-1")
        assert o.kind == "renewal" and o.vpn_account_id == t.account.id and o.user_id == t.user.id  # the order is the customer's
        assert await _balance(s, t) < 50_000  # paid from the customer's wallet in this store; the rules stay the core's
        with pytest.raises(AppError) as e:  # the core's one-open-renewal rule holds for the reseller too
            await rr.store_account_renew(t.account.id, rr.OwnerRenewIn(), _owner_ctx(t), s, idempotency_key="owner-renew-2")
        assert e.value.code == "RENEWAL_IN_PROGRESS"


async def test_reseller_cannot_renew_another_resellers_customer():
    from melorin.modules.reseller import router as rr

    async with open_session() as s:
        t = await _world(s, store_kind="reseller")
        eve = await make_user(s)
        other = await make_store(s, kind="reseller", owner=eve)
        await s.commit()
        for call in (
            rr.store_account_renewal(t.account.id, _owner_ctx(t, other, eve), s),
            rr.store_account_renew(t.account.id, rr.OwnerRenewIn(), _owner_ctx(t, other, eve), s, idempotency_key="evil-key-1"),
        ):
            with pytest.raises(AppError) as e:
                await call
            assert e.value.code == "NOT_FOUND"
        assert await _balance(s, t) == 50_000  # nothing was charged


async def test_reseller_renews_his_own_account_without_an_owner_audit_entry():
    from melorin.modules.reseller import router as rr

    async with open_session() as s:
        t = await _world(s, store_kind="reseller")
        first = await make_order(s, user=t.owner, store=t.store, product=t.product, total=2_000, status="completed")
        first.bundle_id = t.bundle.id
        own = VpnAccount(
            username="acc_owner", user_id=t.owner.id, store_id=t.store.id, order_id=first.id, product_id=t.product.id,
            server_id=t.account.server_id, panel_id=t.panel.id, panel_ref="r2", status="expired",
            expires_at=NOW - dt.timedelta(days=3), traffic_limit_bytes=10 * GIB, traffic_used_bytes=0, subscription_url="https://sub.test/o", links=[],
        )
        s.add_all([own, StoreMembership(store_id=t.store.id, user_id=t.owner.id, role="owner", status="active")])
        await _fund(s, t.owner, t.store, 50_000)
        await s.commit()
        o = await rr.store_account_renew(own.id, rr.OwnerRenewIn(), _owner_ctx(t), s, idempotency_key="own-renew-1")
        assert o.user_id == t.owner.id and o.kind == "renewal" and o.vpn_account_id == own.id
