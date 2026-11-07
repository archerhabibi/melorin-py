"""PasarGuard Phase 3 / PG-09: panel templates managed from Melorin, prepaid renewal (``next_plan``) and plan change.

Rules under test: Melorin edits only templates it created; a package without a mapped template (or a panel without the
capability) never offers a prepaid renewal and is refused BEFORE any money moves; a prepaid renewal never touches the
running package; a timed-out queue call is settled without paying twice; the queue slot is released when the panel starts
the package; a refunded prepaid renewal takes back only the queued package; plan change is admin-only and audited."""

from __future__ import annotations

import datetime as dt
import itertools
import types

import pytest
from sqlalchemy import select

from _db import make_user, open_session
from melorin.core import codes
from melorin.core.errors import AppError
from melorin.kernel.models.catalog import Product
from melorin.kernel.models.orders import Order
from melorin.kernel.models.system import AuditEvent, OutboxEvent
from melorin.kernel.models.vpn import ProductTemplate
from melorin.modules.orders import provisioning as vpn
from melorin.modules.orders import service as orders
from melorin.modules.vpn import plans, sync, templates
from melorin.modules.vpn.adapters.base import Capabilities, ErrorKind, PanelAccount, PanelError
from test_renewal_core import _balance, _world  # the shared renewal world: wallet, bundle, panel, account

GIB = 1024**3
NOW = dt.datetime.now(dt.UTC)
FLAGS = Capabilities(suspend=True, extend=True, subscription_url=True, traffic_reset=True, template_ops=True, next_plan_ops=True).to_dict()


@pytest.fixture(autouse=True)
def _sqlite_order_numbers(monkeypatch):
    counter = itertools.count(1)

    async def next_code(session, sequence):
        return f"Q{next(counter):05d}"

    monkeypatch.setattr(codes, "next_code", next_code)


# ---------------------------------------------------------------------------------------------------------------- fakes
class FakeAdapter:
    """One panel: templates + one account with an optional queued plan. ``fail`` raises on the next call of that name."""

    kind = "pasarguard"

    def __init__(self, *, caps=None, expire_days=10):
        self.caps = caps or Capabilities(template_ops=True, next_plan_ops=True, extend=True)
        self.calls: list[tuple] = []
        self.fail: dict[str, PanelError] = {}
        self.echo_next_plan = True
        self.templates: dict[int, dict] = {}
        self.next_id = 7
        self.state = PanelAccount(
            ref="r", username="acc_1", status="active", remote_status="active", expire_at=NOW + dt.timedelta(days=expire_days),
            traffic_limit_bytes=10 * GIB, traffic_used_bytes=GIB, subscription_url="https://sub.test/x", links=[],
            next_plan=None, next_plan_reported=True,
        )  # fmt: skip

    def capabilities(self):
        return self.caps

    def _go(self, name, *args):
        self.calls.append((name, *args))
        if name in self.fail:
            raise self.fail.pop(name)

    # templates
    async def list_templates(self):
        self._go("list_templates")
        return [dict(t) for t in self.templates.values()]

    async def create_template(self, spec):
        self._go("create_template", spec["name"])
        tid, self.next_id = self.next_id, self.next_id + 1
        self.templates[tid] = {"id": tid, **spec}
        return {"id": tid, **spec}

    async def update_template(self, template_id, spec):
        self._go("update_template", template_id)
        self.templates[template_id].update(spec)
        return self.templates[template_id]

    async def set_template_disabled(self, template_id, disabled):
        self._go("disable" if disabled else "enable", template_id)
        return {}

    # next plan
    async def set_next_plan(self, username, *, template_id, add_remaining_traffic=False):
        self._go("set_next_plan", template_id)
        self.state.next_plan = {"user_template_id": template_id, "add_remaining_traffic": add_remaining_traffic} if self.echo_next_plan else None
        return self.state

    async def clear_next_plan(self, username):
        self._go("clear_next_plan")
        self.state.next_plan = None
        return self.state

    async def activate_next_plan(self, username):
        self._go("activate_next")
        return self.state

    async def apply_template(self, username, template_id):
        self._go("apply_template", template_id)
        self.state.expire_at, self.state.traffic_limit_bytes, self.state.traffic_used_bytes = NOW + dt.timedelta(days=90), 50 * GIB, 0
        return self.state

    async def get_account(self, username):
        self._go("get_account")
        return self.state

    async def extend_account(self, username, *, expire_at, traffic_bytes):
        self._go("extend")
        self.state.expire_at, self.state.traffic_limit_bytes = expire_at, traffic_bytes
        return self.state

    async def close(self):
        pass


