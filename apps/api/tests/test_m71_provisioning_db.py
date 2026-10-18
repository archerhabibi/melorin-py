"""M7.1: provisioning failure/retry through ``provision_order`` with a scripted fake panel adapter.

Covers success, transient failure -> retry scheduled, retries exhausted -> automatic refund, permanent allocation
failure, timeout reconcile (no duplicate account), duplicate worker claim and renewal on the existing panel account."""

import datetime as dt
import uuid

import pytest
from sqlalchemy import select

from _db import make_order, make_product, make_store, make_user, open_session
from melorin.modules.orders.models import Order
from melorin.modules.system.models import AuditEvent, OutboxEvent
from melorin.modules.vpn import service as vpn
from melorin.modules.vpn.adapters.base import AccountSpec, ErrorKind, PanelAccount, PanelError
from melorin.modules.vpn.bundles import Bundle, BundleMember, BundleProduct
from melorin.modules.vpn.models import Panel, ProvisioningAttempt, Server, VpnAccount
from melorin.modules.wallet import service as wallet


class ScriptedPanel:
    """Each create/extend call pops the next scripted outcome (an exception to raise or ``None`` for success)."""

    kind = "scripted"

    def __init__(self, script=(), remote=None):
        self.script = list(script)
        self.remote = remote
        self.created: list[AccountSpec] = []
        self.extended: list[tuple] = []

    def _next(self):
        step = self.script.pop(0) if self.script else None
        if step is not None:
            raise step

    def _account(self, username, expire=None, traffic=0):
        return PanelAccount(
            ref=f"ref-{username}",
            username=username,
            status="active",
            expire_at=expire or dt.datetime.now(dt.UTC) + dt.timedelta(days=30),
            traffic_limit_bytes=traffic,
            traffic_used_bytes=0,
            subscription_url=f"https://sub.test/{username}",
            links=["vless://x"],
        )

    async def create_account(self, spec):
        self._next()
        self.created.append(spec)
        return self._account(spec.username, spec.expire_at, spec.traffic_bytes)

    async def extend_account(self, username, *, expire_at, traffic_bytes):
        self._next()
        self.extended.append((username, expire_at, traffic_bytes))
        return self._account(username, expire_at, traffic_bytes)

    async def get_account(self, username):
        return self.remote

    async def close(self):
        return None


@pytest.fixture
def panel_factory(monkeypatch):
    holder = {}

    def install(panel: ScriptedPanel):
        holder["panel"] = panel
        monkeypatch.setattr(vpn, "build_adapter", lambda _panel: panel)
        return panel

    return install


async def _world(s, *, order_status="paid", balance=2_000, with_server=True):
    store, user, product = await make_store(s), await make_user(s), await make_product(s, price=2_000)
    group = Bundle(name="G", selection_mode="automatic", is_enabled=True)
    panel = Panel(name="P1", kind="mock", base_url="http://x", is_enabled=True, health_status="healthy")
    s.add_all([group, panel])
    await s.flush()
    s.add(BundleMember(bundle_id=group.id, panel_id=panel.id, sort=0))
    s.add(BundleProduct(bundle_id=group.id, product_id=product.id))
    server = Server(name="S1", panel_id=panel.id) if with_server else None
    if server:
        s.add(server)
    w = await wallet.get_wallet(s, user.id, store.id)
    await wallet.post(
        s,
        kind="topup",
        key="seed",
        currency="IRT",
        postings=[wallet.Posting(-balance, account="gateway:test:clearing"), wallet.Posting(balance, wallet=w)],
    )
    order = await make_order(s, user=user, store=store, product=product, total=2_000, status="pending")
    order.bundle_id = group.id
    from melorin.modules.orders import service as orders

    await orders.pay_with_wallet(s, order, store)
    if order_status != "paid":
        order.status = order_status
    await s.commit()
    return dict(store=store, user=user, product=product, group=group, panel=panel, server=server, wallet=w, order=order)


async def _topics(s):
    return (await s.scalars(select(OutboxEvent.topic))).all()


async def test_successful_provisioning_completes_the_order_and_activates_the_account(panel_factory):
    async with open_session() as s:
        w = await _world(s)
        panel = panel_factory(ScriptedPanel())
        assert await vpn.provision_order(s, w["order"].id) == "completed"
        order = await s.get(Order, w["order"].id)
        acc = await s.get(VpnAccount, order.vpn_account_id)
        assert order.status == "completed" and order.provisioning_attempts == 1 and order.completed_at is not None
        assert acc.status == "active" and acc.panel_ref and acc.subscription_url
        assert acc.traffic_limit_bytes == w["product"].traffic_gb * 1024**3
        assert len(panel.created) == 1
        topics = await _topics(s)
        assert "order.completed" in topics and "order.delivery" in topics
        attempt = await s.scalar(select(ProvisioningAttempt))
        assert (attempt.status, attempt.action) == ("succeeded", "create")


