"""Guard the authoritative release matrix against accidental green claims."""

from pathlib import Path

ROOT = (
    Path(__file__).resolve().parents[1]
)  # work from any cwd (CI runs this from apps/api)

text = (ROOT / "docs/20-TESTING-QUALITY-RELEASE.md").read_text()
head_migration = (ROOT / "apps/api/alembic/versions/0001_initial_baseline.py").read_text()
assert "RELEASE BLOCKED" in text
assert "Runtime-tested" in text
assert "Production-evidenced" in text
assert text.count("| Blocked |") >= 10
assert "historical" in text.lower()
assert "J01-J19 remediation status" in text
assert "0001_initial_baseline" in head_migration
assert (
    "scripts/runtime_evidence.py" in text
)  # M7.3: the matrix points at the evidence collector
assert (
    ROOT / "scripts/runtime_evidence.py"
).is_file() and "Runtime evidence collector" in text  # merged into the matrix
policy = (ROOT / "docs/06-ARCHITECTURE-DECISIONS.md").read_text()
assert "I33" in policy
print("release evidence matrix is present and fail-closed")
