"""Auto target selection on a real (SQLite) schema: even spread, pinning on retry, renewal never allocates, placement, migration 0039."""

import datetime as dt
import importlib.util
import types
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select

from _db import open_session
from melorin.kernel.models.bundles import Bundle, BundleMember, BundleProduct
from melorin.kernel.models.catalog import Product
from melorin.kernel.models.orders import Order
from melorin.kernel.models.vpn import Panel, Server, VpnAccount
from melorin.modules.catalog.allocation import resolve_allocation
from melorin.modules.orders import provisioning as vpn
from melorin.modules.vpn.adapters.base import PanelError
from test_provisioning_db import ScriptedPanel, _world, panel_factory  # noqa: F401,F811

ROOT = Path(__file__).resolve().parents[1]


async def _pool(s, *, targets=4, balancing="round_robin", capacity=500):
    group = Bundle(name="G", selection_mode="automatic", is_enabled=True, balancing=balancing)
    panel = Panel(name="P1", kind="pasarguard", base_url="http://x", is_enabled=True, health_status="healthy", config={"group_ids": [1]})
    s.add_all([group, panel])
    await s.flush()
    s.add(BundleMember(bundle_id=group.id, panel_id=panel.id, sort=0))
    servers = []
    for i in range(targets):
        srv = Server(name=f"G{i}", panel_id=panel.id, capacity=capacity, target={"group_ids": [10 + i]})
        s.add(srv)
        servers.append(srv)
    product = Product(code="10", name="p", duration_days=30, traffic_gb=10, main_price=1, reseller_price=1, default_bundle_id=group.id)
    s.add(product)
    await s.flush()
    s.add(BundleProduct(bundle_id=group.id, product_id=product.id))
    await s.flush()
    return group, panel, servers, product


def _order(group, **kw):
    return types.SimpleNamespace(
        id=uuid.uuid4(), bundle_id=group.id, selected_panel_id=None, store_id=None, kind="purchase", allocated_server_id=None, **kw
    )


async def _sell(s, group, product, n):
    """n new sales; every one becomes an ACTIVE account so load counts move like in production."""
    from _db import make_order, make_store, make_user

    store, user = await make_store(s), await make_user(s)
    host = await make_order(s, user=user, store=store, product=product, total=1, status="paid", number="HOST")
    picked = []
    for _ in range(n):
        server, panel, _g = await resolve_allocation(s, _order(group), product)
        s.add(
            VpnAccount(
                user_id=user.id,
                store_id=store.id,
                order_id=host.id,
                product_id=product.id,
                username=f"u{uuid.uuid4().hex[:10]}",
                server_id=server.id,
                panel_id=panel.id,
                status="active",
            )
        )
        picked.append(server.id)
        await s.flush()
    return picked


async def test_100_new_sales_spread_over_4_destinations_within_one_of_each_other():
    async with open_session() as s:
        group, _p, servers, product = await _pool(s)
        picked = await _sell(s, group, product, 100)
        counts = [picked.count(x.id) for x in servers]
        assert max(counts) - min(counts) <= 1 and sum(counts) == 100


async def test_least_fill_follows_the_ratio_not_the_turn():
    async with open_session() as s:
        group, _p, servers, product = await _pool(s, balancing="least_fill")
        servers[0].capacity = 1000  # same load, bigger destination = emptier ratio
        for srv in servers[1:]:
            srv.capacity = 100
        await s.flush()
        picked = await _sell(s, group, product, 40)
        counts = {x.id: picked.count(x.id) for x in servers}
        assert counts[servers[0].id] > counts[servers[1].id]


async def test_round_robin_without_account_rows_still_rotates():
    async with open_session() as s:
        group, _p, servers, product = await _pool(s)
        picked = []
        for _ in range(8):
            server, _panel, _g = await resolve_allocation(s, _order(group), product)
            picked.append(server.id)
        assert [picked.count(x.id) for x in servers] == [2, 2, 2, 2]
        assert picked[:4] == picked[4:]  # the same cycle repeats


async def test_a_retry_reuses_the_pinned_destination_and_does_not_spend_a_turn():
    async with open_session() as s:
        group, _p, servers, product = await _pool(s)
        order = _order(group)
        first, _panel, _g = await resolve_allocation(s, order, product)
        stamp = first.last_assigned_at
        assert order.allocated_server_id == first.id
        for _ in range(3):
            again, _panel, _g = await resolve_allocation(s, order, product)
            assert again.id == first.id
        assert first.last_assigned_at == stamp
        nxt, _panel, _g = await resolve_allocation(s, _order(group), product)
        assert nxt.id != first.id  # the retries did not waste the turn: the next order moves on


async def test_a_full_or_disabled_destination_leaves_the_rotation():
    async with open_session() as s:
        group, _p, servers, product = await _pool(s)
        servers[0].capacity = 0
        servers[1].is_enabled = False
        await s.flush()
        picked = {(await resolve_allocation(s, _order(group), product))[0].id for _ in range(6)}
        assert picked == {servers[2].id, servers[3].id}


async def test_fill_first_sticks_to_the_first_destination_until_it_is_full():
    async with open_session() as s:
        group, _p, servers, product = await _pool(s, balancing="fill_first")
        picked = {(await resolve_allocation(s, _order(group), product))[0].id for _ in range(5)}
        assert len(picked) == 1
        for srv in servers:
            await s.refresh(srv)


async def test_no_destination_available_is_a_clear_error():
    async with open_session() as s:
        group, _p, servers, product = await _pool(s, targets=2)
        for srv in servers:
            srv.is_enabled = False
        await s.flush()
        with pytest.raises(PanelError) as exc:
            await resolve_allocation(s, _order(group), product)
        assert "no healthy compatible server" in exc.value.message


