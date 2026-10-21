"""Regression coverage for the eight failures reported by review L-03."""

from pathlib import Path

from _source import read_source

ROOT = Path(__file__).resolve().parents[3]
API = ROOT / "apps/api"


def test_l03_readiness_and_worker_signals_are_wired():
    app = read_source(API / "melorin/app.py")
    worker = read_source(API / "melorin/worker/arq_app.py")
    assert "ready_ok = db_ok and redis_ok and worker_ok" in app
    assert "melorin:worker:last_tick" in app and "melorin_worker_last_tick" in app
    assert "melorin:worker:last_tick" in worker


def test_l03_operational_controls_are_wired():
    arq = read_source(API / "melorin/worker/arq_app.py")
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "backup_job" in arq and "timeout=900" in arq
    assert "secrets/metrics-token" in compose and "recipients.txt:/run/melorin-backup/recipients.txt:ro" in compose


def test_l03_lint_policy_is_correctness_focused():
    config = (API / "pyproject.toml").read_text()
    assert "[tool.ruff.lint]" in config
    assert 'select = ["E4", "E9", "F"]' in config
    assert 'ignore = ["F403", "F405"]' in config


def test_l03_redis_fallback_is_bounded_and_concurrency_smoke_is_declared():
    limiter = read_source(API / "melorin/core/ratelimit.py")
    smoke = ROOT / "scripts/postgres_concurrency_smoke.py"
    assert "_local_hit" in limiter and "return await _local_hit" in limiter
    assert smoke.is_file()


def test_l03_production_security_and_multistore_bot_contracts():
    config = read_source(API / "melorin/core/config.py")
    read_source(ROOT / "apps/telegram-main/runner.py")  # must exist and be readable
    reseller = read_source(ROOT / "apps/telegram-reseller/runner.py")
    assert "Fernet(self.encryption_key.encode())" in config
    assert 'parsed_api.scheme != "https"' in config
    assert "MELORIN_RESELLER_BOTS_JSON" in reseller and "asyncio.gather" in reseller
    assert "self.api(ctx" in reseller and "panel" not in reseller.lower()
    assert "/api/v1/stores/by-slug/" in reseller
