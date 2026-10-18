from pathlib import Path

from _source import read_source

ROOT = Path(__file__).resolve().parents[3]


def test_reseller_runner_supports_multiple_core_bound_store_bots():
    source = read_source(ROOT / "apps/telegram-reseller/runner.py")
    assert "MELORIN_RESELLER_BOTS_JSON" in source
    assert "store_slug" in source and "state_suffix" in source
    assert "asyncio.gather" in source
    assert "/api/v1/stores/by-slug/" in read_source(ROOT / "apps/telegram-reseller/runner.py")


def test_reseller_runner_routes_business_operations_through_core():
    source = read_source(ROOT / "apps/telegram-reseller/runner.py")
    assert "self.api(ctx" in source
    assert "panel" not in source.lower()