async def test_three_renewals_stay_on_the_original_destination_and_never_allocate(panel_factory, monkeypatch):  # noqa: F811
    async with open_session() as s:
        w = await _world(s)
        other = Server(name="C", panel_id=w["panel"].id)  # a completely empty destination that a new sale would prefer
        s.add(other)
        await s.commit()
        panel_factory(ScriptedPanel())
        await vpn.provision_order(s, w["order"].id)
        first = await s.get(Order, w["order"].id)
        acc = await s.get(VpnAccount, first.vpn_account_id)
        home, stamp = acc.server_id, (await s.get(Server, acc.server_id)).last_assigned_at
        assert acc.placement and acc.placement["server"]["id"] == str(home) and acc.placement["selected_by"] == "automatic"
        snapshot = dict(acc.placement)

        async def boom(*a, **k):
            raise AssertionError("a renewal must never allocate")

        monkeypatch.setattr(vpn, "resolve_allocation", boom)
        from _db import make_order

        for n in range(3):
            r = await make_order(s, user=w["user"], store=w["store"], product=w["product"], total=2_000, status="paid", number=f"R{n}")
            r.kind, r.vpn_account_id = "renewal", acc.id
            acc.sold_expires_at = dt.datetime.now(dt.UTC) + dt.timedelta(days=3)
            await s.commit()
            assert await vpn.provision_order(s, r.id) == "completed", r.last_error
            await s.refresh(acc)
            assert acc.server_id == home and r.allocated_server_id is None
        assert (await s.get(Server, home)).last_assigned_at == stamp
        assert acc.placement == snapshot  # written once at creation, never by a renewal


async def test_a_renewal_of_an_account_without_a_server_goes_to_review_instead_of_allocating(panel_factory, monkeypatch):  # noqa: F811
    async with open_session() as s:
        w = await _world(s)
        panel_factory(ScriptedPanel())
        await vpn.provision_order(s, w["order"].id)
        acc = await s.get(VpnAccount, (await s.get(Order, w["order"].id)).vpn_account_id)
        acc.server_id = None

        async def boom(*a, **k):
            raise AssertionError("a renewal must never allocate")

        monkeypatch.setattr(vpn, "resolve_allocation", boom)
        from _db import make_order

        r = await make_order(s, user=w["user"], store=w["store"], product=w["product"], total=2_000, status="paid", number="RX")
        r.kind, r.vpn_account_id = "renewal", acc.id
        await s.commit()
        assert await vpn.provision_order(s, r.id) == "needs_review"
        await s.refresh(r)
        assert r.needs_review is True


async def test_new_account_is_created_with_its_servers_target_and_records_the_placement(monkeypatch):
    async with open_session() as s:
        w = await _world(s)
        w["panel"].kind, w["panel"].config = "pasarguard", {"group_ids": [1]}
        w["server"].target = {"group_ids": [7]}
        await s.commit()
        seen = {}
        panel = ScriptedPanel()

        def fake_build(p, server=None):
            seen["server"] = server
            return panel

        monkeypatch.setattr(vpn, "build_adapter", fake_build)
        await vpn.provision_order(s, w["order"].id)
        acc = await s.scalar(select(VpnAccount))
        assert seen["server"] is not None and seen["server"].id == w["server"].id
        assert acc.placement["target"] == {"group_ids": [7]}
        assert acc.placement["panel"]["kind"] == "pasarguard" and acc.placement["remote_ref"] == acc.panel_ref
        assert "password" not in str(acc.placement).lower() and "token" not in str(acc.placement).lower()


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "alembic/versions" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_0039_follows_0038_and_fits_the_version_column():
    m = _load("m0039", "0039_target_selection.py")
    assert m.down_revision == "0038_store_site_enabled" and len(m.revision) <= 32


def test_0039_adds_the_columns_backfills_round_robin_and_downgrades_cleanly():
    m = _load("m0039", "0039_target_selection.py")
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        for sql in (
            "CREATE TABLE servers (id CHAR(32) PRIMARY KEY, name VARCHAR(80))",
            "CREATE TABLE bundles (id CHAR(32) PRIMARY KEY, name VARCHAR(80))",
            "CREATE TABLE orders (id CHAR(32) PRIMARY KEY)",
            "CREATE TABLE vpn_accounts (id CHAR(32) PRIMARY KEY)",
            "INSERT INTO servers VALUES ('s', 'S1')",
            "INSERT INTO bundles VALUES ('b', 'old')",
            "INSERT INTO orders VALUES ('o')",
            "INSERT INTO vpn_accounts VALUES ('a')",
        ):
            conn.exec_driver_sql(sql)
        with Operations.context(MigrationContext.configure(conn, opts={"render_as_batch": True})):
            m.upgrade()
        insp = sa.inspect(conn)
        cols = lambda t: {c["name"] for c in insp.get_columns(t)}  # noqa: E731
        assert {"target", "last_assigned_at"} <= cols("servers")
        assert "balancing" in cols("bundles") and "allocated_server_id" in cols("orders") and "placement" in cols("vpn_accounts")
        assert conn.exec_driver_sql("SELECT balancing FROM bundles").fetchall() == [("round_robin",)]
        assert conn.exec_driver_sql("SELECT name FROM servers").fetchall() == [("S1",)]  # existing rows survive
        with Operations.context(MigrationContext.configure(conn, opts={"render_as_batch": True})):
            m.downgrade()
        insp = sa.inspect(conn)
        assert not ({"target", "last_assigned_at"} & {c["name"] for c in insp.get_columns("servers")})
        assert "balancing" not in {c["name"] for c in insp.get_columns("bundles")}
        assert "placement" not in {c["name"] for c in insp.get_columns("vpn_accounts")}