async def test_second_run_after_completion_is_ignored_and_never_creates_a_second_account(panel_factory):
    async with open_session() as s:
        w = await _world(s)
        panel = panel_factory(ScriptedPanel())
        await vpn.provision_order(s, w["order"].id)
        assert await vpn.provision_order(s, w["order"].id) == "ignored"
        assert len(panel.created) == 1


async def test_missing_order_is_reported_not_raised(panel_factory):
    import uuid

    async with open_session() as s:
        await _world(s)
        assert await vpn.provision_order(s, uuid.uuid4()) == "missing"


async def test_fresh_provisioning_claim_blocks_a_second_worker_but_a_stale_one_is_taken_over(panel_factory):
    async with open_session() as s:
        w = await _world(s)
        panel_factory(ScriptedPanel())
        order = await s.get(Order, w["order"].id)
        order.status = "provisioning"
        order.updated_at = dt.datetime.now(dt.UTC)
        await s.commit()
        assert await vpn.provision_order(s, order.id) == "already_claimed"
        order.updated_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=16)
        await s.commit()
        assert await vpn.provision_order(s, order.id) == "completed"


async def test_transient_panel_error_schedules_a_delayed_retry_and_keeps_the_money(panel_factory):
    async with open_session() as s:
        w = await _world(s)
        panel_factory(ScriptedPanel([PanelError(ErrorKind.TRANSIENT, "502 from panel")]))
        assert await vpn.provision_order(s, w["order"].id) == "retry_scheduled"
        order = await s.get(Order, w["order"].id)
        assert order.status == "processing" and order.last_error == "502 from panel" and order.provisioning_attempts == 1
        retry = await s.scalar(select(OutboxEvent).where(OutboxEvent.dedup_key == f"provision:{order.id}:1"))
        assert retry is not None and retry.available_at > dt.datetime.now(dt.UTC).replace(tzinfo=retry.available_at.tzinfo) - dt.timedelta(
            seconds=1
        )
        assert w["wallet"].balance == 0  # paid, not refunded yet
        stub = await s.scalar(select(VpnAccount))
        assert stub.status == "archived" and stub.username.endswith("_r1")  # stub archived so the retry can reuse the name


async def test_retry_after_a_transient_failure_succeeds_without_duplicate_accounts(panel_factory):
    async with open_session() as s:
        w = await _world(s)
        panel = panel_factory(ScriptedPanel([PanelError(ErrorKind.TRANSIENT, "timeout")]))
        assert await vpn.provision_order(s, w["order"].id) == "retry_scheduled"
        assert await vpn.provision_order(s, w["order"].id) == "completed"
        order = await s.get(Order, w["order"].id)
        accounts = (await s.scalars(select(VpnAccount).where(VpnAccount.status == "active"))).all()
        assert order.status == "completed" and order.provisioning_attempts == 2 and len(accounts) == 1
        assert len(panel.created) == 1 and order.last_error is None


async def test_exhausted_retries_trigger_an_automatic_refund_and_an_admin_notification(panel_factory):
    async with open_session() as s:
        w = await _world(s)
        panel_factory(ScriptedPanel([PanelError(ErrorKind.TRANSIENT, f"down {i}") for i in range(4)]))
        results = [await vpn.provision_order(s, w["order"].id) for _ in range(4)]
        assert results == ["retry_scheduled", "retry_scheduled", "retry_scheduled", "refunded"]
        order = await s.get(Order, w["order"].id)
        await s.refresh(w["wallet"])
        assert order.status == "refunded" and order.provisioning_attempts == 4 and order.needs_review is True
        assert w["wallet"].balance == 2_000
        topics = await _topics(s)
        assert "provisioning.failed" in topics and "order.refunded" in topics
        assert await wallet.find_tx(s, f"order:{order.id}:refund") is not None


async def test_no_compatible_server_is_retried_then_refunded(panel_factory):
    async with open_session() as s:
        w = await _world(s, with_server=False)
        panel_factory(ScriptedPanel())
        results = [await vpn.provision_order(s, w["order"].id) for _ in range(4)]
        assert results[-1] == "refunded" and results[0] == "retry_scheduled"
        order = await s.get(Order, w["order"].id)
        assert "no healthy compatible server" in (order.last_error or "") or order.last_error