@pytest.fixture
def adapter(monkeypatch):
    fake = FakeAdapter()
    for module in (templates, plans, vpn):
        monkeypatch.setattr(module, "build_adapter", lambda panel, server=None: fake)
    monkeypatch.setattr(plans, "seed_adapter", lambda a, acc: a)
    monkeypatch.setattr(vpn, "seed_adapter", lambda a, acc: a)
    return fake


async def _prepare(s, **world_kw):
    """The renewal world, with an ACTIVE account that has 10 days left on a panel that can queue, plus a mapped template."""
    t = await _world(s, expired_days_ago=-10, status="active", **world_kw)
    t.panel.kind, t.panel.capabilities = "pasarguard", {"flags": FLAGS}
    t.account.remote_status = "active"
    s.add(ProductTemplate(panel_id=t.panel.id, product_id=t.product.id, remote_template_id=7, name="melorin-x", managed=True))
    await s.commit()
    return t


async def _audits(s, action):
    return list(await s.scalars(select(AuditEvent).where(AuditEvent.action == action)))


# ------------------------------------------------------------------------------------------------------------ spec rules
def test_spec_equals_the_package_and_validation_refuses_nonsense():
    p = Product(code="gold 30!", name="Gold", duration_days=30, traffic_gb=50, max_devices=2, main_price=1, reseller_price=1)
    spec = templates.spec_for(p, [2, 3])
    assert spec == {"name": "melorin-gold-30-", "group_ids": [2, 3], "data_limit": 50 * GIB, "expire_duration": 30 * 86400, "status": "active", "hwid_limit": 2}
    templates.validate_spec(spec)
    for bad in ({**spec, "group_ids": []}, {**spec, "expire_duration": 0}, {**spec, "name": ""}, {**spec, "hwid_limit": 1000}, {**spec, "expire_duration": 4000 * 86400}):
        with pytest.raises(AppError) as e:
            templates.validate_spec(bad)
        assert e.value.code == "BAD_TEMPLATE" and e.value.status == 400
    unlimited = templates.spec_for(Product(code="u", name="U", duration_days=30, traffic_gb=0, main_price=1, reseller_price=1), [1])
    assert unlimited["data_limit"] == 0 and "hwid_limit" not in unlimited


def test_drift_reports_only_what_differs_and_ignores_group_order():
    spec = {"data_limit": 5, "expire_duration": 86400, "group_ids": [1, 2]}
    assert templates.drift(spec, {"data_limit": 5, "expire_duration": 86400, "group_ids": [2, 1]}) == {}
    assert set(templates.drift(spec, {"data_limit": 6, "expire_duration": 86400, "group_ids": [1]})) == {"data_limit", "group_ids"}


# ------------------------------------------------------------------------------------------------------------ templates
async def test_create_maps_the_package_once_and_repeating_makes_no_second_template(adapter):
    async with open_session() as s:
        t = await _prepare(s)
        s.add(ProductTemplate(panel_id=t.panel.id, product_id=t.other.id, remote_template_id=1))  # noise: another package
        await s.execute(ProductTemplate.__table__.delete().where(ProductTemplate.product_id == t.product.id))
        t.panel.config = {"group_ids": [2]}
        await s.commit()
        admin = await make_user(s, super_admin=True)
        first = await templates.create_for_product(s, t.panel, t.product, admin_id=admin.id)
        again = await templates.create_for_product(s, t.panel, t.product, admin_id=admin.id)
        assert first.id == again.id and first.managed and [c[0] for c in adapter.calls].count("create_template") == 1
        assert adapter.templates[first.remote_template_id]["group_ids"] == [2]
        assert len(await _audits(s, "panel_template.created")) == 1


