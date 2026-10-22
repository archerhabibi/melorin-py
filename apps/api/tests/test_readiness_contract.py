from pathlib import Path

from _source import read_source

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent.parent


def test_readiness_is_dependency_based_and_returns_503_when_not_ready():
    source = read_source(ROOT / "melorin/app.py")
    assert "ready_ok = db.ok and worker.redis_ok and worker.worker_ok" in source
    assert "status_code=200 if ready_ok else 503" in source
    assert "age = time.time() - float(result.last_tick)" in source
    assert "0 <= age <= WORKER_MAX_AGE_SECONDS" in source
    assert "WORKER_MAX_AGE_SECONDS = 15" in source


def test_compose_waits_for_health_before_starting_dependents():
    compose = (PROJECT / "docker-compose.yml").read_text()
    assert "condition: service_healthy" in compose
    assert "api: {condition: service_healthy}" in compose
    assert "store_web: {condition: service_healthy}" in compose
    assert "admin_web: {condition: service_healthy}" in compose
