from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent.parent


def test_ruff_policy_is_correctness_focused_with_format_section():
    config = (ROOT / "pyproject.toml").read_text()
    assert 'select = ["E4", "E9", "F"]' in config
    assert "[tool.ruff.format]" in config


def test_local_and_ci_gates_run_format_checks():
    gate = (PROJECT / "scripts/run_quality_gate.sh").read_text()
    ci = (PROJECT / ".github/workflows/ci.yml").read_text()
    make = (PROJECT / "Makefile").read_text()
    assert "ruff format --check" in gate
    assert "ruff format --check" in ci
    assert "ruff format --check" in make