async def test_a_panel_without_template_ops_is_refused_and_never_called(adapter):
    async with open_session() as s:
        t = await _prepare(s)
        t.panel.capabilities = {"flags": Capabilities(extend=True).to_dict()}
        admin = await make_user(s, super_admin=True)
        with pytest.raises(AppError) as e:
            await templates.create_for_product(s, t.panel, t.other, admin_id=admin.id)
        assert e.value.code == "TEMPLATES_UNSUPPORTED" and e.value.status == 409 and adapter.calls == []


async def test_linked_templates_are_never_modified_but_managed_ones_are_synced_idempotently(adapter):
    async with open_session() as s:
        t = await _prepare(s)
        admin = await make_user(s, super_admin=True)
        adapter.templates[7] = {"id": 7, "name": "melorin-x", "group_ids": [2], "data_limit": 1, "expire_duration": 86400}
        # managed: drift is fixed once, a second sync changes nothing
        first = await templates.sync_product(s, t.panel, t.product, admin_id=admin.id)
        assert set(first["changed"]) >= {"data_limit", "expire_duration"}
        calls = len(adapter.calls)
        second = await templates.sync_product(s, t.panel, t.product, admin_id=admin.id)
        assert second["changed"] == {} and [c[0] for c in adapter.calls[calls:]].count("update_template") == 0
        # linked: refused
        adapter.templates[9] = {"id": 9, "name": "hand-made", "group_ids": [2]}
        row = await templates.link_existing(s, t.panel, t.product, 9, admin_id=admin.id)
        assert not row.managed and row.remote_template_id == 9
        with pytest.raises(AppError) as e:
            await templates.sync_product(s, t.panel, t.product, admin_id=admin.id)
        assert e.value.code == "TEMPLATE_NOT_MANAGED"
        with pytest.raises(AppError) as e:
            await templates.link_existing(s, t.panel, t.product, 404, admin_id=admin.id)
        assert e.value.code == "TEMPLATE_NOT_FOUND" and e.value.status == 404


async def test_overview_lists_drift_and_templates_nobody_maps(adapter):
    async with open_session() as s:
        t = await _prepare(s)
        adapter.templates[7] = {"id": 7, "name": "melorin-x", "group_ids": [2], "data_limit": 1, "expire_duration": 1}
        adapter.templates[8] = {"id": 8, "name": "stray"}
        out = await templates.overview(s, t.panel)
        assert out["unmapped"] == [{"id": 8, "name": "stray"}]
        (row,) = out["mappings"]
        assert row["exists_on_panel"] is True and "data_limit" in row["drift"]
        adapter.templates.pop(7)
        assert (await templates.overview(s, t.panel))["mappings"][0]["exists_on_panel"] is False


async def test_a_panel_error_becomes_a_safe_client_error(adapter):
    async with open_session() as s:
        t = await _prepare(s)
        await s.execute(ProductTemplate.__table__.delete())
        admin = await make_user(s, super_admin=True)
        adapter.fail["create_template"] = PanelError(ErrorKind.TRANSIENT, "boom 10.0.0.5")
        with pytest.raises(AppError) as e:
            await templates.create_for_product(s, t.panel, t.product, admin_id=admin.id, group_ids=[2])
        assert e.value.code == "PANEL_UNAVAILABLE" and e.value.status == 503 and "10.0.0.5" not in e.value.message


