from pathlib import Path

from _source import read_source


def test_metrics_are_bounded_and_prometheus_wired():
    middleware = read_source(Path(__file__).parents[1].joinpath("melorin", "core", "middleware.py"))
    app = read_source(Path(__file__).parents[1].joinpath("melorin", "app.py"))
    prometheus = Path(__file__).parents[3].joinpath("infra", "prometheus.yml").read_text()
    assert 'route = "/api/v1/*"' in middleware
    assert 'media_type="text/plain; version=0.0.4"' in app
    assert "metrics_path: /metrics" in prometheus
