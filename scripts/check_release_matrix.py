"""Guard the authoritative release matrix against accidental green claims."""
from pathlib import Path

text = Path("docs/RELEASE-EVIDENCE-MATRIX.md").read_text()
head_migration = Path("apps/api/alembic/versions/0012_baskets_to_panel_groups.py").read_text()
assert "RELEASE BLOCKED" in text
assert "Runtime-tested" in text
assert "Production-evidenced" in text
assert text.count("| Blocked |") >= 10
assert "historical" in text.lower()
assert "J01-J19 remediation status" in text
assert "0012" in head_migration
assert "scripts/runtime_evidence.py" in text  # M7.3: the matrix points at the evidence collector
assert Path("scripts/runtime_evidence.py").is_file() and Path("docs/RUNTIME-EVIDENCE.md").is_file()
policy = Path("docs/history/I33_DOCUMENTATION_STATUS.md").read_text()
assert "I33" in policy
print("release evidence matrix is present and fail-closed")
