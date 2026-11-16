"""Regression contracts for the lint gate and the 0009 PostgreSQL migration."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
API = ROOT / "apps/api"


def test_quality_gate_uses_the_correctness_policy_and_ci_runs_it():
    config = (API / "pyproject.toml").read_text()
    gate = (ROOT / "scripts/run_quality_gate.sh").read_text()
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert 'select = ["E4", "E9", "F", "DTZ", "B", "ASYNC", "S"]' in config
    assert "ruff check" in gate and "ruff format --check" in gate
    assert "ruff check melorin" in ci and "ruff format --check" in ci


def test_ci_executes_real_postgresql_migration_smoke():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "bash ../../scripts/migration_smoke.sh" in ci