async def test_unexpected_adapter_exception_is_treated_like_a_failure_not_a_crash(panel_factory):
    async with open_session() as s:
        w = await _world(s)
        panel_factory(ScriptedPanel([ValueError("bad json")]))
        assert await vpn.provision_order(s, w["order"].id) == "retry_scheduled"
        attempt = await s.scalar(select(ProvisioningAttempt))
        assert attempt.status == "failed" and attempt.error_kind == ErrorKind.UNKNOWN


async def test_timeout_that_actually_succeeded_is_reconciled_instead_of_retried(panel_factory):
    async with open_session() as s:
        w = await _world(s)
        remote = PanelAccount(
            ref="remote-1",
            username="m_remote",
            status="active",
            expire_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=30),
            traffic_limit_bytes=10 * 1024**3,
            traffic_used_bytes=0,
            subscription_url="https://sub.test/remote",
        )
        panel = panel_factory(ScriptedPanel([PanelError(ErrorKind.UNKNOWN, "read timeout")], remote=remote))
        assert await vpn.provision_order(s, w["order"].id) == "completed_after_reconcile"
        order = await s.get(Order, w["order"].id)
        acc = await s.get(VpnAccount, order.vpn_account_id)
        assert order.status == "completed" and acc.panel_ref == "remote-1" and acc.status == "active"
        assert panel.created == []
        assert (await s.scalars(select(VpnAccount))).all() == [acc]  # exactly one account for the order


async def test_unknown_error_without_a_remote_account_falls_back_to_the_retry_path(panel_factory):
    async with open_session() as s:
        w = await _world(s)
        panel_factory(ScriptedPanel([PanelError(ErrorKind.UNKNOWN, "read timeout")], remote=None))
        assert await vpn.provision_order(s, w["order"].id) == "retry_scheduled"


async def test_provisioning_kill_switch_leaves_the_order_untouched(panel_factory):
    from melorin.modules.system.models import FeatureFlag

    async with open_session() as s:
        w = await _world(s)
        panel = panel_factory(ScriptedPanel())
        s.add(FeatureFlag(key="provisioning", scope_type="global", scope_id=None, enabled=False))
        await s.commit()
        assert await vpn.provision_order(s, w["order"].id) == "blocked"
        order = await s.get(Order, w["order"].id)
        assert order.status == "processing" and panel.created == []


async def test_missing_product_marks_the_order_failed_for_review(panel_factory):
    async with open_session() as s:
        w = await _world(s)
        panel_factory(ScriptedPanel())
        order = await s.get(Order, w["order"].id)
        order.product_id = uuid.uuid4()
        await s.commit()
        assert await vpn.provision_order(s, order.id) == "failed"
        assert order.status == "provisioning_failed" and order.needs_review is True


async def test_renewal_extends_the_existing_account_on_its_own_panel_and_never_reduces_unlimited_traffic(panel_factory):
    async with open_session() as s:
        w = await _world(s)
        panel = panel_factory(ScriptedPanel())
        await vpn.provision_order(s, w["order"].id)
        first = await s.get(Order, w["order"].id)
        acc = await s.get(VpnAccount, first.vpn_account_id)
        acc.traffic_limit_bytes = 0  # unlimited account
        # SQLite hands back naive datetimes; PostgreSQL (timestamptz) returns aware ones, so pin an aware value.
        acc.expires_at = old_expiry = dt.datetime.now(dt.UTC) + dt.timedelta(days=10)
        renewal = await make_order(s, user=w["user"], store=w["store"], product=w["product"], total=2_000, status="paid", number="RENEW1")
        renewal.kind, renewal.vpn_account_id = "renewal", acc.id
        await s.commit()
        result = await vpn.provision_order(s, renewal.id)
        assert result == "completed", renewal.last_error
        username, expire, traffic = panel.extended[-1]
        assert username == acc.username and traffic == 0
        assert expire >= old_expiry + dt.timedelta(days=w["product"].duration_days) - dt.timedelta(seconds=5)
        attempt = (await s.scalars(select(ProvisioningAttempt).order_by(ProvisioningAttempt.created_at))).all()[-1]
        assert attempt.action == "extend"


async def test_completed_provisioning_is_audited_and_counts_one_bundle_sale(panel_factory):
    async with open_session() as s:
        w = await _world(s)
        panel_factory(ScriptedPanel())
        await vpn.provision_order(s, w["order"].id)
        await s.refresh(w["group"])
        assert w["group"].sold_count == 1
        audit = await s.scalar(select(AuditEvent).where(AuditEvent.action == "provisioning.completed"))
        assert audit is not None and audit.actor_type == "system"
