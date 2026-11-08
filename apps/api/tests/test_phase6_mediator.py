"""Phase 6 ("Melorin is a mediator"): panel-decided expiry (R2), fail-closed refunds (R3), closed issues of archived accounts (L4),
configurable retention days (decision 2)."""

import datetime as dt
import types

import pytest
from sqlalchemy import select

from _db import make_order, make_product, make_store, make_user, open_session
from melorin.core.errors import AppError
from melorin.kernel.models.vpn import Panel, ReconciliationIssue, VpnAccount
from melorin.modules.vpn import inquiry, issues, settings_drift, sync

NOW = dt.datetime.now(dt.UTC)


async def _panel(s, **kw) -> Panel:
    panel = Panel(kind="pasarguard", name="p", base_url="https://panel.test", **kw)
    s.add(panel)
    await s.flush()
    return panel


async def _account(s, panel, *, status="active", archived=False, expires=None, name="acc") -> VpnAccount:
    store, user, product = await make_store(s), await make_user(s), await make_product(s)
    order = await make_order(s, user=user, store=store, product=product, status="completed")
    acc = VpnAccount(
        username=name, user_id=user.id, store_id=store.id, order_id=order.id, product_id=product.id, panel_id=panel.id,
        status=status, expires_at=expires, traffic_limit_bytes=10, traffic_used_bytes=0, links=[],
    )  # fmt: skip
    if archived:
        acc.archived_at = NOW
    s.add(acc)
    await s.flush()
    return acc


# ---------------------------------------------------------------- L4
async def test_issues_of_archived_and_revoked_accounts_are_closed_active_ones_stay():
    async with open_session() as s:
        panel = await _panel(s)
        gone = await _account(s, panel, status="archived", archived=True, name="gone")
        revoked = await _account(s, panel, status="revoked", name="rev")
        live = await _account(s, panel, name="live")
        for acc in (gone, revoked, live):
            await issues.open_issue(s, acc.id, issues.MISSING, {})
        assert await issues.close_for_inactive_accounts(s, panel.id) == 2
        await s.commit()
        rows = {r.vpn_account_id: r for r in (await s.scalars(select(ReconciliationIssue))).all()}
        assert rows[gone.id].status == "resolved" and rows[gone.id].resolution == "account_inactive"
        assert rows[revoked.id].status == "resolved"
        assert rows[live.id].status == "open"


# ---------------------------------------------------------------- R2
def test_a_panel_without_status_but_with_a_past_expiry_means_expired():
    remote = types.SimpleNamespace(remote_status=None, expire_at=NOW - dt.timedelta(hours=1))
    assert sync.status_from_remote("active", remote) == "expired"
    future = types.SimpleNamespace(remote_status=None, expire_at=NOW + dt.timedelta(days=1))
    assert sync.status_from_remote("active", future) == "active"
    # an explicit panel status always wins over the date
    on_hold = types.SimpleNamespace(remote_status="on_hold", expire_at=NOW - dt.timedelta(days=1))
    assert sync.status_from_remote("active", on_hold) == "active"


async def test_expiry_job_asks_the_panel_and_never_expires_by_its_own_clock(monkeypatch):
    from melorin.modules.vpn import service
    from melorin.worker import jobs

    asked: list = []

    async def fake_reconcile(session, account_id):
        asked.append(account_id)
        return "ok"

    async with open_session() as s:
        panel = await _panel(s)
        late = await _account(s, panel, expires=NOW - dt.timedelta(days=1), name="late")
        hold = await _account(s, panel, expires=NOW - dt.timedelta(days=1), name="hold")
        hold.remote_status = "on_hold"
        no_panel = await _account(s, panel, expires=NOW - dt.timedelta(days=1), name="nopanel")
        no_panel.panel_id = None
        await s.commit()
        late_id = late.id
        monkeypatch.setattr(service, "reconcile", fake_reconcile)
        monkeypatch.setattr(jobs, "session_factory", lambda: (lambda: _Same(s)))
        assert await jobs.expiry_job() == 1
        assert asked == [late_id]
        assert (await s.get(VpnAccount, late_id)).status == "active"  # the clock alone changed nothing


class _Same:
    """Async context manager that hands out an already open session (the job opens its own in production)."""

    def __init__(self, s):
        self.s = s

    async def __aenter__(self):
        return self.s

    async def __aexit__(self, *exc):
        return False


# ---------------------------------------------------------------- R3
async def test_require_live_fails_closed_when_the_panel_cannot_answer(monkeypatch):
    from melorin.modules.vpn import service

    async def down(session, account_id):
        return "issue"

    async with open_session() as s:
        panel = await _panel(s)
        acc = await _account(s, panel)
        monkeypatch.setattr(service, "reconcile", down)
        with pytest.raises(AppError) as err:
            await inquiry.require_live(s, acc)
        assert err.value.code == "PANEL_UNAVAILABLE" and err.value.status == 503


async def test_require_live_ignores_the_ttl_and_passes_when_the_panel_answers(monkeypatch):
    from melorin.modules.vpn import service

    calls = []

    async def ok(session, account_id):
        calls.append(account_id)
        return "updated"

    async with open_session() as s:
        panel = await _panel(s)
        acc = await _account(s, panel)
        monkeypatch.setattr(service, "reconcile", ok)
        inquiry._last_refresh[acc.id] = 10**12  # a "fresh" TTL entry must not skip a financial read
        await inquiry.require_live(s, acc)
        await inquiry.require_live(s, acc)
        assert len(calls) == 2
        acc.panel_id = None  # never placed on a panel: nothing to ask
        await inquiry.require_live(s, acc)
        assert len(calls) == 2


# ---------------------------------------------------------------- decision 2
async def test_retention_days_are_configurable_validated_and_only_for_aligned():
    async with open_session() as s:
        panel = await _panel(s)
        await s.commit()
        actor = (await make_user(s)).id
        out = await settings_drift.set_policy(s, panel.id, "aligned", actor_id=actor, reason="keep 30d", retention_days=30)
        assert out["expected_retention_days"] == 30
        assert settings_drift.retention_days(await s.get(Panel, panel.id)) == 30
        with pytest.raises(AppError):
            await settings_drift.set_policy(s, panel.id, "aligned", actor_id=actor, reason="too short", retention_days=3)
        out = await settings_drift.set_policy(s, panel.id, "keep", actor_id=actor, reason="back to off")
        assert out["expected_retention_days"] is None


def test_cleanup_verdict_uses_the_configured_retention():
    cleanup = {"expired_users_retention_days": 20}
    assert settings_drift.evaluate_cleanup(cleanup, "aligned", 30)["state"] == "drift"
    assert settings_drift.evaluate_cleanup(cleanup, "aligned", 15)["state"] == "ok"
