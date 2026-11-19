"""Worker-process metrics are exposed only on the authenticated internal scrape endpoint."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from melorin.worker import arq_app, metrics_server


async def _request(port: int, *, path: str = "/metrics", authorization: str | None = None) -> str:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    headers = ["Host: localhost", "Connection: close"]
    if authorization is not None:
        headers.append(f"Authorization: {authorization}")
    writer.write(f"GET {path} HTTP/1.1\r\n".encode() + "\r\n".join(headers).encode() + b"\r\n\r\n")
    await writer.drain()
    response = (await reader.read()).decode()
    writer.close()
    await writer.wait_closed()
    return response


@pytest.mark.asyncio
async def test_worker_metrics_endpoint_requires_bearer_and_serves_process_registry(monkeypatch):
    monkeypatch.setattr(metrics_server, "get_settings", lambda: SimpleNamespace(is_dev=False, metrics_token="scrape-secret"))
    monkeypatch.setattr(metrics_server, "render", lambda: 'melorin_job_runs_total{job="expiry_job",outcome="ok"} 3\n')
    ctx = {}
    server = await metrics_server.start_metrics_server(ctx, host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    try:
        unauthorized = await _request(port)
        assert unauthorized.startswith("HTTP/1.1 401 Unauthorized")
        assert "WWW-Authenticate: Bearer" in unauthorized

        wrong = await _request(port, authorization="Bearer wrong")
        assert wrong.startswith("HTTP/1.1 401 Unauthorized")

        ok = await _request(port, authorization="Bearer scrape-secret")
        assert ok.startswith("HTTP/1.1 200 OK")
        assert 'melorin_job_runs_total{job="expiry_job",outcome="ok"} 3' in ok
    finally:
        await metrics_server.stop_metrics_server(ctx)
    assert "metrics_server" not in ctx


@pytest.mark.asyncio
async def test_worker_metrics_endpoint_fails_closed_without_production_token(monkeypatch):
    monkeypatch.setattr(metrics_server, "get_settings", lambda: SimpleNamespace(is_dev=False, metrics_token=""))
    ctx = {}
    server = await metrics_server.start_metrics_server(ctx, host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    try:
        response = await _request(port)
        assert response.startswith("HTTP/1.1 503 Service Unavailable")
    finally:
        await metrics_server.stop_metrics_server(ctx)


@pytest.mark.asyncio
async def test_worker_metrics_endpoint_allows_unconfigured_development_mode(monkeypatch):
    monkeypatch.setattr(metrics_server, "get_settings", lambda: SimpleNamespace(is_dev=True, metrics_token=""))
    monkeypatch.setattr(metrics_server, "render", lambda: "dev_metric 1\n")
    server = await metrics_server.start_metrics_server({}, host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    try:
        response = await _request(port)
        assert response.startswith("HTTP/1.1 200 OK")
        assert "dev_metric 1" in response
    finally:
        server.close()
        await server.wait_closed()


def test_prometheus_scrapes_worker_and_alerts_on_lock_failures():
    root = Path(__file__).resolve().parents[4]
    config = yaml.safe_load((root / "infra/prometheus.yml").read_text())
    worker = next(job for job in config["scrape_configs"] if job["job_name"] == "melorin-worker")
    assert worker["static_configs"][0]["targets"] == ["worker:8001"]
    assert worker["bearer_token_file"] == "/etc/prometheus/metrics-token"
    assert worker["honor_labels"] is True

    rules = yaml.safe_load((root / "infra/alerts.yml").read_text())
    alerts = [rule for group in rules["groups"] for rule in group["rules"]]
    item_failures = next(rule for rule in alerts if rule["alert"] == "MelorinJobItemFailures")
    lock_failures = next(rule for rule in alerts if rule["alert"] == "MelorinWorkerJobLockUnavailable")
    assert "melorin_job_item_failures_total" in item_failures["expr"]
    assert 'outcome="lock_error"' in lock_failures["expr"]


@pytest.mark.asyncio
async def test_arq_lifecycle_starts_and_stops_worker_metrics_server(monkeypatch):
    monkeypatch.setattr(metrics_server, "PORT", 0)
    monkeypatch.setattr(metrics_server, "get_settings", lambda: SimpleNamespace(is_dev=True, metrics_token=""))

    async def close_clients():
        return None

    from melorin.channels.telegram import bot_api

    monkeypatch.setattr(bot_api, "close_shared_clients", close_clients)
    ctx = {}
    await arq_app.startup(ctx)
    server = ctx.get("metrics_server")
    assert server is not None and server.is_serving()
    await arq_app.shutdown(ctx)
    assert "metrics_server" not in ctx