# ------------------------------------------------------------------------------------------------------------ queue rules
async def test_queue_is_offered_only_for_a_running_account_on_a_capable_panel_with_a_mapped_template(adapter):
    async with open_session() as s:
        t = await _prepare(s)
        ok = await plans.check_queueable(s, t.account, t.product, now=NOW)
        assert ok.ok and ok.template_id == 7
        t.account.queued_plan = {"template_id": 7}
        assert (await plans.check_queueable(s, t.account, t.product, now=NOW)).code == "RENEWAL_ALREADY_QUEUED"
        t.account.queued_plan = None
        for mutate, code in (
            (lambda: setattr(t.account, "status", "expired"), "QUEUE_NOT_APPLICABLE"),
            (lambda: setattr(t.account, "status", "limited"), "QUEUE_NOT_APPLICABLE"),
        ):
            mutate()
            assert (await plans.check_queueable(s, t.account, t.product, now=NOW)).code == code
        t.account.status = "active"
        t.account.remote_status = "on_hold"
        assert (await plans.check_queueable(s, t.account, t.product, now=NOW)).code == "QUEUE_NOT_APPLICABLE"
        t.account.remote_status, t.account.expires_at = "active", NOW - dt.timedelta(minutes=1)
        assert (await plans.check_queueable(s, t.account, t.product, now=NOW)).code == "QUEUE_NOT_APPLICABLE"
        t.account.expires_at = NOW + dt.timedelta(days=3)
        t.panel.capabilities = {"flags": Capabilities(extend=True).to_dict()}
        assert (await plans.check_queueable(s, t.account, t.product, now=NOW)).code == "QUEUE_UNSUPPORTED"
        t.panel.capabilities = {"flags": FLAGS}
        await s.execute(ProductTemplate.__table__.delete())
        assert (await plans.check_queueable(s, t.account, t.product, now=NOW)).code == "QUEUE_NO_TEMPLATE"


async def test_the_promise_never_invents_a_start_date_and_keeps_the_days_left(adapter):
    async with open_session() as s:
        t = await _prepare(s)
        d = plans.describe_queue(t.account, t.product, now=NOW)
        assert d["starts"] == "when_current_ends" and d["mode"] == "queue"
        assert d["remaining_days_kept"] in (9, 10) and d["duration_days"] == t.product.duration_days
        assert d["earliest_end_estimate"] - d["current_expires_at"] == dt.timedelta(days=t.product.duration_days)
    assert plans.normalize_mode(None) == "replace" and plans.normalize_mode(" QUEUE ") == "queue"
    with pytest.raises(AppError) as e:
        plans.normalize_mode("append")
    assert e.value.code == "BAD_RENEWAL_MODE"


async def test_apply_queue_trusts_only_what_the_panel_shows(adapter):
    async with open_session() as s:
        t = await _prepare(s)
        pa = await plans.apply_queue(adapter, t.account, 7)
        assert plans.queued_landed(pa, 7) and not plans.queued_landed(pa, 8)
        adapter.state.next_plan, adapter.echo_next_plan = None, False
        with pytest.raises(PanelError) as e:  # the panel accepted the call but does not show the plan: never report success
            await plans.apply_queue(adapter, t.account, 7)
        assert e.value.kind == ErrorKind.TRANSIENT


def test_a_panel_that_does_not_report_next_plan_never_says_nothing_is_queued():
    remote = PanelAccount(ref="r", username="a", status="active", expire_at=None, traffic_limit_bytes=0, traffic_used_bytes=0, next_plan_reported=False)
    assert not plans.queued_landed(remote, 7)


