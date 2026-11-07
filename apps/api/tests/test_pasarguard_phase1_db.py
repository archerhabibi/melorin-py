"""PasarGuard Phase 1 against real tables: reconcile v2 (PG-02 / PG-04), issue de-duplication and auto-close, orphans, node health rows (PG-01)."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_order, make_product, make_store, make_user, open_schema_engine
from melorin.core.db import utcnow
from melorin.kernel.models.vpn import Panel, PanelAdmin, PanelNode, PanelOrphan, ReconciliationIssue, VpnAccount
from melorin.modules.vpn import health, issues, reconcile
from melorin.modules.vpn.adapters.base import ErrorKind, PanelAccount, PanelError

NOW = utcnow()


def _aware(value):
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


@pytest.fixture
async def maker():
    async with open_schema_engine() as engine:
        yield async_sessionmaker(engine, expire_on_commit=False)


class FakePanel:
    """Adapter double: a panel with a user list, optional node list, and an optional outage."""

    def __init__(self, users=(), nodes=None, down=False):
        self.users = {u.username: u for u in users}
        self.nodes, self.down, self.single_calls = nodes, down, 0

    def capabilities(self):  # only what ``supports`` needs
        from melorin.modules.vpn.adapters.base import Capabilities

        return Capabilities(account_listing=True, node_ops=True)

    async def list_accounts(self, offset=0, limit=200):
        if self.down:
            raise PanelError(ErrorKind.TRANSIENT, "panel down")
        rows = list(self.users.values())
        return rows[offset : offset + limit], len(rows)

    async def get_account(self, username):
        self.single_calls += 1
        return self.users.get(username)

    async def list_nodes(self):
        return self.nodes or []

    async def get_node(self, node_id):
        return next((n for n in self.nodes or [] if n["id"] == node_id), None)

    async def reconnect_node(self, node_id):
        return None

    async def health_check(self):
        return not self.down

    async def close(self):
        return None


def remote(username, *, status="active", owner="ml_main", expire_days=30, limit=10 * 2**30, used=0, ref="1"):
    return PanelAccount(
        ref=ref,
        username=username,
        status="active" if status == "on_hold" else status,
        expire_at=NOW + dt.timedelta(days=expire_days),
        traffic_limit_bytes=limit,
        traffic_used_bytes=used,
        remote_status=status,
        owner=owner,
    )


async def seed(maker, usernames, *, with_admin="ml_main"):
    async with maker() as s:
        store, user, product = await make_store(s), await make_user(s), await make_product(s)
        panel = Panel(name="pg", kind="mock", base_url="http://pg", is_enabled=True)
        s.add(panel)
        await s.flush()
        if with_admin:
            s.add(PanelAdmin(panel_id=panel.id, store_id=store.id, username=with_admin, status="active"))
        ids = {}
        for name in usernames:
            order = await make_order(s, user=user, store=store, product=product)
            acc = VpnAccount(
                username=name,
                user_id=user.id,
                store_id=store.id,
                order_id=order.id,
                product_id=product.id,
                panel_id=panel.id,
                status="active",
                expires_at=NOW + dt.timedelta(days=30),
                traffic_limit_bytes=10 * 2**30,
                last_synced_at=NOW - dt.timedelta(hours=2),
            )
            s.add(acc)
            await s.flush()
            ids[name] = acc.id
        await s.commit()
        return panel.id, ids


def use(monkeypatch, fake):
    monkeypatch.setattr(reconcile, "build_adapter", lambda panel: fake)
    monkeypatch.setattr(reconcile, "seed_adapter", lambda adapter, account: adapter)


async def run(maker, panel_id, **kw):
    async with maker() as s:
        return await reconcile.reconcile_panel(s, await s.get(Panel, panel_id), **kw)


async def open_issues(maker, kind=None):
    async with maker() as s:
        q = select(ReconciliationIssue).where(ReconciliationIssue.status == "open")
        if kind:
            q = q.where(ReconciliationIssue.kind == kind)
        return (await s.scalars(q)).all()


# ----------------------------------------------------------------------------------------------------- PG-02 status sync
async def test_panel_side_changes_reach_melorin_in_one_pass(maker, monkeypatch):
    panel_id, ids = await seed(maker, ["limited_user", "disabled_user", "expired_user", "fine_user"])
    use(
        monkeypatch,
        FakePanel(
            [
                remote("limited_user", status="limited", used=10 * 2**30),
                remote("disabled_user", status="disabled"),
                remote("expired_user", status="expired", expire_days=-1),
                remote("fine_user"),
            ]
        ),
    )
    result = await run(maker, panel_id)
    assert result.checked == 4 and result.updated == 3 and result.complete
    async with maker() as s:
        status = {a.username: (a.status, a.remote_status) for a in (await s.scalars(select(VpnAccount))).all()}
        synced = (await s.scalars(select(VpnAccount.last_synced_at))).all()
    assert status == {
        "limited_user": ("limited", "limited"),
        "disabled_user": ("suspended", "disabled"),
        "expired_user": ("expired", "expired"),
        "fine_user": ("active", "active"),
    }
    assert all(_aware(t) >= NOW for t in synced)


async def test_re_enabling_on_the_panel_brings_a_suspended_account_back(maker, monkeypatch):
    panel_id, ids = await seed(maker, ["u1"])
    async with maker() as s:
        (await s.get(VpnAccount, ids["u1"])).status = "suspended"
        await s.commit()
    use(monkeypatch, FakePanel([remote("u1")]))
    await run(maker, panel_id)
    async with maker() as s:
        assert (await s.get(VpnAccount, ids["u1"])).status == "active"


async def test_one_listing_call_replaces_one_call_per_account(maker, monkeypatch):
    panel_id, _ = await seed(maker, ["a", "b", "c"])
    fake = FakePanel([remote(n) for n in "abc"])
    use(monkeypatch, fake)
    await run(maker, panel_id)
    assert fake.single_calls == 0


async def test_least_recently_synced_accounts_go_first_when_the_batch_is_small(maker, monkeypatch):
    panel_id, ids = await seed(maker, ["old", "newer"])
    async with maker() as s:
        (await s.get(VpnAccount, ids["old"])).last_synced_at = None  # never synced
        await s.commit()
    use(monkeypatch, FakePanel([remote("old"), remote("newer")]))
    result = await run(maker, panel_id, batch=1)
    assert result.checked == 1
    async with maker() as s:
        assert (await s.get(VpnAccount, ids["old"])).last_synced_at is not None
        assert _aware((await s.get(VpnAccount, ids["newer"])).last_synced_at) < NOW - dt.timedelta(hours=1)


# ----------------------------------------------------------------------------------------------- PG-04 issues, no dupes
async def test_a_missing_user_opens_one_issue_and_repeats_only_count(maker, monkeypatch):
    panel_id, ids = await seed(maker, ["ghost", "real"])
    use(monkeypatch, FakePanel([remote("real")]))
    for _ in range(3):
        await run(maker, panel_id)
    rows = await open_issues(maker, issues.MISSING)
    assert len(rows) == 1 and rows[0].vpn_account_id == ids["ghost"] and rows[0].occurrences == 3


async def test_a_missing_issue_closes_itself_when_the_user_reappears(maker, monkeypatch):
    panel_id, ids = await seed(maker, ["ghost"])
    fake = FakePanel([])
    use(monkeypatch, fake)
    await run(maker, panel_id)
    assert len(await open_issues(maker, issues.MISSING)) == 1
    fake.users["ghost"] = remote("ghost")
    await run(maker, panel_id)
    assert await open_issues(maker, issues.MISSING) == []
    async with maker() as s:
        closed = (await s.scalars(select(ReconciliationIssue))).one()
    assert closed.status == "resolved" and closed.resolution == "auto" and closed.resolved_at is not None


async def test_panel_outage_opens_unreachable_then_recovery_closes_it(maker, monkeypatch):
    panel_id, ids = await seed(maker, ["u1", "u2"])
    fake = FakePanel([remote("u1"), remote("u2")], down=True)
    use(monkeypatch, fake)
    outage = await run(maker, panel_id)
    assert outage.unreachable and len(await open_issues(maker, issues.UNREACHABLE)) == 2
    assert await open_issues(maker, issues.MISSING) == []  # an outage must never be reported as "deleted"
    fake.down = False
    await run(maker, panel_id)
    assert await open_issues(maker, issues.UNREACHABLE) == []


async def test_wrong_owner_is_flagged_and_clears_when_fixed(maker, monkeypatch):
    panel_id, ids = await seed(maker, ["u1"])
    fake = FakePanel([remote("u1", owner="someone_else")])
    use(monkeypatch, fake)
    result = await run(maker, panel_id)
    assert result.owner_mismatch == 1
    row = (await open_issues(maker, issues.OWNER_MISMATCH))[0]
    assert row.details == {"expected": "ml_main", "panel": "someone_else"}
    fake.users["u1"] = remote("u1", owner="ml_main")
    await run(maker, panel_id)
    assert await open_issues(maker, issues.OWNER_MISMATCH) == []


async def test_manual_limit_edit_on_the_panel_is_reported_and_mirrored(maker, monkeypatch):
    panel_id, ids = await seed(maker, ["u1"])
    use(monkeypatch, FakePanel([remote("u1", limit=50 * 2**30, expire_days=90)]))
    result = await run(maker, panel_id)
    assert result.limits_mismatch == 1
    assert len(await open_issues(maker, issues.LIMITS_MISMATCH)) == 1
    async with maker() as s:
        acc = await s.get(VpnAccount, ids["u1"])
    assert acc.traffic_limit_bytes == 50 * 2**30  # the panel is the source of truth


async def test_the_database_itself_rejects_a_second_open_issue(maker):
    _, ids = await seed(maker, ["u1"])
    from sqlalchemy.exc import IntegrityError

    async with maker() as s:
        s.add(ReconciliationIssue(vpn_account_id=ids["u1"], kind=issues.MISSING, status="open", occurrences=1))
        await s.commit()
        s.add(ReconciliationIssue(vpn_account_id=ids["u1"], kind=issues.MISSING, status="open", occurrences=1))
        with pytest.raises(IntegrityError):
            await s.commit()


# ----------------------------------------------------------------------------------------------------------- orphans
async def test_unknown_panel_users_are_listed_never_touched_and_marked_gone_when_deleted(maker, monkeypatch):
    panel_id, _ = await seed(maker, ["mine"])
    fake = FakePanel([remote("mine"), remote("amin_tonnell", owner="Ajdar"), remote("rahim", owner="Ajdar")])
    use(monkeypatch, fake)
    result = await run(maker, panel_id)
    assert result.orphans == 2
    async with maker() as s:
        rows = {o.username: o for o in (await s.scalars(select(PanelOrphan))).all()}
    assert set(rows) == {"amin_tonnell", "rahim"} and rows["rahim"].owner_username == "Ajdar" and rows["rahim"].status == "open"
    del fake.users["rahim"]
    await run(maker, panel_id)
    async with maker() as s:
        rows = {o.username: o.status for o in (await s.scalars(select(PanelOrphan))).all()}
    assert rows == {"amin_tonnell": "open", "rahim": "gone"}


async def test_an_incomplete_listing_makes_no_missing_or_orphan_verdicts(maker, monkeypatch):
    panel_id, _ = await seed(maker, ["u1"])
    use(monkeypatch, FakePanel([remote("u1"), remote("stranger")]))
    monkeypatch.setattr(reconcile, "MAX_PAGES", 0)  # the listing never completes
    result = await run(maker, panel_id)
    assert not result.complete and result.orphans == 0 and await open_issues(maker) == []


# ------------------------------------------------------------------------------------------------- PG-01 node health rows
def nodes_payload(*statuses):
    return [
        {"id": i + 1, "name": f"n{i + 1}", "status": s, "message": "CERTIFICATE_VERIFY_FAILED" if s == "error" else None}
        for i, s in enumerate(statuses)
    ]


async def test_check_panel_persists_nodes_and_reports_transitions(maker):
    panel_id, _ = await seed(maker, [])
    fake = FakePanel(nodes=nodes_payload("connected", "error", "disabled"))
    async with maker() as s:
        panel = await s.get(Panel, panel_id)
        panel.capabilities = {"flags": {"node_ops": True}, "source": "probe"}
        first = await health.check_panel(s, panel, fake)
        health.apply(panel, first)
        await s.commit()
        assert first.status == "degraded" and first.detail["sellable"] is True and panel.health_status == "degraded"
        assert [c["to"] for c in first.node_changes] == ["error"]

        again = await health.check_panel(s, panel, fake)
        assert again.node_changes == []  # no new transition: no repeated alert

        fake.nodes = nodes_payload("error", "error", "disabled")
        down = await health.check_panel(s, panel, fake)
        assert down.status == "unhealthy" and down.detail["sellable"] is False
        assert {c["name"]: (c["from"], c["to"]) for c in down.node_changes} == {"n1": ("connected", "error")}
        await s.commit()
        count = await s.scalar(select(func.count()).select_from(PanelNode).where(PanelNode.panel_id == panel_id))
    assert count == 3


async def test_removed_nodes_are_marked_not_deleted(maker):
    panel_id, _ = await seed(maker, [])
    fake = FakePanel(nodes=nodes_payload("connected", "connected"))
    async with maker() as s:
        panel = await s.get(Panel, panel_id)
        panel.capabilities = {"flags": {"node_ops": True}, "source": "probe"}
        await health.check_panel(s, panel, fake)
        fake.nodes = nodes_payload("connected")
        await health.check_panel(s, panel, fake)
        await s.commit()
        rows = {r.remote_id: r.removed_at for r in (await s.scalars(select(PanelNode))).all()}
    assert rows[1] is None and rows[2] is not None


async def test_a_panel_that_does_not_answer_is_unhealthy_at_layer_one(maker):
    panel_id, _ = await seed(maker, [])
    async with maker() as s:
        result = await health.check_panel(s, await s.get(Panel, panel_id), FakePanel(down=True))
    assert result.status == "unhealthy" and result.detail["layer"] == 1 and result.detail["sellable"] is False


async def test_a_credential_without_node_access_keeps_the_layer_one_verdict(maker):
    panel_id, _ = await seed(maker, [])
    async with maker() as s:
        panel = await s.get(Panel, panel_id)
        panel.capabilities = {"flags": {"node_ops": False}, "source": "probe"}
        result = await health.check_panel(s, panel, FakePanel(nodes=nodes_payload("error")))
    assert result.status == "healthy" and result.detail["node_check"] == "skipped"
