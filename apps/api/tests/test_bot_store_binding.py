from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bot_store_owner_mapping_has_database_and_core_admin_surface():
    model = (ROOT / "melorin/modules/stores/models.py").read_text()
    migration = (ROOT / "alembic/versions/0008_bot_store_bindings.py").read_text()
    router = (ROOT / "melorin/modules/admin/router.py").read_text()
    runner = (ROOT.parent.parent / "apps/telegram-reseller/runner.py").read_text()
    for field in ("bot_key", "store_id", "owner_user_id", "bot_kind", "status"):
        assert field in model and field in migration
    assert "/bot-store-bindings" in router
    assert "MELORIN_RESELLER_BOTS_JSON" in runner
