from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_reseller_runner_supports_multiple_core_bound_store_bots():
    source = (ROOT / "apps/telegram-reseller/runner.py").read_text()
    assert "MELORIN_RESELLER_BOTS_JSON" in source
    assert "store_slug" in source and "state_suffix" in source
    assert "asyncio.gather" in source
    assert "/api/v1/stores/by-slug/" in (ROOT / "apps/telegram-reseller/runner.py").read_text()


def test_reseller_runner_routes_business_operations_through_core():
    source = (ROOT / "apps/telegram-reseller/runner.py").read_text()
    assert "self.api(ctx" in source
    assert "panel" not in source.lower()
