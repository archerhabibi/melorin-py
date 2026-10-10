from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent.parent


def test_ruff_policy_is_broader_than_correctness_only():
    config = (ROOT / "pyproject.toml").read_text()
    assert '"I"' in config and '"UP"' in config and '"B"' in config
    assert "[tool.ruff.format]" in config


def test_local_and_ci_gates_run_format_checks():
    gate = (PROJECT / "scripts/run_quality_gate.sh").read_text()
    ci = (PROJECT / ".github/workflows/ci.yml").read_text()
    make = (PROJECT / "Makefile").read_text()
    assert "ruff format --check" in gate
    assert "ruff format --check" in ci
    assert "ruff format --check" in make
