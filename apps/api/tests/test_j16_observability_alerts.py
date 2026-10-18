from pathlib import Path

from _source import read_source

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent.parent


def test_alert_state_and_prometheus_rules_are_wired():
    metrics = read_source(ROOT / "melorin/core/metrics.py")
    app = read_source(ROOT / "melorin/app.py")
    rules = (PROJECT / "infra/alerts.yml").read_text()
    prometheus = (PROJECT / "infra/prometheus.yml").read_text()
    compose = (PROJECT / "docker-compose.yml").read_text()
    assert "def set_alert" in metrics and "def alert_snapshot" in metrics
    for alert in ("DatabaseUnavailable", "RedisUnavailable", "WorkerStale", "PanelsUnhealthy", "OutboxBacklog"):
        assert alert in app and f"Melorin{alert}" in rules
    assert "rule_files:" in prometheus and "./infra/alerts.yml:/etc/prometheus/alerts.yml:ro" in compose
