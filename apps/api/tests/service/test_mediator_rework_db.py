"""Mediator rework (Melorin reads panel-owned data, it does not own it): fail-closed refunds, expiry decided by the panel,
and issues of archived accounts that close themselves."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_order, make_product, make_store, make_user, open_schema_engine
from melorin.core.errors import AppError
from melorin.kernel.models.vpn import Panel, ReconciliationIssue, VpnAccount
from melorin.modules.vpn import inquiry, issues
from melorin.modules.panel_integrations.adapters.base import ErrorKind, PanelError
from melorin.worker import jobs
from test_pasarguard_service_db import FakePanel, remote, run, seed, use

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def maker():
    async with open_schema_engine() as engine:
        yield async_sessionmaker(engine, expire_on_commit=False)


class _DownPanel(FakePanel):
    """A panel whose single-user read times out (what ``reconcile_account`` uses)."""

    async def get_account(self, username):
        raise PanelError(ErrorKind.TRANSIENT, "panel down")


# ------------------------------------------------------------------------------------------------ R3: fail-closed refunds
async def test_strict_refresh_refuses_when_the_panel_cannot_answer(maker, monkeypatch):
    panel_id, ids = await seed(maker, ["u1"])
    use(monkeypatch, _DownPanel())
    async with maker() as s:
        acc = await s.get(VpnAccount, ids["u1"])
        with pytest.raises(inquiry.PanelUnavailable) as err:
            await inquiry.refresh_from_panel(s, acc, strict=True)
        assert err.value.status == 503 and err.value.code == "PANEL_UNAVAILABLE"


async def test_strict_refresh_refuses_when_the_user_is_missing_on_the_panel(maker, monkeypatch):
    panel_id, ids = await seed(maker, ["u1"])
    use(monkeypatch, FakePanel([]))
    async with maker() as s:
        with pytest.raises(AppError):
            await inquiry.refresh_from_panel(s, await s.get(VpnAccount, ids["u1"]), strict=True)


async def test_strict_refresh_ignores_the_rate_limit_and_reads_live_usage(maker, monkeypatch):
    panel_id, ids = await seed(maker, ["u1"])
    use(monkeypatch, FakePanel([remote("u1", used=3 * 2**30)]))
    async with maker() as s:
        acc = await s.get(VpnAccount, ids["u1"])
        assert await inquiry.refresh_from_panel(s, acc) is True  # first call asks the panel ...
        assert await inquiry.refresh_from_panel(s, acc) is False  # ... the display path is rate limited
        assert await inquiry.refresh_from_panel(s, acc, strict=True) is True  # a refund never is
        # the reading is the panel's: it is not copied onto the account
        assert not hasattr(acc, "traffic_used_bytes")


async def test_strict_refresh_passes_for_an_account_without_a_panel(maker):
    async with maker() as s:
        store, user, product = await make_store(s), await make_user(s), await make_product(s)
        order = await make_order(s, user=user, store=store, product=product)
        acc = VpnAccount(username="nopanel", user_id=user.id, store_id=store.id, order_id=order.id, product_id=product.id, status="active")
        s.add(acc)
        await s.flush()
        assert await inquiry.refresh_from_panel(s, acc, strict=True) is False


# ------------------------------------------------------------------------------------------- R2: the panel decides expiry
async def _overdue(maker, name, *, panel_id=None, hours=-2):
    async with maker() as s:
        acc = await s.scalar(select(VpnAccount).where(VpnAccount.username == name))
        acc.sold_expires_at = dt.datetime.now(dt.UTC) + dt.timedelta(hours=hours)
        await s.commit()


async def test_expiry_job_does_not_expire_a_panel_account_on_its_own_clock(maker, monkeypatch):
    panel_id, ids = await seed(maker, ["renewed_on_panel", "really_expired", "panel_down"])
    for n in ids:
        await _overdue(maker, n)
    fake = FakePanel([remote("renewed_on_panel", expire_days=20), remote("really_expired", status="expired", expire_days=-1)])
    monkeypatch.setattr(jobs, "session_factory", lambda: maker)
    use(monkeypatch, fake)  # "panel_down" is simply absent from the panel => missing => no verdict
    await jobs.expiry_job()
    async with maker() as s:
        st = {a.username: a.status for a in (await s.scalars(select(VpnAccount))).all()}
    assert st["renewed_on_panel"] == "active"  # the panel says it was renewed
    assert st["really_expired"] == "expired"  # the panel says it ended
    assert st["panel_down"] == "active"  # no answer, no verdict


async def test_expiry_job_still_uses_the_clock_for_accounts_without_a_panel(maker, monkeypatch):
    async with maker() as s:
        store, user, product = await make_store(s), await make_user(s), await make_product(s)
        order = await make_order(s, user=user, store=store, product=product)
        s.add(
            VpnAccount(
                username="manual",
                user_id=user.id,
                store_id=store.id,
                order_id=order.id,
                product_id=product.id,
                status="active",
                sold_expires_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=1),
            )
        )
        await s.commit()
    monkeypatch.setattr(jobs, "session_factory", lambda: maker)
    await jobs.expiry_job()
    async with maker() as s:
        assert (await s.scalar(select(VpnAccount.status))) == "expired"


# --------------------------------------------------------------------------------- L4: archived accounts keep no open issue
async def test_issues_of_archived_accounts_are_closed_by_reconcile(maker, monkeypatch):
    panel_id, ids = await seed(maker, ["gone_on_purpose", "live"])
    async with maker() as s:
        acc = await s.get(VpnAccount, ids["gone_on_purpose"])
        acc.status, acc.archived_at = "archived", dt.datetime.now(dt.UTC)
        s.add(ReconciliationIssue(vpn_account_id=acc.id, kind=issues.MISSING, status="open", occurrences=3))
        await s.commit()
    use(monkeypatch, FakePanel([remote("live")]))
    await run(maker, panel_id)
    async with maker() as s:
        row = await s.scalar(select(ReconciliationIssue))
        assert row.status == "resolved" and row.resolution == "account_inactive"


# ----------------------------------------------------------------------------------- decision 1: orphan as manual account
async def test_a_manual_orphan_stays_manual_and_goes_gone_when_the_panel_user_disappears(maker, monkeypatch):
    from melorin.kernel.models.vpn import PanelOrphan

    panel_id, _ = await seed(maker, ["mine"])
    use(monkeypatch, FakePanel([remote("mine"), remote("rahim", owner="Ajdar", ref="7")]))
    await run(maker, panel_id)
    async with maker() as s:
        o = await s.scalar(select(PanelOrphan))
        assert o.username == "rahim" and o.status == "open"
        o.status = "manual"  # what POST /panel-orphans/{id}/manual does
        await s.commit()
    await run(maker, panel_id)
    async with maker() as s:
        assert (await s.scalar(select(PanelOrphan))).status == "manual"  # a later pass does not reopen or hide it
    use(monkeypatch, FakePanel([remote("mine")]))  # the panel user was deleted by hand
    await run(maker, panel_id)
    async with maker() as s:
        assert (await s.scalar(select(PanelOrphan))).status == "gone"


# ------------------------------------------------------------------------------- decision 2: configurable retention days
async def test_aligned_policy_uses_the_panel_specific_retention_days():
    from melorin.modules.panelops import settings_drift as sd

    cleanup = {"expired_users_retention_days": 20}
    assert sd.evaluate_cleanup(cleanup, "aligned", 30)["state"] == "drift"  # the admin expects at least 30
    assert sd.evaluate_cleanup(cleanup, "aligned", 20)["state"] == "ok"
    assert sd.evaluate_cleanup({"expired_users_retention_days": 0}, "aligned", 30)["state"] == "ok"  # panel auto-delete off
    assert sd.evaluate_cleanup(cleanup, "keep", 30)["state"] == "drift"  # keep: any auto-delete is drift


async def test_set_policy_stores_and_clears_the_retention_days(maker, monkeypatch):
    from melorin.modules.panelops import settings_drift as sd

    panel_id, _ = await seed(maker, [])
    async with maker() as s:
        panel = await s.get(Panel, panel_id)
        panel.kind = "pasarguard"
        await s.commit()
        assert sd.effective_days(panel) == sd.GRACE_DAYS
        with pytest.raises(AppError):
            await sd.set_policy(s, panel_id, "aligned", actor_id=None, reason="test", retention_days=0)
        assert (await s.get(Panel, panel_id)).expected_retention_days is None  # a rejected number changes nothing

        async def _no_recheck(session, pid, *, actor_id):  # the read-only panel check is not under test here
            return {}

        monkeypatch.setattr(sd, "recheck", _no_recheck)
        await sd.set_policy(s, panel_id, "aligned", actor_id=None, reason="test", retention_days=30)
        panel = await s.get(Panel, panel_id)
        assert panel.expected_retention_days == 30 and sd.effective_days(panel) == 30
        await sd.set_policy(s, panel_id, "keep", actor_id=None, reason="test")  # only ``aligned`` carries a number
        assert (await s.get(Panel, panel_id)).expected_retention_days is None


# ------------------------------------------------------------------------------------------------ PG-04: link_existing
async def test_link_existing_points_a_missing_account_at_the_real_panel_user(maker, monkeypatch):
    import types

    from melorin.kernel.models.vpn import PanelOrphan
    from melorin.modules.admin import panel_reconciliation

    panel_id, ids = await seed(maker, ["old_name"])
    async with maker() as s:
        issue = await issues.open_issue(s, ids["old_name"], issues.MISSING, {})
        orphan = PanelOrphan(panel_id=panel_id, username="renamed_on_panel", remote_id=42, status="open")
        s.add(orphan)
        await s.commit()
        admin = types.SimpleNamespace(id=(await make_user(s)).id)

        async def fake_reconcile(session, account_id):
            return "ok"

        monkeypatch.setattr(panel_reconciliation.reconcile, "reconcile_account", fake_reconcile)
        assert "link_existing" in panel_reconciliation.allowed_actions(issues.MISSING, "open")
        with pytest.raises(AppError):  # an orphan is required
            await panel_reconciliation.issue_action(issue.id, panel_reconciliation.IssueActionIn(action="link_existing"), admin, s)
        await panel_reconciliation.issue_action(
            issue.id, panel_reconciliation.IssueActionIn(action="link_existing", orphan_id=orphan.id), admin, s
        )
        acc = await s.get(VpnAccount, ids["old_name"])
        assert acc.username == "renamed_on_panel" and acc.panel_ref == "42"
        assert (await s.get(PanelOrphan, orphan.id)).status == "gone"
        assert (await s.get(ReconciliationIssue, issue.id)).status == "resolved"


# ------------------------------------------------------- near-expiry warning needs the panel's agreement (mediator rule)
async def test_near_expiry_warning_is_sent_only_when_the_panel_agrees(maker, monkeypatch):
    from melorin.modules.vpn import live, notices

    names = ["agrees", "on_hold", "renewed_on_panel", "panel_silent"]
    panel_id, ids = await seed(maker, names)
    soon = dt.datetime.now(dt.UTC) + dt.timedelta(hours=20)
    async with maker() as s:
        for a in (await s.scalars(select(VpnAccount))).all():
            a.sold_expires_at = soon  # Melorin sold "ends in 20 h" for all four
        await s.commit()
    fake = FakePanel(
        [
            remote("agrees", expire_days=1),
            remote("on_hold", status="on_hold", expire_days=1),
            remote("renewed_on_panel", expire_days=20),
            # "panel_silent": absent from the panel -> no reading -> no verdict
        ]
    )
    monkeypatch.setattr(live, "build_adapter", lambda panel: fake)
    monkeypatch.setattr(live, "seed_adapter", lambda adapter, account: adapter)
    live.clear_cache()
    sent: list[str] = []

    async def fake_notice(session, account):
        sent.append(account.username)

    monkeypatch.setattr(notices, "near_expiry", fake_notice)
    monkeypatch.setattr(jobs, "session_factory", lambda: maker)
    await jobs.near_expiry_job()
    assert sent == ["agrees"]
    async with maker() as s:
        flags = {a.username: a.near_expiry_notified for a in (await s.scalars(select(VpnAccount))).all()}
    assert flags == {"agrees": True, "on_hold": False, "renewed_on_panel": False, "panel_silent": False}  # unknowns try again next run
    live.clear_cache()
    await jobs.near_expiry_job()
    assert sent == ["agrees"]  # dedup still holds for the one that was warned


async def test_near_expiry_reads_every_page_not_only_the_first(maker, monkeypatch):
    """T23: with more candidates than one live read may take, the rest must still be warned (soonest-ending first)."""
    from melorin.modules.vpn import live, notices

    names = [f"u{i}" for i in range(5)]
    panel_id, ids = await seed(maker, names)
    base = dt.datetime.now(dt.UTC)
    async with maker() as s:
        for i, a in enumerate((await s.scalars(select(VpnAccount).order_by(VpnAccount.username))).all()):
            a.sold_expires_at = base + dt.timedelta(hours=40 - i)
        await s.commit()
    fake = FakePanel([remote(n, expire_days=1) for n in names])
    monkeypatch.setattr(live, "build_adapter", lambda panel: fake)
    monkeypatch.setattr(live, "seed_adapter", lambda adapter, account: adapter)
    monkeypatch.setattr(live, "MAX_ACCOUNTS", 2)
    live.clear_cache()
    sent: list[str] = []

    async def fake_notice(session, account):
        sent.append(account.username)

    monkeypatch.setattr(notices, "near_expiry", fake_notice)
    monkeypatch.setattr(jobs, "session_factory", lambda: maker)
    await jobs.near_expiry_job()
    assert sorted(sent) == sorted(names)
    assert sent[0] == "u4"  # the account that ends first is handled first
