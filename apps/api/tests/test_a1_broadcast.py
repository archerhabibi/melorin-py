"""A1: پیام همگانی. The admin reaches his resellers / his customers / every customer of the project; a reseller reaches ONLY
the customers of his own store; delivery is per (person, store), idempotent, paced, and limited per day."""

import types

import pytest
from sqlalchemy import select

from _db import make_store, make_user, open_session
from melorin.core import events
from melorin.core.errors import AppError
from melorin.kernel.models.notifications import Broadcast
from melorin.kernel.models.stores import StoreMembership
from melorin.kernel.models.system import OutboxEvent
from melorin.modules.broadcast import service


async def _member(s, store, user=None, role="customer", status="active"):
    user = user or await make_user(s)
    s.add(StoreMembership(store_id=store.id, user_id=user.id, role=role, status=status))
    await s.flush()
    return user


async def _world(s):
    admin = await make_user(s, super_admin=True)
    main = await make_store(s, kind="main")
    r1_owner, r2_owner = await make_user(s), await make_user(s)
    r1, r2 = await make_store(s, kind="reseller", owner=r1_owner), await make_store(s, kind="reseller", owner=r2_owner)
    c_main, c_main2 = await _member(s, main), await _member(s, main)
    c_r1, c_r2 = await _member(s, r1), await _member(s, r2)
    await _member(s, r1, r1_owner, role="owner")
    await s.commit()
    return types.SimpleNamespace(**locals())


def _ids(rs):
    return {(r.user_id, r.store_id) for r in rs}


async def test_admin_audiences_cover_exactly_the_people_each_group_means():
    async with open_session() as s:
        w = await _world(s)
        res = _ids(await service.recipients(s, w.main, "resellers"))
        assert res == {(w.r1_owner.id, w.main.id), (w.r2_owner.id, w.main.id)}  # through the MAIN store's bot
        cust = _ids(await service.recipients(s, w.main, "customers"))
        assert cust == {(w.c_main.id, w.main.id), (w.c_main2.id, w.main.id)}
        assert _ids(await service.recipients(s, w.main, "all_own")) == res | cust
        every = _ids(await service.recipients(s, w.main, "everyone"))
        assert every == cust | {(w.c_r1.id, w.r1.id), (w.c_r2.id, w.r2.id)}  # the owner is not a "customer" of his own store


async def test_reseller_reaches_only_his_own_stores_customers():
    async with open_session() as s:
        w = await _world(s)
        assert _ids(await service.recipients(s, w.r1, "customers")) == {(w.c_r1.id, w.r1.id)}
        for bad in ("everyone", "resellers", "all_own"):
            with pytest.raises(AppError) as exc:
                await service.recipients(s, w.r1, bad)
            assert exc.value.code == "BROADCAST_AUDIENCE"


async def test_blocked_inactive_admin_and_suspended_store_people_are_skipped():
    async with open_session() as s:
        w = await _world(s)
        blocked = await _member(s, w.main, status="blocked")
        gone = await _member(s, w.main)
        gone.is_active = False
        await _member(s, w.main, w.admin)  # an admin is never a broadcast recipient
        w.r2.status = "suspended"
        await s.commit()
        cust = _ids(await service.recipients(s, w.main, "everyone"))
        assert (blocked.id, w.main.id) not in cust and (gone.id, w.main.id) not in cust and (w.admin.id, w.main.id) not in cust
        assert (w.c_r2.id, w.r2.id) not in cust
        assert (w.r2_owner.id, w.main.id) not in _ids(await service.recipients(s, w.main, "resellers"))


async def test_send_queues_one_idempotent_notification_event_per_person_and_records_it():
    async with open_session() as s:
        w = await _world(s)
        bc = await service.send(s, sender=w.admin, store=w.main, audience="all_own", title=" سلام ", body=" متن ")
        assert bc.recipients == 4 and bc.title == "سلام" and bc.body == "متن"
        evs = (await s.scalars(select(OutboxEvent).where(OutboxEvent.topic == events.NOTIFY))).all()
        assert len(evs) == 4 and len({e.dedup_key for e in evs}) == 4
        assert all(e.payload["kind"] == "broadcast" and e.dedup_key.startswith(f"bc:{bc.id.hex}:") for e in evs)
        h = await service.history(s, w.main)
        assert h[0]["recipients"] == 4 and h[0]["queued"] == 4 and h[0]["audience_label"]


async def test_everyone_notifications_are_scoped_to_each_recipients_own_store():
    async with open_session() as s:
        w = await _world(s)
        await service.send(s, sender=w.admin, store=w.main, audience="everyone", title="t", body="b")
        evs = (await s.scalars(select(OutboxEvent).where(OutboxEvent.topic == events.NOTIFY))).all()
        stores = {(e.payload["user_id"], e.payload["store_id"]) for e in evs}
        assert (str(w.c_r1.id), str(w.r1.id)) in stores and (str(w.c_r2.id), str(w.r2.id)) in stores
        assert (str(w.c_r1.id), str(w.main.id)) not in stores  # a reseller's customer is NOT messaged through the main store


async def test_sending_is_paced_and_validated_and_limited_per_day():
    async with open_session() as s:
        w = await _world(s)
        with pytest.raises(AppError) as e1:
            await service.send(s, sender=w.admin, store=w.main, audience="customers", title="  ", body="x")
        assert e1.value.code == "BROADCAST_EMPTY"
        with pytest.raises(AppError) as e2:
            await service.send(s, sender=w.admin, store=w.main, audience="customers", title="t", body="x" * (service.BODY_MAX + 1))
        assert e2.value.code == "BROADCAST_TOO_LONG"
        empty_store = await make_store(s, kind="reseller", owner=await make_user(s))
        with pytest.raises(AppError) as e3:
            await service.send(s, sender=w.admin, store=empty_store, audience="customers", title="t", body="b")
        assert e3.value.code == "BROADCAST_NO_RECIPIENTS"
        for _ in range(service.DAILY_LIMIT):
            await service.send(s, sender=w.admin, store=w.main, audience="customers", title="t", body="b")
        with pytest.raises(AppError) as e4:
            await service.send(s, sender=w.admin, store=w.main, audience="customers", title="t", body="b")
        assert e4.value.code == "BROADCAST_LIMIT" and e4.value.status == 429
        assert len((await s.scalars(select(Broadcast))).all()) == service.DAILY_LIMIT


async def test_pacing_spreads_a_big_audience_over_seconds():
    async with open_session() as s:
        w = await _world(s)
        for _ in range(service.PER_SECOND * 2):
            await _member(s, w.r1)
        await s.commit()
        await service.send(s, sender=w.r1_owner, store=w.r1, audience="customers", title="t", body="b")
        evs = (await s.scalars(select(OutboxEvent).where(OutboxEvent.topic == events.NOTIFY))).all()
        spread = {e.available_at for e in evs}
        assert len(evs) == service.PER_SECOND * 2 + 1 and len({e.available_at.replace(microsecond=0) for e in evs}) >= 2
        assert spread


def test_routes_exist_and_stay_in_their_planes():
    from melorin.modules.admin import broadcasts as admin_bc
    from melorin.modules.reseller.routes import broadcasts as reseller_bc

    admin_paths = {r.path for r in admin_bc.router.routes}
    assert {"/admin/broadcasts", "/admin/broadcasts/audiences"} <= admin_paths
    assert {r.path for r in reseller_bc.router.routes} == {"/stores/{store_id}/reseller/broadcasts"}
