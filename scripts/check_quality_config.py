"""Static guard that the declared quality policy is present and consistent."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
pyproject = (ROOT / "apps/api/pyproject.toml").read_text()
gate = (ROOT / "scripts/run_quality_gate.sh").read_text()
ci = (ROOT / ".github/workflows/ci.yml").read_text()

# Must mirror [tool.ruff.lint] select in apps/api/pyproject.toml. Widening the policy (E7, I, UP, B) needs a
# dedicated cleanup first (about 200 existing findings); keep both places in sync when that happens.
required = ('"E4"', '"E9"', '"F"')
missing = [rule for rule in required if rule not in pyproject]
if missing:
    raise SystemExit(f"quality policy missing rules: {missing}")
for text in (gate, ci):
    if "ruff check" not in text or "ruff format --check" not in text:
        raise SystemExit("quality gate is missing ruff check or format check")
print("Quality configuration is explicit and wired into local gate and CI")
