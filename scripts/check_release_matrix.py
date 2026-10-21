"""Guard the authoritative release matrix against accidental green claims."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # work from any cwd (CI runs this from apps/api)

text = (ROOT / "docs/RELEASE-EVIDENCE-MATRIX.md").read_text()
head_migration = (ROOT / "apps/api/alembic/versions/0012_baskets_to_panel_groups.py").read_text()
assert "RELEASE BLOCKED" in text
assert "Runtime-tested" in text
assert "Production-evidenced" in text
assert text.count("| Blocked |") >= 10
assert "historical" in text.lower()
assert "J01-J19 remediation status" in text
assert "0012" in head_migration
assert "scripts/runtime_evidence.py" in text  # M7.3: the matrix points at the evidence collector
assert (ROOT / "scripts/runtime_evidence.py").is_file() and "Runtime evidence collector" in text  # merged into the matrix
policy = (ROOT / "docs/history/I33_DOCUMENTATION_STATUS.md").read_text()
assert "I33" in policy
print("release evidence matrix is present and fail-closed")
