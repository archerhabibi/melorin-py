from pathlib import Path

from _source import read_source

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent.parent


def test_ci_has_non_regressing_coverage_gate_and_integration_job():
    ci = (PROJECT / ".github/workflows/ci.yml").read_text()
    assert "--cov-fail-under=20" in ci
    assert "--cov-report=xml" in ci
    assert "pytest -q -m integration" in ci
    assert "postgresql+asyncpg://" in ci and "redis://localhost:6379/0" in ci


def test_test_matrix_exposes_unit_integration_and_concurrency_boundaries():
    matrix = read_source(PROJECT / "scripts/test_matrix.py")
    assert '"unit"' in matrix
    assert '"integration"' in matrix
    assert '"concurrency"' in matrix
    assert '"all"' in matrix


def test_coverage_excludes_generated_and_test_code():
    config = (ROOT / "pyproject.toml").read_text()
    assert "branch = true" in config
    assert 'omit = ["*/tests/*", "*/alembic/*"]' in config
