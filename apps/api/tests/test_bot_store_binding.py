from pathlib import Path

from _source import read_source

ROOT = Path(__file__).resolve().parents[1]


def test_bot_store_owner_mapping_has_database_and_core_admin_surface():
    model = read_source(ROOT / "melorin/modules/stores/models.py")
    migration = read_source(ROOT / "alembic/versions/0008_bot_store_bindings.py")
    router = read_source(ROOT / "melorin/modules/admin/router.py")
    runner = read_source(ROOT.parent.parent / "apps/telegram-reseller/runner.py")
    for field in ("bot_key", "store_id", "owner_user_id", "bot_kind", "status"):
        assert field in model and field in migration
    assert "/bot-store-bindings" in router
    assert "MELORIN_RESELLER_BOTS_JSON" in runner