async def test_the_slot_is_released_only_when_the_panel_reports_nothing_queued(adapter):
    async with open_session() as s:
        t = await _prepare(s)
        plans.mark_queued(t.account, template_id=7, product_id=t.product.id, order_id=t.account.order_id, now=NOW)
        t.account.near_expiry_notified, t.account.traffic_notified_level = True, 90
        still = PanelAccount(ref="r", username="a", status="active", expire_at=None, traffic_limit_bytes=0, traffic_used_bytes=0, next_plan={"user_template_id": 7}, next_plan_reported=True)
        unknown = PanelAccount(ref="r", username="a", status="active", expire_at=None, traffic_limit_bytes=0, traffic_used_bytes=0, next_plan=None, next_plan_reported=False)
        assert not await plans.settle_from_remote(s, t.account, still) and not await plans.settle_from_remote(s, t.account, unknown)
        assert t.account.queued_plan is not None
        started = PanelAccount(ref="r", username="a", status="active", expire_at=None, traffic_limit_bytes=0, traffic_used_bytes=0, next_plan=None, next_plan_reported=True)
        assert await plans.settle_from_remote(s, t.account, started)
        assert t.account.queued_plan is None and not t.account.near_expiry_notified and t.account.traffic_notified_level == 0
        assert len(await _audits(s, "vpn_account.queued_plan_started")) == 1
        topics = (await s.scalars(select(OutboxEvent.payload))).all()
        assert any("vpn_queued_plan_started" in str(p) for p in topics)


async def test_sync_releases_the_slot_through_apply_remote(adapter):
    async with open_session() as s:
        t = await _prepare(s)
        plans.mark_queued(t.account, template_id=7, product_id=t.product.id, order_id=t.account.order_id, now=NOW)
        remote = PanelAccount(
            ref="r", username="acc_1", status="active", remote_status="active", expire_at=NOW + dt.timedelta(days=30),
            traffic_limit_bytes=10 * GIB, traffic_used_bytes=0, next_plan=None, next_plan_reported=True,
        )  # fmt: skip
        await sync.apply_remote(s, t.account, remote, now=NOW)
        assert t.account.queued_plan is None


# ------------------------------------------------------------------------------------------------------------ orders
async def _queue_order(s, t, key="k1"):
    return await orders.create_order(
        s, t.ctx, product_id=t.product.id, idempotency_key=key, kind="renewal", vpn_account_id=t.account.id, channel="web", renewal_mode="queue"
    )


async def test_a_prepaid_order_is_priced_like_a_renewal_and_carries_the_template(adapter):
    async with open_session() as s:
        t = await _prepare(s)
        o = await _queue_order(s, t)
        assert o.kind == "renewal" and o.renewal_mode == "queue" and o.total == 2_000
        assert o.pricing_snapshot["renewal_queue"] == {"template_id": 7} and o.pricing_snapshot["renewal"]["mode"] == "queue"
        assert await _balance(s, t) == 50_000 - 2_000


async def test_a_prepaid_order_is_refused_before_money_moves_when_it_cannot_be_queued(adapter):
    async with open_session() as s:
        t = await _prepare(s)
        await s.execute(ProductTemplate.__table__.delete())
        await s.commit()
        with pytest.raises(AppError) as e:
            await _queue_order(s, t)
        assert e.value.code == "QUEUE_NO_TEMPLATE" and e.value.status == 409
        assert await _balance(s, t) == 50_000
        assert (await s.scalars(select(Order).where(Order.kind == "renewal"))).all() == []


async def test_queue_mode_is_meaningless_for_a_purchase_and_unknown_modes_are_refused(adapter):
    async with open_session() as s:
        t = await _prepare(s)
        for kind, mode, code in (("purchase", "queue", "BAD_RENEWAL_MODE"), ("renewal", "append", "BAD_RENEWAL_MODE")):
            with pytest.raises(AppError) as e:
                await orders.create_order(
                    s, t.ctx, product_id=t.product.id, idempotency_key=f"x{mode}{kind}", kind=kind, vpn_account_id=t.account.id,
                    channel="web", renewal_mode=mode,
                )  # fmt: skip
            assert e.value.code == code and e.value.status == 400
        assert await _balance(s, t) == 50_000


async def test_the_same_idempotency_key_cannot_switch_the_renewal_mode(adapter):
    async with open_session() as s:
        t = await _prepare(s)
        first = await _queue_order(s, t, key="same-key")
        assert (await _queue_order(s, t, key="same-key")).id == first.id
        with pytest.raises(AppError) as e:
            await orders.create_order(
                s, t.ctx, product_id=t.product.id, idempotency_key="same-key", kind="renewal", vpn_account_id=t.account.id, channel="web"
            )
        assert e.value.code == "IDEMPOTENCY_KEY_REUSE"


