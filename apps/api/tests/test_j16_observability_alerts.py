from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent.parent


def test_alert_state_and_prometheus_rules_are_wired():
    metrics = (ROOT / "melorin/core/metrics.py").read_text()
    app = (ROOT / "melorin/app.py").read_text()
    rules = (PROJECT / "infra/alerts.yml").read_text()
    prometheus = (PROJECT / "infra/prometheus.yml").read_text()
    compose = (PROJECT / "docker-compose.yml").read_text()
    assert "def set_alert" in metrics and "def alert_snapshot" in metrics
    for alert in ("DatabaseUnavailable", "RedisUnavailable", "WorkerStale", "PanelsUnhealthy", "OutboxBacklog"):
        assert alert in app and f"Melorin{alert}" in rules
    assert "rule_files:" in prometheus and "./infra/alerts.yml:/etc/prometheus/alerts.yml:ro" in compose
