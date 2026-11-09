"""Panel admin routers hold no SQL (audit T11): reads go through ``panelops.queries``. Add a router here once it is clean."""

from __future__ import annotations

import ast
from pathlib import Path

ADMIN = Path(__file__).resolve().parents[1] / "melorin" / "modules" / "admin"
CLEAN = ["panel_reconciliation", "panel_orphans", "panel_live_events", "panel_operations", "panel_monitoring"]


def _selects(path: Path) -> list[int]:
    tree = ast.parse(path.read_text())
    return [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", None)) in {"select", "update", "delete", "insert"}
    ]


def test_clean_routers_build_no_sql():
    bad = {name: lines for name in CLEAN if (lines := _selects(ADMIN / f"{name}.py"))}
    assert not bad, f"move these queries into modules/panelops/queries.py: {bad}"
