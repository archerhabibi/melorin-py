"""Regression contracts for installation, operations, integrations and frontend gates."""

from pathlib import Path

from _source import normalize_source

ROOT = Path(__file__).resolve().parents[3]


def read(path):
    """Read a repo file; Python sources are layout-normalised (M6.7)."""
    text = (ROOT / path).read_text()
    return normalize_source(text) if str(path).endswith(".py") else text


def test_installation_is_external_proxy_aware_and_atomic():
    installer = read("scripts/install_server.sh")
    readme = read("README.md")
    assert "EXTERNAL_PROXY=true" in installer and "127.0.0.1:18080" in readme
    assert "ENV_FILE=.env.tmp" in installer and 'mv -f "$ENV_FILE" .env' in installer


def test_manual_install_steps_and_optional_integrations_are_documented():
    readme = read("README.md")
    assert "alembic upgrade head" in readme and "admin bootstrap" in readme.lower()
    assert "Admin panel" in readme and "S3" in readme


def test_postgres16_backup_tool_and_restore_checks_are_present():
    dockerfile = read("apps/api/Dockerfile")
    backup = read("scripts/backup_restore_verify.sh")
    assert "postgresql-client-16" in dockerfile and "pg_restore --list" in backup


def test_acceptance_smoke_covers_real_provider_boundaries():
    smoke = read("scripts/integration_smoke.sh")
    assert "MELORIN_RUN_EXTERNAL_PROVIDERS" in smoke
    assert "MELORIN_RUN_TELEGRAM_SMOKE" in smoke
    assert "MELORIN_PANEL_SMOKE_URL" in smoke


def test_telegram_retries_transient_core_errors_without_advancing_offset():
    bot = read("apps/telegram-main/runner.py")
    assert "offset is deliberately NOT advanced" in bot
    assert 'self._save_offset(update["update_id"] + 1)' in bot


def test_production_redis_policy_and_frontend_audit_gate_are_explicit():
    runbook = read("docs/RUNBOOK.md")
    gate = read("scripts/run_quality_gate.sh")
    assert "fails closed" in runbook
    assert "npm audit --include=dev --audit-level=high" in gate
