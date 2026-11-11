"""T01 guard: UTC helpers live in melorin.domain.timeutil only."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "melorin"


def test_no_local_aware_definitions():
    offenders = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*.py") if "def _aware(" in p.read_text() or "def aware(" in p.read_text()]
    assert offenders == ["domain/timeutil.py"]
