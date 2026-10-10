from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent.parent


def test_readiness_is_dependency_based_and_returns_503_when_not_ready():
    source = (ROOT / "melorin/app.py").read_text()
    assert "ready_ok = db_ok and redis_ok and worker_ok" in source
    assert "status_code=200 if ready_ok else 503" in source
    assert "worker_age" in source
    assert "worker_age <= 15" in source


def test_compose_waits_for_health_before_starting_dependents():
    compose = (PROJECT / "docker-compose.yml").read_text()
    assert "condition: service_healthy" in compose
    assert "api: {condition: service_healthy}" in compose
    assert "store_web: {condition: service_healthy}" in compose
    assert "admin_web: {condition: service_healthy}" in compose
