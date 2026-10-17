"""Regression contracts for restore, observability, operations and auth."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def read(path):
    return (ROOT / path).read_text()


def test_restore_drill_and_postgres16_tools_are_real_paths():
    drill = read("scripts/backup_restore_drill.sh")
    verify = read("scripts/backup_restore_verify.sh")
    docker = read("apps/api/Dockerfile")
    assert "pg_restore --no-owner --exit-on-error" in drill
    assert "pg_restore --list" in verify and "postgresql-client-16" in docker


def test_telegram_healthcheck_checks_getme():
    health = read("scripts/telegram_healthcheck.py")
    compose = read("docker-compose.yml")
    assert "/getMe" in health and "telegram_healthcheck.py" in compose


def test_metrics_secret_and_resource_limits_are_hardened():
    compose = read("docker-compose.yml")
    installer = read("scripts/install_server.sh")
    assert "secrets/metrics-token" in compose and "tmp_metrics" in installer
    assert "mem_limit:" in compose and "cpus:" in compose


def test_documentation_and_cookie_auth_gates_exist():
    policy = read("docs/DOCUMENTATION-POLICY.md")
    smoke = read("scripts/auth_cookie_smoke.py")
    api = read("apps/api/melorin/modules/identity/router.py")
    assert "docs/history/" in policy and "HttpOnly" in smoke and "httponly=True" in api
