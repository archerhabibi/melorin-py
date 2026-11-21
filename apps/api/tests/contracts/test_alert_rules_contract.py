from pathlib import Path

from _source import read_source

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT.parent.parent


def test_alert_state_and_prometheus_rules_are_wired():
    metrics = read_source(ROOT / "melorin/core/metrics.py")
    health = read_source(ROOT / "melorin/core/health.py")
    rules = (PROJECT / "infra/alerts.yml").read_text()
    prometheus = (PROJECT / "infra/prometheus.yml").read_text()
    compose = (PROJECT / "docker-compose.yml").read_text()
    assert "def set_alert" in metrics and "def alert_snapshot" in metrics
    for alert in ("DatabaseUnavailable", "RedisUnavailable", "WorkerStale", "PanelsUnhealthy", "OutboxBacklog"):
        assert alert in health and f"Melorin{alert}" in rules
    assert (
        "rule_files:" in prometheus and "./infra:/etc/prometheus/infra:ro" in compose and "/etc/prometheus/infra/alerts.yml" in prometheus
    )


def test_fail_closed_job_lock_has_a_metric_and_an_alert():
    wrap = read_source(ROOT / "melorin/worker/wrap.py")
    rules = (PROJECT / "infra/alerts.yml").read_text()
    assert 'outcome="lock_error"' in wrap
    assert "MelorinJobLockUnavailable" in rules and 'outcome="lock_error"' in rules
