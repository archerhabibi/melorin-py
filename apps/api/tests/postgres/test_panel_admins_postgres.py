"""Per-store panel admins, PostgreSQL lane: the guards hold under REAL concurrency (SQLite serialises everything, so it proves nothing here).

Runs only with ``TEST_PG_URL``. Every contender has its own session and connection on one private schema:

* the worker and provisioning (and a burst of orders) all ask for the same store's admin at the same moment -> ONE row, ONE login, no crash;
* two stores whose logins would be identical are planned at the same moment -> two different logins, neither adopts the other's admin;
* two pending change requests of one store filed at the same moment -> the database lets exactly one in.
"""

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_store, make_user, open_schema_engine, pg_url
from melorin.kernel.models.vpn import Panel, PanelAdmin, PanelAdminChangeRequest
from melorin.modules.panelops import panel_admins as svc
from test_panel_admins import FakeAdapter

pytestmark = [
    pytest.mark.concurrency,
    pytest.mark.skipif(pg_url() is None, reason="PostgreSQL lane: set TEST_PG_URL"),
]


async def _seed(factory, *slugs):
    async with factory() as s:
        panel = Panel(name="P", kind="pasarguard", base_url="https://p.example.com", is_enabled=True, config={"group_ids": [1]})
        s.add(panel)
        owner = await make_user(s)
        stores = [await make_store(s, kind="reseller", slug=slug, owner=owner) for slug in slugs]
        await s.commit()
        return panel.id, [st.id for st in stores]


async def _owner(factory, adapter, panel_id, store_id):
    async with factory() as s:
        return await svc.owner_for(s, await s.get(Panel, panel_id), store_id, adapter)


async def test_a_burst_asking_for_one_stores_admin_creates_exactly_one_row():
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        panel_id, (store_id,) = await _seed(factory, "reseller-aaaa1111")
        adapter = FakeAdapter()
        names = await asyncio.gather(*[_owner(factory, adapter, panel_id, store_id) for _ in range(8)])
        assert set(names) == {"rs_aaaa1111"}
        async with factory() as s:
            rows = (await s.scalars(select(PanelAdmin))).all()
            assert len(rows) == 1 and rows[0].status == "active" and rows[0].username == "rs_aaaa1111"
        assert set(adapter.admins) == {"rs_aaaa1111"}  # one login on the panel


async def test_two_stores_with_the_same_login_planned_at_once_get_different_admins():
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        panel_id, (a, b) = await _seed(factory, "reseller-ab-cd", "reseller-ab_cd")  # both collapse to rs_ab_cd
        adapter = FakeAdapter()
        names = await asyncio.gather(_owner(factory, adapter, panel_id, a), _owner(factory, adapter, panel_id, b))
        assert len(set(names)) == 2 and all(n.startswith("rs_ab_cd") for n in names)
        async with factory() as s:
            rows = {r.store_id: r.username for r in (await s.scalars(select(PanelAdmin))).all()}
        assert rows == {a: names[0], b: names[1]}
        assert set(adapter.admins) == set(names)  # neither store adopted (or re-passworded) the other's admin


async def test_the_database_lets_only_one_of_two_simultaneous_pending_requests_in():
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        _, (store_id,) = await _seed(factory, "reseller-aaaa1111")

        async def file_request(title, hold):
            async with factory() as s:
                s.add(PanelAdminChangeRequest(store_id=store_id, changes={"profile_title": title}, status="pending"))
                try:
                    await s.flush()
                    await asyncio.sleep(hold)  # still uncommitted: the competitor's INSERT must wait for us
                    await s.commit()
                    return "filed"
                except IntegrityError:
                    await s.rollback()
                    return "refused"

        results = await asyncio.gather(file_request("one", 0.4), file_request("two", 0.0))
        assert sorted(results) == ["filed", "refused"]
        async with factory() as s:
            rows = (await s.scalars(select(PanelAdminChangeRequest))).all()
            assert len(rows) == 1 and rows[0].status == "pending"
