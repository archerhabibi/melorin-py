"""PasarGuard Phase 5: panel metrics + alerts (PG-14), settings drift + lifecycle policy (PG-15), panel backup (PG-16).

Rules under test: scrape-time gauges come from the database only (no panel call); a metric with no data is absent, never a fake zero;
gone panels do not keep reporting; drift detection is READ-ONLY and never leaks a secret from the panel's settings; the lifecycle policy
decides whether a panel auto-delete is drift; a failed read never invents or clears drift; panel backups are a separate series that cannot
trip the Melorin-backup alert; every new endpoint needs an admin."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pytest
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_order, make_product, make_user, open_schema_engine
from _http import PASSWORD, add_user, api_client, totp_now
from melorin.core import metrics
from melorin.core.db import utcnow
from melorin.domain.order_state import VpnStatus
from melorin.kernel.models.system import AuditEvent, BackupRun
from melorin.kernel.models.vpn import Panel, PanelNode, ReconciliationIssue, Server, VpnAccount
from melorin.modules.reports import business_metrics
from melorin.modules.vpn import panel_backup, panel_metrics, settings_drift
from melorin.modules.vpn.adapters.base import Capabilities, ErrorKind, PanelError
from melorin.modules.vpn.renewal import GRACE_DAYS

ROOT = Path(__file__).resolve().parents[3]
NOW = dt.datetime(2026, 11, 8, 12, 0, tzinfo=dt.UTC)
BASE = "/api/v1/admin"


@pytest.fixture(autouse=True)
def _clean():
    metrics.reset()
    yield
    metrics.reset()


@pytest.fixture(autouse=True)
def _no_panel_backup_env(monkeypatch):
    for k in ("MELORIN_PANEL_BACKUP_DATABASE_URL", "MELORIN_PANEL_BACKUP_PATHS"):
        monkeypatch.delenv(k, raising=False)


def _rendered() -> str:
    return metrics.render()


async def _panel(s, *, name="pg", status="healthy", **kw) -> Panel:
    p = Panel(name=name, kind="pasarguard", base_url="https://panel.example.com", config=kw.pop("config", {}), health_status=status,
              last_health_at=NOW, **kw)  # fmt: skip
    s.add(p)
    await s.flush()
    return p


def _node(p, rid, status, name=None):
    return PanelNode(panel_id=p.id, remote_id=rid, name=name or f"n{rid}", status=status, status_changed_at=NOW)


# ------------------------------------------------------------------------------------------------------------ PG-14 parsing
def test_parse_system_keeps_only_real_numbers_and_converts_ratios():
    out = panel_metrics.parse_system(
        {"active_users": 7, "on_hold_users": 1, "expired_users": 2, "total_user": 10, "online_users": 3, "cpu_usage": 42.5,
         "mem_used": 1, "mem_total": 4, "disk_used": 50, "disk_total": 0, "limited_users": "x", "disabled_users": True}
    )  # fmt: skip
    assert out["users"] == {"active": 7, "on_hold": 1, "expired": 2} and out["users_total"] == 10 and out["online_users"] == 3
    assert out["cpu_ratio"] == 0.425 and out["mem_ratio"] == 0.25
    assert "disk_ratio" not in out  # total 0: unknown, not 0%
    assert panel_metrics.parse_system(None) == {} and panel_metrics.parse_system({"cpu_usage": 250})["cpu_ratio"] == 1.0


class FakeAdapter:
    def __init__(self, *, up=True, stats=None, stats_error=None, health_error=None):
        self.up, self.stats, self.stats_error, self.health_error = up, stats or {}, stats_error, health_error
        self.calls: list[str] = []

    def capabilities(self):
        return Capabilities(node_insight=True)

    async def health_check(self):
        self.calls.append("health")
        if self.health_error:
            raise self.health_error
        return self.up

    async def get_system_stats(self):
        self.calls.append("system")
        if self.stats_error:
            raise self.stats_error
        return self.stats

    # the rest of the NodeInsight protocol: ``supports()`` requires every method, the snapshot only calls get_system_stats
    async def get_system_resources(self):
        return {}

    async def get_nodes_realtime(self):
        return {}

    async def get_node_stats(self, node_id):
        return {}


async def test_snapshot_records_latency_and_readings(monkeypatch):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        p = await _panel(s)
        snap = await panel_metrics.snapshot_panel(p, FakeAdapter(stats={"active_users": 4, "online_users": 2, "cpu_usage": 10}), now=NOW)
        assert snap["up"] is True and snap["users"] == {"active": 4} and snap["online_users"] == 2 and snap["latency_seconds"] >= 0
        assert p.metrics_snapshot_at == NOW


async def test_snapshot_survives_failures_and_records_them():
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        p = await _panel(s)
        down = await panel_metrics.snapshot_panel(p, FakeAdapter(health_error=PanelError(ErrorKind.TRANSIENT, "timeout")), now=NOW)
        assert down["up"] is False and down["error"] == "timeout" and "users" not in down
        denied = await panel_metrics.snapshot_panel(p, FakeAdapter(stats_error=PanelError(ErrorKind.PERMANENT, "403 system.read")), now=NOW)
        assert denied["up"] is True and denied["insight_error"] == "403 system.read"  # up, but the credential cannot read system
        buggy = await panel_metrics.snapshot_panel(p, FakeAdapter(health_error=RuntimeError("boom")), now=NOW)
        assert buggy["up"] is False and buggy["error"].startswith("RuntimeError")


async def test_snapshot_skips_system_call_when_the_credential_may_not_read_it():
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        p = await _panel(s, capabilities={"flags": {"node_insight": False}, "source": "probe"})
        a = FakeAdapter(stats={"active_users": 1})
        snap = await panel_metrics.snapshot_panel(p, a, now=NOW)
        assert a.calls == ["health"] and "users" not in snap


# ------------------------------------------------------------------------------------------------------------ PG-14 scrape
async def test_collect_renders_panel_gauges_from_the_database():
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        p = await _panel(s, status="degraded")
        s.add_all([_node(p, 1, "connected"), _node(p, 2, "error"), _node(p, 3, "disabled"), _node(p, 4, "limited")])
        p.metrics_snapshot = {"latency_seconds": 0.42, "users": {"active": 5, "limited": 1}, "online_users": 3, "cpu_ratio": 0.3, "mem_ratio": 0.5}
        p.metrics_snapshot_at = NOW - dt.timedelta(minutes=2)
        await s.flush()
        seen = await panel_metrics.collect(s, NOW)
        assert seen['melorin_panel_up{panel="pg"}'] == 1.0  # degraded still serves
        assert seen['melorin_panel_nodes{panel="pg",status="connected"}'] == 1.0
        assert seen['melorin_panel_nodes{panel="pg",status="error"}'] == 2.0  # error + limited
        assert seen['melorin_panel_nodes{panel="pg",status="disabled"}'] == 1.0
        assert seen['melorin_panel_users{panel="pg",status="active"}'] == 5.0 and seen['melorin_panel_online_users{panel="pg"}'] == 3.0
        assert seen['melorin_panel_api_latency_seconds{panel="pg"}'] == 0.42 and seen['melorin_panel_snapshot_age_seconds{panel="pg"}'] == 120.0
        assert not any("disk_ratio" in k for k in seen)  # never read: absent, not zero
        text = _rendered()
        assert 'melorin_panel_cpu_ratio{panel="pg"} 0.3' in text
        alerts = metrics.alert_snapshot()
        assert alerts["MelorinPanelDegraded"]["state"] == "firing" and alerts["MelorinPanelNodeDown"]["state"] == "resolved"


async def test_unhealthy_panel_is_down_and_no_connected_node_is_the_critical_alert():
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        p = await _panel(s, status="unhealthy")
        s.add_all([_node(p, 1, "error"), _node(p, 2, "connecting")])
        await s.flush()
        seen = await panel_metrics.collect(s, NOW)
        assert seen['melorin_panel_up{panel="pg"}'] == 0.0
        alert = metrics.alert_snapshot()["MelorinPanelNodeDown"]
        assert alert["state"] == "firing" and alert["severity"] == "critical" and "pg" in alert["details"]


async def test_unknown_health_and_panels_without_node_data_emit_nothing_for_them():
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        await _panel(s, status="unknown")
        await s.flush()
        seen = await panel_metrics.collect(s, NOW)
        assert not [k for k in seen if k.startswith(("melorin_panel_up", "melorin_panel_nodes"))]


async def test_a_deleted_or_disabled_panel_stops_reporting():
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        p = await _panel(s)
        await s.flush()
        await panel_metrics.collect(s, NOW)
        assert 'melorin_panel_up{panel="pg"}' in _rendered()
        p.is_enabled = False
        await s.flush()
        await panel_metrics.collect(s, NOW)
        assert 'panel="pg"' not in _rendered()  # clear_gauges forgot it


async def test_stale_snapshot_raises_the_stale_alert():
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        p = await _panel(s)
        p.metrics_snapshot, p.metrics_snapshot_at = {"latency_seconds": 0.1}, NOW - dt.timedelta(minutes=40)
        await s.flush()
        seen = await panel_metrics.collect(s, NOW)
        assert seen['melorin_panel_snapshot_age_seconds{panel="pg"}'] == 2400.0
        assert metrics.alert_snapshot()["MelorinPanelMetricsStale"]["state"] == "firing"


async def test_reconcile_issues_and_lag():
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        from _db import make_store

        store, user, product = await make_store(s), await make_user(s), await make_product(s)
        p = await _panel(s)
        order = await make_order(s, user=user, store=store, product=product)
        acc = VpnAccount(username="a1", user_id=user.id, store_id=store.id, order_id=order.id, product_id=product.id, panel_id=p.id,
                         status=VpnStatus.ACTIVE, last_synced_at=NOW - dt.timedelta(hours=4))  # fmt: skip
        s.add(acc)
        await s.flush()
        s.add(ReconciliationIssue(vpn_account_id=acc.id, kind="missing_on_panel", status="open"))
        s.add(ReconciliationIssue(vpn_account_id=acc.id, kind="owner_mismatch", status="resolved"))
        await s.flush()
        seen = await panel_metrics.collect(s, NOW)
        assert seen['melorin_reconcile_open_issues{kind="missing_on_panel"}'] == 1.0
        assert seen['melorin_reconcile_open_issues{kind="owner_mismatch"}'] == 0.0  # resolved rows do not count
        assert seen['melorin_reconcile_open_issues{kind="panel_unreachable"}'] == 0.0  # known kinds always present
        assert seen["melorin_reconcile_lag_seconds"] == 4 * 3600.0
        assert metrics.alert_snapshot()["MelorinReconcileLagHigh"]["state"] == "firing"


async def test_reconcile_lag_is_zero_without_accounts():
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        seen = await panel_metrics.collect(s, NOW)
        assert seen["melorin_reconcile_lag_seconds"] == 0.0
        assert metrics.alert_snapshot()["MelorinReconcileLagHigh"]["state"] == "resolved"


async def test_server_capacity_ratio_and_alert():
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        p = await _panel(s)
        full = Server(name="full", panel_id=p.id, capacity=10, capacity_source="panel", panel_total_users=10)
        roomy = Server(name="roomy", panel_id=p.id, capacity=100)
        s.add_all([full, roomy])
        await s.flush()
        seen = await panel_metrics.collect(s, NOW)
        assert seen['melorin_server_capacity_ratio{server="full"}'] == 1.0 and seen['melorin_server_capacity_ratio{server="roomy"}'] == 0.0
        alert = metrics.alert_snapshot()["MelorinCapacityHigh"]
        assert alert["state"] == "firing" and alert["details"] == "full"


async def test_webhook_silence_is_measured_from_last_delivery_or_from_connecting():
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        a = await _panel(s, name="a", webhook_connected_at=NOW - dt.timedelta(hours=5), webhook_last_at=NOW - dt.timedelta(hours=1))
        b = await _panel(s, name="b", webhook_connected_at=NOW - dt.timedelta(hours=2))
        await _panel(s, name="c")
        await s.flush()
        seen = await panel_metrics.collect(s, NOW)
        assert seen['melorin_panel_webhook_lag_seconds{panel="a"}'] == 3600.0
        assert seen['melorin_panel_webhook_lag_seconds{panel="b"}'] == 7200.0
        assert not any('panel="c"' in k and "webhook" in k for k in seen)  # never connected: not a silence
        assert a.id != b.id


# ------------------------------------------------------------------------------------------------------------ PG-16 backup
async def test_panel_backup_is_a_separate_series_and_not_in_use_until_configured(monkeypatch):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        seen = await panel_metrics.collect(s, NOW)
        assert not any("backup_age" in k for k in seen)  # not configured, never ran: "not in use", no stale alert
        assert metrics.alert_snapshot()["MelorinPanelBackupStale"]["state"] == "resolved"
        monkeypatch.setenv("MELORIN_PANEL_BACKUP_PATHS", "/var/lib/pasarguard")
        seen = await panel_metrics.collect(s, NOW)
        assert seen['melorin_backup_age_seconds{target="panel"}'] == 10**9  # configured but never succeeded: stale
        assert metrics.alert_snapshot()["MelorinPanelBackupStale"]["state"] == "firing"
        s.add(BackupRun(status="succeeded", target="panel", size=5, created_at=NOW - dt.timedelta(hours=3)))
        await s.flush()
        seen = await panel_metrics.collect(s, NOW)
        assert seen['melorin_backup_age_seconds{target="panel"}'] == 3 * 3600.0
        assert metrics.alert_snapshot()["MelorinPanelBackupStale"]["state"] == "resolved"


async def test_a_fresh_panel_backup_does_not_hide_a_stale_melorin_backup():
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        s.add(BackupRun(status="succeeded", target="panel", created_at=NOW - dt.timedelta(minutes=5)))
        s.add(BackupRun(status="succeeded", target="melorin", created_at=NOW - dt.timedelta(hours=60)))
        await s.flush()
        values = await business_metrics.collect(s, NOW)
        assert values["melorin_backup_age_seconds"] == 60 * 3600.0  # the Melorin series ignores panel runs
        assert metrics.alert_snapshot()["MelorinBackupStale"]["state"] == "firing"


async def test_panel_backup_status_for_the_admin(monkeypatch):
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        assert (await panel_backup.status(s, NOW))["state"] == "not_configured"
        monkeypatch.setenv("MELORIN_PANEL_BACKUP_DATABASE_URL", "postgresql://u:p@db/panel")
        assert (await panel_backup.status(s, NOW))["state"] == "stale"
        s.add(BackupRun(status="failed", target="panel", details="x" * 900, created_at=NOW - dt.timedelta(hours=1)))
        s.add(BackupRun(status="succeeded", target="panel", location="/var/backups/panel-20261108.tar.age", size=9, created_at=NOW - dt.timedelta(hours=2)))
        s.add(BackupRun(status="succeeded", target="melorin", created_at=NOW))
        await s.flush()
        st = await panel_backup.status(s, NOW)
        assert st["state"] == "ok" and st["age_seconds"] == 2 * 3600.0 and st["database_configured"] and not st["paths_configured"]
        assert len(st["runs"]) == 2 and {r["status"] for r in st["runs"]} == {"failed", "succeeded"}
        assert any(r["file"] == "panel-20261108.tar.age" for r in st["runs"]) and all("/" not in (r["file"] or "") for r in st["runs"])
        assert all(len(r["details"]) <= 300 for r in st["runs"])


async def test_panel_backup_job_does_nothing_until_configured():
    from melorin.worker import jobs

    assert await jobs.panel_backup_job() == "not_configured"


async def test_panel_backup_job_records_a_panel_run(monkeypatch, tmp_path):
    from melorin.worker import jobs

    async with open_schema_engine() as engine:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(jobs, "session_factory", lambda: maker)
        artifact = tmp_path / "panel-1.tar.age"
        artifact.write_bytes(b"x" * 12)
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()
        script = script_dir / "backup_panel.sh"
        script.write_text(f"#!/usr/bin/env bash\necho {artifact}\n")
        script.chmod(0o755)
        monkeypatch.setenv("MELORIN_PROJECT_ROOT", str(tmp_path))
        monkeypatch.setenv("MELORIN_PANEL_BACKUP_PATHS", "/var/lib/pasarguard")
        assert await jobs.panel_backup_job() == "succeeded"
        async with maker() as s:
            run = (await s.scalars(select(BackupRun))).one()
            assert run.target == "panel" and run.status == "succeeded" and run.size == 12
        script.write_text("#!/usr/bin/env bash\necho nope >&2\nexit 1\n")
        assert await jobs.panel_backup_job() == "failed"


def test_backup_scripts_are_valid_and_never_touch_melorin_backups():
    import subprocess

    for name in ("backup_panel.sh", "verify_panel_backup.sh"):
        path = ROOT / "scripts" / name
        assert path.stat().st_mode & 0o111, f"{name} must be executable"
        assert subprocess.run(["bash", "-n", str(path)]).returncode == 0
    src = (ROOT / "scripts" / "backup_panel.sh").read_text()
    assert "-name 'panel-*.tar.age'" in src  # retention only ever deletes panel artifacts
    assert "MELORIN_PANEL_BACKUP_DATABASE_URL" in src and "age --encrypt" in src and "sha256sum --check" in src
    assert "--password" not in src and "PGPASSWORD" not in src  # no password in argv or environment
    refused = subprocess.run(["bash", str(ROOT / "scripts" / "backup_panel.sh")], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    assert refused.returncode == 2 and "not configured" in refused.stderr


# ------------------------------------------------------------------------------------------------------------ PG-15 drift (pure)
def test_cleanup_off_is_ok_under_both_policies():
    for policy in ("keep", "aligned"):
        for block in ({"expired_users_retention_days": 0}, {}, {"expired_users_retention_days": None}, {"expired_users_retention_days": "x"}):
            assert settings_drift.evaluate_cleanup(block, policy)["state"] == "ok"


def test_cleanup_keep_policy_flags_any_auto_delete():
    f = settings_drift.evaluate_cleanup({"expired_users_retention_days": 30, "include_limited_users": True}, "keep")
    assert f["state"] == "drift" and f["retention_days"] == 30 and f["include_limited"] and "missing_on_panel" in f["message"]


def test_cleanup_aligned_policy_accepts_retention_at_or_above_the_grace_days():
    assert settings_drift.evaluate_cleanup({"expired_users_retention_days": GRACE_DAYS}, "aligned")["state"] == "ok"
    assert settings_drift.evaluate_cleanup({"expired_users_retention_days": 90}, "aligned")["state"] == "ok"
    short = settings_drift.evaluate_cleanup({"expired_users_retention_days": GRACE_DAYS - 1}, "aligned")
    assert short["state"] == "drift" and str(GRACE_DAYS) in short["message"]


def test_cleanup_unreadable_block_is_unknown_not_drift():
    assert settings_drift.evaluate_cleanup(None, "keep")["state"] == "unknown"


def test_webhook_findings():
    url = "https://melorin.example.com/api/v1/webhooks/pasarguard/p1"
    on = {"enable": True, "webhooks": [{"url": url}]}
    assert settings_drift.evaluate_webhook(on, connected=True, url=url)["state"] == "ok"
    assert settings_drift.evaluate_webhook({"enable": False, "webhooks": [{"url": url}]}, connected=True, url=url)["state"] == "drift"
    assert settings_drift.evaluate_webhook({"enable": True, "webhooks": [{"url": "https://other"}]}, connected=True, url=url)["state"] == "drift"
    assert settings_drift.evaluate_webhook({}, connected=True, url=None)["state"] == "unknown"
    assert settings_drift.evaluate_webhook(on, connected=False, url=url)["state"] == "ok"  # registered but Melorin not "connected": fine
    other = settings_drift.evaluate_webhook({"enable": True, "webhooks": [{"url": "https://other"}]}, connected=False, url=url)
    assert other["state"] == "info"
    assert settings_drift.evaluate_webhook(None, connected=False, url=url)["state"] == "ok"


def test_subscription_prefix_findings():
    ev = settings_drift.evaluate_subscription
    assert ev({"url_prefix": "https://sub.example.com:1010"}, "https://sub.example.com:1010/sub")["state"] == "ok"  # origin, not path
    bad = ev({"url_prefix": "https://sub.example.com:1010"}, "https://other.example.com/sub")
    assert bad["state"] == "drift" and bad["panel"] == "https://sub.example.com:1010"
    assert ev({"url_prefix": "https://sub.example.com"}, None)["state"] == "info"
    assert ev({}, "https://sub.example.com")["state"] == "info"


def test_notifications_and_hwid_are_informational_and_never_leak_secrets():
    settings = {
        "notification_settings": {"notify_telegram": True, "telegram_api_token": "123456:SECRET-TOKEN", "telegram_chat_id": -100123, "discord_webhook_url": "https://discord/hook/SECRET"},
        "hwid": {"enabled": True, "forced": False, "max_limit": 3, "fallback_limit": 1},
        "cleanup": {"expired_users_retention_days": 0},
    }
    findings = settings_drift.evaluate(settings, policy="keep", connected=False, webhook_url=None, sub_base_url=None)
    blob = repr(findings)
    for secret in ("SECRET-TOKEN", "123456", "100123", "discord/hook"):
        assert secret not in blob
    by = {f["key"]: f for f in findings}
    assert by["panel_notifications"]["state"] == "info" and by["panel_notifications"]["telegram"] is True
    assert by["hwid"]["state"] == "info" and by["hwid"]["max_limit"] == 3
    assert settings_drift.verdict(findings, policy="keep", now=NOW)["drifting"] == 0  # info never counts


# ------------------------------------------------------------------------------------------------------------ PG-15 drift (I/O)
class SettingsAdapter:
    def __init__(self, settings=None, error=None):
        self.settings, self.error, self.writes = settings or {}, error, []

    def capabilities(self):
        return Capabilities(settings_ops=True)

    async def get_settings(self):
        if self.error:
            raise self.error
        return self.settings

    async def _req(self, *a, **k):  # any write path would land here: it must never be used
        self.writes.append((a, k))


async def test_check_panel_stores_a_verdict_and_never_writes():
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        p = await _panel(s)
        a = SettingsAdapter({"cleanup": {"expired_users_retention_days": 7}})
        out = await settings_drift.check_panel(p, a, now=NOW)
        assert out["drifting"] == 1 and p.settings_drift["findings"][2]["key"] == "expired_cleanup" and p.settings_drift_at == NOW
        assert a.writes == []


async def test_failed_read_keeps_the_previous_verdict_and_notes_the_error():
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        p = await _panel(s)
        await settings_drift.check_panel(p, SettingsAdapter({"cleanup": {"expired_users_retention_days": 7}}), now=NOW)
        later = NOW + dt.timedelta(hours=1)
        out = await settings_drift.check_panel(p, SettingsAdapter(error=PanelError(ErrorKind.TRANSIENT, "timeout")), now=later)
        assert out["drifting"] == 1 and out["error"] == "timeout"  # an outage neither clears nor invents drift
        assert p.settings_drift_at == NOW  # time of the last SUCCESSFUL read
        ok = await settings_drift.check_panel(p, SettingsAdapter({"cleanup": {}}), now=later)
        assert ok["drifting"] == 0 and ok["error"] is None


async def test_credential_without_settings_access_is_reported_not_guessed():
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        p = await _panel(s, capabilities={"flags": {"settings_ops": False}, "source": "probe"})
        out = await settings_drift.check_panel(p, SettingsAdapter(), now=NOW)
        assert out["error"] == "settings_unreadable" and out["drifting"] == 0 and out["findings"] == []


async def test_policy_change_is_audited_validated_and_rechecked(monkeypatch):
    from melorin.modules.vpn import settings_drift as mod

    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        p = await _panel(s)
        admin = await make_user(s, super_admin=True)
        await s.commit()
        adapter = SettingsAdapter({"cleanup": {"expired_users_retention_days": 30}})
        import melorin.modules.vpn.adapters.registry as registry

        monkeypatch.setattr(registry, "build_adapter", lambda panel, server=None: adapter)
        before = await mod.recheck(s, p.id, actor_id=None)
        assert before["drifting"] == 1 and before["policy"] == "keep"
        after = await mod.set_policy(s, p.id, "aligned", actor_id=admin.id, reason="مهلت تمدید")
        assert after["policy"] == "aligned" and after["drifting"] == 0  # 30 days >= the renewal grace
        events = (await s.scalars(select(AuditEvent).where(AuditEvent.action == "panel.cleanup_policy_changed"))).all()
        assert len(events) == 1 and events[0].data["from"] == "keep" and events[0].data["to"] == "aligned"
        assert adapter.writes == []
        with pytest.raises(Exception) as bad:
            await mod.set_policy(s, p.id, "delete_everything", actor_id=admin.id, reason="x")
        assert "BAD_POLICY" in repr(getattr(bad.value, "code", bad.value))


async def test_non_pasarguard_panels_are_not_checked():
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        p = Panel(name="sn", kind="sanaei", base_url="https://x", config={}, health_status="healthy")
        s.add(p)
        await s.commit()
        with pytest.raises(Exception) as err:
            await settings_drift.recheck(s, p.id, actor_id=None)
        assert "NOT_PASARGUARD" in repr(getattr(err.value, "code", err.value))


async def test_run_all_announces_a_drift_change_once(monkeypatch):
    from melorin.modules.eventcenter import rules as ec

    announced: list[tuple[int, int]] = []

    async def fake_notice(session, panel, before, after):
        announced.append((before, after))

    monkeypatch.setattr(ec, "notify_settings_drift", fake_notice)
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as s:
        await _panel(s)
        await s.commit()
        adapter = SettingsAdapter({"cleanup": {"expired_users_retention_days": 7}})
        import melorin.modules.vpn.adapters.registry as registry

        monkeypatch.setattr(registry, "build_adapter", lambda panel, server=None: adapter)

        async def close(_a):
            return None

        assert await settings_drift.run_all(s, close_adapter=close) == 1
        assert await settings_drift.run_all(s, close_adapter=close) == 1
        assert announced == [(0, 1), (1, 1)]  # the notice function itself ignores 1 -> 1


async def test_drift_notice_only_on_state_change(monkeypatch):
    from melorin.modules.eventcenter import rules as ec

    sent: list[str] = []

    async def emit(session, channel, payload, **kw):
        sent.append(payload["text"])

    monkeypatch.setattr(ec.events, "emit", emit)

    class FakeSession:
        def begin_nested(self):
            import contextlib

            return contextlib.nullcontext()

    class P:
        id, name = "p1", "pg"
        settings_drift = {"findings": [{"key": "expired_cleanup", "state": "drift"}, {"key": "hwid", "state": "info"}]}

    await ec.notify_settings_drift(FakeSession(), P, 0, 1)
    await ec.notify_settings_drift(FakeSession(), P, 1, 1)
    await ec.notify_settings_drift(FakeSession(), P, 1, 0)
    await ec.notify_settings_drift(FakeSession(), P, 0, 0)
    assert len(sent) == 2 and "expired_cleanup" in sent[0] and "hwid" not in sent[0] and "🟢" in sent[1]


# ------------------------------------------------------------------------------------------------------------ alerts + docs wiring
def _alert_rules():
    data = yaml.safe_load((ROOT / "infra" / "alerts.yml").read_text())
    return {r["alert"]: r for g in data["groups"] for r in g["rules"]}


def test_phase5_alert_rules_exist_with_severity_and_summary():
    rules = _alert_rules()
    for name in ("MelorinPanelNodeDown", "MelorinPanelDegraded", "MelorinPanelApiSlow", "MelorinPanelResourcesHigh", "MelorinPanelMetricsStale",
                 "MelorinReconcileLagHigh", "MelorinCapacityHigh", "MelorinPanelSettingsDrift", "MelorinPanelBackupStale"):  # fmt: skip
        assert name in rules, name
        assert rules[name]["labels"]["severity"] in ("warning", "critical") and rules[name]["annotations"]["summary"]


def test_melorin_backup_alert_ignores_the_panel_series():
    rules = _alert_rules()
    assert 'target=""' in rules["MelorinBackupStale"]["expr"]  # without it a stale PANEL backup would fire the Melorin alert
    assert 'target="panel"' in rules["MelorinPanelBackupStale"]["expr"]


def test_every_gauge_is_declared_and_every_collector_alert_has_a_rule_or_a_ui_reason():
    src = (ROOT / "apps/api/melorin/modules/vpn/panel_metrics.py").read_text()
    declared = set(panel_metrics.GAUGES)
    used = set(re.findall(r'"(melorin_[a-z_]+)"', src))
    assert declared <= used
    for name in ("MelorinPanelNodeDown", "MelorinPanelDegraded", "MelorinReconcileLagHigh", "MelorinCapacityHigh", "MelorinPanelMetricsStale",
                 "MelorinPanelSettingsDrift", "MelorinPanelBackupStale"):  # fmt: skip
        assert name in _alert_rules()


def test_worker_schedules_the_new_jobs():
    arq = (ROOT / "apps/api/melorin/worker/arq_app.py").read_text()
    for job in ("panel_metrics_job", "panel_settings_drift_job", "panel_backup_job"):
        assert f"cron({job}" in arq and arq.count(job) >= 3, job


# ------------------------------------------------------------------------------------------------------------ admin API
async def _login(c, maker):
    await add_user(maker, email="root@example.com", admin=True, totp=True)
    r = await c.post("/api/v1/auth/password/login", json={"email": "root@example.com", "password": PASSWORD, "totp_code": totp_now()})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_every_phase5_endpoint_needs_an_admin():
    pid = "00000000-0000-0000-0000-000000000001"
    async with api_client() as (c, _, __):
        for method, path in (
            ("get", f"/panels/{pid}/metrics"), ("get", f"/panels/{pid}/settings-drift"), ("post", f"/panels/{pid}/settings-drift/check"),
            ("put", f"/panels/{pid}/lifecycle-policy"), ("get", "/panel-backups"),
        ):  # fmt: skip
            r = await getattr(c, method)(BASE + path)
            assert r.status_code in (401, 403), (method, path, r.status_code)


async def test_phase5_http_flow(monkeypatch):
    import melorin.modules.vpn.adapters.registry as registry

    adapter = SettingsAdapter({"cleanup": {"expired_users_retention_days": 5}})
    monkeypatch.setattr(registry, "build_adapter", lambda panel, server=None: adapter)
    async with api_client() as (c, maker, _main):
        h = await _login(c, maker)
        async with maker() as s:
            p = await _panel(s)
            s.add_all([_node(p, 1, "connected"), _node(p, 2, "error")])
            p.metrics_snapshot, p.metrics_snapshot_at = {"up": True, "latency_seconds": 0.2, "users": {"active": 3}}, utcnow()
            await s.commit()
            pid = str(p.id)
        reading = (await c.get(f"{BASE}/panels/{pid}/metrics", headers=h)).json()
        assert reading["nodes"] == {"connected": 1, "connecting": 0, "disabled": 0, "error": 1} and reading["reading"]["users"] == {"active": 3}
        first = (await c.get(f"{BASE}/panels/{pid}/settings-drift", headers=h)).json()
        assert first["policy"] == "keep" and first["drifting"] == 0 and first["checked_at"] is None and first["grace_days"] == GRACE_DAYS
        checked = await c.post(f"{BASE}/panels/{pid}/settings-drift/check", headers=h)
        assert checked.status_code == 200 and checked.json()["drifting"] == 1
        short = await c.put(f"{BASE}/panels/{pid}/lifecycle-policy", headers=h, json={"policy": "aligned", "reason": "x"})
        assert short.status_code == 422  # a reason is required
        bad = await c.put(f"{BASE}/panels/{pid}/lifecycle-policy", headers=h, json={"policy": "purge", "reason": "because"})
        assert bad.status_code == 422
        ok = await c.put(f"{BASE}/panels/{pid}/lifecycle-policy", headers=h, json={"policy": "aligned", "reason": "مهلت تمدید ده روز"})
        assert ok.status_code == 200 and ok.json()["policy"] == "aligned" and ok.json()["drifting"] == 1  # 5 days < grace
        backups = (await c.get(f"{BASE}/panel-backups", headers=h)).json()
        assert backups["state"] == "not_configured" and backups["runs"] == []
        missing = await c.get(f"{BASE}/panels/00000000-0000-0000-0000-0000000000aa/settings-drift", headers=h)
        assert missing.status_code == 404
        assert adapter.writes == []
