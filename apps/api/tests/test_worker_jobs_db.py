"""Phase 4: periodic worker jobs against real tables (expiry, near-expiry, health, reconcile, retention, backup).

``jobs.session_factory`` is pointed at the per-test schema; backups run a real (tiny) shell script so exit-code
handling (0 = ok, 3 = off-site failed, other = failed) is exercised end to end.
"""

from __future__ import annotations

import datetime as dt
import stat

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_order, make_product, make_store, make_user, open_schema_engine
from melorin.core.db import utcnow
from melorin.kernel.models.identity import VerificationCode
from melorin.kernel.models.system import BackupRun, OutboxEvent, SystemSetting
from melorin.kernel.models.vpn import Panel, VpnAccount
from melorin.worker import jobs


@pytest.fixture
async def maker(monkeypatch):
    async with open_schema_engine() as engine:
        m = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(jobs, "session_factory", lambda: m)
        yield m


async def _account(s, *, status="active", expires_in_hours=None, notified=False, panel=None):
    store, user, product = await make_store(s), await make_user(s), await make_product(s)
    order = await make_order(s, user=user, store=store, product=product)
    a = VpnAccount(
        username=f"u{utcnow().timestamp()}{id(object())}"[:60],
        user_id=user.id,
        store_id=store.id,
        order_id=order.id,
        product_id=product.id,
        panel_id=panel.id if panel else None,
        status=status,
        expires_at=None if expires_in_hours is None else utcnow() + dt.timedelta(hours=expires_in_hours),
        near_expiry_notified=notified,
    )
    s.add(a)
    await s.flush()
    return a


async def _outbox(m):
    async with m() as s:
        return (await s.scalars(select(OutboxEvent))).all()


# --- expiry --------------------------------------------------------------------------------------------------------


async def test_expiry_job_expires_only_overdue_active_accounts_and_notifies_once(maker):
    async with maker() as s:
        old = await _account(s, expires_in_hours=-1)
        fresh = await _account(s, expires_in_hours=24)
        no_end = await _account(s, expires_in_hours=None)
        already = await _account(s, status="suspended", expires_in_hours=-5)
        await s.commit()
    await jobs.expiry_job()
    await jobs.expiry_job()  # idempotent: second run finds nothing active+overdue and emits nothing new
    async with maker() as s:
        st = {a.id: a.status for a in (await s.scalars(select(VpnAccount))).all()}
    assert st[old.id] == "expired" and st[fresh.id] == "active" and st[no_end.id] == "active" and st[already.id] == "suspended"
    events = await _outbox(maker)
    assert [e.dedup_key for e in events] == [f"notify:expired:{old.id}"]
    assert events[0].payload["kind"] == "vpn_expired" and events[0].payload["user_id"] == str(old.user_id)


async def test_near_expiry_job_respects_window_flag_and_dedup(maker):
    async with maker() as s:
        soon = await _account(s, expires_in_hours=10)
        later = await _account(s, expires_in_hours=200)
        done = await _account(s, expires_in_hours=10, notified=True)
        past = await _account(s, expires_in_hours=-1)
        await s.commit()
    await jobs.near_expiry_job()
    await jobs.near_expiry_job()
    async with maker() as s:
        flags = {a.id: a.near_expiry_notified for a in (await s.scalars(select(VpnAccount))).all()}
    assert flags[soon.id] is True and flags[later.id] is False and flags[past.id] is False and flags[done.id] is True
    assert [e.dedup_key for e in await _outbox(maker)] == [f"notify:near-expiry:{soon.id}"]


async def test_near_expiry_window_is_configurable_through_settings(maker):
    async with maker() as s:
        a = await _account(s, expires_in_hours=100)
        s.add(SystemSetting(key="vpn.near_expiry_hours", value=120))
        await s.commit()
    await jobs.near_expiry_job()
    async with maker() as s:
        assert (await s.get(VpnAccount, a.id)).near_expiry_notified is True


# --- panel health --------------------------------------------------------------------------------------------------


