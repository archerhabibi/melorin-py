"""Guard the authoritative release matrix against accidental green claims."""
from pathlib import Path

text = Path("docs/RELEASE-EVIDENCE-MATRIX.md").read_text()
assert "RELEASE BLOCKED" in text
assert "Runtime-tested" in text
assert "Production-evidenced" in text
assert text.count("| Blocked |") >= 10
assert "historical" in text.lower()
assert "J01-J19 remediation status" in text
assert "0008" in text
assert "0005" not in text
policy = Path("I33_DOCUMENTATION_STATUS.md").read_text()
assert "I33" in policy
print("release evidence matrix is present and fail-closed")
