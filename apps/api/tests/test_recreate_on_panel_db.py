"""PG-04 "re-create on panel": an account whose panel user vanished is put back from Melorin's sold entitlement, never as a free renewal."""

from __future__ import annotations

import datetime as dt
import types

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_user, open_schema_engine
from melorin.core.errors import AppError
from melorin.kernel.models.vpn import ReconciliationIssue, Server, VpnAccount
from melorin.modules.admin import panel_ops
from melorin.modules.vpn import issues, recreate
from melorin.modules.vpn.adapters.base import ErrorKind, PanelError
from test_pasarguard_phase1_db import FakePanel, remote, seed

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def maker():
    async with open_schema_engine() as engine:
        yield async_sessionmaker(engine, expire_on_commit=False)


class _Creating(FakePanel):
    def __init__(self, *, existing=(), fail=None):
        super().__init__(existing)
        self.created, self.fail = [], fail

    async def create_account(self, spec):
        if self.fail:
            raise PanelError(self.fail, "nope")
        self.created.append(spec)
        made = remote(spec.username, ref="77", owner=spec.owner)
        self.users[spec.username] = made
        return made


async def _setup(maker, monkeypatch, fake, *, days=30, status="active", with_server=True):
    panel_id, ids = await seed(maker, ["gone"])
    async with maker() as s:
        acc = await s.get(VpnAccount, ids["gone"])
        acc.sold_expires_at = dt.datetime.now(dt.UTC) + dt.timedelta(days=days)
        acc.status = status
        if with_server:
            server = Server(name="srv", panel_id=panel_id)
            s.add(server)
            await s.flush()
            acc.server_id = server.id
        issue = await issues.open_issue(s, acc.id, issues.MISSING, {})
        admin = types.SimpleNamespace(id=(await make_user(s)).id)
        await s.commit()
        issue_id = issue.id

    async def owner_for(session, panel, store_id, adapter):
        return "ml_main"

    monkeypatch.setattr(recreate, "build_adapter", lambda panel, server=None: fake)
    monkeypatch.setattr(recreate.panel_admins, "owner_for", owner_for)

    async def fake_reconcile(session, account_id):
        return "ok"

    monkeypatch.setattr(panel_ops.reconcile, "reconcile_account", fake_reconcile)
    return panel_id, ids["gone"], issue_id, admin


async def _act(maker, issue_id, admin, **kw):
    async with maker() as s:
        return await panel_ops.issue_action(issue_id, panel_ops.IssueActionIn(action="recreate_on_panel", **kw), admin, s)


async def test_recreate_puts_the_sold_package_back_under_the_stores_admin(maker, monkeypatch):
    fake = _Creating()
    _, acc_id, issue_id, admin = await _setup(maker, monkeypatch, fake)
    assert "recreate_on_panel" in panel_ops.allowed_actions(issues.MISSING, "open")
    await _act(maker, issue_id, admin, reason="panel was restored from an old backup")
    spec = fake.created[0]
    assert spec.username == "gone" and spec.owner == "ml_main" and spec.traffic_bytes == 10 * 2**30
    assert spec.expire_at is not None and spec.expire_at > dt.datetime.now(dt.UTC) + dt.timedelta(days=29)
    async with maker() as s:
        assert (await s.get(VpnAccount, acc_id)).panel_ref == "77"
        issue = await s.get(ReconciliationIssue, issue_id)
        assert issue.status == "resolved" and "re-created" in issue.resolution


async def test_recreate_needs_a_reason(maker, monkeypatch):
    fake = _Creating()
    _, _, issue_id, admin = await _setup(maker, monkeypatch, fake)
    with pytest.raises(AppError) as e:
        await _act(maker, issue_id, admin)
    assert e.value.code == "REASON_REQUIRED" and fake.created == []


async def test_recreate_refuses_an_account_whose_time_is_over(maker, monkeypatch):
    fake = _Creating()
    _, _, issue_id, admin = await _setup(maker, monkeypatch, fake, days=-1)
    with pytest.raises(AppError) as e:
        await _act(maker, issue_id, admin, reason="try")
    assert e.value.code == "ENTITLEMENT_OVER" and fake.created == []  # money goes through the renewal flow, not an issue action


async def test_recreate_never_reuses_a_name_that_exists_on_the_panel(maker, monkeypatch):
    fake = _Creating(existing=[remote("gone")])
    _, _, issue_id, admin = await _setup(maker, monkeypatch, fake)
    with pytest.raises(AppError) as e:
        await _act(maker, issue_id, admin, reason="try")
    assert e.value.code == "ALREADY_ON_PANEL" and fake.created == []


async def test_recreate_needs_a_destination(maker, monkeypatch):
    fake = _Creating()
    _, _, issue_id, admin = await _setup(maker, monkeypatch, fake, with_server=False)
    with pytest.raises(AppError) as e:
        await _act(maker, issue_id, admin, reason="try")
    assert e.value.code == "CANNOT_RECREATE"


@pytest.mark.parametrize(
    ("kind", "code", "status"), [(ErrorKind.TRANSIENT, "PANEL_UNAVAILABLE", 503), (ErrorKind.PERMANENT, "PANEL_REJECTED", 409)]
)
async def test_recreate_reports_panel_failures_and_keeps_the_issue_open(maker, monkeypatch, kind, code, status):
    fake = _Creating(fail=kind)
    _, _, issue_id, admin = await _setup(maker, monkeypatch, fake)
    with pytest.raises(AppError) as e:
        await _act(maker, issue_id, admin, reason="try")
    assert e.value.code == code and e.value.status == status
    async with maker() as s:
        assert (await s.get(ReconciliationIssue, issue_id)).status == "open"
