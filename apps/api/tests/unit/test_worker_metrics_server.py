"""Worker-process metrics are exposed only on the authenticated internal scrape endpoint."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from melorin.worker import arq_app, backup_main, metrics_server


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


@pytest.mark.asyncio
async def test_non_ascii_authorization_is_rejected_not_crashed(monkeypatch):
    monkeypatch.setattr(metrics_server, "get_settings", lambda: SimpleNamespace(is_dev=False, metrics_token="scrape-secret"))
    server = await metrics_server.start_metrics_server({}, host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write("GET /metrics HTTP/1.1\r\nAuthorization: Bearer tökén\r\n\r\n".encode("latin-1"))
        await writer.drain()
        response = (await reader.read()).decode()
        writer.close()
        assert response.startswith("HTTP/1.1 401 Unauthorized")
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_head_query_string_and_methods(monkeypatch):
    monkeypatch.setattr(metrics_server, "get_settings", lambda: SimpleNamespace(is_dev=True, metrics_token=""))
    monkeypatch.setattr(metrics_server, "render", lambda: "m 1\n")
    server = await metrics_server.start_metrics_server({}, host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]

    async def raw(line: str) -> str:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(f"{line}\r\nHost: x\r\n\r\n".encode())
        await writer.drain()
        data = (await reader.read()).decode()
        writer.close()
        return data

    try:
        assert (await raw("GET /metrics?x=1 HTTP/1.1")).startswith("HTTP/1.1 200 OK")
        head = await raw("HEAD /metrics HTTP/1.1")
        assert head.startswith("HTTP/1.1 200 OK") and head.endswith("\r\n\r\n")
        assert (await raw("POST /metrics HTTP/1.1")).startswith("HTTP/1.1 405")
        assert (await raw("GET /other HTTP/1.1")).startswith("HTTP/1.1 404")
        assert (await raw("GET /metrics HTTP/2")).startswith("HTTP/1.1 400")
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_bind_failure_is_not_fatal():
    ctx: dict = {}
    first = await metrics_server.start_metrics_server(ctx, host="127.0.0.1", port=0)
    port = first.sockets[0].getsockname()[1]
    try:
        assert await metrics_server.start_metrics_server({}, host="127.0.0.1", port=port) is None
    finally:
        await metrics_server.stop_metrics_server(ctx)
    await metrics_server.stop_metrics_server(ctx)  # idempotent


def test_worker_and_backup_publish_no_host_port():
    root = Path(__file__).resolve().parents[4]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text())
    for name in ("worker", "backup"):
        assert "ports" not in compose["services"][name]


def test_prometheus_scrapes_worker_and_alerts_on_lock_failures():
    root = Path(__file__).resolve().parents[4]
    config = yaml.safe_load((root / "infra/prometheus.yml").read_text())
    worker = next(job for job in config["scrape_configs"] if job["job_name"] == "melorin-worker")
    backup = next(job for job in config["scrape_configs"] if job["job_name"] == "melorin-backup")
    assert worker["static_configs"][0]["targets"] == ["worker:8001"]
    assert backup["static_configs"][0]["targets"] == ["backup:8001"]
    assert worker["bearer_token_file"] == backup["bearer_token_file"] == "/etc/prometheus/metrics-token"
    assert worker["honor_labels"] is backup["honor_labels"] is True

    rules = yaml.safe_load((root / "infra/alerts.yml").read_text())
    alerts = [rule for group in rules["groups"] for rule in group["rules"]]
    item_failures = next(rule for rule in alerts if rule["alert"] == "MelorinJobItemFailures")
    lock_failures = next(rule for rule in alerts if rule["alert"] == "MelorinWorkerJobLockUnavailable")
    worker_down = next(rule for rule in alerts if rule["alert"] == "MelorinWorkerMetricsUnavailable")
    backup_down = next(rule for rule in alerts if rule["alert"] == "MelorinBackupMetricsUnavailable")
    assert "melorin_job_item_failures_total" in item_failures["expr"]
    assert 'outcome="lock_error"' in lock_failures["expr"]
    assert 'job="melorin-worker"' in worker_down["expr"]
    assert 'job="melorin-backup"' in backup_down["expr"]


@pytest.mark.asyncio
async def test_arq_lifecycle_starts_and_stops_worker_metrics_server(monkeypatch):
    monkeypatch.setattr(metrics_server, "HOST", "127.0.0.1")
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


@pytest.mark.asyncio
async def test_backup_scheduler_starts_and_stops_its_metrics_server(monkeypatch):
    started = stopped = False

    async def start(ctx):
        nonlocal started
        started = True
        ctx["metrics_server"] = object()

    async def stop(ctx):
        nonlocal stopped
        assert "metrics_server" in ctx
        stopped = True
        ctx.pop("metrics_server")

    async def run(stop_event, clock=None):
        assert started
        stop_event.set()

    monkeypatch.setattr(metrics_server, "start_metrics_server", start)
    monkeypatch.setattr(metrics_server, "stop_metrics_server", stop)
    monkeypatch.setattr(backup_main, "run_forever", run)
    await backup_main.run_with_metrics(asyncio.Event())
    assert started and stopped
