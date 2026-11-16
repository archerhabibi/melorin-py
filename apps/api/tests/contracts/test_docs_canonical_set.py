"""The docs folder holds exactly 24 canonical documents: 00..21 (hand-written) plus generated STATUS.md and API.md."""

import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[4] / "docs"


def test_docs_folder_is_exactly_24_canonical_files():
    names = sorted(p.name for p in DOCS.glob("*.md"))
    numbered = [n for n in names if re.match(r"^\d\d-", n)]
    assert [n[:2] for n in numbered] == [f"{i:02d}" for i in range(22)]
    assert {"STATUS.md", "API.md"} <= set(names)
    assert len(names) == 24, names