class _Adapter:
    def __init__(self, result, *, sync_close=False, close_fails=False):
        self.result, self.closed, self.sync_close, self.close_fails = result, False, sync_close, close_fails

    async def health_check(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def close(self):
        if self.close_fails:
            raise RuntimeError("close failed")
        self.closed = True
        if self.sync_close:
            return None

        async def _c():
            return None

        return _c()


async def test_panel_health_job_records_healthy_unhealthy_error_and_closes_adapters(maker, monkeypatch):
    adapters = {"ok": _Adapter(True), "down": _Adapter(False, sync_close=True), "boom": _Adapter(RuntimeError("timeout"), close_fails=True)}
    monkeypatch.setattr("melorin.modules.vpn.adapters.registry.build_adapter", lambda p: adapters[p.name])
    async with maker() as s:
        for name in (*adapters, "disabled"):
            s.add(Panel(name=name, kind="mock", base_url="http://x", is_enabled=name != "disabled"))
        await s.commit()
    await jobs.panel_health_job()
    async with maker() as s:
        by = {p.name: p for p in (await s.scalars(select(Panel))).all()}
    assert (by["ok"].health_status, by["ok"].last_health_error) == ("healthy", None)
    assert (by["down"].health_status, by["down"].last_health_error) == ("unhealthy", "health check returned false")
    assert by["boom"].health_status == "unhealthy" and "timeout" in by["boom"].last_health_error
    assert by["disabled"].health_status == "unknown" and by["disabled"].last_health_at is None
    assert adapters["ok"].closed and adapters["down"].closed  # sync and async close() both honoured; failing close() is swallowed


async def test_close_adapter_tolerates_adapters_without_close():
    await jobs._close_adapter(object())


# --- reconciliation / retention / telegram gc ----------------------------------------------------------------------


async def test_reconciliation_job_visits_active_and_suspended_accounts_only(maker, monkeypatch):
    seen = []

    async def fake(session, account_id):
        seen.append(account_id)
        return "ok"

    monkeypatch.setattr(jobs.service, "reconcile", fake)
    async with maker() as s:
        a, b = await _account(s), await _account(s, status="suspended")
        await _account(s, status="expired")
        await s.commit()
    await jobs.reconciliation_job()
    assert set(seen) == {a.id, b.id}


async def test_privacy_retention_deletes_only_old_expired_codes_and_returns_count(maker):
    now = utcnow()

    def code(created_days_ago, expires_days_ago, tag):
        return VerificationCode(
            purpose="email_login",
            target=tag,
            code_hash=tag,
            created_at=now - dt.timedelta(days=created_days_ago),
            expires_at=now - dt.timedelta(days=expires_days_ago),
        )

    async with maker() as s:
        s.add_all([code(30, 29, "old"), code(30, -1, "still-valid"), code(1, 0, "recent")])
        await s.commit()
    assert await jobs.privacy_retention_job() == 1
    async with maker() as s:
        assert {c.target for c in (await s.scalars(select(VerificationCode))).all()} == {"still-valid", "recent"}
    # retention is configurable and never drops below one day
    async with maker() as s:
        s.add(SystemSetting(key="privacy.verification_code_retention_days", value=0))
        await s.commit()
    assert await jobs.privacy_retention_job() == 0


async def test_telegram_login_gc_job_delegates_to_purge(maker, monkeypatch):
    async def fake_purge(session, *a, **k):
        return 4

    monkeypatch.setattr("melorin.channels.telegram.web.purge_old", fake_purge)
    assert await jobs.telegram_login_gc_job() == 4


# --- backup --------------------------------------------------------------------------------------------------------


def _script(tmp_path, body):
    (tmp_path / "scripts").mkdir()
    sh = tmp_path / "scripts" / "backup_secure.sh"
    sh.write_text("#!/bin/sh\n" + body)
    sh.chmod(sh.stat().st_mode | stat.S_IEXEC)
    return sh


@pytest.fixture
def backup_env(maker, monkeypatch, tmp_path):
    monkeypatch.setenv("MELORIN_PROJECT_ROOT", str(tmp_path))

    async def no_s3(session):
        return {}

    monkeypatch.setattr(jobs.integrations, "get_backup_s3", no_s3)
    monkeypatch.setattr(jobs.integrations, "backup_s3_ready", lambda cfg: False)
    return tmp_path


async def _runs(maker):
    async with maker() as s:
        return (await s.scalars(select(BackupRun))).all()


async def test_backup_job_success_records_artifact_size_and_local_only_note(maker, backup_env):
    artifact = backup_env / "dump.enc"
    artifact.write_bytes(b"x" * 123)
    _script(backup_env, f"echo noise\necho {artifact}\n")
    assert await jobs.backup_job() == "succeeded"
    (run,) = await _runs(maker)
    assert (run.status, run.location, run.size) == ("succeeded", str(artifact), 123) and "local only" in run.details


async def test_backup_job_exit_3_is_partial_with_stderr_tail(maker, backup_env):
    artifact = backup_env / "dump.enc"
    artifact.write_bytes(b"1")
    _script(backup_env, f"echo {artifact}\necho s3 unreachable >&2\nexit 3\n")
    assert await jobs.backup_job() == "partial"
    (run,) = await _runs(maker)
    assert run.status == "partial" and "S3 upload failed" in run.details and "s3 unreachable" in run.details


async def test_backup_job_failure_modes_are_recorded_not_raised(maker, backup_env, caplog):
    _script(backup_env, "echo disk full >&2\nexit 1\n")
    assert await jobs.backup_job() == "failed"
    (run,) = await _runs(maker)
    assert run.status == "failed" and "disk full" in run.details and run.location is None
    assert "backup failed" in caplog.text


async def test_backup_job_missing_script_is_a_recorded_failure(maker, backup_env):
    assert await jobs.backup_job() == "failed"
    (run,) = await _runs(maker)
    assert run.status == "failed" and run.details


async def test_backup_job_passes_offsite_settings_to_the_script_when_s3_is_ready(maker, backup_env, monkeypatch):
    artifact = backup_env / "dump.enc"
    artifact.write_bytes(b"1")
    _script(backup_env, f'echo "$MELORIN_BACKUP_OFFSITE_URI" > {backup_env}/uri\necho {artifact}\n')
    monkeypatch.setattr(jobs.integrations, "backup_s3_ready", lambda cfg: True)
    monkeypatch.setattr(jobs.integrations, "rclone_env", lambda cfg: {"RCLONE_X": "1"})
    monkeypatch.setattr(jobs.integrations, "rclone_uri", lambda cfg: "s3:bucket/path")
    assert await jobs.backup_job() == "succeeded"
    assert (backup_env / "uri").read_text().strip() == "s3:bucket/path"
    (run,) = await _runs(maker)
    assert "copied to S3" in run.details
