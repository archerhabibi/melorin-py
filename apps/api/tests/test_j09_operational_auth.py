from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent.parent


def test_metrics_requires_bearer_token_outside_development():
    source = (ROOT / "melorin/app.py").read_text()
    assert 'request.headers.get("Authorization"' in source
    assert 'f"Bearer {s.metrics_token}"' in source
    assert "unauthorized" in source


def test_health_details_require_separate_operator_token():
    source = (ROOT / "melorin/app.py").read_text()
    assert 'X-Melorin-Health-Token' in source
    assert 'payload = {"status": "ready" if ready_ok else "not_ready"}' in source


def test_prometheus_uses_a_secret_file_for_scraping():
    prometheus = (PROJECT / "infra/prometheus.yml").read_text()
    compose = (PROJECT / "docker-compose.yml").read_text()
    assert "bearer_token_file: /etc/prometheus/metrics-token" in prometheus
    assert "./secrets/metrics-token:/etc/prometheus/metrics-token:ro" in compose
