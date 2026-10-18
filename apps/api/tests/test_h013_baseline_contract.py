from pathlib import Path

from _source import read_source


def test_initial_migration_is_non_destructive_and_contract_marked():
    source = (Path(__file__).parents[1] / "alembic" / "versions" / "0001_initial.py").read_text()
    # 0001 is a frozen static DDL snapshot (no runtime model fingerprinting).
    assert "BASELINE_DDL" in source
    assert "drop_all" not in source
    assert "create_all" not in source
    assert "raise RuntimeError" in source
    assert "MODEL_SOURCE_FINGERPRINT" in source
    assert "_model_source_fingerprint" not in source
    assert "must not be regenerated from the live models" in source


def test_bot_binding_table_has_one_migration_owner():
    root = Path(__file__).parents[1] / "alembic" / "versions"
    baseline = read_source(root / "0001_initial.py")
    binding = read_source(root / "0008_bot_store_bindings.py")
    assert "bot_store_bindings" not in baseline
    assert binding.count('"bot_store_bindings"') >= 1
    assert "sole owner" in binding
