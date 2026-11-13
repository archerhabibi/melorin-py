"""PasarGuard Phase 4 / PG-11: bulk operations - preview, typed confirmation, chunked and resumable runs, absolute (never double) writes,
store suspension that only touches what it disabled."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_order, make_product, make_store, make_user, open_schema_engine
from melorin.core.errors import AppError
from melorin.domain.order_state import VpnStatus
from melorin.kernel.models.system import AuditEvent
from melorin.kernel.models.vpn import BulkOperation, BulkOperationItem, Panel, VpnAccount
from melorin.modules.panelops import bulk
from melorin.modules.vpn.adapters.base import Capabilities, ErrorKind, PanelAccount, PanelError

GIB = 1024**3
NOW = dt.datetime.now(dt.UTC).replace(microsecond=0)


class FakePanel:
    """A tiny in-memory PasarGuard: users by username, records every call, can be told to fail."""

    kind = "pasarguard"

    def __init__(self):
        self.users: dict[str, PanelAccount] = {}
        self.calls: list[tuple] = []
        self.fail_next: list[PanelError] = []
        self.apply_then_fail_extend = False

    def capabilities(self):
        return Capabilities(bulk_actions=True)

    def add(self, username, *, expire_days=10, limit=10 * GIB, ref="1"):
        self.users[username] = PanelAccount(
            ref=ref, username=username, status="active", remote_status="active",
            expire_at=NOW + dt.timedelta(days=expire_days) if expire_days is not None else None,
            traffic_limit_bytes=limit, traffic_used_bytes=GIB, subscription_url="https://sub/x",
        )  # fmt: skip

    async def bulk_users_action(self, refs, action):
        self.calls.append(("bulk", action, tuple(refs)))
        if self.fail_next:
            raise self.fail_next.pop(0)
        return len(refs)

    async def set_admin_users_state(self, remote_id, *, active):
        self.calls.append(("admin_state", remote_id, active))

    async def get_account(self, username):
        self.calls.append(("get", username))
        return self.users.get(username)

    async def extend_account(self, username, *, expire_at, traffic_bytes):
        self.calls.append(("extend", username, expire_at, traffic_bytes))
        u = self.users[username]
        if self.fail_next and not self.apply_then_fail_extend:
            raise self.fail_next.pop(0)
        u.expire_at, u.traffic_limit_bytes = expire_at, traffic_bytes
        if self.apply_then_fail_extend and self.fail_next:  # the panel applied it, the answer was lost
            raise self.fail_next.pop(0)
        return u

    async def close(self):
        pass


@pytest.fixture
def panel_api(monkeypatch):
    fake = FakePanel()
    monkeypatch.setattr(bulk, "build_adapter", lambda panel, server=None: fake)
    return fake


async def _world(s, n=3, *, status=VpnStatus.ACTIVE, expire_days=10, limit=10 * GIB, suspend_policy="none"):
    user, store, product = await make_user(s), await make_store(s, kind="reseller"), await make_product(s)
    store.suspend_policy = suspend_policy
    panel = Panel(name="pg", kind="pasarguard", base_url="https://panel.example.com")
    s.add(panel)
    await s.flush()
    accounts = []
    for i in range(n):
        order = await make_order(s, user=user, store=store, product=product)
        a = VpnAccount(
            delivery_snapshot={"subscription_url": "https://sub/x"}, username=f"acc{i}", user_id=user.id, store_id=store.id, order_id=order.id, product_id=product.id, panel_id=panel.id,
            panel_ref=str(i + 1), status=status, sold_expires_at=NOW + dt.timedelta(days=expire_days) if expire_days is not None else None,
            sold_traffic_bytes=limit,         )  # fmt: skip
        s.add(a)
        accounts.append(a)
    await s.commit()
    return user, store, panel, accounts


def _sel(panel, store=None, **kw):
    return bulk.Selection(panel_id=panel.id, store_id=store.id if store else None, **kw)


async def _items(s, op):
    return {i.username: i for i in (await s.scalars(select(BulkOperationItem).where(BulkOperationItem.operation_id == op.id))).all()}


async def _run_to_end(s, op_id, *, ticks=10):
    for _ in range(ticks):
        claimed = await bulk.claim_next(s)
        if claimed is None:
            break
        await bulk.execute(s, claimed, budget_seconds=5)
    return await bulk.get(s, op_id)


# ----------------------------------------------------------------------------------------------------------------- preview
async def test_preview_freezes_eligible_accounts_and_sends_nothing(panel_api):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        user, store, panel, accounts = await _world(s, 3)
        accounts[2].status = VpnStatus.SUSPENDED  # not eligible for a "disable"
        await s.commit()
        op = await bulk.preview(s, kind="disable", selection=_sel(panel, store), reason="قطعی نود", actor_id=user.id)
        assert op.status == "previewed" and op.total == 2 and op.sample == ["acc0", "acc1"]
        assert panel_api.calls == []  # a preview never reaches the panel
        assert op.expires_at is not None
        assert set((await _items(s, op))) == {"acc0", "acc1"}


async def test_preview_needs_a_reason_and_valid_params(panel_api):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        user, store, panel, _ = await _world(s, 1)
        with pytest.raises(AppError) as e:
            await bulk.preview(s, kind="disable", selection=_sel(panel), reason=" ", actor_id=user.id)
        assert e.value.code == "REASON_REQUIRED"
        for params in ({"days": 0}, {"days": bulk.MAX_DAYS + 1}, {}):
            with pytest.raises(AppError) as e:
                await bulk.preview(s, kind="extend_days", selection=_sel(panel), params=params, reason="جبران", actor_id=user.id)
            assert e.value.code == "BAD_BULK_PARAMS"
        with pytest.raises(AppError) as e:
            await bulk.preview(s, kind="delete_everything", selection=_sel(panel), reason="x" * 5, actor_id=user.id)
        assert e.value.code == "BAD_BULK_KIND"


async def test_unlimited_accounts_are_skipped_for_compensation_and_an_empty_selection_is_refused(panel_api):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        user, store, panel, accounts = await _world(s, 2)
        accounts[1].sold_expires_at, accounts[1].sold_traffic_bytes = None, 0  # unlimited time and traffic
        await s.commit()
        op = await bulk.preview(s, kind="extend_days", selection=_sel(panel), params={"days": 3}, reason="جبران", actor_id=user.id)
        assert op.total == 1 and op.skipped == 1 and op.selection["skipped"] == {"unlimited_time": 1}
        with pytest.raises(AppError) as e:
            await bulk.preview(
                s, kind="add_traffic", selection=_sel(panel, usernames=["acc1"]), params={"gb": 1}, reason="جبران", actor_id=user.id
            )
        assert e.value.code == "BULK_EMPTY" and e.value.details == {"skipped": {"unlimited_traffic": 1}}


async def test_selection_is_limited_to_the_chosen_store_and_panel(panel_api):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        user, store, panel, accounts = await _world(s, 2)
        other = await make_store(s, kind="reseller")
        accounts[1].store_id = other.id
        await s.commit()
        op = await bulk.preview(s, kind="disable", selection=_sel(panel, store), reason="تعلیق", actor_id=user.id)
        assert op.sample == ["acc0"]


# ------------------------------------------------------------------------------------------------------------ confirmation
async def test_confirmation_needs_the_exact_count(panel_api):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        user, store, panel, _ = await _world(s, 3)
        op = await bulk.preview(s, kind="disable", selection=_sel(panel), reason="تعلیق", actor_id=user.id)
        with pytest.raises(AppError) as e:
            await bulk.confirm(s, op.id, count=2, actor_id=user.id)
        assert e.value.code == "BULK_COUNT_MISMATCH"
        assert (await bulk.get(s, op.id)).status == "previewed"
        assert await bulk.claim_next(s) is None  # an unconfirmed preview is never run
        await bulk.confirm(s, op.id, count=3, actor_id=user.id)
        assert (await bulk.get(s, op.id)).status == "confirmed"
        with pytest.raises(AppError) as e:  # confirming twice is refused, not repeated
            await bulk.confirm(s, op.id, count=3, actor_id=user.id)
        assert e.value.code == "BULK_NOT_PREVIEWED"


async def test_a_stale_preview_expires_and_cannot_be_confirmed(panel_api):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        user, store, panel, _ = await _world(s, 1)
        op = await bulk.preview(s, kind="disable", selection=_sel(panel), reason="تعلیق", actor_id=user.id)
        op.expires_at = NOW - dt.timedelta(minutes=1)
        await s.commit()
        with pytest.raises(AppError) as e:
            await bulk.confirm(s, op.id, count=1, actor_id=user.id)
        assert e.value.code == "BULK_PREVIEW_EXPIRED" and (await bulk.get(s, op.id)).status == "expired"


async def test_only_one_operation_may_be_open_per_panel(panel_api):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        user, store, panel, _ = await _world(s, 2)
        first = await bulk.preview(s, kind="disable", selection=_sel(panel), reason="تعلیق", actor_id=user.id)
        second = await bulk.preview(s, kind="reset_usage", selection=_sel(panel), reason="ریست", actor_id=user.id)
        await bulk.confirm(s, first.id, count=2, actor_id=user.id)
        with pytest.raises(AppError) as e:
            await bulk.confirm(s, second.id, count=2, actor_id=user.id)
        assert e.value.code == "BULK_BUSY"


# ----------------------------------------------------------------------------------------------------------- panel actions
async def test_disable_runs_in_chunks_marks_accounts_and_audits(panel_api, monkeypatch):
    monkeypatch.setattr(bulk, "CHUNK", 2)
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        user, store, panel, accounts = await _world(s, 5)
        op = await bulk.preview(s, kind="disable", selection=_sel(panel), reason="قطعی", actor_id=user.id)
        await bulk.confirm(s, op.id, count=5, actor_id=user.id)
        op = await _run_to_end(s, op.id)
        assert op.status == "done" and (op.succeeded, op.failed) == (5, 0) and op.finished_at is not None
        sent = [c for c in panel_api.calls if c[0] == "bulk"]
        assert [len(c[2]) for c in sent] == [2, 2, 1] and all(c[1] == "disable" for c in sent)
        rows = (await s.scalars(select(VpnAccount).order_by(VpnAccount.username))).all()
        assert all(a.status == VpnStatus.SUSPENDED and a.last_synced_at is None for a in rows)
        actions = {a.action for a in (await s.scalars(select(AuditEvent))).all()}
        assert {"bulk.previewed", "bulk.confirmed", "bulk.finished"} <= actions


async def test_transient_error_stops_the_run_and_the_rest_resumes_without_repeating_done_chunks(panel_api, monkeypatch):
    monkeypatch.setattr(bulk, "CHUNK", 2)
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        user, store, panel, _ = await _world(s, 4)
        op = await bulk.preview(s, kind="reset_usage", selection=_sel(panel), reason="ریست", actor_id=user.id)
        await bulk.confirm(s, op.id, count=4, actor_id=user.id)
        panel_api.fail_next = [PanelError(ErrorKind.TRANSIENT, "502")]
        claimed = await bulk.claim_next(s)
        mid = await bulk.execute(s, claimed, budget_seconds=5)
        assert mid.status == "confirmed" and mid.succeeded == 0  # nothing marked done, picked up again on the next tick
        end = await _run_to_end(s, op.id)
        assert end.status == "done" and end.succeeded == 4
        done_chunks = [c for c in panel_api.calls if c[0] == "bulk"]
        assert len(done_chunks) == 3  # the failed chunk was resent once, the others once


async def test_permanent_error_fails_items_and_resume_retries_only_those(panel_api, monkeypatch):
    monkeypatch.setattr(bulk, "CHUNK", 2)
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        user, store, panel, _ = await _world(s, 4)
        op = await bulk.preview(s, kind="rotate_links", selection=_sel(panel), reason="لینک", actor_id=user.id)
        await bulk.confirm(s, op.id, count=4, actor_id=user.id)
        panel_api.fail_next = [PanelError(ErrorKind.PERMANENT, "403 forbidden")]
        end = await _run_to_end(s, op.id)
        assert end.status == "partial" and (end.succeeded, end.failed) == (2, 2)
        resumed = await bulk.resume(s, op.id, actor_id=user.id)
        assert resumed.status == "confirmed"
        end = await _run_to_end(s, op.id)
        assert end.status == "done" and end.succeeded == 4
        refs = [c[2] for c in panel_api.calls if c[0] == "bulk"]
        flat = sum((list(r) for r in refs), [])
        assert flat.count("3") == flat.count("4") == 1  # the chunk that succeeded was never sent twice
        assert flat.count("1") == flat.count("2") == 2  # the rejected chunk was retried once by the resume


async def test_cancel_stops_a_confirmed_operation_before_anything_is_sent(panel_api):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        user, store, panel, _ = await _world(s, 2)
        op = await bulk.preview(s, kind="disable", selection=_sel(panel), reason="تعلیق", actor_id=user.id)
        await bulk.confirm(s, op.id, count=2, actor_id=user.id)
        await bulk.cancel(s, op.id, actor_id=user.id)
        assert await bulk.claim_next(s) is None and panel_api.calls == []
        with pytest.raises(AppError) as e:
            await bulk.cancel(s, op.id, actor_id=user.id)
        assert e.value.code == "BULK_FINISHED"


async def test_a_live_lease_blocks_a_second_runner(panel_api):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        user, store, panel, _ = await _world(s, 2)
        op = await bulk.preview(s, kind="disable", selection=_sel(panel), reason="تعلیق", actor_id=user.id)
        await bulk.confirm(s, op.id, count=2, actor_id=user.id)
        # An explicit clock: NOW is fixed at import time, so mixing it with the real clock made this test depend on suite duration.
        assert await bulk.claim_next(s, now=NOW) == op.id
        assert await bulk.claim_next(s, now=NOW) is None  # leased
        stale = NOW + dt.timedelta(minutes=10)
        assert await bulk.claim_next(s, now=stale) == op.id  # a crashed runner's lease expires


async def test_a_panel_without_the_capability_fails_cleanly_and_sends_nothing(monkeypatch):
    class Limited(FakePanel):
        def capabilities(self):
            return Capabilities(bulk_actions=False)

    fake = Limited()
    monkeypatch.setattr(bulk, "build_adapter", lambda panel, server=None: fake)
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        user, store, panel, _ = await _world(s, 2)
        op = await bulk.preview(s, kind="disable", selection=_sel(panel), reason="تعلیق", actor_id=user.id)
        await bulk.confirm(s, op.id, count=2, actor_id=user.id)
        end = await _run_to_end(s, op.id)
        assert end.status == "failed" and "capability" in (end.error or "") and fake.calls == []


# ------------------------------------------------------------------------------------------------------ absolute compensation
async def test_extend_days_writes_an_absolute_value_and_mirrors_it(panel_api):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        user, store, panel, accounts = await _world(s, 2)
        for a in accounts:
            panel_api.add(a.username)
        op = await bulk.preview(s, kind="extend_days", selection=_sel(panel), params={"days": 3}, reason="قطعی گروه", actor_id=user.id)
        await bulk.confirm(s, op.id, count=2, actor_id=user.id)
        end = await _run_to_end(s, op.id)
        assert end.status == "done"
        expect = NOW + dt.timedelta(days=13)
        for name in ("acc0", "acc1"):
            assert abs(panel_api.users[name].expire_at - expect) < dt.timedelta(seconds=2)
        row = await s.scalar(select(VpnAccount).where(VpnAccount.username == "acc0"))
        assert abs(row.sold_expires_at.replace(tzinfo=dt.UTC) - expect) < dt.timedelta(seconds=2)


async def test_extend_never_adds_twice_when_the_first_answer_was_lost(panel_api):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        user, store, panel, accounts = await _world(s, 1)
        panel_api.add("acc0")
        op = await bulk.preview(s, kind="extend_days", selection=_sel(panel), params={"days": 3}, reason="قطعی", actor_id=user.id)
        await bulk.confirm(s, op.id, count=1, actor_id=user.id)
        panel_api.apply_then_fail_extend = True
        panel_api.fail_next = [PanelError(ErrorKind.UNKNOWN, "timeout")]  # applied on the panel, answer lost
        claimed = await bulk.claim_next(s)
        mid = await bulk.execute(s, claimed, budget_seconds=5)
        assert mid.status == "confirmed"
        after_first = panel_api.users["acc0"].expire_at
        end = await _run_to_end(s, op.id)
        assert end.status == "done" and panel_api.users["acc0"].expire_at == after_first  # same value, not +3 days again
        assert [c[0] for c in panel_api.calls].count("extend") == 1


async def test_an_account_changed_on_the_panel_since_the_preview_is_skipped_not_overwritten(panel_api):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        user, store, panel, accounts = await _world(s, 2)
        panel_api.add("acc0")
        panel_api.add("acc1")
        op = await bulk.preview(s, kind="extend_days", selection=_sel(panel), params={"days": 2}, reason="قطعی", actor_id=user.id)
        await bulk.confirm(s, op.id, count=2, actor_id=user.id)
        manual = NOW + dt.timedelta(days=40)
        panel_api.users["acc1"].expire_at = manual  # someone edited it in the panel meanwhile
        end = await _run_to_end(s, op.id)
        items = await _items(s, end)
        assert items["acc0"].status == "done" and items["acc1"].status == "skipped"
        assert panel_api.users["acc1"].expire_at == manual and end.status == "done" and end.skipped == 1


async def test_add_traffic_is_absolute_and_idempotent(panel_api):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        user, store, panel, _ = await _world(s, 1)
        panel_api.add("acc0")
        op = await bulk.preview(s, kind="add_traffic", selection=_sel(panel), params={"gb": 5}, reason="جبران حجم", actor_id=user.id)
        await bulk.confirm(s, op.id, count=1, actor_id=user.id)
        end = await _run_to_end(s, op.id)
        assert end.status == "done" and panel_api.users["acc0"].traffic_limit_bytes == 15 * GIB
        item = (await _items(s, end))["acc0"]
        item.status = "pending"  # a forced replay must find the panel already at the target and write nothing
        end.status = "confirmed"
        await s.commit()
        before = [c for c in panel_api.calls if c[0] == "extend"]
        await _run_to_end(s, op.id)
        assert [c for c in panel_api.calls if c[0] == "extend"] == before and panel_api.users["acc0"].traffic_limit_bytes == 15 * GIB


# ------------------------------------------------------------------------------------------------------------- store state
async def test_store_suspension_disables_only_active_accounts_and_reactivation_restores_only_those(panel_api):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        user, store, panel, accounts = await _world(s, 3, suspend_policy="disable_accounts")
        accounts[2].status = VpnStatus.SUSPENDED  # its owner suspended it long before
        await s.commit()
        ops = await bulk.plan_store_state(s, store, suspend=True, actor_id=user.id)
        assert len(ops) == 1 and ops[0].status == "confirmed" and ops[0].origin == "store_state" and ops[0].total == 2
        await _run_to_end(s, ops[0].id)
        rows = {a.username: a for a in (await s.scalars(select(VpnAccount))).all()}
        assert all(a.status == VpnStatus.SUSPENDED for a in rows.values())
        back = await bulk.plan_store_state(s, store, suspend=False, actor_id=user.id)
        assert len(back) == 1 and back[0].kind == "enable" and back[0].total == 2
        await _run_to_end(s, back[0].id)
        rows = {a.username: a for a in (await s.scalars(select(VpnAccount))).all()}
        assert rows["acc0"].status == rows["acc1"].status == VpnStatus.ACTIVE
        assert rows["acc2"].status == VpnStatus.SUSPENDED  # never switched back on by the store's reactivation


async def test_store_suspension_does_nothing_unless_the_store_opted_in(panel_api):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        user, store, panel, _ = await _world(s, 2, suspend_policy="none")
        assert await bulk.plan_store_state(s, store, suspend=True, actor_id=user.id) == []
        assert (await s.scalars(select(BulkOperation))).all() == []
        _ = uuid.uuid4()