async def test_provisioning_a_prepaid_order_queues_the_package_and_leaves_the_running_one_alone(adapter):
    async with open_session() as s:
        t = await _prepare(s)
        t.account.near_expiry_notified = True  # the CURRENT period was already warned about: a queue must not reset that
        o = await _queue_order(s, t)
        before = (t.account.expires_at, t.account.traffic_limit_bytes)
        adapter.state.expire_at = t.account.expires_at
        result = await vpn.provision_order(s, o.id)
        assert result == "completed", o.last_error
        names = [c[0] for c in adapter.calls]
        assert "set_next_plan" in names and "extend" not in names and "reset_traffic" not in names
        await s.refresh(t.account)
        assert t.account.queued_plan["template_id"] == 7 and t.account.queued_plan["order_id"] == str(o.id)
        assert t.account.near_expiry_notified is True
        assert (t.account.expires_at, t.account.traffic_limit_bytes) == (adapter.state.expire_at, adapter.state.traffic_limit_bytes)
        assert t.account.traffic_limit_bytes == before[1]


async def test_a_timed_out_queue_call_that_really_landed_is_settled_without_a_second_attempt(adapter):
    async with open_session() as s:
        t = await _prepare(s)
        o = await _queue_order(s, t)
        adapter.fail["set_next_plan"] = PanelError(ErrorKind.UNKNOWN, "timeout")
        adapter.state.next_plan = {"user_template_id": 7}  # the panel did queue it before the connection died
        assert await vpn.provision_order(s, o.id) == "completed_after_reconcile"
        await s.refresh(t.account)
        assert t.account.queued_plan["template_id"] == 7 and o.status == "completed"


async def test_a_timed_out_queue_call_that_did_not_land_is_retried_not_reported_done(adapter):
    async with open_session() as s:
        t = await _prepare(s)
        o = await _queue_order(s, t)
        adapter.fail["set_next_plan"] = PanelError(ErrorKind.UNKNOWN, "timeout")
        assert await vpn.provision_order(s, o.id) != "completed_after_reconcile"
        await s.refresh(t.account)
        assert t.account.queued_plan is None and o.status != "completed"


async def test_refunding_a_prepaid_order_takes_back_only_the_queued_package(adapter):
    from melorin.worker import runner

    async with open_session() as s:
        t = await _prepare(s)
        o = await _queue_order(s, t)
        await vpn.provision_order(s, o.id)
        await s.refresh(t.account)
        assert t.account.queued_plan is not None
        adapter.calls.clear()
        monkey_build = lambda panel, server=None: adapter  # noqa: E731
        runner.build_adapter, runner.seed_adapter = monkey_build, lambda a, acc: a
        await runner.rollback_renewal(s, {"vpn_account_id": t.account.id, "before": {"expires_at": None, "traffic_limit_bytes": 0}, "mode": "queue"})
        assert [c[0] for c in adapter.calls] == ["clear_next_plan"]  # the running package is NOT re-extended
        await s.refresh(t.account)
        assert t.account.queued_plan is None
        adapter.calls.clear()  # nothing queued any more (it already started): nothing to undo on the panel
        await runner.rollback_renewal(s, {"vpn_account_id": t.account.id, "before": {}, "mode": "queue"})
        assert adapter.calls == []


