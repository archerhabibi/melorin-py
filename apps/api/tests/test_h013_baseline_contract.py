from pathlib import Path

def test_initial_migration_is_non_destructive_and_contract_marked():
    source = (Path(__file__).parents[1] / "alembic" / "versions" / "0001_initial.py").read_text()
    assert "BASELINE_SCHEMA_CONTRACT" in source
    assert "drop_all" not in source
    assert "create_all" not in source
    assert "raise RuntimeError" in source
    assert "MODEL_SOURCE_FINGERPRINT" in source
    assert "_model_source_fingerprint" in source
    assert "model sources changed" in source
    assert "_LATER_MIGRATION_TABLES" in source
    assert '"bot_store_bindings"' in source


def test_bot_binding_table_has_one_migration_owner():
    root = Path(__file__).parents[1] / "alembic" / "versions"
    baseline = (root / "0001_initial.py").read_text()
    binding = (root / "0008_bot_store_bindings.py").read_text()
    assert baseline.count('"bot_store_bindings"') == 1
    assert binding.count('"bot_store_bindings"') >= 1
    assert "sole owner" in binding
