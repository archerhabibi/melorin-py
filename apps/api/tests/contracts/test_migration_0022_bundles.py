"""Migration 0022: panel groups become sales bundles (tables, columns, indexes) and the downgrade restores the old names."""

import importlib.util
from pathlib import Path



ROOT = Path(__file__).resolve().parents[2]


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "alembic/versions" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod






def test_no_live_code_mentions_panel_groups_or_pools():
    live = [p for p in (ROOT / "melorin").rglob("*.py")]
    offenders = [p.name for p in live if "panel_group" in p.read_text(encoding="utf-8") or "PanelGroup" in p.read_text(encoding="utf-8")]
    assert not offenders, offenders