# ------------------------------------------------------------------------------------------------------------ plan change
async def test_change_plan_is_admin_only_needs_a_reason_and_a_mapped_template(adapter):
    async with open_session() as s:
        t = await _prepare(s)
        admin = await make_user(s, super_admin=True)
        for role in ("owner", "customer"):
            with pytest.raises(AppError) as e:
                await plans.change_plan(s, t.account, t.other, admin_id=admin.id, reason="upgrade", role=role)
            assert e.value.status == 403
        with pytest.raises(AppError) as e:
            await plans.change_plan(s, t.account, t.other, admin_id=admin.id, reason=" ")
        assert e.value.code == "REASON_REQUIRED"
        with pytest.raises(AppError) as e:
            await plans.change_plan(s, t.account, t.product, admin_id=admin.id, reason="same one")
        assert e.value.code == "SAME_PLAN"
        with pytest.raises(AppError) as e:
            await plans.change_plan(s, t.account, t.other, admin_id=admin.id, reason="no template yet")
        assert e.value.code == "QUEUE_NO_TEMPLATE"
        assert adapter.calls == [] and t.account.product_id == t.product.id


async def test_change_plan_moves_the_account_drops_the_queue_and_is_audited(adapter):
    async with open_session() as s:
        t = await _prepare(s)
        admin = await make_user(s, super_admin=True)
        s.add(ProductTemplate(panel_id=t.panel.id, product_id=t.other.id, remote_template_id=12))
        plans.mark_queued(t.account, template_id=7, product_id=t.product.id, order_id=t.account.order_id, now=NOW)
        adapter.state.next_plan = {"user_template_id": 7}
        await s.commit()
        account = await plans.change_plan(s, t.account, t.other, admin_id=admin.id, reason="customer upgraded by phone")
        assert account.product_id == t.other.id and account.queued_plan is None
        assert account.traffic_limit_bytes == 50 * GIB and account.traffic_used_bytes == 0
        assert [c[0] for c in adapter.calls if c[0] in ("apply_template", "clear_next_plan")] == ["apply_template", "clear_next_plan"]
        (audit,) = await _audits(s, "vpn_account.plan_changed")
        assert audit.data["reason"] == "customer upgraded by phone" and audit.data["template_id"] == 12 and audit.data["to_product"] == str(t.other.id)
        assert audit.data["before"]["product_id"] == str(t.product.id)


async def test_change_plan_refuses_a_revoked_account(adapter):
    async with open_session() as s:
        t = await _prepare(s)
        admin = await make_user(s, super_admin=True)
        t.account.status = "revoked"
        with pytest.raises(AppError) as e:
            await plans.change_plan(s, t.account, t.other, admin_id=admin.id, reason="support")
        assert e.value.code == "TOOL_UNAVAILABLE" and adapter.calls == []


# ------------------------------------------------------------------------------------------------------------ HTTP surface
def test_admin_template_routes_exist_and_are_admin_guarded():
    from melorin.modules.admin.router import router

    paths = {(m, r.path) for r in router.routes for m in getattr(r, "methods", ())}
    for method, path in (
        ("GET", "/admin/panels/{panel_id}/templates"),
        ("POST", "/admin/panels/{panel_id}/templates"),
        ("POST", "/admin/panels/{panel_id}/templates/link"),
        ("POST", "/admin/panels/{panel_id}/templates/{product_id}/sync"),
        ("DELETE", "/admin/panels/{panel_id}/templates/{product_id}"),
        ("POST", "/admin/vpn-accounts/{account_id}/change-plan"),
    ):
        assert (method, path) in paths


def test_the_account_output_tells_every_channel_that_a_package_is_waiting():
    from melorin.modules.vpn import inquiry

    acc = types.SimpleNamespace(
        id=__import__("uuid").uuid4(), username="a", status="active", is_test=False, expires_at=NOW + dt.timedelta(days=3),
        traffic_limit_bytes=GIB, traffic_used_bytes=0, subscription_url=None, links=[], server_id=None, store_id=None,
        created_at=NOW, updated_at=NOW, archived_at=None, queued_plan={"template_id": 7, "queued_at": NOW.isoformat()},
    )  # fmt: skip
    out = inquiry.account_out(acc, NOW)
    assert out.next_plan_queued is True and out.next_plan_queued_at == NOW
    acc.queued_plan = None
    assert inquiry.account_out(acc, NOW).next_plan_queued is False
