"""Panel admin routers hold no SQL (audit T11): reads go through ``panelops.queries``. Add a router here once it is clean."""

from __future__ import annotations

import ast
from pathlib import Path

ADMIN = Path(__file__).resolve().parents[1] / "melorin" / "modules" / "admin"
CLEAN = [
    "panel_reconciliation",
    "panel_orphans",
    "panel_live_events",
    "panel_operations",
    "panel_monitoring",
    "panel_admins",
    "targets",
    "capacity",
]


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


MODULES = Path(__file__).resolve().parents[1] / "melorin" / "modules"
CLEAN_MODULE_ROUTERS = ["notifications", "wallet", "reports"]


def test_clean_module_routers_build_no_sql():
    """T11: customer/report routers call ``<module>/queries.py``; add a module here once its router is clean."""
    bad = {m: lines for m in CLEAN_MODULE_ROUTERS if (lines := _selects(MODULES / m / "router.py"))}
    assert not bad, f"move these queries into modules/<name>/queries.py: {bad}"
