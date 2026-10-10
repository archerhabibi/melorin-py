from pathlib import Path


def test_initial_migration_does_not_use_create_all_or_drop_all():
    source = Path(__file__).parents[1].joinpath("alembic", "versions", "0001_initial.py").read_text()
    assert "Base.metadata.create_all" not in source
    assert "Base.metadata.drop_all" not in source
    assert "CreateTable" in source
    assert "CreateIndex" in source
    assert ".compile(" not in source
    assert "op.execute(CreateTable(table))" in source
    assert "op.execute(CreateIndex(index))" in source
