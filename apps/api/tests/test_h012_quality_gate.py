from pathlib import Path


def test_quality_gate_covers_declared_test_and_static_surfaces():
    source = Path(__file__).parents[3].joinpath("scripts", "run_quality_gate.sh").read_text()
    for marker in (
        "verify_runtime.py",
        "check_frontend_contracts.py",
        "check_release_matrix.py",
        "compileall",
        "ruff check",
        "test_matrix.py",
    ):
        assert marker in source
    assert "check_web_lockfiles.py" not in source
