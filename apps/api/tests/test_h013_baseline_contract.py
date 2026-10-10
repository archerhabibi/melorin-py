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
