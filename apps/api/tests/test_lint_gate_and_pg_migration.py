"""Regression contracts for the lint gate and the 0009 PostgreSQL migration."""

from pathlib import Path

from _source import read_source

ROOT = Path(__file__).resolve().parents[3]
API = ROOT / "apps/api"


def test_quality_gate_uses_the_correctness_policy_and_ci_runs_it():
    config = (API / "pyproject.toml").read_text()
    gate = (ROOT / "scripts/run_quality_gate.sh").read_text()
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert 'select = ["E4", "E9", "F"]' in config
    assert "ruff check" in gate and "ruff format --check" in gate
    assert "ruff check melorin" in ci and "ruff format --check" in ci


def test_migration_smoke_checks_0009_and_schema_contract():
    smoke = (ROOT / "scripts/migration_smoke.sh").read_text()
    migration = read_source(API / "alembic/versions/0009_referral_first_reward_guard.py")
    assert "version == head" in smoke and "get_current_head" in smoke
    assert "information_schema.columns" in smoke
    assert "uq_commissions_store_referred_signup_reward" in smoke
    assert "uq_commissions_store_id_referred_user_id_kind" in smoke  # asserted ABSENT: 0037 dropped it
    assert "indexdef" in smoke and "UNIQUE" in smoke  # the index must be unique and partial, not just present by name
    assert "referred_user_id" in migration
    assert "newer.created_at = c.created_at" in migration
    assert "newer.id < c.id" in migration


def test_ci_executes_real_postgresql_migration_smoke():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "bash ../../scripts/migration_smoke.sh" in ci
