from pathlib import Path


def test_metrics_are_bounded_and_prometheus_wired():
    middleware = Path(__file__).parents[1].joinpath("melorin", "core", "middleware.py").read_text()
    app = Path(__file__).parents[1].joinpath("melorin", "app.py").read_text()
    prometheus = Path(__file__).parents[3].joinpath("infra", "prometheus.yml").read_text()
    assert 'route = "/api/v1/*"' in middleware
    assert 'media_type="text/plain; version=0.0.4"' in app
    assert "metrics_path: /metrics" in prometheus
